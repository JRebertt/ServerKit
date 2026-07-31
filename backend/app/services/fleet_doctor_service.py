"""Fleet health doctor — the panel-host doctor, extended across the agent fleet
(Fleet Parity Sweep, plan 26 Phase 2-4).

The panel-host :class:`doctor_service.DoctorService` answers "is *this* box
healthy?" and stores a single ``doctor_last_report`` blob. This service answers
the same question for every *connected agent*, recording each remote per-check
outcome as a :class:`FleetDoctorResult` ROW keyed ``(server_id, check_key)`` so
the report API can merge the two and the repair layer can act on one finding
(Fleet Contract, rule 3).

Runs-where (Fleet Contract, rule 4): the fan-out happens **inside a job
handler** via the one sweep primitive :func:`fleet_sweep`, never on a request
thread — the agent gateway registry is single-worker + in-memory.

Composing vs probing (Fleet Contract, rule 5 / ``docs/AGENT_DOCTOR_PROBE_SPEC``):
each server's checks are composed from commands every already-deployed agent
understands (``systemd:status`` per unit + ``system:metrics``). When an agent
advertises the ``doctor.probe`` capability the panel negotiates to a single
``doctor:probe`` round trip instead — both paths emit *identical* rows, so the
report/UI/repair layers don't care which produced them. If the probe errors the
composed path is the permanent fallback.

DNS-vs-IP is a panel-side host probe (Fleet Contract table): the panel already
knows each server's advertised hostname and IP, so it resolves the hostname and
checks it points back at the box — no agent round trip needed, so it runs for
every server, connected or not.

Remote repair of a stopped core service is allowlisted + audited in
:mod:`fleet_repair_service` (rule 6); the doctor only *marks* a finding
``repairable`` (and only when the agent also advertises ``systemd.restart``).
"""
import logging
import socket
from datetime import datetime

from app.services.agent_registry import agent_registry
from app.services.fleet_sweep import fleet_sweep

logger = logging.getLogger(__name__)

FLEET_DOCTOR_JOB_KIND = 'doctor.fleet.run'
FLEET_DOCTOR_SCHEDULE_NAME = 'fleet-doctor'

# Core systemd units the fleet doctor probes on every agent (mirrors the
# panel-host doctor's CORE_SERVICES).
#
# Deliberately NOT profile-aware, unlike DoctorService._expected_services():
# an install profile describes the *panel* host, and these units live on remote
# agent boxes that were never provisioned by this panel's installer. Telling a
# Dockerless agent apart from a stopped-Docker agent needs the agent to report
# "unit not installed" rather than just active=false, which is a change in the
# serverkit-agent repo — panel↔agent protocol changes are not atomic with this
# one. Until then a Dockerless fleet member reports a Docker failure.
DOCTOR_UNITS = ('nginx', 'docker')

# Capability an agent advertises when it implements the batched doctor:probe
# round trip; and the one it advertises when it can restart a unit.
PROBE_CAPABILITY = 'doctor.probe'
RESTART_CAPABILITY = 'systemd.restart'

# Disk-headroom thresholds (percent free on /). Match the panel-host doctor.
DISK_WARN_FREE_PCT = 10.0
DISK_FAIL_FREE_PCT = 5.0

# Sweep bounds — kept small; the single-worker panel competes with live agent
# traffic (Fleet Contract, rule 4).
SWEEP_POOL = 4
SWEEP_PER_AGENT_TIMEOUT = 15.0
SWEEP_BUDGET = 90.0


def _row(check_key, title, status, detail, repairable=False, repair_ref=None):
    """One fleet-doctor finding (same shape as doctor_service._check)."""
    return {
        'key': check_key,
        'title': title,
        'status': status,  # 'ok' | 'warn' | 'fail' | 'error'
        'detail': detail,
        'repairable': bool(repairable),
        'repair_ref': repair_ref,
    }


def _resolve_host_ips(host):
    """IPs ``host`` resolves to; raises on failure. Module-level so tests can
    stub the resolver."""
    ips = []
    for info in socket.getaddrinfo(host, None):
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    return ips


class FleetDoctorService:
    """Run the fleet health sweep, persist per-server rows, expose the results."""

    # ------------------------------------------------------------------ #
    # Targets
    # ------------------------------------------------------------------ #

    @classmethod
    def _target_servers(cls):
        """Every registered server (agent fleet). The DNS probe runs for all of
        them; the remote probe degrades to an ``offline`` row for any that isn't
        connected."""
        try:
            from app.models.server import Server
            return Server.query.all()
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------ #
    # Per-server remote probe (composed, or batched doctor:probe)
    # ------------------------------------------------------------------ #

    @classmethod
    def _compose_server_checks(cls, server_id, per_agent_timeout):
        """``fleet_sweep`` composer: produce this server's remote check rows.

        Negotiates the batched ``doctor:probe`` when the agent advertises it,
        else composes from ``systemd:status`` + ``system:metrics``. Both paths
        emit identical rows. Returns a sweep result dict
        ``{'status': ..., 'checks': [...]}``.
        """
        if not agent_registry.is_agent_connected(server_id):
            return {'status': 'offline', 'checks': []}

        caps = agent_registry.get_capabilities(server_id) or {}
        checks = None
        if caps.get(PROBE_CAPABILITY):
            checks = cls._probe_checks(server_id, per_agent_timeout, caps)
        if checks is None:
            checks = cls._compose_v1(server_id, per_agent_timeout, caps)
        if checks is None:
            # Agent can neither probe nor report systemd — unsupported (rule 2).
            return {'status': 'unsupported', 'checks': []}
        return {'status': 'ok', 'checks': checks}

    @classmethod
    def _probe_checks(cls, server_id, per_agent_timeout, caps):
        """One ``doctor:probe`` round trip → check rows, or ``None`` when the
        probe errors / returns an unusable payload (caller falls back to v1)."""
        res = agent_registry.send_command(
            server_id, 'doctor:probe', {'units': list(DOCTOR_UNITS)},
            timeout=per_agent_timeout)
        if not res or not res.get('success'):
            return None
        data = res.get('data')
        if not isinstance(data, dict):
            return None

        restartable = bool(caps.get(RESTART_CAPABILITY))
        checks = []
        units = data.get('units') or {}
        for unit in DOCTOR_UNITS:
            info = units.get(unit) if isinstance(units, dict) else None
            active = bool(info.get('active')) if isinstance(info, dict) else False
            checks.append(cls._service_row(server_id, unit, active, restartable))

        disk = data.get('disk') if isinstance(data.get('disk'), dict) else None
        if disk is not None and disk.get('percent') is not None:
            try:
                checks.append(cls._disk_row(100.0 - float(disk['percent'])))
            except (TypeError, ValueError):
                pass
        return checks

    @classmethod
    def _compose_v1(cls, server_id, per_agent_timeout, caps):
        """Compose checks from commands every deployed agent understands. Returns
        ``None`` (→ unsupported) when the agent can't even report systemd."""
        if not caps.get('systemd'):
            return None
        restartable = bool(caps.get(RESTART_CAPABILITY))
        checks = []
        for unit in DOCTOR_UNITS:
            res = agent_registry.send_command(
                server_id, 'systemd:status', {'unit': unit},
                timeout=per_agent_timeout)
            if not res or not res.get('success'):
                checks.append(_row(
                    f'service.{unit}', f'{unit} service', 'warn',
                    f'Status probe failed: {(res or {}).get("error") or "no response"}'))
                continue
            data = res.get('data') or {}
            active = bool(data.get('active')) if isinstance(data, dict) else False
            checks.append(cls._service_row(server_id, unit, active, restartable))

        # Disk headroom from system:metrics (disk_percent = used %).
        res = agent_registry.send_command(
            server_id, 'system:metrics', {}, timeout=per_agent_timeout)
        if res and res.get('success') and isinstance(res.get('data'), dict):
            used = res['data'].get('disk_percent')
            if used is not None:
                try:
                    checks.append(cls._disk_row(100.0 - float(used)))
                except (TypeError, ValueError):
                    pass
        return checks

    @staticmethod
    def _service_row(server_id, unit, active, restartable):
        if active:
            return _row(f'service.{unit}', f'{unit} service', 'ok', 'Running.')
        return _row(
            f'service.{unit}', f'{unit} service', 'fail', 'Not running.',
            repairable=restartable,
            repair_ref=({'kind': 'fleet.service', 'server_id': server_id,
                         'name': unit} if restartable else None))

    @staticmethod
    def _disk_row(free_pct):
        detail = f'{free_pct:.1f}% free on /.'
        if free_pct < DISK_FAIL_FREE_PCT:
            return _row('disk.headroom', 'Disk headroom', 'fail', detail)
        if free_pct < DISK_WARN_FREE_PCT:
            return _row('disk.headroom', 'Disk headroom', 'warn', detail)
        return _row('disk.headroom', 'Disk headroom', 'ok', detail)

    # ------------------------------------------------------------------ #
    # DNS-vs-IP (panel-side host probe; no agent round trip)
    # ------------------------------------------------------------------ #

    @classmethod
    def _dns_check_for_server(cls, server):
        """Does the server's advertised hostname resolve back to its IP?"""
        key = 'dns.hostname'
        title = 'Hostname DNS'
        host = (getattr(server, 'hostname', None) or '').strip().lower().rstrip('.')
        ip = (getattr(server, 'ip_address', None) or '').strip()
        if not host or '.' not in host:
            return _row(key, title, 'ok', 'No public hostname to check.')
        if not ip:
            return _row(key, title, 'warn',
                        f'{host}: server IP is unknown, cannot verify DNS.')
        try:
            ips = _resolve_host_ips(host)
        except Exception:  # noqa: BLE001
            return _row(key, title, 'fail',
                        f'{host} does not resolve to any address.')
        if ip in ips:
            return _row(key, title, 'ok', f'{host} resolves to {ip}.')
        return _row(key, title, 'warn',
                    f'{host} resolves to {", ".join(ips)}, not this server ({ip}).')

    # ------------------------------------------------------------------ #
    # Persistence — one row per (server_id, check_key)
    # ------------------------------------------------------------------ #

    @classmethod
    def _persist(cls, server_id, checks, ran_at=None):
        """Upsert the given checks as FleetDoctorResult rows. Returns the number
        of rows written."""
        from app import db
        from app.models.fleet_doctor_result import FleetDoctorResult

        ran_at = ran_at or datetime.utcnow()
        written = 0
        for c in checks or []:
            key = c.get('key')
            if not key:
                continue
            row = FleetDoctorResult.query.filter_by(
                server_id=server_id, check_key=key).first()
            if row is None:
                row = FleetDoctorResult(server_id=server_id, check_key=key)
                db.session.add(row)
            row.status = c.get('status') or FleetDoctorResult.STATUS_OK
            row.title = c.get('title')
            row.detail = c.get('detail')
            row.repairable = bool(c.get('repairable'))
            row.set_repair_ref(c.get('repair_ref'))
            row.ran_at = ran_at
            written += 1
        try:
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()
            logger.exception('failed to persist fleet doctor rows for %s', server_id)
            return 0
        return written

    # ------------------------------------------------------------------ #
    # Sweep entrypoints
    # ------------------------------------------------------------------ #

    @classmethod
    def run_server(cls, server):
        """Probe one server (accepts a Server or a server_id) and persist its
        rows. Returns the list of check rows written."""
        if isinstance(server, str):
            from app.models.server import Server
            server = Server.query.get(server)
        if server is None:
            return []
        result = cls._compose_server_checks(server.id, SWEEP_PER_AGENT_TIMEOUT)
        rows = list(result.get('checks', []))
        rows.append(cls._dns_check_for_server(server))
        cls._persist(server.id, rows)
        return rows

    @classmethod
    def run_fleet_doctor(cls):
        """Run the health sweep across the whole fleet and persist per-server
        rows. Returns a summary dict. Call this from the job handler only."""
        servers = cls._target_servers()
        ran_at = datetime.utcnow()
        if not servers:
            return {'servers': 0, 'checks_written': 0,
                    'ran_at': ran_at.isoformat() + 'Z'}

        # Fan out the remote probe over connected agents (bounded, off-thread).
        probe = fleet_sweep(
            cls._compose_server_checks, servers,
            pool=SWEEP_POOL, per_agent_timeout=SWEEP_PER_AGENT_TIMEOUT,
            budget=SWEEP_BUDGET)

        written = 0
        statuses = {}
        for server in servers:
            res = probe.get(server.id) or {'status': 'offline', 'checks': []}
            statuses[res.get('status', 'ok')] = statuses.get(res.get('status', 'ok'), 0) + 1
            rows = list(res.get('checks', []))
            # DNS-vs-IP runs for every server, connected or not.
            rows.append(cls._dns_check_for_server(server))
            written += cls._persist(server.id, rows, ran_at=ran_at)

        return {'servers': len(servers), 'checks_written': written,
                'sweep_statuses': statuses, 'ran_at': ran_at.isoformat() + 'Z'}

    @classmethod
    def run_fleet_doctor_job(cls, job=None):
        """Job handler for ``doctor.fleet.run`` (scheduled sweep)."""
        return cls.run_fleet_doctor()

    # ------------------------------------------------------------------ #
    # Read side
    # ------------------------------------------------------------------ #

    @classmethod
    def results_for_server(cls, server_id):
        """All recorded rows for one server, newest first, as dicts."""
        from app.models.fleet_doctor_result import FleetDoctorResult
        rows = (FleetDoctorResult.query
                .filter_by(server_id=server_id)
                .order_by(FleetDoctorResult.check_key.asc())
                .all())
        return [r.to_dict() for r in rows]

    @classmethod
    def all_results(cls):
        """Every recorded fleet-doctor row grouped by server_id."""
        from app.models.fleet_doctor_result import FleetDoctorResult
        out = {}
        for r in FleetDoctorResult.query.all():
            out.setdefault(r.server_id, []).append(r.to_dict())
        return out

    # ------------------------------------------------------------------ #
    # Job plumbing
    # ------------------------------------------------------------------ #

    @classmethod
    def register_jobs(cls):
        """Register the fleet-doctor handler with the job registry. Called once
        at app startup (see app/__init__.py)."""
        from app.jobs import registry
        registry.register(FLEET_DOCTOR_JOB_KIND, cls.run_fleet_doctor_job,
                          replace=True)
