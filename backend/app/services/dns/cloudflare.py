"""The single Cloudflare DNS API client used by every Cloudflare path in ServerKit.

Centralizes, in one place:

* **auth** — scoped API token (``Authorization: Bearer``) *or* global key
  (``X-Auth-Email`` + ``X-Auth-Key``),
* the **CAA** structured-``data`` wire format (Cloudflare rejects a flat
  ``content`` string for CAA),
* **MX/SRV priority** parsing (a leading integer in the value), and
* **idempotent upsert** — update an existing record (by id when known, else by
  name) instead of blindly POSTing a duplicate.

Both ``DNSProviderService`` (provider layer) and ``DNSZoneService`` (zone layer)
delegate here, so a wire-format fix is made once rather than twice.
"""
import json
import logging

import requests

from app.services.dns.base import DnsCredential, DnsRecordSpec

logger = logging.getLogger(__name__)

API_BASE = 'https://api.cloudflare.com/client/v4'


def parse_caa_value(value: str) -> dict:
    """Parse a BIND-style CAA value (``0 issue "letsencrypt.org"``) into the
    ``{flags, tag, value}`` object Cloudflare expects. The CA value is unquoted.
    Kept here so the CAA wire format lives in exactly one place."""
    parts = (value or '').strip().split(None, 2)
    flags = int(parts[0]) if parts and parts[0].lstrip('-').isdigit() else 0
    tag = parts[1] if len(parts) > 1 else 'issue'
    ca = parts[2].strip().strip('"') if len(parts) > 2 else ''
    return {'flags': flags, 'tag': tag, 'value': ca}


def _first_error(data: dict) -> str:
    try:
        return (data.get('errors') or [{}])[0].get('message', 'Unknown error')
    except Exception:
        return 'Unknown error'


def _is_missing_record(data: dict) -> bool:
    errors = data.get('errors') or []
    for error in errors:
        if error.get('code') in (81044, 81057):
            return True
        message = str(error.get('message') or '').lower()
        if 'does not exist' in message or 'not found' in message:
            return True
    return False


class CloudflareClient:
    """Stateless wrapper around the Cloudflare v4 DNS API for one credential."""

    def __init__(self, credential: DnsCredential):
        self.cred = credential

    # ── auth ────────────────────────────────────────────────────────────────
    def _headers(self) -> dict:
        if self.cred.email:
            return {
                'X-Auth-Email': self.cred.email,
                'X-Auth-Key': self.cred.token or '',
                'Content-Type': 'application/json',
            }
        return {
            'Authorization': f'Bearer {self.cred.token or ""}',
            'Content-Type': 'application/json',
        }

    # ── connection / zones ──────────────────────────────────────────────────
    def verify(self) -> dict:
        """Verify the credential (token scope check)."""
        try:
            resp = requests.get(f'{API_BASE}/user/tokens/verify',
                                headers=self._headers(), timeout=15)
            data = resp.json()
            if data.get('success'):
                return {'success': True, 'message': 'Cloudflare connection successful'}
            return {'success': False, 'error': _first_error(data)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def list_zones(self) -> dict:
        """List the zones this credential can manage. Each zone carries its
        ``account_id`` so account-scoped lookups (e.g. registrar expiry) need no
        second discovery call."""
        try:
            resp = requests.get(f'{API_BASE}/zones?per_page=100',
                                headers=self._headers(), timeout=15)
            data = resp.json()
            if not data.get('success'):
                return {'success': False, 'error': _first_error(data) or 'Failed to list zones'}
            zones = [{'id': z['id'], 'name': z['name'], 'status': z['status'],
                      'account_id': (z.get('account') or {}).get('id')}
                     for z in data.get('result', [])]
            return {'success': True, 'zones': zones}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def list_registrar_domains(self, account_id: str) -> dict:
        """Domains registered through Cloudflare Registrar for ``account_id``, with
        their registration expiry and auto-renew flag.

        Best-effort by design: a DNS-scoped token without *Domain (Registrar): Read*
        returns an error the caller is expected to ignore (the domain simply shows no
        expiry), and only domains actually registered at Cloudflare appear — a zone
        whose domain is registered elsewhere won't be listed here."""
        if not account_id:
            return {'success': False, 'error': 'No account id'}
        try:
            resp = requests.get(
                f'{API_BASE}/accounts/{account_id}/registrar/domains?per_page=100',
                headers=self._headers(), timeout=15)
            data = resp.json()
            if not data.get('success'):
                return {'success': False, 'error': _first_error(data)}
            domains = [{
                'name': (d.get('name') or '').lower().rstrip('.'),
                'expires_at': d.get('expires_at'),
                'auto_renew': d.get('auto_renew'),
                'registrar': d.get('current_registrar') or 'Cloudflare',
            } for d in (data.get('result') or [])]
            return {'success': True, 'domains': domains}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def list_records(self, zone_id: str) -> dict:
        """List every record in a zone (paginated) — the live state the mirror
        classifies into ServerKit-owned vs the user's own records."""
        try:
            out, page = [], 1
            while True:
                resp = requests.get(
                    f'{API_BASE}/zones/{zone_id}/dns_records?per_page=100&page={page}',
                    headers=self._headers(), timeout=15)
                data = resp.json()
                if not data.get('success'):
                    return {'success': False, 'error': _first_error(data)}
                for r in data.get('result', []):
                    out.append({
                        'id': r.get('id'),
                        'type': r.get('type'),
                        'name': r.get('name'),
                        'content': r.get('content', ''),
                        'ttl': r.get('ttl'),
                        'proxied': bool(r.get('proxied', False)),
                        'priority': r.get('priority'),
                    })
                info = data.get('result_info') or {}
                if page >= (info.get('total_pages') or 1):
                    break
                page += 1
            return {'success': True, 'records': out}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ── records ─────────────────────────────────────────────────────────────
    def _payload(self, spec: DnsRecordSpec) -> dict:
        """Render a record spec into a Cloudflare ``dns_records`` payload."""
        payload = {'type': spec.record_type, 'name': spec.name, 'ttl': spec.ttl}

        # CAA needs Cloudflare's structured `data` object, not a flat `content`
        # string (and `proxied`/`priority` are meaningless for it).
        if spec.record_type == 'CAA':
            payload['data'] = parse_caa_value(spec.content)
            return payload

        content, priority = spec.content, spec.priority
        # MX/SRV may carry a leading priority in the value ("10 mail.example.com")
        # — split it out so Cloudflare gets a separate `priority` field.
        if spec.record_type in ('MX', 'SRV') and priority is None:
            head, _, rest = (spec.content or '').strip().partition(' ')
            if head.isdigit() and rest.strip():
                priority, content = int(head), rest.strip()

        payload['content'] = content
        payload['proxied'] = bool(spec.proxied)
        if priority is not None:
            payload['priority'] = priority
        return payload

    def find_record_id(self, zone_id: str, record_type: str, name: str,
                       caa: dict = None):
        """Return the id of an existing record matching ``type``+``name`` (and, for
        CAA, the same CA), or ``None``. CAA is matched on tag+value so a *different*
        CA's authorization is never clobbered."""
        resp = requests.get(
            f'{API_BASE}/zones/{zone_id}/dns_records?type={record_type}&name={name}',
            headers=self._headers(), timeout=15,
        )
        data = resp.json() or {}
        if data.get('success') is False:
            raise RuntimeError(_first_error(data))
        existing = data.get('result', []) or []
        if caa is not None:
            existing = [
                r for r in existing
                if (r.get('data') or {}).get('tag') == caa['tag']
                and str((r.get('data') or {}).get('value', '')).strip('"').rstrip('.').lower()
                    == caa['value'].rstrip('.').lower()
            ]
        return existing[0]['id'] if existing else None

    def upsert(self, zone_id: str, spec: DnsRecordSpec, record_id: str = None) -> dict:
        """Create or update a record idempotently.

        If ``record_id`` is known, PUT it directly; otherwise look up a matching
        record by name and PUT it, else POST a new one. Returns
        ``{success, record_id?, error?}`` so callers can persist the id.
        """
        try:
            base = f'{API_BASE}/zones/{zone_id}/dns_records'
            payload = self._payload(spec)

            if record_id is None:
                caa = payload.get('data') if spec.record_type == 'CAA' else None
                record_id = self.find_record_id(zone_id, spec.record_type, spec.name, caa=caa)

            if record_id:
                resp = requests.put(f'{base}/{record_id}', headers=self._headers(),
                                    json=payload, timeout=15)
            else:
                resp = requests.post(base, headers=self._headers(),
                                     json=payload, timeout=15)

            data = resp.json()
            if data.get('success'):
                rid = (data.get('result') or {}).get('id') or record_id
                return {'success': True, 'record_id': rid,
                        'message': f'{spec.record_type} record set for {spec.name}'}
            return {'success': False, 'error': _first_error(data)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def delete(self, zone_id: str, *, record_id: str = None,
               record_type: str = None, name: str = None) -> dict:
        """Delete by ``record_id`` when known, else by ``type``+``name`` (removes
        every match). A missing record is treated as success (already gone)."""
        try:
            base = f'{API_BASE}/zones/{zone_id}/dns_records'
            if record_id:
                ids = [record_id]
            else:
                resp = requests.get(f'{base}?type={record_type}&name={name}',
                                    headers=self._headers(), timeout=15)
                data = resp.json() or {}
                if data.get('success') is False:
                    return {'success': False, 'error': _first_error(data)}
                ids = [r['id'] for r in data.get('result', []) or []]
                if not ids:
                    return {'success': True, 'message': 'Record not found (already deleted)'}
            for rid in ids:
                resp = requests.delete(
                    f'{base}/{rid}', headers=self._headers(), timeout=15,
                )
                data = resp.json() or {}
                if data.get('success') is False:
                    if _is_missing_record(data):
                        continue
                    return {'success': False, 'error': _first_error(data)}
            return {'success': True, 'message': 'Record deleted'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ── generic v4 access (zone settings, cache, WAF, Workers, …) ─────────────
    #
    # The record methods above are the DNS-specific surface. Everything else in
    # the Cloudflare operations roadmap (zone settings, cache purge, WAF rules,
    # Workers, Tunnels, R2) is plain v4 REST, so it shares one thin ``request``
    # helper rather than a bespoke method per call. It normalizes the envelope so
    # every caller can rely on ``{success, error?, result?}``.
    def request(self, method: str, path: str, json: dict = None,
                params: dict = None, timeout: int = 20, headers: dict = None) -> dict:
        """Make a Cloudflare v4 call. ``path`` is relative to the API base (a
        leading slash is optional). Returns the parsed envelope dict (always with
        a ``success`` key and, on failure, a human ``error``), or a normalized
        ``{success: False, error}`` on a transport error.

        ``headers`` overrides the default auth headers — used by the Origin CA
        endpoints, which authenticate with the account-level Origin CA service key
        (``X-Auth-User-Service-Key``) rather than the zone token."""
        try:
            url = f'{API_BASE}/{path.lstrip("/")}'
            resp = requests.request(method.upper(), url, headers=headers or self._headers(),
                                    json=json, params=params, timeout=timeout)
            try:
                data = resp.json()
            except ValueError:
                return {'success': False,
                        'error': f'HTTP {resp.status_code}: non-JSON response from Cloudflare'}
            if not isinstance(data, dict):
                return {'success': False, 'error': 'Unexpected Cloudflare response'}
            if not data.get('success') and not data.get('error'):
                data['error'] = _first_error(data)
            return data
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_zone_settings(self, zone_id: str) -> dict:
        """All zone settings (``result`` is a list of ``{id, value, editable, …}``)."""
        return self.request('GET', f'/zones/{zone_id}/settings')

    def get_zone_setting(self, zone_id: str, setting_id: str) -> dict:
        """A single zone setting by id."""
        return self.request('GET', f'/zones/{zone_id}/settings/{setting_id}')

    def update_zone_setting(self, zone_id: str, setting_id: str, value) -> dict:
        """Patch a single zone setting. ``value`` is a scalar for most toggles or a
        structured object for compound settings (e.g. HSTS ``security_header``)."""
        return self.request('PATCH', f'/zones/{zone_id}/settings/{setting_id}',
                            json={'value': value})

    def purge_cache(self, zone_id: str, payload: dict) -> dict:
        """Purge the zone's Cloudflare cache. ``payload`` is one of
        ``{purge_everything: true}`` or ``{files|hosts|prefixes|tags: [...]}``."""
        return self.request('POST', f'/zones/{zone_id}/purge_cache', json=payload)

    # ── DNSSEC ────────────────────────────────────────────────────────────────
    # DNSSEC is a per-zone toggle; enabling it returns the DS record payload the
    # operator must place at their registrar. No registrar automation — display.
    def get_dnssec(self, zone_id: str) -> dict:
        """The zone's DNSSEC status + DS record fields (``result`` carries ``status``,
        ``ds``, ``digest``, ``key_tag``, …)."""
        return self.request('GET', f'/zones/{zone_id}/dnssec')

    def set_dnssec(self, zone_id: str, status: str) -> dict:
        """Enable (``status='active'``) or disable (``status='disabled'``) DNSSEC."""
        return self.request('PATCH', f'/zones/{zone_id}/dnssec', json={'status': status})

    # ── Origin CA certificates ────────────────────────────────────────────────
    # Origin CA certs are valid ONLY behind the Cloudflare proxy. They authenticate
    # with the account-level Origin CA *service key* (``X-Auth-User-Service-Key``)
    # OR a token carrying the SSL and Certificates permission. The CSR is generated
    # panel-side; the private key never leaves the box.
    ORIGIN_CA_BASE = 'certificates'

    def _origin_ca_headers(self, service_key: str = None) -> dict:
        """Auth headers for the Origin CA endpoints. Prefer the dedicated service
        key when present; otherwise fall back to the zone's normal token headers
        (a suitably-scoped token also authenticates these calls)."""
        if service_key:
            return {'X-Auth-User-Service-Key': service_key,
                    'Content-Type': 'application/json'}
        return self._headers()

    def create_origin_certificate(self, *, csr: str, hostnames: list,
                                  requested_validity: int = 5475,
                                  request_type: str = 'origin-rsa',
                                  service_key: str = None) -> dict:
        """Sign a panel-generated CSR into an Origin CA certificate for ``hostnames``
        (``result.certificate`` is the signed PEM). ``requested_validity`` is in days
        (7, 30, 90, 365, 730, 1095 or 5475)."""
        return self.request(
            'POST', f'/{self.ORIGIN_CA_BASE}',
            json={'csr': csr, 'hostnames': hostnames,
                  'requested_validity': requested_validity, 'request_type': request_type},
            headers=self._origin_ca_headers(service_key))

    def list_origin_certificates(self, zone_id: str, *, service_key: str = None) -> dict:
        """List Origin CA certificates for a zone (``result`` is a list)."""
        return self.request('GET', f'/{self.ORIGIN_CA_BASE}', params={'zone_id': zone_id},
                            headers=self._origin_ca_headers(service_key))

    def revoke_origin_certificate(self, certificate_id: str, *, service_key: str = None) -> dict:
        """Revoke an Origin CA certificate by id."""
        return self.request('DELETE', f'/{self.ORIGIN_CA_BASE}/{certificate_id}',
                            headers=self._origin_ca_headers(service_key))

    # ── WAF / rulesets ────────────────────────────────────────────────────────
    # Custom firewall rules live in the zone's ``http_request_firewall_custom``
    # phase entry-point ruleset. We list rulesets to find it (cleanly telling
    # "no custom ruleset yet" apart from an auth error), then read/append rules
    # by id; the first rule is created by PUTting the phase entry point.
    def list_rulesets(self, zone_id: str) -> dict:
        return self.request('GET', f'/zones/{zone_id}/rulesets')

    def get_ruleset(self, zone_id: str, ruleset_id: str) -> dict:
        return self.request('GET', f'/zones/{zone_id}/rulesets/{ruleset_id}')

    def create_phase_ruleset(self, zone_id: str, phase: str, rules: list) -> dict:
        """Create/replace a phase entry-point ruleset with ``rules`` (used to seed the
        first custom rule when no ruleset exists yet)."""
        return self.request(
            'PUT', f'/zones/{zone_id}/rulesets/phases/{phase}/entrypoint',
            json={'rules': rules})

    def add_ruleset_rule(self, zone_id: str, ruleset_id: str, rule: dict) -> dict:
        return self.request('POST', f'/zones/{zone_id}/rulesets/{ruleset_id}/rules',
                            json=rule)

    def update_ruleset_rule(self, zone_id: str, ruleset_id: str, rule_id: str,
                            rule: dict) -> dict:
        return self.request('PATCH',
                            f'/zones/{zone_id}/rulesets/{ruleset_id}/rules/{rule_id}',
                            json=rule)

    def delete_ruleset_rule(self, zone_id: str, ruleset_id: str, rule_id: str) -> dict:
        return self.request('DELETE',
                            f'/zones/{zone_id}/rulesets/{ruleset_id}/rules/{rule_id}')

    # ── Workers (edge scripts) ────────────────────────────────────────────────
    # Workers/R2/Tunnels are account-scoped; the owning account is read from the
    # zone. Script upload uses the stable multipart PUT /scripts/{name} (module
    # syntax) rather than the still-beta resource-oriented Workers API.
    def _auth_only_headers(self) -> dict:
        """Auth headers WITHOUT ``Content-Type`` — for multipart uploads where
        ``requests`` must set the multipart boundary itself."""
        if self.cred.email:
            return {'X-Auth-Email': self.cred.email, 'X-Auth-Key': self.cred.token or ''}
        return {'Authorization': f'Bearer {self.cred.token or ""}'}

    def get_zone_account_id(self, zone_id: str) -> dict:
        """Zone details — used to read the owning ``account.id``."""
        return self.request('GET', f'/zones/{zone_id}')

    def list_worker_scripts(self, account_id: str) -> dict:
        return self.request('GET', f'/accounts/{account_id}/workers/scripts')

    def upload_worker_module(self, account_id: str, name: str, code: str,
                             compatibility_date: str, main: str = 'worker.js') -> dict:
        """Create/overwrite a module-syntax Worker via the stable multipart
        ``PUT /accounts/{id}/workers/scripts/{name}`` endpoint."""
        url = f'{API_BASE}/accounts/{account_id}/workers/scripts/{name}'
        metadata = {'main_module': main, 'compatibility_date': compatibility_date}
        files = {
            'metadata': (None, json.dumps(metadata), 'application/json'),
            main: (main, code, 'application/javascript+module'),
        }
        try:
            resp = requests.put(url, headers=self._auth_only_headers(), files=files, timeout=30)
            try:
                data = resp.json()
            except ValueError:
                return {'success': False,
                        'error': f'HTTP {resp.status_code}: non-JSON response from Cloudflare'}
            if not isinstance(data, dict):
                return {'success': False, 'error': 'Unexpected Cloudflare response'}
            if not data.get('success') and not data.get('error'):
                data['error'] = _first_error(data)
            return data
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def delete_worker_script(self, account_id: str, name: str) -> dict:
        return self.request('DELETE', f'/accounts/{account_id}/workers/scripts/{name}')

    def list_worker_routes(self, zone_id: str) -> dict:
        return self.request('GET', f'/zones/{zone_id}/workers/routes')

    def add_worker_route(self, zone_id: str, pattern: str, script: str) -> dict:
        return self.request('POST', f'/zones/{zone_id}/workers/routes',
                            json={'pattern': pattern, 'script': script})

    def delete_worker_route(self, zone_id: str, route_id: str) -> dict:
        return self.request('DELETE', f'/zones/{zone_id}/workers/routes/{route_id}')

    # ── Tunnels (cloudflared / cfd_tunnel) ────────────────────────────────────
    # Account-scoped. As of Dec 2025 the list endpoint defaults to active-only;
    # we pass is_deleted=false explicitly to be unambiguous.
    def list_tunnels(self, account_id: str) -> dict:
        return self.request('GET', f'/accounts/{account_id}/cfd_tunnel',
                            params={'is_deleted': 'false'})

    def create_tunnel(self, account_id: str, name: str) -> dict:
        """Create a remotely-managed tunnel (config stored at Cloudflare)."""
        return self.request('POST', f'/accounts/{account_id}/cfd_tunnel',
                            json={'name': name, 'config_src': 'cloudflare'})

    def delete_tunnel(self, account_id: str, tunnel_id: str) -> dict:
        return self.request('DELETE', f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}')

    def get_tunnel_token(self, account_id: str, tunnel_id: str) -> dict:
        """The connector token (``result`` is the token string for ``cloudflared``)."""
        return self.request('GET', f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token')

    def get_tunnel_connections(self, account_id: str, tunnel_id: str) -> dict:
        return self.request('GET', f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}/connections')

    def get_tunnel_configuration(self, account_id: str, tunnel_id: str) -> dict:
        return self.request('GET', f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations')

    def put_tunnel_configuration(self, account_id: str, tunnel_id: str, config: dict) -> dict:
        """Set the tunnel's ingress rules (public hostname → local service)."""
        return self.request('PUT',
                            f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations',
                            json={'config': config})

    # ── Developer platform: R2 / KV / D1 ──────────────────────────────────────
    # Account-scoped storage primitives. Management only (list/create/delete);
    # object/key/row data planes are out of scope.
    def list_r2_buckets(self, account_id: str) -> dict:
        return self.request('GET', f'/accounts/{account_id}/r2/buckets')

    def create_r2_bucket(self, account_id: str, name: str) -> dict:
        return self.request('POST', f'/accounts/{account_id}/r2/buckets', json={'name': name})

    def delete_r2_bucket(self, account_id: str, name: str) -> dict:
        return self.request('DELETE', f'/accounts/{account_id}/r2/buckets/{name}')

    def list_kv_namespaces(self, account_id: str) -> dict:
        return self.request('GET', f'/accounts/{account_id}/storage/kv/namespaces',
                            params={'per_page': 100})

    def create_kv_namespace(self, account_id: str, title: str) -> dict:
        return self.request('POST', f'/accounts/{account_id}/storage/kv/namespaces',
                            json={'title': title})

    def delete_kv_namespace(self, account_id: str, namespace_id: str) -> dict:
        return self.request('DELETE',
                            f'/accounts/{account_id}/storage/kv/namespaces/{namespace_id}')

    def list_d1_databases(self, account_id: str) -> dict:
        return self.request('GET', f'/accounts/{account_id}/d1/database')

    def create_d1_database(self, account_id: str, name: str) -> dict:
        return self.request('POST', f'/accounts/{account_id}/d1/database', json={'name': name})

    def delete_d1_database(self, account_id: str, database_id: str) -> dict:
        return self.request('DELETE', f'/accounts/{account_id}/d1/database/{database_id}')
