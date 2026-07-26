"""
Plugins API - Install, manage, and uninstall ServerKit plugins.

Supports installing plugins from:
  - GitHub repo URLs (resolves latest release automatically)
  - GitHub release URLs (specific version)
  - Direct zip download URLs
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.services.audit_service import AuditService
from app.models.audit_log import AuditLog

plugins_bp = Blueprint('plugins', __name__)


def get_current_user():
    from flask_jwt_extended import get_jwt_identity
    from app.models.user import User
    return User.query.get(get_jwt_identity())


@plugins_bp.route('', methods=['GET'])
@plugins_bp.route('/', methods=['GET'])
@jwt_required()
def list_plugins():
    """List all installed plugins."""
    from app.services.plugin_service import list_plugins
    status = request.args.get('status')
    plugins = list_plugins(status=status)
    return jsonify({'plugins': [p.to_dict() for p in plugins]})


@plugins_bp.route('/<int:plugin_id>', methods=['GET'])
@jwt_required()
def get_plugin(plugin_id):
    """Get details of an installed plugin."""
    from app.services.plugin_service import get_plugin
    plugin = get_plugin(plugin_id)
    if not plugin:
        return jsonify({'error': 'Plugin not found'}), 404
    return jsonify(plugin.to_dict())


@plugins_bp.route('/install', methods=['POST'])
@jwt_required()
def install_plugin():
    """Install a plugin from a URL.

    Body: { "url": "https://github.com/user/repo" }

    Accepts:
      - GitHub repo URL (downloads latest release)
      - GitHub release URL (specific version)
      - Direct .zip URL
    """
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'url required'}), 400

    url = data['url'].strip()
    if not url:
        return jsonify({'error': 'url cannot be empty'}), 400

    # Optional checksum continuity: the preview step returns the resolved URL +
    # sha256; passing them here pins the install to the exact previewed bytes.
    expected_sha256 = (data.get('sha256') or None)

    from app.services.plugin_service import install_from_url
    try:
        plugin = install_from_url(url, user_id=user.id, expected_sha256=expected_sha256)
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_CREATE,
            user_id=user.id,
            target_type='plugin',
            target_id=plugin.id,
            details={'name': plugin.name, 'version': plugin.version, 'url': url}
        )
        return jsonify(plugin.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        # Log full traceback server-side; details go to the InstalledPlugin
        # row's error_message field. Don't echo raw exceptions to the
        # client — they can leak filesystem paths, library versions, or
        # SQL fragments.
        import logging, uuid
        ref = uuid.uuid4().hex[:8]
        logging.getLogger(__name__).exception(
            'Plugin install failed (ref=%s)', ref
        )
        return jsonify({
            'error': 'Installation failed. Check server logs.',
            'ref': ref,
        }), 500


@plugins_bp.route('/preview', methods=['POST'])
@jwt_required()
def preview_plugin():
    """Preview a GitHub/zip extension WITHOUT installing it.

    Body: { "url": "owner/repo" | "owner/repo@tag" | "https://github.com/..." | ".zip URL" }

    Resolves the source, downloads it, reads plugin.json, and returns the
    metadata a user consents to (slug, version, permissions, panel-version gate)
    plus the resolved download URL, its sha256, and any warnings — so the UI can
    show a consent card before the install re-downloads the exact same bytes.
    """
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'url required'}), 400

    from app.services.plugin_service import preview_from_url
    try:
        return jsonify(preview_from_url(url))
    except ValueError as e:
        # GitHubResolveError is a ValueError subclass — its message is already
        # user-actionable (rate limit / 404 / private / no plugin.json).
        return jsonify({'error': str(e)}), 400
    except Exception:
        import logging, uuid
        ref = uuid.uuid4().hex[:8]
        logging.getLogger(__name__).exception('Plugin preview failed (ref=%s)', ref)
        return jsonify({
            'error': 'Preview failed. Check server logs.',
            'ref': ref,
        }), 500


@plugins_bp.route('/install-local', methods=['POST'])
@jwt_required()
def install_plugin_local():
    """Install a plugin from a local directory on the panel host.

    Body: { "path": "/abs/path/to/plugin-folder" }

    Intended for plugin development: point at the working tree, install,
    iterate. The path must exist on the panel host's filesystem and
    contain a plugin.json. The folder is zipped in memory and run
    through the same install pipeline as URL/upload installs, so
    behavior matches.
    """
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.get_json() or {}
    path = (data.get('path') or '').strip()
    if not path:
        return jsonify({'error': 'path required'}), 400

    from app.services.plugin_service import install_from_path
    try:
        plugin = install_from_path(path, user_id=user.id)
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_CREATE,
            user_id=user.id,
            target_type='plugin',
            target_id=plugin.id,
            details={'name': plugin.name, 'version': plugin.version, 'path': path, 'source': 'local'}
        )
        return jsonify(plugin.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        # Log full traceback server-side; details go to the InstalledPlugin
        # row's error_message field. Don't echo raw exceptions to the
        # client — they can leak filesystem paths, library versions, or
        # SQL fragments.
        import logging, uuid
        ref = uuid.uuid4().hex[:8]
        logging.getLogger(__name__).exception(
            'Plugin install failed (ref=%s)', ref
        )
        return jsonify({
            'error': 'Installation failed. Check server logs.',
            'ref': ref,
        }), 500


@plugins_bp.route('/install-upload', methods=['POST'])
@jwt_required()
def install_plugin_upload():
    """Install a plugin from an uploaded zip file.

    Multipart: file=<plugin.zip>

    Cap at 50 MB. Anything that needs to be bigger probably belongs in
    a release artifact installed via /install instead.
    """
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded (use multipart field "file")'}), 400

    f = request.files['file']
    if not f or not f.filename:
        return jsonify({'error': 'No file uploaded'}), 400

    raw = f.read()
    max_bytes = 50 * 1024 * 1024
    if len(raw) > max_bytes:
        return jsonify({'error': f'Upload exceeds {max_bytes // (1024 * 1024)} MB cap'}), 413

    from app.services.plugin_service import install_from_zip
    try:
        plugin = install_from_zip(raw, user_id=user.id, source_name=f.filename)
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_CREATE,
            user_id=user.id,
            target_type='plugin',
            target_id=plugin.id,
            details={
                'name': plugin.name, 'version': plugin.version,
                'filename': f.filename, 'source': 'upload',
            }
        )
        return jsonify(plugin.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        # Log full traceback server-side; details go to the InstalledPlugin
        # row's error_message field. Don't echo raw exceptions to the
        # client — they can leak filesystem paths, library versions, or
        # SQL fragments.
        import logging, uuid
        ref = uuid.uuid4().hex[:8]
        logging.getLogger(__name__).exception(
            'Plugin install failed (ref=%s)', ref
        )
        return jsonify({
            'error': 'Installation failed. Check server logs.',
            'ref': ref,
        }), 500


@plugins_bp.route('/<int:plugin_id>', methods=['DELETE'])
@jwt_required()
def uninstall_plugin(plugin_id):
    """Uninstall a plugin (removes files and DB record)."""
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    from app.services.plugin_service import uninstall_plugin, get_plugin
    plugin = get_plugin(plugin_id)
    if not plugin:
        return jsonify({'error': 'Plugin not found'}), 404

    # Keep-data by default; purge drops the plugin's ext_<slug>_ tables. Accept
    # ?purge=true or a JSON body {"purge": true}.
    purge = str(request.args.get('purge', '')).lower() in ('1', 'true', 'yes')
    if not purge:
        body = request.get_json(silent=True) or {}
        purge = bool(body.get('purge'))

    plugin_name = plugin.name
    uninstall_plugin(plugin_id, purge=purge)

    AuditService.log(
        action=AuditLog.ACTION_RESOURCE_DELETE,
        user_id=user.id,
        target_type='plugin',
        target_id=plugin_id,
        details={'name': plugin_name, 'purge': purge}
    )
    return jsonify({'message': f'Plugin {plugin_name} uninstalled. Restart to fully unload backend routes.'})


@plugins_bp.route('/<int:plugin_id>/enable', methods=['POST'])
@jwt_required()
def enable_plugin(plugin_id):
    """Enable a disabled plugin."""
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    from app.services.plugin_service import enable_plugin
    plugin = enable_plugin(plugin_id)
    if not plugin:
        return jsonify({'error': 'Plugin not found'}), 404
    AuditService.log(
        action=AuditLog.ACTION_RESOURCE_ENABLE,
        user_id=user.id,
        target_type='plugin',
        target_id=plugin.id,
        details={'name': plugin.name, 'version': plugin.version},
    )
    return jsonify(plugin.to_dict())


@plugins_bp.route('/<int:plugin_id>/disable', methods=['POST'])
@jwt_required()
def disable_plugin(plugin_id):
    """Disable a plugin without removing it."""
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    from app.services.plugin_service import disable_plugin
    plugin = disable_plugin(plugin_id)
    if not plugin:
        return jsonify({'error': 'Plugin not found'}), 404
    AuditService.log(
        action=AuditLog.ACTION_RESOURCE_DISABLE,
        user_id=user.id,
        target_type='plugin',
        target_id=plugin.id,
        details={'name': plugin.name, 'version': plugin.version},
    )
    return jsonify(plugin.to_dict())


@plugins_bp.route('/builtin', methods=['GET'])
@jwt_required()
def list_builtin():
    """Enumerate bundled extensions in BUILTIN_EXTENSIONS_DIR.

    Used by the Marketplace UI to show one-click installs for plugins
    that ship with the repo (e.g. the Git extension) without making the
    user paste an absolute path.
    """
    from app.services.plugin_service import list_builtin_extensions
    return jsonify({'builtin': list_builtin_extensions()})


@plugins_bp.route('/recommendations', methods=['GET'])
@jwt_required()
def recommendations():
    """Extensions recommended for the given onboarding use cases (setup wizard).

    Query: ``?use_cases=wordpress,web-apps``. Returns each recommended
    extension's real display_name/description + install source, so the wizard
    can render checkboxes that install the actual extension on Finish."""
    from app.services.plugin_service import recommend_extensions_for_use_cases
    raw = request.args.get('use_cases', '')
    use_cases = [u.strip() for u in raw.split(',') if u.strip()]
    return jsonify({'recommendations': recommend_extensions_for_use_cases(use_cases)})


@plugins_bp.route('/builtin/<slug>/install', methods=['POST'])
@jwt_required()
def install_builtin(slug):
    """Install a bundled extension by slug.

    Mirror of /plugins/install — admin-only, since this writes to disk
    and may execute lifecycle hooks.
    """
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    from app.services.plugin_service import install_builtin_extension
    try:
        plugin = install_builtin_extension(slug, user_id=user.id)
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_CREATE,
            user_id=user.id,
            target_type='plugin',
            target_id=plugin.id,
            details={'name': plugin.name, 'version': plugin.version, 'source': 'builtin'},
        )
        return jsonify(plugin.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        # Log full traceback server-side; details go to the InstalledPlugin
        # row's error_message field. Don't echo raw exceptions to the
        # client — they can leak filesystem paths, library versions, or
        # SQL fragments.
        import logging, uuid
        ref = uuid.uuid4().hex[:8]
        logging.getLogger(__name__).exception(
            'Plugin install failed (ref=%s)', ref
        )
        return jsonify({
            'error': 'Installation failed. Check server logs.',
            'ref': ref,
        }), 500


@plugins_bp.route('/<slug>/assets/<path:asset_path>', methods=['GET'])
@jwt_required()
def plugin_asset(slug, asset_path):
    """Serve a file from an installed plugin's frontend directory.

    Foundation for the future remote-frontend delivery mechanism (ADR 0001):
    a panel can serve a plugin's prebuilt/static assets. Path-traversal safe via
    send_from_directory. Only active plugins' assets are served.
    """
    import re
    from flask import send_from_directory
    if not re.match(r'^[a-zA-Z0-9_-]+$', slug or ''):
        return jsonify({'error': 'Invalid slug'}), 400

    from app.services.plugin_service import get_plugin_by_slug, FRONTEND_PLUGINS_DIR
    import os
    plugin = get_plugin_by_slug(slug)
    if not plugin or plugin.status != 'active':
        return jsonify({'error': 'Plugin not active'}), 404

    base = os.path.join(FRONTEND_PLUGINS_DIR, slug)
    if not os.path.isdir(base):
        return jsonify({'error': 'No assets for this plugin'}), 404
    try:
        return send_from_directory(base, asset_path)
    except Exception:
        return jsonify({'error': 'Asset not found'}), 404


@plugins_bp.route('/manifest-spec', methods=['GET'])
@jwt_required()
def get_manifest_spec():
    """Return the documented plugin.json contract.

    Used by SDK tooling, marketplace submissions, and the in-panel
    plugin developer UI to validate a manifest before install. The
    spec mirrors what `plugin_service` actually consumes — keep them
    in sync when extending the contract.
    """
    return jsonify({
        'schema_version': '1.0',
        'required': ['name', 'display_name', 'version'],
        'fields': {
            'name': {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]+$',
                     'description': 'Filesystem-safe slug; also used as URL prefix default.'},
            'display_name': {'type': 'string'},
            'slug': {'type': 'string', 'description': 'Optional; defaults to `name`.'},
            'version': {'type': 'string', 'description': 'Semver recommended.'},
            'description': {'type': 'string'},
            'author': {'type': 'string'},
            'homepage': {'type': 'string'},
            'repository': {'type': 'string'},
            'license': {'type': 'string'},
            'category': {'type': 'string',
                         'description': "monitoring|security|deployment|integration|ui|utility"},
            'entry_point': {'type': 'string',
                            'description': "Backend blueprint ref, format 'module:bp_var'."},
            'url_prefix': {'type': 'string',
                           'description': 'Defaults to /api/v1/<slug>.'},
            'frontend_entry': {'type': 'string',
                               'description': 'Optional path within the frontend bundle (informational).'},
            'permissions': {'type': 'array', 'items': {'type': 'string'},
                            'description': 'Declared host capabilities (docker, shell, filesystem, network, db) or agent.command:<action>. Surfaced as a consent step on install and enforced by the SDK capability gate (require_permission).'},
            'min_panel_version': {'type': 'string',
                                  'description': 'Lowest compatible panel version (inclusive). Enforced at install/update.'},
            'max_panel_version': {'type': 'string',
                                  'description': 'Highest compatible panel version (inclusive). Optional.'},
            'templates': {'type': 'array',
                          'description': 'App-template ids to install on plugin install. String or {id, app_name?, variables?}.'},
            'models': {'type': 'string',
                       'description': "module:func — returns/defines the plugin's SQLAlchemy models (tables named ext_<slug>_*). Tables are created on install; dropped on uninstall --purge."},
            'jobs': {'type': 'array',
                     'description': 'Background job handlers: [{kind, handler}] where handler is module:func.'},
            'schedules': {'type': 'array',
                          'description': 'Recurring jobs: [{name, kind, cron?|interval_seconds?, payload?}]. Paused automatically when the plugin is disabled.'},
            'socket_entry': {'type': 'string',
                             'description': "module:func returning {event: handler}. Registers a status-guarded Socket.IO namespace at /ext/<slug>."},
            'config_schema': {'type': 'object',
                              'description': 'JSON-schema-ish object rendered as a settings form on the installed-extension detail.'},
            'lifecycle': {'type': 'object',
                          'properties': {
                              'install': {'type': 'string', 'description': "module:func — runs after install."},
                              'upgrade': {'type': 'string', 'description': "module:func — runs when installing a different version."},
                              'uninstall': {'type': 'string', 'description': "module:func(plugin, purge=bool) — runs before uninstall."},
                          }},
            'contributions': {
                'type': 'object',
                'properties': {
                    'nav': {'type': 'array', 'description': 'Sidebar items: {id, label, route, category, icon}.'},
                    'routes': {'type': 'array',
                               'description': 'SPA routes: {path, component, layout?, group?}. component matches a named export of the plugin index module. layout: padded (default) | full | bare | <custom-layout-id>. group nests the route inside that core tab group\'s TabGroupLayout instead (see tabs).'},
                    'tabs': {'type': 'array',
                             'description': 'Tabs added to a core-owned tab group: {group, to, label, icon?, end?, order?}. group is the core group id (files | servers | monitoring; == the sidebar item id). Pair with a route contribution carrying the same group. icon is raw inner-SVG markup; order is an optional insertion index (default: appended).'},
                    'page_titles': {'type': 'object', 'description': 'Map of route path → document title.'},
                    'command_palette': {'type': 'array', 'description': '{label, path, category, keywords}.'},
                    'widgets': {'type': 'array', 'description': '{slot, component}. slot=global renders globally inside DashboardLayout.'},
                    'dashboard_widgets': {'type': 'array',
                                          'description': 'Placeable dashboard widget types: {id, name, component, icon?, category?, description?, w?, h?, min?, default_cfg?}. Unlike widgets (fixed host slot), these appear in the dashboard widget library and the user positions, resizes and configures instances of them.'},
                    'layouts': {'type': 'array',
                                'description': 'Custom layout components: {id, component}. The component must render <Outlet/> somewhere; it wraps every route that references its id. Built-in layouts (padded, full, bare) are reserved.'},
                },
            },
        },
        'example': {
            'name': 'serverkit-git',
            'display_name': 'Git Server',
            'version': '1.0.0',
            'entry_point': 'blueprint:git_bp',
            'url_prefix': '/api/v1/git',
            'permissions': ['docker', 'filesystem'],
            'templates': ['gitea'],
            'lifecycle': {'install': 'lifecycle:on_install'},
            'contributions': {
                'nav': [{'id': 'git', 'label': 'Git', 'route': '/git',
                         'category': 'infrastructure',
                         'icon': '<circle cx="18" cy="18" r="3"/>'}],
                'routes': [
                    {'path': 'git', 'component': 'GitPage'},
                    {'path': 'git/:tab', 'component': 'GitPage'},
                ],
                'page_titles': {'/git': 'Git Repositories'},
                'command_palette': [
                    {'label': 'Git', 'path': '/git', 'category': 'Pages',
                     'keywords': 'repos deploy'},
                ],
            },
        },
    })


@plugins_bp.route('/<int:plugin_id>/config', methods=['GET'])
@jwt_required()
def get_plugin_config(plugin_id):
    """Read a plugin's saved config values + its schema (#49).

    Admin-only: config values may hold secrets (API keys etc.), which is also
    why they are deliberately NOT part of the plugin's to_dict().
    """
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    from app.services.plugin_service import get_plugin, RESERVED_PLUGIN_CONFIG_KEYS
    plugin = get_plugin(plugin_id)
    if not plugin:
        return jsonify({'error': 'Plugin not found'}), 404
    # Hide panel-managed reserved keys (e.g. _frontend_hashes) — they're not
    # user config and must not be echoed back for editing.
    user_config = {
        k: v for k, v in (plugin.config or {}).items()
        if k not in RESERVED_PLUGIN_CONFIG_KEYS
    }
    return jsonify({
        'config': user_config,
        'config_schema': (plugin.manifest or {}).get('config_schema') or {},
    })


@plugins_bp.route('/<int:plugin_id>/config', methods=['PUT'])
@jwt_required()
def update_plugin_config(plugin_id):
    """Save a plugin's config values (#49). Body: {"config": {...}}.

    The manifest's config_schema is advisory — values are stored as given so a
    plugin can evolve its fields without a panel release. Plugins read them via
    plugins_sdk.config(slug).
    """
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    from app.services.plugin_service import (
        get_plugin, update_plugin_config as svc_update_plugin_config,
        RESERVED_PLUGIN_CONFIG_KEYS,
    )
    plugin = get_plugin(plugin_id)
    if not plugin:
        return jsonify({'error': 'Plugin not found'}), 404

    data = request.get_json(silent=True) or {}
    config = data.get('config')
    if not isinstance(config, dict):
        return jsonify({'error': 'config must be an object'}), 400

    # The service strips/re-applies panel-managed reserved keys (e.g. the
    # runtime-frontend integrity pins), so a config PUT can't drop or forge them.
    plugin = svc_update_plugin_config(plugin.slug, config)
    AuditService.log(
        action=AuditLog.ACTION_RESOURCE_UPDATE,
        user_id=user.id,
        target_type='plugin',
        target_id=str(plugin.id),
        details={'event': 'config_update', 'keys': sorted(config.keys())},
    )
    user_config = {
        k: v for k, v in (plugin.config or {}).items()
        if k not in RESERVED_PLUGIN_CONFIG_KEYS
    }
    return jsonify({'config': user_config})


@plugins_bp.route('/updates', methods=['GET'])
@jwt_required()
def list_updates():
    """List installed plugins that have a newer version in the registry.

    Each entry: {slug, plugin_id, installed_version, available_version,
    update_available, compatible, source}.
    """
    from app.services.plugin_service import check_for_updates
    return jsonify({'updates': check_for_updates()})


@plugins_bp.route('/<int:plugin_id>/update', methods=['POST'])
@jwt_required()
def update_plugin_route(plugin_id):
    """Update an installed plugin to the registry version (reinstall in place)."""
    user = get_current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    from app.services.plugin_service import update_plugin
    try:
        plugin = update_plugin(plugin_id, user_id=user.id)
        AuditService.log(
            action=AuditLog.ACTION_RESOURCE_UPDATE,
            user_id=user.id,
            target_type='plugin',
            target_id=plugin.id,
            details={'name': plugin.name, 'version': plugin.version, 'source': 'registry-update'},
        )
        return jsonify(plugin.to_dict())
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        import logging, uuid
        ref = uuid.uuid4().hex[:8]
        logging.getLogger(__name__).exception('Plugin update failed (ref=%s)', ref)
        return jsonify({'error': 'Update failed. Check server logs.', 'ref': ref}), 500


@plugins_bp.route('/contributions', methods=['GET'])
@jwt_required()
def get_contributions():
    """Return merged UI contributions from all active plugins.

    Shape:
        {
          "nav":             [...],
          "routes":          [...],
          "page_titles":     {...},
          "command_palette": [...],
          "widgets":         [...]
        }

    Each item in the lists carries a `plugin` field with the source slug
    so the frontend can resolve component references against the correct
    plugin module.
    """
    from app.services.contribution_service import get_active_contributions
    return jsonify(get_active_contributions())
