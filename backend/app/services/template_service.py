"""
Template Service - Manages application templates for one-click deployment.

Supports:
- YAML-based template schema
- Docker Compose compatibility
- Variable substitution
- Post-install scripts
- Template repositories (local + remote)
- Update mechanism
"""

import os
import re
import yaml
import json
import shutil
import secrets
import string
import hashlib
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import requests

from app import paths


class TemplateService:
    """Service for managing and deploying application templates."""

    CONFIG_DIR = paths.SERVERKIT_CONFIG_DIR
    TEMPLATES_DIR = paths.TEMPLATES_DIR
    LOCAL_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'templates')
    INSTALLED_DIR = paths.APPS_DIR
    TEMPLATE_CONFIG = os.path.join(CONFIG_DIR, 'templates.json')

    # Default template repository
    DEFAULT_REPOS = [
        {
            'name': 'serverkit-official',
            'url': 'https://raw.githubusercontent.com/serverkit/templates/main',
            'enabled': True
        }
    ]

    # Template schema version
    SCHEMA_VERSION = '1.0'

    # ==================================================================
    # The `engine:` block — what makes a template a database engine
    # ------------------------------------------------------------------
    # A template becomes installable from the Databases page purely by
    # carrying a top-level ``engine:`` mapping. Presence of the block is the
    # ONLY marker; there is no allow-list of engine ids anywhere in Python, so
    # shipping a new engine (CockroachDB, DuckDB, whatever) is dropping a YAML
    # file into ``backend/templates/`` or syncing a template repository.
    #
    #   engine:
    #     family: Relational              # see ENGINE_FAMILIES
    #     protocol: postgresql            # see ENGINE_PROTOCOLS
    #     default_port: 26257
    #     admin_user: root
    #     admin_password_var: DB_PASSWORD # which `variables` entry is the secret
    #     database_var: DB_NAME           # optional: seeds an initial database
    #     port_var: PORT                  # optional: which variable is the port
    #     bind_var: BIND_ADDRESS          # optional: private-vs-public bind
    #     unit: tables
    #     client: cockroach sql
    #     data_path: /cockroach/cockroach-data
    #
    # ``protocol: none`` is legitimate: the engine installs and is listed, but
    # the database tree offers no introspection for it. That is honest — better
    # than pretending we can browse it.
    # ==================================================================
    ENGINE_FAMILIES = (
        'Relational', 'Document', 'Key-value', 'Time-series',
        'Analytics', 'Search', 'Graph',
    )
    # Which client adapter (if any) can introspect the engine once it is up.
    ENGINE_PROTOCOLS = ('postgresql', 'mysql', 'mongodb', 'redis', 'none')

    # Conventional variable names, used when the block does not name its own.
    ENGINE_DEFAULT_PORT_VAR = 'PORT'
    ENGINE_DEFAULT_BIND_VAR = 'BIND_ADDRESS'
    # Safety rule 1: an engine is reachable only from the host unless the
    # operator explicitly opts out.
    ENGINE_PRIVATE_BIND = '127.0.0.1'
    ENGINE_PUBLIC_BIND = '0.0.0.0'

    @classmethod
    def get_config(cls) -> Dict:
        """Get template configuration."""
        if os.path.exists(cls.TEMPLATE_CONFIG):
            try:
                with open(cls.TEMPLATE_CONFIG, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            'repos': cls.DEFAULT_REPOS,
            'installed': {},
            'last_sync': None
        }

    @classmethod
    def save_config(cls, config: Dict) -> Dict:
        """Save template configuration."""
        try:
            os.makedirs(cls.CONFIG_DIR, exist_ok=True)
            with open(cls.TEMPLATE_CONFIG, 'w') as f:
                json.dump(config, f, indent=2)
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def validate_template(cls, template: Dict) -> Dict:
        """Validate a template against the schema."""
        errors = []

        # Required fields
        required = ['name', 'version', 'description']
        for field in required:
            if field not in template:
                errors.append(f"Missing required field: {field}")

        # A template is either a one-click compose/dockerfile stack (the default,
        # kind: compose) or a deployable Git repository (kind: repo). Repo
        # templates carry a `repo` block with a `url` instead of a compose stack;
        # they are deployed through the New Service wizard, not installed here.
        kind = template.get('kind', 'compose')
        if kind == 'repo':
            repo = template.get('repo')
            if not isinstance(repo, dict) or not repo.get('url'):
                errors.append("Repo template must have a 'repo' block with a 'url'")
        elif kind == 'compose':
            # Must have either compose or dockerfile
            if 'compose' not in template and 'dockerfile' not in template:
                errors.append("Template must have either 'compose' or 'dockerfile'")
        else:
            errors.append(f"Unknown template kind: {kind}")

        # Validate compose structure
        if 'compose' in template:
            compose = template['compose']
            if 'services' not in compose:
                errors.append("Compose section must have 'services'")

        # Validate variables (support both list and dict formats)
        if 'variables' in template:
            variables = template['variables']
            if isinstance(variables, list):
                # List format: [{name: 'PORT', type: 'port', ...}, ...]
                for var in variables:
                    if not isinstance(var, dict):
                        errors.append("Each variable in list must be a dictionary")
                    elif 'name' not in var:
                        errors.append("Each variable must have a 'name' field")
            elif isinstance(variables, dict):
                # Dict format: {PORT: {type: 'port', ...}, ...}
                for var_name, var_config in variables.items():
                    if not isinstance(var_config, dict):
                        errors.append(f"Variable {var_name} must be a dictionary")

        # Validate the optional `engine:` block. Unknown top-level keys were
        # already tolerated (this validator checks required fields, it does not
        # reject extras) -- what was missing is that a MALFORMED engine block
        # went unnoticed and then silently produced a broken catalog card.
        if 'engine' in template:
            errors.extend(cls._engine_block_errors(template['engine']))

        if errors:
            return {'valid': False, 'errors': errors}
        return {'valid': True}

    @classmethod
    def _engine_block_errors(cls, engine: Any) -> List[str]:
        """Hard errors in an ``engine:`` block (shape only, never opinions)."""
        if not isinstance(engine, dict):
            return ["'engine' must be a mapping"]
        errors = []
        family = engine.get('family')
        if family is not None and family not in cls.ENGINE_FAMILIES:
            errors.append(
                f"engine.family '{family}' is not one of: {', '.join(cls.ENGINE_FAMILIES)}")
        protocol = engine.get('protocol')
        if protocol is not None and protocol not in cls.ENGINE_PROTOCOLS:
            errors.append(
                f"engine.protocol '{protocol}' is not one of: {', '.join(cls.ENGINE_PROTOCOLS)}")
        port = engine.get('default_port')
        if port is not None:
            try:
                if not 1 <= int(port) <= 65535:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append('engine.default_port must be a port number (1-65535)')
        return errors

    @classmethod
    def is_engine_template(cls, template: Dict) -> bool:
        """True when a template declares itself a database engine."""
        return isinstance(template, dict) and isinstance(template.get('engine'), dict)

    @classmethod
    def engine_metadata(cls, template: Dict) -> Optional[Dict]:
        """Normalized ``engine:`` block, or ``None`` for a non-engine template.

        Fills in the conventional variable names so every consumer sees the same
        keys, and resolves ``versions`` from the template's own ``version`` plus
        any ``engine.versions`` the author offers. Nothing here is hardcoded per
        engine -- it is all read off the YAML.
        """
        if not cls.is_engine_template(template):
            return None
        engine = dict(template['engine'])
        versions = engine.get('versions')
        if not isinstance(versions, list) or not versions:
            versions = [template.get('version')] if template.get('version') else []
        return {
            'family': engine.get('family'),
            'protocol': engine.get('protocol') or 'none',
            'default_port': engine.get('default_port'),
            'admin_user': engine.get('admin_user'),
            'admin_password_var': engine.get('admin_password_var'),
            'database_var': engine.get('database_var'),
            'port_var': engine.get('port_var') or cls.ENGINE_DEFAULT_PORT_VAR,
            'bind_var': engine.get('bind_var') or cls.ENGINE_DEFAULT_BIND_VAR,
            'unit': engine.get('unit'),
            'client': engine.get('client'),
            'data_path': engine.get('data_path'),
            'versions': [str(v) for v in versions],
        }

    @classmethod
    def parse_template(cls, template_path: str) -> Dict:
        """Parse a template file."""
        try:
            with open(template_path, 'r') as f:
                template = yaml.safe_load(f)

            validation = cls.validate_template(template)
            if not validation['valid']:
                return {'success': False, 'errors': validation['errors']}

            return {'success': True, 'template': template}
        except yaml.YAMLError as e:
            return {'success': False, 'error': f"YAML parse error: {e}"}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def generate_value(cls, var_config: Dict, force_generate: bool = False) -> str:
        """Generate a value for a variable based on its configuration.

        Args:
            var_config: Variable configuration dict
            force_generate: If True, always generate new value even for ports
        """
        var_type = var_config.get('type', 'string')
        default = var_config.get('default', '')

        if var_type == 'password':
            length = var_config.get('length', 32)
            chars = string.ascii_letters + string.digits
            if var_config.get('special_chars', False):
                chars += '!@#$%^&*'
            return ''.join(secrets.choice(chars) for _ in range(length))

        elif var_type == 'port':
            # ALWAYS find an available port - never trust defaults
            start_port = int(default) if default else 8000
            # A global base-port setting (Settings > managed_app_base_port)
            # overrides the per-template default when configured (non-zero).
            base = cls._managed_app_base_port()
            if base:
                start_port = base
            return str(cls._find_available_port(start_port))

        elif var_type == 'uuid':
            import uuid
            return str(uuid.uuid4())

        elif var_type == 'random':
            length = var_config.get('length', 16)
            return secrets.token_hex(length // 2)

        return str(default)

    # ==================================================================
    # Magic variables
    # ------------------------------------------------------------------
    # "Magic variables" let template authors use industry-standard
    # placeholders that ServerKit auto-resolves at install time, instead of
    # declaring an explicit ``variables:`` entry for every generated secret.
    #
    # Supported tokens (used as ``${SERVICE_<KIND>_<NAME>}`` in compose / files /
    # scripts), where ``<NAME>`` is an author-chosen identifier that groups
    # related tokens (the same ``<NAME>`` resolves to a consistent value):
    #
    #   SERVICE_PASSWORD_<NAME>  -> a generated strong password
    #   SERVICE_USER_<NAME>      -> a generated service username (svc_<name>_<rand>)
    #   SERVICE_FQDN_<NAME>      -> the app's auto-assigned hostname (best-effort)
    #   SERVICE_URL_<NAME>       -> full URL derived from the FQDN (+ scheme)
    #   SERVICE_BASE64_<NAME>    -> base64 of a freshly generated secret
    #
    # Resolution is PURE and unit-testable: no Docker, no network. The only
    # contextual input is an optional ``context`` dict (app_name / fqdn / scheme).
    # ==================================================================

    # Order matters: longer prefixes (BASE64) must be matched before shorter
    # ones so they are not mis-parsed. Each entry maps the wire prefix to an
    # internal "kind".
    MAGIC_PREFIXES = [
        ('SERVICE_PASSWORD_', 'password'),
        ('SERVICE_USER_', 'user'),
        ('SERVICE_FQDN_', 'fqdn'),
        ('SERVICE_URL_', 'url'),
        ('SERVICE_BASE64_', 'base64'),
    ]

    # Matches ``${SERVICE_...}`` magic tokens specifically (a subset of the
    # generic ``${VAR}`` substitution pattern). ``<NAME>`` may be empty-safe:
    # we require at least one trailing char after the prefix.
    MAGIC_TOKEN_PATTERN = (
        r'\$\{(SERVICE_(?:PASSWORD|USER|FQDN|URL|BASE64)_[A-Z0-9_]+|SERVER_PUBLIC_IP)\}'
    )

    # Default password length for magic SERVICE_PASSWORD_* tokens.
    MAGIC_PASSWORD_LENGTH = 32

    @classmethod
    def _classify_magic_token(cls, token: str):
        """Return ``(kind, name)`` for a bare magic token (no ``${}``), or
        ``(None, None)`` if it is not a recognized magic variable."""
        if token == 'SERVER_PUBLIC_IP':  # appliance tier (plan 35), no name suffix
            return 'server_public_ip', ''
        for prefix, kind in cls.MAGIC_PREFIXES:
            if token.startswith(prefix):
                return kind, token[len(prefix):]
        return None, None

    @classmethod
    def _generate_magic_password(cls) -> str:
        """Strong password for a SERVICE_PASSWORD_* token (alnum, no special
        chars to stay shell/compose-safe). Reuses the same primitive as
        ``generate_value(type=password)``."""
        chars = string.ascii_letters + string.digits
        return ''.join(secrets.choice(chars) for _ in range(cls.MAGIC_PASSWORD_LENGTH))

    @classmethod
    def _generate_magic_user(cls, name: str) -> str:
        """Service username for a SERVICE_USER_* token: ``svc_<name>_<rand>``,
        lowercased and reduced to ``[a-z0-9_]`` so it is safe as a DB/app user."""
        base = re.sub(r'[^a-z0-9]+', '_', (name or 'service').lower()).strip('_') or 'service'
        suffix = secrets.token_hex(2)  # 4 hex chars, keeps it short but unique
        return f'svc_{base}_{suffix}'

    @classmethod
    def _resolve_magic_value(cls, kind: str, name: str, context: Dict) -> str:
        """Resolve a single magic token to a value.

        ``context`` may carry ``fqdn`` / ``scheme`` (and ``app_name``); when an
        FQDN is not known yet the FQDN/URL forms degrade to a documented
        placeholder (``localhost``) that the install finalizer can later fill —
        this keeps resolution best-effort and non-fatal.
        """
        context = context or {}
        if kind == 'password':
            return cls._generate_magic_password()
        if kind == 'user':
            return cls._generate_magic_user(name)
        if kind == 'base64':
            import base64
            secret = secrets.token_bytes(24)
            return base64.b64encode(secret).decode('ascii')
        if kind == 'fqdn':
            return str(context.get('fqdn') or context.get('app_name') or 'localhost')
        if kind == 'url':
            scheme = str(context.get('scheme') or 'http')
            host = context.get('fqdn') or context.get('app_name') or 'localhost'
            return f'{scheme}://{host}'
        if kind == 'server_public_ip':
            ip = context.get('server_public_ip')
            if not ip:
                try:
                    from app.services.site_domain_service import SiteDomainService
                    ip = SiteDomainService.server_ip()
                except Exception:
                    ip = None
            return str(ip or '')
        return ''

    @classmethod
    def resolve_magic_variables(cls, content: Any, context: Dict = None):
        """Scan ``content`` for ``${SERVICE_*}`` magic tokens, generate a value
        once per unique token, substitute, and return ``(substituted, generated)``.

        Args:
            content: A string, or a (possibly nested) dict/list — e.g. a parsed
                compose section. Returned with the same shape.
            context: Optional dict with ``app_name`` / ``fqdn`` / ``scheme`` used
                to resolve FQDN/URL tokens. No Docker/network access is performed.

        Returns:
            ``(substituted_content, generated_vars)`` where ``generated_vars`` maps
            each magic variable name (without ``${}``) to its generated value, so
            callers can persist them as env vars / surface them post-install.
            Pure and idempotent for a given ``content`` within one call (the same
            token always maps to the same generated value here).
        """
        context = context or {}
        generated: Dict[str, str] = {}

        def _collect(text: str):
            for match in re.finditer(cls.MAGIC_TOKEN_PATTERN, text):
                token = match.group(1)
                if token in generated:
                    continue
                kind, name = cls._classify_magic_token(token)
                if kind is None:
                    continue
                generated[token] = cls._resolve_magic_value(kind, name, context)

        def _walk_collect(node: Any):
            if isinstance(node, str):
                _collect(node)
            elif isinstance(node, dict):
                for value in node.values():
                    _walk_collect(value)
            elif isinstance(node, list):
                for item in node:
                    _walk_collect(item)

        # Pass 1: discover every unique token and generate a stable value.
        _walk_collect(content)

        # Pass 2: substitute using the generated values. Reuse the existing
        # ${VAR} substitution so behavior is identical to normal variables.
        if isinstance(content, str):
            substituted = cls.substitute_variables(content, generated)
        else:
            substituted = cls.substitute_in_dict(content, generated)

        return substituted, generated

    @classmethod
    def collect_magic_variables(cls, template: Dict, context: Dict = None) -> Dict[str, str]:
        """Generate the magic variables a template uses, given its declared
        ``compose`` / ``files`` / ``scripts`` sections, WITHOUT mutating the
        template. Returns ``{name: value}`` for every ``${SERVICE_*}`` token found.

        This is the wiring entry point for the install flow: the returned dict is
        merged into the install ``variables`` so the existing ``${VAR}``
        substitution renders the tokens, and so the secrets land in ``.env`` /
        post-install output. Templates with no magic tokens get ``{}`` and behave
        exactly as before.
        """
        # Scan the parts that the installer substitutes against.
        scan_target = {
            'compose': template.get('compose', {}),
            'files': template.get('files', []),
            'scripts': template.get('scripts', {}),
        }
        _, generated = cls.resolve_magic_variables(scan_target, context)
        return generated

    @classmethod
    def _install_magic_context(cls, template: Dict, app_name: str,
                               variables: Dict = None) -> Dict:
        """Build the best-effort ``context`` for magic-variable resolution at
        install time.

        Resolves the would-be FQDN from the managed-sites base domain when one is
        configured (the same ``<slug>.<base>`` the finalizer publishes), and the
        scheme from whether wildcard HTTPS is on. All of this is best-effort and
        non-fatal: if site routing isn't set up (or we're outside an app context),
        FQDN/URL tokens fall back to a documented ``localhost`` placeholder that
        the install finalizer can later fill in.
        """
        context = {'app_name': app_name}
        try:
            from app.services.site_domain_service import SiteDomainService
            base = SiteDomainService.base_domain()
            # Only assign an FQDN when the template opts into auto-domain and a
            # base domain exists — mirrors the finalizer's publish condition.
            if base and template.get('auto_domain'):
                host = SiteDomainService.subdomain_for(app_name)
                if host:
                    context['fqdn'] = host
                    context['scheme'] = 'https' if (
                        SiteDomainService.https_enabled()
                        and SiteDomainService.covers(host)
                    ) else 'http'
        except Exception:
            # No app context / site routing not available — leave FQDN unset so
            # tokens degrade to the localhost placeholder.
            pass
        return context

    @classmethod
    def _collect_magic_for_install(cls, template: Dict, app_name: str,
                                   variables: Dict = None) -> Dict[str, str]:
        """Resolve a template's magic variables for an install, using the
        best-effort FQDN context. Thin wrapper over :meth:`collect_magic_variables`."""
        context = cls._install_magic_context(template, app_name, variables)
        return cls.collect_magic_variables(template, context)

    @classmethod
    def validate_catalog_entry(cls, entry: Dict) -> Dict:
        """Lightweight validation of a declarative catalog entry (the YAML
        template shape documented in ``docs/TEMPLATE_CATALOG_SCHEMA.md``).

        Complements :meth:`validate_template` (which the loader uses) with a few
        catalog-level checks: an ``id`` slug, declared variable ``type`` values,
        and well-formed magic tokens. Returns ``{'valid': bool, 'errors': [...],
        'warnings': [...]}``. Non-fatal issues are reported as warnings so the
        loader stays permissive.
        """
        errors: List[str] = []
        warnings: List[str] = []

        if not isinstance(entry, dict):
            return {'valid': False, 'errors': ['Catalog entry must be a mapping'], 'warnings': []}

        # Reuse the canonical template validation for required fields/compose.
        base = cls.validate_template(entry)
        if not base.get('valid'):
            errors.extend(base.get('errors', []))

        # id should be a DNS/file-safe slug when present.
        entry_id = entry.get('id')
        if entry_id is not None:
            if not isinstance(entry_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', entry_id or ''):
                errors.append("Field 'id' must be a lowercase slug (a-z, 0-9, dashes)")

        # Validate declared variable types (list or dict form).
        known_types = {'string', 'password', 'port', 'uuid', 'random', 'boolean', 'select'}
        raw_vars = entry.get('variables', [])
        var_items = []
        if isinstance(raw_vars, list):
            var_items = [(v.get('name'), v) for v in raw_vars if isinstance(v, dict)]
        elif isinstance(raw_vars, dict):
            var_items = list(raw_vars.items())
        for var_name, var_config in var_items:
            if not isinstance(var_config, dict):
                continue
            vtype = var_config.get('type', 'string')
            if vtype not in known_types:
                warnings.append(f"Variable '{var_name}' uses unknown type '{vtype}'")

        # Validate any magic tokens embedded in compose/files/scripts.
        scan_target = {
            'compose': entry.get('compose', {}),
            'files': entry.get('files', []),
            'scripts': entry.get('scripts', {}),
        }

        def _check_tokens(node):
            if isinstance(node, str):
                for match in re.finditer(r'\$\{(SERVICE_[A-Z0-9_]+)\}', node):
                    token = match.group(1)
                    kind, name = cls._classify_magic_token(token)
                    if kind is None:
                        warnings.append(f"Unrecognized magic token '${{{token}}}'")
                    elif not name:
                        warnings.append(f"Magic token '${{{token}}}' is missing a <NAME> suffix")
            elif isinstance(node, dict):
                for value in node.values():
                    _check_tokens(value)
            elif isinstance(node, list):
                for item in node:
                    _check_tokens(item)

        _check_tokens(scan_target)

        # Engine templates: shape errors already came from validate_template
        # above. Here we add the soft checks -- a block that names variables
        # which don't exist would install, but the Databases UI could not find
        # the password field or the port field.
        if cls.is_engine_template(entry):
            engine = entry['engine']
            declared = {name for name, _ in var_items if name}
            for key in ('admin_password_var', 'database_var', 'port_var', 'bind_var'):
                var_name = engine.get(key)
                if var_name and var_name not in declared:
                    warnings.append(
                        f"engine.{key} references '{var_name}', which is not a declared variable")
            if not engine.get('family'):
                warnings.append('engine block has no family; it will not match a family filter')

        return {'valid': not errors, 'errors': errors, 'warnings': warnings}

    @classmethod
    def validate_mysql_connection(cls, host: str, port: int, user: str,
                                   password: str, database: str) -> Dict:
        """Validate MySQL database connection.

        Args:
            host: Database host
            port: Database port
            user: Database username
            password: Database password
            database: Database name

        Returns:
            Dict with 'success' and optional 'error' or 'warning' message
        """
        import socket

        try:
            # First check if host:port is reachable
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, int(port)))
            sock.close()

            if result != 0:
                return {
                    'success': False,
                    'error': f'Cannot connect to {host}:{port} - host unreachable'
                }

            # Try MySQL connection if pymysql available
            try:
                import pymysql
                conn = pymysql.connect(
                    host=host,
                    port=int(port),
                    user=user,
                    password=password,
                    database=database,
                    connect_timeout=5
                )
                conn.close()
                return {'success': True}
            except ImportError:
                # pymysql not available, just check port was reachable
                return {
                    'success': True,
                    'warning': 'MySQL library not available, only port check performed'
                }
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Database connection failed: {str(e)}'
                }

        except Exception as e:
            return {
                'success': False,
                'error': f'Connection check failed: {str(e)}'
            }

    @classmethod
    def _managed_app_base_port(cls) -> int:
        """Return the admin-configured base port for managed apps, or 0 if unset.

        Reads the ``managed_app_base_port`` system setting. Returns 0 (meaning
        "use each template's own default") on any error, e.g. if the settings
        table isn't ready yet during early startup.
        """
        try:
            from app.services.settings_service import SettingsService
            return int(SettingsService.get('managed_app_base_port', 0) or 0)
        except Exception:
            return 0

    @classmethod
    def _find_available_port(cls, start_port: int = 8000, max_attempts: int = 1000) -> int:
        """Find an available port that's not in use by the system, Docker, or database.

        Checks:
        1. Ports assigned to existing applications in the database
        2. Docker container port mappings
        3. Socket binding test
        """
        import socket

        # Get ports from database (assigned to apps)
        db_ports = cls._get_database_used_ports()

        # Get ports currently used by Docker containers
        docker_ports = cls._get_docker_used_ports()

        # Combine all used ports
        used_ports = db_ports | docker_ports

        for port in range(start_port, start_port + max_attempts):
            # Skip reserved/common ports
            if port < 1024:
                continue

            # Skip if already assigned in DB or Docker
            if port in used_ports:
                continue

            # Check if port is available on localhost (where Docker binds)
            try:
                # Try to bind - most reliable check
                test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                test_sock.bind(('127.0.0.1', port))
                test_sock.close()
                return port
            except OSError:
                continue
            except Exception:
                continue

        # Fallback: return a random high port
        import random
        return random.randint(10000, 60000)

    @classmethod
    def _port_is_free(cls, port) -> bool:
        """True when nothing -- app row, container, or live socket -- holds
        ``port``. Same three sources as :meth:`_find_available_port`, asked
        about one specific port instead of scanning."""
        import socket
        try:
            port = int(port)
        except (TypeError, ValueError):
            return False
        if not 1 <= port <= 65535:
            return False
        if port in (cls._get_database_used_ports() | cls._get_docker_used_ports()):
            return False
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_sock.bind(('127.0.0.1', port))
            test_sock.close()
            return True
        except OSError:
            return False
        except Exception:
            return False

    @classmethod
    def _get_database_used_ports(cls) -> set:
        """Get all ports assigned to applications in the database."""
        used_ports = set()
        try:
            from app.models import Application
            apps = Application.query.filter(Application.port.isnot(None)).all()
            for app in apps:
                if app.port:
                    used_ports.add(app.port)
        except Exception:
            pass
        return used_ports

    @classmethod
    def _get_docker_used_ports(cls) -> set:
        """Get all ports currently mapped by Docker containers."""
        used_ports = set()
        try:
            result = subprocess.run(
                ['docker', 'ps', '--format', '{{.Ports}}'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                # Parse port mappings like "0.0.0.0:8080->80/tcp, 127.0.0.1:3306->3306/tcp"
                import re
                for line in result.stdout.strip().split('\n'):
                    if line:
                        # Find all host ports in the format "host:port->container"
                        matches = re.findall(r'(?:[\d.]+:)?(\d+)->', line)
                        for port_str in matches:
                            try:
                                used_ports.add(int(port_str))
                            except ValueError:
                                pass
        except Exception:
            pass
        return used_ports

    @classmethod
    def substitute_variables(cls, content: str, variables: Dict) -> str:
        """Substitute variables in content using ${VAR} syntax."""
        def replace_var(match):
            var_name = match.group(1)
            return str(variables.get(var_name, match.group(0)))

        # Replace ${VAR} patterns
        pattern = r'\$\{([A-Z_][A-Z0-9_]*)\}'
        return re.sub(pattern, replace_var, content)

    @classmethod
    def substitute_in_dict(cls, data: Any, variables: Dict) -> Any:
        """Recursively substitute variables in a dictionary."""
        if isinstance(data, str):
            return cls.substitute_variables(data, variables)
        elif isinstance(data, dict):
            return {k: cls.substitute_in_dict(v, variables) for k, v in data.items()}
        elif isinstance(data, list):
            return [cls.substitute_in_dict(item, variables) for item in data]
        return data

    @classmethod
    def generate_compose(cls, template: Dict, variables: Dict) -> str:
        """Generate docker-compose.yml from template."""
        compose = template.get('compose', {})

        # Substitute variables
        compose = cls.substitute_in_dict(compose, variables)

        # Remove obsolete version field (not needed in modern Docker Compose)
        if 'version' in compose:
            del compose['version']

        return yaml.dump(compose, default_flow_style=False, sort_keys=False)

    @classmethod
    def list_local_templates(cls) -> List[Dict]:
        """List locally available templates."""
        templates = []
        seen_ids = set()

        for templates_dir in [cls.TEMPLATES_DIR, cls.LOCAL_TEMPLATES_DIR]:
            if not os.path.exists(templates_dir):
                continue

            for filename in os.listdir(templates_dir):
                if filename.endswith('.yaml') or filename.endswith('.yml'):
                    template_id = filename.rsplit('.', 1)[0]
                    if template_id in seen_ids:
                        continue
                    filepath = os.path.join(templates_dir, filename)
                    result = cls.parse_template(filepath)
                    if result.get('success'):
                        template = result['template']
                        seen_ids.add(template_id)
                        kind = template.get('kind', 'compose')
                        entry = {
                            'id': template_id,
                            'name': template.get('name'),
                            'version': template.get('version'),
                            'description': template.get('description'),
                            'icon': template.get('icon'),
                            'categories': template.get('categories', []),
                            'kind': kind,
                            'source': 'local',
                            'filepath': filepath
                        }
                        # Repo templates surface a minimal repo summary so the
                        # catalog grid can badge them and link to the wizard
                        # without a second fetch.
                        if kind == 'repo' and isinstance(template.get('repo'), dict):
                            repo = template['repo']
                            entry['repo'] = {
                                'url': repo.get('url'),
                                'branch': repo.get('branch', 'main'),
                            }
                        # A database engine declares itself with a top-level
                        # `engine:` block. This listing is a fixed projection,
                        # so without carrying the block through, the Databases
                        # catalog could never see an engine without re-parsing
                        # every YAML file.
                        engine = cls.engine_metadata(template)
                        if engine:
                            entry['engine'] = engine
                        templates.append(entry)

        return templates

    @classmethod
    def list_engine_templates(cls) -> List[Dict]:
        """Every available template carrying an ``engine:`` block.

        This is what the Databases engine catalog renders. It is derived
        entirely from the template sources -- drop a new engine YAML into
        ``backend/templates/`` (or sync a repository that ships one) and it
        appears here with no code change.
        """
        return [t for t in cls.list_all_templates()
                if isinstance(t.get('engine'), dict)]

    @classmethod
    def build_repo_index(cls, repo_name: str = 'serverkit-official') -> Dict:
        """Build the ``index.json`` document that describes the locally-bundled
        templates as a publishable repository.

        This is the exact shape :meth:`fetch_remote_templates` / :meth:`sync_templates`
        consume from ``<repo_url>/index.json`` (templates served at
        ``<repo_url>/templates/<id>.yaml``). Publishing a repo is then just:
        host the ``templates/*.yaml`` files plus this ``index.json``. Lets
        Prompture Hub & friends ship template updates without a panel release.
        """
        templates = []
        for t in cls.list_local_templates():
            entry = {
                'id': t['id'],
                'name': t.get('name'),
                'version': t.get('version'),
                'description': t.get('description'),
                'icon': t.get('icon'),
                'categories': t.get('categories', []),
            }
            # Carried in the index so a panel that syncs this repo can list the
            # engine catalog without fetching all 100+ template files first.
            if isinstance(t.get('engine'), dict):
                entry['engine'] = t['engine']
            templates.append(entry)
        return {
            'name': repo_name,
            'schema_version': cls.SCHEMA_VERSION,
            'generated_at': datetime.now().isoformat(),
            'count': len(templates),
            'templates': templates,
        }

    @classmethod
    def export_repo_index(cls, dest_path: str = None) -> Dict:
        """Write :meth:`build_repo_index` to ``dest_path`` (defaults to
        ``index.json`` alongside the bundled templates). Returns a status dict."""
        index = cls.build_repo_index()
        path = dest_path or os.path.join(cls.LOCAL_TEMPLATES_DIR, 'index.json')
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(index, f, indent=2)
            return {'success': True, 'path': path, 'count': index['count']}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def fetch_remote_templates(cls, repo_url: str) -> List[Dict]:
        """Fetch templates from a remote repository."""
        templates = []

        try:
            # Fetch index.json from repo
            index_url = f"{repo_url}/index.json"
            response = requests.get(index_url, timeout=30)
            response.raise_for_status()

            index = response.json()
            for template_info in index.get('templates', []):
                template_info['source'] = 'remote'
                template_info['repo_url'] = repo_url
                templates.append(template_info)

        except Exception as e:
            print(f"Failed to fetch templates from {repo_url}: {e}")

        return templates

    @classmethod
    def list_all_templates(cls, category: str = None, search: str = None) -> List[Dict]:
        """List all available templates from all sources."""
        templates = []

        # Local templates
        templates.extend(cls.list_local_templates())

        # Remote templates
        config = cls.get_config()
        for repo in config.get('repos', []):
            if repo.get('enabled', True):
                templates.extend(cls.fetch_remote_templates(repo['url']))

        # Filter by category
        if category:
            templates = [t for t in templates if category in t.get('categories', [])]

        # Search filter
        if search:
            search_lower = search.lower()
            templates = [
                t for t in templates
                if search_lower in t.get('name', '').lower()
                or search_lower in t.get('description', '').lower()
            ]

        return templates

    @classmethod
    def get_template(cls, template_id: str) -> Dict:
        """Get full template details."""
        # Check local directories (system dir, then bundled fallback)
        for templates_dir in [cls.TEMPLATES_DIR, cls.LOCAL_TEMPLATES_DIR]:
            for ext in ['.yaml', '.yml']:
                filepath = os.path.join(templates_dir, f"{template_id}{ext}")
                if os.path.exists(filepath):
                    result = cls.parse_template(filepath)
                    if result.get('success'):
                        template = result['template']
                        template['source'] = 'local'
                        template['filepath'] = filepath
                        return {'success': True, 'template': template}
                    return result

        # Check remote repos
        config = cls.get_config()
        for repo in config.get('repos', []):
            if not repo.get('enabled', True):
                continue

            try:
                url = f"{repo['url']}/templates/{template_id}.yaml"
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
                    template = yaml.safe_load(response.text)
                    validation = cls.validate_template(template)
                    if validation['valid']:
                        template['source'] = 'remote'
                        template['repo_url'] = repo['url']
                        return {'success': True, 'template': template}
            except Exception:
                continue

        return {'success': False, 'error': 'Template not found'}

    @classmethod
    def build_template_hints(cls, template: Dict) -> Dict:
        """Build a manifest-shaped payload from a repo template's declared
        ``repo`` hints, used as an honest fallback when the public repo cannot be
        inspected live. Mirrors ``RepositoryManifestService`` output so the wizard
        renders it with the same code path; the caller tags ``source`` so the UI
        can label confidence.
        """
        repo = template.get('repo') if isinstance(template.get('repo'), dict) else {}
        build_method = repo.get('build_method')
        recommended = {
            'app_type': repo.get('app_type'),
            'build_method': build_method,
            'port': repo.get('port'),
            'dockerfile_path': repo.get('dockerfile_path')
            or ('Dockerfile' if build_method == 'dockerfile' else None),
            'custom_build_cmd': repo.get('build_command'),
            'custom_start_cmd': repo.get('start_command'),
            'healthcheck_path': repo.get('healthcheck_path'),
        }
        manifests = [
            {
                'type': 'template-hint',
                'file': file_name,
                'label': file_name,
                'summary': 'Declared by template',
            }
            for file_name in (repo.get('manifest_files') or [])
        ]
        env = []
        for item in (repo.get('env') or []):
            if isinstance(item, dict) and item.get('key'):
                env.append({
                    'key': item['key'],
                    'value': None if item.get('secret') else item.get('value'),
                    'required': bool(item.get('required')),
                    'secret': bool(item.get('secret')),
                    'source': 'template-hints',
                    'description': item.get('description', ''),
                })
        return {
            'success': True,
            'strategy': repo.get('strategy')
            or ('docker_compose' if build_method else None),
            'recommended': recommended,
            'manifests': manifests,
            'env': env,
            'ports': [repo['port']] if repo.get('port') else [],
            'detected_files': list(repo.get('manifest_files') or []),
            'warnings': [],
        }

    @classmethod
    def build_install_plan(cls, template_id: str, app_name: str,
                           user_variables: Dict = None, user_id: int = None,
                           server_id: str = None) -> Dict:
        """Build a reusable deployment plan for installing a template.

        The returned plan can be executed locally or by a connected agent.
        """
        result = cls.get_template(template_id)
        if not result.get('success'):
            return result

        template = result['template']
        variables_result = cls._prepare_install_variables(
            template_id,
            template,
            app_name,
            user_variables or {},
        )
        if not variables_result.get('success'):
            return variables_result

        variables = variables_result['variables']
        app_path = os.path.join(cls.INSTALLED_DIR, app_name)
        compose_file = os.path.join(app_path, 'docker-compose.yml')

        compose_result = cls._render_compose_and_files(template, variables, app_path)
        if not compose_result.get('success'):
            return compose_result

        install_info = {
            'template_id': template_id,
            'template_version': template.get('version'),
            'template_name': template.get('name'),
            'installed_at': datetime.now().isoformat(),
            'variables': variables,
            'user_id': user_id,
            'server_id': server_id,
        }

        env_content = ''.join(f"{key}={value}\n" for key, value in variables.items())

        app_port = None
        for port_var in ['PORT', 'HTTP_PORT', 'WEB_PORT']:
            if port_var in variables:
                try:
                    app_port = int(variables[port_var])
                    break
                except (ValueError, TypeError):
                    pass

        files = [
            {
                'path': compose_file,
                'content': compose_result['compose_content'],
                'mode': 0o644,
            },
            {
                'path': os.path.join(app_path, '.serverkit-template.json'),
                'content': json.dumps(install_info, indent=2),
                'mode': 0o600,
            },
            {
                'path': os.path.join(app_path, '.env'),
                'content': env_content,
                'mode': 0o600,
            },
        ]
        files.extend(compose_result.get('files', []))

        steps = []
        for file_def in files:
            steps.append({
                'type': 'file.write',
                'name': f"Write {os.path.basename(file_def['path'])}",
                'path': file_def['path'],
                'content': file_def['content'],
                'mode': file_def.get('mode', 0o644),
                'create_dirs': True,
            })

        steps.append({
            'type': 'docker.compose.up',
            'name': 'Start Docker Compose stack',
            'project_dir': app_path,
            'compose_file': compose_file,
            'detach': True,
            'build': True,
            'timeout': 300,
        })
        steps.append({
            'type': 'sleep',
            'name': 'Wait for containers to initialize',
            'seconds': 3,
        })
        steps.append({
            'type': 'docker.compose.ps',
            'name': 'Capture container status',
            'project_dir': app_path,
            'compose_file': compose_file,
            'timeout': 30,
        })

        return {
            'success': True,
            'plan': {
                'kind': 'template_install',
                'template_id': template_id,
                'template_name': template.get('name'),
                'template_version': template.get('version'),
                'app_name': app_name,
                'app_path': app_path,
                'compose_file': compose_file,
                'variables': variables,
                'port': app_port,
                'server_id': server_id,
                'steps': steps,
            },
            'template': template,
            'variables': variables,
            'app_path': app_path,
            'port': app_port,
        }

    @classmethod
    def _prepare_install_variables(cls, template_id: str, template: Dict,
                                    app_name: str, user_variables: Dict) -> Dict:
        """Prepare template variables for installation."""
        variables = {
            'APP_NAME': app_name,
        }
        template_vars = template.get('variables', {})

        if isinstance(template_vars, list):
            template_vars = {v['name']: v for v in template_vars if isinstance(v, dict) and 'name' in v}

        for var_name, var_config in template_vars.items():
            var_type = var_config.get('type', 'string')

            if var_type == 'port':
                # Ports are auto-assigned by default (template defaults are
                # never trusted). An explicitly REQUESTED port is honored, but
                # only after confirming it is actually free -- so the caller
                # still can never be handed a port that is already bound. The
                # Databases engine installer relies on this to make its
                # documented `port` parameter real rather than advisory.
                requested = (user_variables or {}).get(var_name)
                if requested and cls._port_is_free(requested):
                    variables[var_name] = str(requested)
                else:
                    variables[var_name] = cls.generate_value(var_config)
            elif user_variables and var_name in user_variables and user_variables[var_name]:
                variables[var_name] = user_variables[var_name]
            elif var_config.get('required', False) and var_name not in user_variables:
                return {'success': False, 'error': f"Required variable not provided: {var_name}"}
            else:
                variables[var_name] = cls.generate_value(var_config)

        if template_id == 'wordpress-external-db':
            db_check = cls.validate_mysql_connection(
                host=variables.get('DB_HOST'),
                port=variables.get('DB_PORT', '3306'),
                user=variables.get('DB_USER'),
                password=variables.get('DB_PASSWORD'),
                database=variables.get('DB_NAME')
            )
            if not db_check.get('success'):
                return {
                    'success': False,
                    'error': f"Database connection failed: {db_check.get('error')}"
                }

        # Resolve magic variables (${SERVICE_PASSWORD_*} etc.) used in the
        # template's compose/files/scripts and merge the generated values into the
        # install variables. A template with no magic tokens gets {} here, so this
        # is a no-op for existing templates. User-supplied values win.
        magic = cls._collect_magic_for_install(template, app_name, variables)
        for key, value in magic.items():
            variables.setdefault(key, value)

        return {'success': True, 'variables': variables}

    @classmethod
    def _render_compose_and_files(cls, template: Dict, variables: Dict, app_path: str) -> Dict:
        """Render compose YAML and any template-defined files in memory."""
        try:
            compose = cls.substitute_in_dict(template.get('compose', {}), variables)
            if 'version' in compose:
                del compose['version']

            rendered_files = []
            bind_mounts = []

            for file_def in template.get('files', []) or []:
                container_path = file_def.get('path')
                content = file_def.get('content', '')
                if not container_path:
                    continue

                content = cls.substitute_variables(content, variables)
                filename = os.path.basename(container_path)
                rendered_files.append({
                    'path': os.path.join(app_path, filename),
                    'content': content,
                    'mode': int(file_def.get('mode', 0o644)),
                })
                # Only absolute container paths are bind-mounted into the
                # container (e.g. /app/config.yaml). A relative path like
                # 'Dockerfile' is a build-context file: it is written into the
                # app directory only — mounting it would produce an invalid
                # './Dockerfile:Dockerfile' volume spec and compose up fails.
                if container_path.startswith('/'):
                    bind_mounts.append({
                        'local': f'./{filename}',
                        'container': container_path,
                        'container_dir': os.path.dirname(container_path),
                    })

            if bind_mounts:
                cls._apply_bind_mounts_to_compose(compose, bind_mounts)

            return {
                'success': True,
                'compose_content': yaml.dump(compose, default_flow_style=False, sort_keys=False),
                'files': rendered_files,
            }
        except Exception as e:
            return {'success': False, 'error': f'Failed to render template: {str(e)}'}

    @classmethod
    def _apply_bind_mounts_to_compose(cls, compose: Dict, bind_mounts: List[Dict]) -> None:
        """Apply file bind mounts to a compose dictionary."""
        volumes_to_remove = set()

        for service in compose.get('services', {}).values():
            volumes = service.get('volumes', [])
            new_volumes = []

            for vol in volumes:
                if isinstance(vol, str):
                    parts = vol.split(':')
                    if len(parts) >= 2:
                        mount_target = parts[1].rstrip('/')
                        should_replace = any(
                            mount_target == mount['container_dir'].rstrip('/')
                            for mount in bind_mounts
                        )
                        if should_replace:
                            volumes_to_remove.add(parts[0])
                            continue
                new_volumes.append(vol)

            for mount in bind_mounts:
                bind_mount = f"{mount['local']}:{mount['container']}"
                if bind_mount not in new_volumes:
                    new_volumes.append(bind_mount)

            service['volumes'] = new_volumes

        if 'volumes' in compose:
            for volume_name in volumes_to_remove:
                compose['volumes'].pop(volume_name, None)
            if not compose['volumes']:
                del compose['volumes']

    @classmethod
    def install_template(cls, template_id: str, app_name: str,
                        user_variables: Dict = None, user_id: int = None) -> Dict:
        """Install a template as a new application."""
        from app import db
        from app.models import Application
        from app.services.docker_service import DockerService

        # Get template
        result = cls.get_template(template_id)
        if not result.get('success'):
            return result

        template = result['template']

        # Prepare variables - start with automatic variables
        variables = {
            'APP_NAME': app_name,
        }
        template_vars = template.get('variables', {})

        # Handle both dict format (new) and list format (old)
        if isinstance(template_vars, list):
            # Convert list format to dict
            template_vars = {v['name']: v for v in template_vars if 'name' in v}

        for var_name, var_config in template_vars.items():
            var_type = var_config.get('type', 'string')

            # ALWAYS auto-generate ports - never use user values for ports
            if var_type == 'port':
                variables[var_name] = cls.generate_value(var_config)
            elif user_variables and var_name in user_variables and user_variables[var_name]:
                variables[var_name] = user_variables[var_name]
            elif var_config.get('required', False) and var_name not in (user_variables or {}):
                return {'success': False, 'error': f"Required variable not provided: {var_name}"}
            else:
                variables[var_name] = cls.generate_value(var_config)

        # Validate external database connection for external-db templates
        if template_id == 'wordpress-external-db':
            db_check = cls.validate_mysql_connection(
                host=variables.get('DB_HOST'),
                port=variables.get('DB_PORT', '3306'),
                user=variables.get('DB_USER'),
                password=variables.get('DB_PASSWORD'),
                database=variables.get('DB_NAME')
            )
            if not db_check.get('success'):
                return {
                    'success': False,
                    'error': f"Database connection failed: {db_check.get('error')}"
                }

        # Resolve magic variables (${SERVICE_*}) and merge generated values.
        # No-op for templates that don't use magic tokens; user values win.
        for key, value in cls._collect_magic_for_install(template, app_name, variables).items():
            variables.setdefault(key, value)

        # Create app directory
        app_path = os.path.join(cls.INSTALLED_DIR, app_name)
        if os.path.exists(app_path):
            return {'success': False, 'error': f"App directory already exists: {app_path}"}

        try:
            os.makedirs(app_path, exist_ok=True)

            # Generate docker-compose.yml
            compose_content = cls.generate_compose(template, variables)
            compose_path = os.path.join(app_path, 'docker-compose.yml')
            with open(compose_path, 'w') as f:
                f.write(compose_content)

            # Save installation info
            install_info = {
                'template_id': template_id,
                'template_version': template.get('version'),
                'template_name': template.get('name'),
                'installed_at': datetime.now().isoformat(),
                'variables': variables,
                'user_id': user_id
            }
            info_path = os.path.join(app_path, '.serverkit-template.json')
            with open(info_path, 'w') as f:
                json.dump(install_info, f, indent=2)

            # Save .env file with variables
            env_path = os.path.join(app_path, '.env')
            with open(env_path, 'w') as f:
                for key, value in variables.items():
                    f.write(f"{key}={value}\n")

            # Process template files section - create files and update compose for bind mounts
            if 'files' in template:
                files_result = cls._process_template_files(
                    template['files'],
                    app_path,
                    compose_path,
                    variables
                )
                if not files_result.get('success'):
                    shutil.rmtree(app_path)
                    return files_result

            # Run pre-install script if exists
            if 'scripts' in template and 'pre_install' in template['scripts']:
                script_result = cls._run_script(
                    template['scripts']['pre_install'],
                    app_path,
                    variables
                )
                if not script_result.get('success'):
                    shutil.rmtree(app_path)
                    return script_result

            # Start the app with docker compose
            compose_result = DockerService.compose_up(app_path, detach=True, build=True)
            if not compose_result.get('success'):
                shutil.rmtree(app_path)
                return compose_result

            # Verify container started and port is accessible
            import time
            time.sleep(3)  # Give containers time to fully start

            # Run post-install script if exists
            if 'scripts' in template and 'post_install' in template['scripts']:
                cls._run_script(
                    template['scripts']['post_install'],
                    app_path,
                    variables
                )

            # Create application record
            # Look for port in variables - templates may use PORT or HTTP_PORT
            app_port = None
            for port_var in ['PORT', 'HTTP_PORT', 'WEB_PORT']:
                if port_var in variables:
                    try:
                        app_port = int(variables[port_var])
                        break
                    except (ValueError, TypeError):
                        pass

            # Verify port is accessible after startup
            port_accessible = False
            port_warning = None
            if app_port:
                port_check = DockerService.check_port_accessible(app_port)
                port_accessible = port_check.get('accessible', False)
                if not port_accessible:
                    port_warning = f"Port {app_port} is not accessible after container start. Container may still be initializing or port mapping may be incorrect."
                    print(f"Warning: {port_warning}")

            app = Application(
                name=app_name,
                app_type='docker',
                status='running',
                root_path=app_path,
                docker_image=template.get('name'),
                user_id=user_id or 1,
                port=app_port
            )
            db.session.add(app)
            db.session.commit()

            # Update installed config
            config = cls.get_config()
            config.setdefault('installed', {})[str(app.id)] = {
                'template_id': template_id,
                'template_version': template.get('version'),
                'app_id': app.id,
                'app_name': app_name,
                'installed_at': datetime.now().isoformat()
            }
            cls.save_config(config)

            result = {
                'success': True,
                'app_id': app.id,
                'app_name': app_name,
                'app_path': app_path,
                'variables': variables,
                'port': app_port,
                'port_accessible': port_accessible
            }

            if port_warning:
                result['port_warning'] = port_warning

            return result

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Template install service error: {error_trace}")
            if os.path.exists(app_path):
                shutil.rmtree(app_path)
            return {'success': False, 'error': str(e), 'trace': error_trace}

    @classmethod
    def _process_template_files(cls, files: List[Dict], app_path: str,
                                 compose_path: str, variables: Dict) -> Dict:
        """Process template files section - create files and update compose for bind mounts.

        This method:
        1. Creates files defined in the template's 'files' section
        2. Updates docker-compose.yml to bind mount these files into containers

        Args:
            files: List of file definitions from template (path, content)
            app_path: Path to the app directory
            compose_path: Path to the docker-compose.yml file
            variables: Variables dict for substitution

        Returns:
            Dict with success status
        """
        try:
            created_files = []
            bind_mounts = []  # Track files that need to be bind mounted

            for file_def in files:
                container_path = file_def.get('path')
                content = file_def.get('content', '')

                if not container_path:
                    continue

                # Substitute variables in content
                content = cls.substitute_variables(content, variables)

                # Determine local filename (use basename of container path)
                filename = os.path.basename(container_path)
                local_path = os.path.join(app_path, filename)

                # Write file locally
                with open(local_path, 'w') as f:
                    f.write(content)

                created_files.append(filename)

                # Track for bind mount: local file -> container path
                # Get the container directory from the path
                container_dir = os.path.dirname(container_path)
                bind_mounts.append({
                    'local': f'./{filename}',
                    'container': container_path,
                    'container_dir': container_dir
                })

            # Update docker-compose.yml to use bind mounts instead of named volumes
            if bind_mounts:
                cls._update_compose_with_bind_mounts(compose_path, bind_mounts)

            return {
                'success': True,
                'files_created': created_files,
                'bind_mounts': len(bind_mounts)
            }

        except Exception as e:
            return {'success': False, 'error': f'Failed to process template files: {str(e)}'}

    @classmethod
    def _update_compose_with_bind_mounts(cls, compose_path: str, bind_mounts: List[Dict]) -> None:
        """Update docker-compose.yml to use bind mounts for template files.

        Replaces named volume mounts with bind mounts for specific container paths.

        Args:
            compose_path: Path to docker-compose.yml
            bind_mounts: List of bind mount definitions
        """
        with open(compose_path, 'r') as f:
            compose = yaml.safe_load(f)

        # Group bind mounts by container directory
        dir_to_files = {}
        for mount in bind_mounts:
            dir_to_files.setdefault(mount['container_dir'], []).append(mount)

        # Process each service
        for service_name, service in compose.get('services', {}).items():
            volumes = service.get('volumes', [])
            new_volumes = []
            volumes_to_remove = set()

            for vol in volumes:
                if isinstance(vol, str):
                    # Parse volume string: "name:/path" or "./local:/path"
                    parts = vol.split(':')
                    if len(parts) >= 2:
                        mount_target = parts[1].rstrip('/')

                        # Check if this volume's target directory matches any of our file paths
                        should_replace = False
                        for mount in bind_mounts:
                            container_dir = mount['container_dir'].rstrip('/')
                            if mount_target == container_dir:
                                # This named volume covers a directory where we need to place files
                                should_replace = True
                                volumes_to_remove.add(parts[0])  # Track volume name to remove
                                break

                        if not should_replace:
                            new_volumes.append(vol)
                    else:
                        new_volumes.append(vol)
                else:
                    new_volumes.append(vol)

            # Add bind mounts for our files
            for mount in bind_mounts:
                bind_mount_str = f"{mount['local']}:{mount['container']}"
                if bind_mount_str not in new_volumes:
                    new_volumes.append(bind_mount_str)

            service['volumes'] = new_volumes

        # Remove unused named volumes from top-level volumes section
        if 'volumes' in compose and volumes_to_remove:
            for vol_name in volumes_to_remove:
                if vol_name in compose['volumes']:
                    del compose['volumes'][vol_name]
            # Remove volumes section if empty
            if not compose['volumes']:
                del compose['volumes']

        # Write updated compose file
        with open(compose_path, 'w') as f:
            yaml.dump(compose, f, default_flow_style=False, sort_keys=False)

    @classmethod
    def _run_script(cls, script: str, cwd: str, variables: Dict) -> Dict:
        """Run a script with variable substitution."""
        try:
            script = cls.substitute_variables(script, variables)

            env = os.environ.copy()
            env.update(variables)

            result = subprocess.run(
                ['bash', '-c', script],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                return {
                    'success': False,
                    'error': f"Script failed: {result.stderr}",
                    'output': result.stdout
                }

            return {'success': True, 'output': result.stdout}

        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Script timed out'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def check_updates(cls, app_id: int) -> Dict:
        """Check if an installed app has template updates available."""
        config = cls.get_config()
        installed = config.get('installed', {}).get(str(app_id))

        if not installed:
            return {'success': False, 'error': 'App not installed from template'}

        template_id = installed['template_id']
        installed_version = installed['template_version']

        # Get latest template
        result = cls.get_template(template_id)
        if not result.get('success'):
            return result

        latest_version = result['template'].get('version')

        return {
            'success': True,
            'installed_version': installed_version,
            'latest_version': latest_version,
            'update_available': latest_version != installed_version
        }

    @classmethod
    def update_app(cls, app_id: int, user_id: int = None) -> Dict:
        """Update an installed app to the latest template version."""
        from app import db
        from app.models import Application
        from app.services.docker_service import DockerService

        config = cls.get_config()
        installed = config.get('installed', {}).get(str(app_id))

        if not installed:
            return {'success': False, 'error': 'App not installed from template'}

        app = Application.query.get(app_id)
        if not app:
            return {'success': False, 'error': 'Application not found'}

        template_id = installed['template_id']
        app_path = app.root_path

        # Get latest template
        result = cls.get_template(template_id)
        if not result.get('success'):
            return result

        template = result['template']

        # Load existing variables
        info_path = os.path.join(app_path, '.serverkit-template.json')
        try:
            with open(info_path, 'r') as f:
                install_info = json.load(f)
            variables = install_info.get('variables', {})
        except Exception:
            variables = {}

        # Add any new variables with defaults. Templates may declare variables as
        # a list ([{name: ...}, ...]) or a dict ({NAME: {...}}); normalize to dict
        # so converted templates (which use the list form) update correctly.
        template_vars = template.get('variables', {})
        if isinstance(template_vars, list):
            template_vars = {v['name']: v for v in template_vars
                             if isinstance(v, dict) and 'name' in v}
        for var_name, var_config in template_vars.items():
            if var_name not in variables:
                variables[var_name] = cls.generate_value(var_config)

        try:
            # Backup current compose
            compose_path = os.path.join(app_path, 'docker-compose.yml')
            backup_path = os.path.join(app_path, 'docker-compose.yml.bak')
            if os.path.exists(compose_path):
                shutil.copy(compose_path, backup_path)

            # Run pre-update script
            if 'scripts' in template and 'pre_update' in template['scripts']:
                script_result = cls._run_script(
                    template['scripts']['pre_update'],
                    app_path,
                    variables
                )
                if not script_result.get('success'):
                    return script_result

            # Stop current containers
            DockerService.compose_down(app_path)

            # Generate new docker-compose.yml
            compose_content = cls.generate_compose(template, variables)
            with open(compose_path, 'w') as f:
                f.write(compose_content)

            # Re-render any template-defined files and re-apply their bind mounts,
            # so templates that ship config via a `files:` section (e.g. litellm,
            # signoz, posthog) keep working across updates instead of losing the
            # mounted config when the compose is regenerated.
            if 'files' in template:
                files_result = cls._process_template_files(
                    template['files'], app_path, compose_path, variables
                )
                if not files_result.get('success'):
                    # Roll back to the backed-up compose and abort the update.
                    if os.path.exists(backup_path):
                        shutil.copy(backup_path, compose_path)
                    return files_result

            # Update installation info
            install_info['template_version'] = template.get('version')
            install_info['updated_at'] = datetime.now().isoformat()
            install_info['variables'] = variables
            with open(info_path, 'w') as f:
                json.dump(install_info, f, indent=2)

            # Pull new images and start
            DockerService.compose_pull(app_path)
            compose_result = DockerService.compose_up(app_path, detach=True, build=True)

            if not compose_result.get('success'):
                # Rollback
                if os.path.exists(backup_path):
                    shutil.copy(backup_path, compose_path)
                    DockerService.compose_up(app_path, detach=True)
                return compose_result

            # Run post-update script
            if 'scripts' in template and 'post_update' in template['scripts']:
                cls._run_script(
                    template['scripts']['post_update'],
                    app_path,
                    variables
                )

            # Update config
            config['installed'][str(app_id)]['template_version'] = template.get('version')
            config['installed'][str(app_id)]['updated_at'] = datetime.now().isoformat()
            cls.save_config(config)

            # Remove backup
            if os.path.exists(backup_path):
                os.remove(backup_path)

            return {
                'success': True,
                'version': template.get('version'),
                'app_id': app_id
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def get_installed_info(cls, app_id: int) -> Optional[Dict]:
        """Get template installation info for an app."""
        config = cls.get_config()
        return config.get('installed', {}).get(str(app_id))

    @classmethod
    def propagate_db_credentials(cls, source_app_id: int, target_app_id: int,
                                  target_prefix: str = None) -> Dict:
        """Propagate database credentials from source app to target app.

        Reads source app's .env file for DB credentials, updates target app's
        .env with same credentials but different table prefix.

        Args:
            source_app_id: ID of the app with existing DB credentials
            target_app_id: ID of the app to receive credentials
            target_prefix: Table prefix for target app (default: wp_dev_)

        Returns:
            Dict with success status and propagated config
        """
        from app.models import Application

        source_app = Application.query.get(source_app_id)
        target_app = Application.query.get(target_app_id)

        if not source_app or not target_app:
            return {'success': False, 'error': 'App not found'}

        if not source_app.root_path or not target_app.root_path:
            return {'success': False, 'error': 'Apps must have root_path set'}

        # Read source app's .env file
        source_env_path = os.path.join(source_app.root_path, '.env')
        if not os.path.exists(source_env_path):
            return {'success': False, 'error': 'Source app .env file not found'}

        try:
            env_vars = {}
            with open(source_env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()

            # Extract DB credentials
            db_config = {}
            db_keys = ['DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD',
                       'WORDPRESS_DB_HOST', 'WORDPRESS_DB_NAME', 'WORDPRESS_DB_USER',
                       'WORDPRESS_DB_PASSWORD', 'MYSQL_HOST', 'MYSQL_DATABASE',
                       'MYSQL_USER', 'MYSQL_PASSWORD']

            for key in db_keys:
                if key in env_vars:
                    db_config[key] = env_vars[key]

            if not db_config:
                return {'success': False, 'error': 'No database credentials found in source app'}

            # Set target table prefix (default different from source)
            source_prefix = env_vars.get('TABLE_PREFIX', env_vars.get('WORDPRESS_TABLE_PREFIX', 'wp_'))
            if target_prefix is None:
                if source_prefix == 'wp_':
                    target_prefix = 'wp_dev_'
                else:
                    target_prefix = 'wp_'

            # Update target app's .env file
            target_env_path = os.path.join(target_app.root_path, '.env')

            # Read existing target .env or create new
            target_env = {}
            if os.path.exists(target_env_path):
                with open(target_env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            target_env[key.strip()] = value.strip()

            # Update with source DB credentials
            for key, value in db_config.items():
                target_env[key] = value

            # Set different table prefix
            target_env['TABLE_PREFIX'] = target_prefix
            target_env['WORDPRESS_TABLE_PREFIX'] = target_prefix

            # Write updated .env
            with open(target_env_path, 'w') as f:
                for key, value in target_env.items():
                    f.write(f"{key}={value}\n")

            # Also update docker-compose.yml if it exists
            compose_path = os.path.join(target_app.root_path, 'docker-compose.yml')
            if os.path.exists(compose_path):
                try:
                    with open(compose_path, 'r') as f:
                        compose = yaml.safe_load(f)

                    # Update environment variables in services
                    for service_name, service in compose.get('services', {}).items():
                        env_list = service.get('environment', [])
                        if isinstance(env_list, list):
                            new_env = []
                            for env_item in env_list:
                                if isinstance(env_item, str) and '=' in env_item:
                                    key = env_item.split('=')[0]
                                    if key in target_env:
                                        new_env.append(f"{key}={target_env[key]}")
                                    else:
                                        new_env.append(env_item)
                                else:
                                    new_env.append(env_item)
                            service['environment'] = new_env

                    with open(compose_path, 'w') as f:
                        yaml.dump(compose, f, default_flow_style=False)
                except Exception as e:
                    # Non-fatal, continue
                    pass

            # Store shared config in both apps
            shared_config = {
                'db_host': db_config.get('DB_HOST', db_config.get('WORDPRESS_DB_HOST', '')),
                'db_name': db_config.get('DB_NAME', db_config.get('WORDPRESS_DB_NAME', '')),
                'source_prefix': source_prefix,
                'target_prefix': target_prefix,
                'propagated_at': datetime.now().isoformat()
            }

            return {
                'success': True,
                'shared_config': shared_config,
                'source_prefix': source_prefix,
                'target_prefix': target_prefix
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def add_repository(cls, name: str, url: str) -> Dict:
        """Add a template repository."""
        config = cls.get_config()

        # Check if already exists
        for repo in config.get('repos', []):
            if repo['url'] == url:
                return {'success': False, 'error': 'Repository already exists'}

        config.setdefault('repos', []).append({
            'name': name,
            'url': url.rstrip('/'),
            'enabled': True,
            'added_at': datetime.now().isoformat()
        })

        return cls.save_config(config)

    @classmethod
    def remove_repository(cls, url: str) -> Dict:
        """Remove a template repository."""
        config = cls.get_config()
        config['repos'] = [r for r in config.get('repos', []) if r['url'] != url]
        return cls.save_config(config)

    @classmethod
    def list_repositories(cls) -> List[Dict]:
        """List configured template repositories."""
        config = cls.get_config()
        return config.get('repos', cls.DEFAULT_REPOS)

    @classmethod
    def sync_templates(cls) -> Dict:
        """Sync templates from all repositories."""
        os.makedirs(cls.TEMPLATES_DIR, exist_ok=True)

        config = cls.get_config()
        synced = 0
        errors = []

        for repo in config.get('repos', []):
            if not repo.get('enabled', True):
                continue

            try:
                # Fetch index
                index_url = f"{repo['url']}/index.json"
                response = requests.get(index_url, timeout=30)
                response.raise_for_status()

                index = response.json()

                # Download each template
                for template_info in index.get('templates', []):
                    template_id = template_info.get('id')
                    if not template_id:
                        continue

                    try:
                        template_url = f"{repo['url']}/templates/{template_id}.yaml"
                        response = requests.get(template_url, timeout=30)
                        response.raise_for_status()

                        # Save locally
                        filepath = os.path.join(cls.TEMPLATES_DIR, f"{template_id}.yaml")
                        with open(filepath, 'w') as f:
                            f.write(response.text)

                        synced += 1
                    except Exception as e:
                        errors.append(f"Failed to sync {template_id}: {e}")

            except Exception as e:
                errors.append(f"Failed to sync from {repo['name']}: {e}")

        config['last_sync'] = datetime.now().isoformat()
        cls.save_config(config)

        return {
            'success': True,
            'synced': synced,
            'errors': errors if errors else None
        }

    @classmethod
    def get_categories(cls) -> List[str]:
        """Get all available template categories."""
        templates = cls.list_all_templates()
        categories = set()
        for template in templates:
            categories.update(template.get('categories', []))
        return sorted(categories)

    @classmethod
    def create_local_template(cls, template_data: Dict) -> Dict:
        """Create a local template."""
        validation = cls.validate_template(template_data)
        if not validation['valid']:
            return {'success': False, 'errors': validation['errors']}

        os.makedirs(cls.TEMPLATES_DIR, exist_ok=True)

        template_id = template_data['name'].lower().replace(' ', '-')
        filepath = os.path.join(cls.TEMPLATES_DIR, f"{template_id}.yaml")

        if os.path.exists(filepath):
            return {'success': False, 'error': 'Template with this name already exists'}

        try:
            with open(filepath, 'w') as f:
                yaml.dump(template_data, f, default_flow_style=False, sort_keys=False)

            return {'success': True, 'template_id': template_id, 'filepath': filepath}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def delete_local_template(cls, template_id: str) -> Dict:
        """Delete a local template."""
        for ext in ['.yaml', '.yml']:
            filepath = os.path.join(cls.TEMPLATES_DIR, f"{template_id}{ext}")
            if os.path.exists(filepath):
                os.remove(filepath)
                return {'success': True}

        return {'success': False, 'error': 'Template not found'}
