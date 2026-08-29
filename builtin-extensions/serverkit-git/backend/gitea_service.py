"""Gitea self-host management — the serverkit-git extension's backend half.

Moved verbatim out of core ``GitService`` (plan 52 Phase 6): install/lifecycle
for the panel-managed Gitea container plus its config file. The deploy-side
git CLI operations (clone/pull/deploy/webhooks) STAY core in
``app.services.git_service`` — they are the deploy pipeline and must never
depend on this extension.

Core seams kept on purpose: ``NginxService.create/remove/get_gitea_config``
(the /gitea location blocks) remain core helpers this service calls, the same
two-speed shape as the WP fail2ban filter text.
"""
import os
import json
import logging
from typing import Dict

from app import paths
from app.utils.system import run_checked

logger = logging.getLogger(__name__)


class GiteaServerService:
    CONFIG_DIR = paths.SERVERKIT_CONFIG_DIR

    GITEA_APP_NAME = 'serverkit-gitea'
    GITEA_CONFIG_FILE = os.path.join(CONFIG_DIR, 'gitea.json')

    @classmethod
    def get_gitea_status(cls) -> Dict:
        """Check if Gitea is installed and running."""
        from app.models import Application

        app = Application.query.filter_by(name=cls.GITEA_APP_NAME).first()

        if not app:
            return {
                'installed': False,
                'running': False,
                'http_port': None,
                'ssh_port': None,
                'url': None,
                'url_path': None
            }

        # Check container status
        running = cls._is_gitea_running()

        # Load config for ports
        config = cls._load_gitea_config()

        # Prefer the panel's canonical origin so the link works through a domain
        # and Cloudflare; fall back to the local port only when no domain is set.
        from app.services.site_domain_service import SiteDomainService
        panel_origin = SiteDomainService.panel_origin()
        if panel_origin:
            public_url = f"{panel_origin}/gitea"
        elif app.port:
            public_url = f"http://localhost:{app.port}"
        else:
            public_url = None

        return {
            'installed': True,
            'running': running,
            'http_port': app.port or config.get('http_port'),
            'ssh_port': config.get('ssh_port'),
            'url_path': '/gitea',
            'url': public_url,
            'app_id': app.id,
            'version': config.get('version', '1.21')
        }

    @classmethod
    def _is_gitea_running(cls) -> bool:
        """Check if Gitea container is running."""
        try:
            result = run_checked(
                ['docker', 'ps', '--filter', f'name={cls.GITEA_APP_NAME}',
                 '--format', '{{.Names}}'], timeout=10)
            return cls.GITEA_APP_NAME in result['output']
        except Exception:
            return False

    @classmethod
    def _load_gitea_config(cls) -> Dict:
        """Load Gitea configuration."""
        if os.path.exists(cls.GITEA_CONFIG_FILE):
            try:
                with open(cls.GITEA_CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @classmethod
    def _save_gitea_config(cls, config: Dict) -> bool:
        """Save Gitea configuration."""
        try:
            os.makedirs(cls.CONFIG_DIR, exist_ok=True)
            with open(cls.GITEA_CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except Exception:
            return False

    @classmethod
    def get_gitea_resource_requirements(cls) -> Dict:
        """Get resource requirements for Gitea installation."""
        return {
            'memory_min': '512MB',
            'memory_recommended': '1GB',
            'storage_min': '5GB',
            'storage_recommended': '20GB',
            'components': [
                {'name': 'Gitea', 'memory': '~300MB', 'storage': '~100MB + repos'},
                {'name': 'PostgreSQL', 'memory': '~200MB', 'storage': '~1GB'}
            ],
            'warning': 'Installation will spin up a PostgreSQL database container'
        }

    @classmethod
    def install_gitea(cls, admin_user: str = 'admin',
                      admin_email: str = None,
                      admin_password: str = None) -> Dict:
        """Install Gitea as integrated ServerKit service."""
        from app.services.template_service import TemplateService
        from app.services.nginx_service import NginxService

        # Check if already installed
        status = cls.get_gitea_status()
        if status['installed']:
            return {'success': False, 'error': 'Gitea is already installed'}

        # Generate secure password if not provided
        generated_password = False
        if not admin_password:
            admin_password = secrets.token_urlsafe(16)
            generated_password = True

        try:
            # Install using template service
            result = TemplateService.install_template(
                template_id='gitea',
                app_name=cls.GITEA_APP_NAME,
                user_variables={},
                user_id=1  # System user
            )

            if not result.get('success'):
                return result

            # Get the variables that were generated
            variables = result.get('variables', {})
            http_port = variables.get('HTTP_PORT')
            ssh_port = variables.get('SSH_PORT')

            # Create nginx config for /gitea path
            nginx_result = NginxService.create_gitea_config(int(http_port))
            if not nginx_result.get('success'):
                # Log warning but don't fail - Gitea still works via port
                print(f"Warning: Failed to create Gitea nginx config: {nginx_result.get('error')}")

            # Save config with admin credentials and ports
            config = {
                'admin_user': admin_user,
                'admin_email': admin_email,
                'http_port': http_port,
                'ssh_port': ssh_port,
                'db_password': variables.get('DB_PASSWORD'),
                'installed_at': datetime.now().isoformat(),
                'version': '1.21',
                'url_path': '/gitea'
            }
            cls._save_gitea_config(config)

            response = {
                'success': True,
                'message': 'Gitea installed successfully',
                'http_port': http_port,
                'ssh_port': ssh_port,
                'url_path': '/gitea',
                'admin_user': admin_user
            }

            # Only include password in response if it was generated
            if generated_password:
                response['admin_password'] = admin_password
                response['warning'] = 'Save these credentials - password shown only once!'

            return response

        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def uninstall_gitea(cls, remove_data: bool = False) -> Dict:
        """Uninstall Gitea."""
        from app import db
        from app.models import Application
        from app.services.docker_service import DockerService
        from app.services.nginx_service import NginxService

        app = Application.query.filter_by(name=cls.GITEA_APP_NAME).first()
        if not app:
            return {'success': False, 'error': 'Gitea is not installed'}

        try:
            # Remove nginx config
            NginxService.remove_gitea_config()

            # Stop and remove containers
            if app.root_path and os.path.exists(app.root_path):
                DockerService.compose_down(app.root_path, remove_volumes=remove_data)

                if remove_data:
                    import shutil
                    shutil.rmtree(app.root_path, ignore_errors=True)

            # Remove from database
            db.session.delete(app)
            db.session.commit()

            # Remove config
            if os.path.exists(cls.GITEA_CONFIG_FILE):
                os.remove(cls.GITEA_CONFIG_FILE)

            return {
                'success': True,
                'message': 'Gitea uninstalled successfully',
                'data_removed': remove_data
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def start_gitea(cls) -> Dict:
        """Start Gitea containers."""
        from app import db
        from app.models import Application
        from app.services.docker_service import DockerService

        app = Application.query.filter_by(name=cls.GITEA_APP_NAME).first()
        if not app:
            return {'success': False, 'error': 'Gitea is not installed'}

        if not app.root_path or not os.path.exists(app.root_path):
            return {'success': False, 'error': 'Gitea installation path not found'}

        try:
            result = DockerService.compose_up(app.root_path, detach=True)
            if result.get('success'):
                app.status = 'running'
                db.session.commit()
                return {'success': True, 'message': 'Gitea started'}
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def stop_gitea(cls) -> Dict:
        """Stop Gitea containers."""
        from app import db
        from app.models import Application
        from app.services.docker_service import DockerService

        app = Application.query.filter_by(name=cls.GITEA_APP_NAME).first()
        if not app:
            return {'success': False, 'error': 'Gitea is not installed'}

        if not app.root_path or not os.path.exists(app.root_path):
            return {'success': False, 'error': 'Gitea installation path not found'}

        try:
            result = DockerService.compose_stop(app.root_path)
            if result.get('success'):
                app.status = 'stopped'
                db.session.commit()
                return {'success': True, 'message': 'Gitea stopped'}
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def restart_gitea(cls) -> Dict:
        """Restart Gitea containers."""
        stop_result = cls.stop_gitea()
        if not stop_result.get('success'):
            return stop_result
        return cls.start_gitea()
