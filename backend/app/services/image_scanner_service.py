"""Image vulnerability scanning and SBOM generation using Anchore grype/syft."""
import json
import logging
import os
import platform
import subprocess
import threading
from datetime import datetime
from typing import Dict, List, Optional

from app import db
from app.models import Application, ImageVulnerabilityScan, SbomArtifact

logger = logging.getLogger(__name__)

SCANNERS_DIR = '/var/lib/serverkit/scanners'
GRYPE_BIN = os.path.join(SCANNERS_DIR, 'grype')
SYFT_BIN = os.path.join(SCANNERS_DIR, 'syft')


class ImageScannerService:
    """Manage scanner binaries and run per-image CVE scans + SBOM generation."""

    _install_lock = threading.Lock()

    @classmethod
    def _arch(cls) -> str:
        machine = platform.machine().lower()
        if machine in ('x86_64', 'amd64'):
            return 'amd64'
        if machine in ('aarch64', 'arm64'):
            return 'arm64'
        return machine

    @classmethod
    def _ensure_scanners_dir(cls) -> None:
        os.makedirs(SCANNERS_DIR, exist_ok=True)

    @classmethod
    def grype_installed(cls) -> bool:
        return os.path.isfile(GRYPE_BIN) and os.access(GRYPE_BIN, os.X_OK)

    @classmethod
    def syft_installed(cls) -> bool:
        return os.path.isfile(SYFT_BIN) and os.access(SYFT_BIN, os.X_OK)

    @classmethod
    def install_grype(cls) -> Dict:
        """Download grype binary into /var/lib/serverkit/scanners."""
        with cls._install_lock:
            if cls.grype_installed():
                return {'success': True, 'message': 'grype already installed'}
            cls._ensure_scanners_dir()
            arch = cls._arch()
            version = os.environ.get('GRYPE_VERSION', 'v0.87.0')
            url = f'https://github.com/anchore/grype/releases/download/{version}/grype_{version.lstrip("v")}_linux_{arch}.tar.gz'
            tmp_tar = '/tmp/serverkit-grype.tar.gz'
            try:
                subprocess.run(['curl', '-fsSL', url, '-o', tmp_tar], check=True, capture_output=True)
                subprocess.run(['tar', '-xzf', tmp_tar, '-C', SCANNERS_DIR, 'grype'], check=True, capture_output=True)
                os.chmod(GRYPE_BIN, 0o755)
                version_out = subprocess.run([GRYPE_BIN, 'version'], capture_output=True, text=True)
                return {
                    'success': True,
                    'message': 'grype installed',
                    'version': version_out.stdout.strip().splitlines()[0] if version_out.returncode == 0 else version
                }
            except subprocess.CalledProcessError as e:
                return {'success': False, 'error': f'Failed to install grype: {e.stderr.decode(errors="ignore")[:200]}'}
            finally:
                if os.path.exists(tmp_tar):
                    os.remove(tmp_tar)

    @classmethod
    def install_syft(cls) -> Dict:
        """Download syft binary into /var/lib/serverkit/scanners."""
        with cls._install_lock:
            if cls.syft_installed():
                return {'success': True, 'message': 'syft already installed'}
            cls._ensure_scanners_dir()
            arch = cls._arch()
            version = os.environ.get('SYFT_VERSION', 'v1.22.0')
            url = f'https://github.com/anchore/syft/releases/download/{version}/syft_{version.lstrip("v")}_linux_{arch}.tar.gz'
            tmp_tar = '/tmp/serverkit-syft.tar.gz'
            try:
                subprocess.run(['curl', '-fsSL', url, '-o', tmp_tar], check=True, capture_output=True)
                subprocess.run(['tar', '-xzf', tmp_tar, '-C', SCANNERS_DIR, 'syft'], check=True, capture_output=True)
                os.chmod(SYFT_BIN, 0o755)
                version_out = subprocess.run([SYFT_BIN, 'version'], capture_output=True, text=True)
                return {
                    'success': True,
                    'message': 'syft installed',
                    'version': version_out.stdout.strip().splitlines()[0] if version_out.returncode == 0 else version
                }
            except subprocess.CalledProcessError as e:
                return {'success': False, 'error': f'Failed to install syft: {e.stderr.decode(errors="ignore")[:200]}'}
            finally:
                if os.path.exists(tmp_tar):
                    os.remove(tmp_tar)

    @classmethod
    def _run_grype(cls, image_ref: str) -> Dict:
        if not cls.grype_installed():
            install = cls.install_grype()
            if not install['success']:
                return install
        try:
            result = subprocess.run(
                [GRYPE_BIN, image_ref, '-o', 'json', '--quiet'],
                capture_output=True,
                text=True,
                timeout=600,
                env={**os.environ, 'GRYPE_DB_CACHE_DIR': os.path.join(SCANNERS_DIR, 'grype-db')}
            )
            if result.returncode not in (0, 1):
                return {'success': False, 'error': result.stderr[:500] or f'grype exited {result.returncode}'}
            data = json.loads(result.stdout)
            return {'success': True, 'data': data}
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'grype scan timed out after 10 minutes'}
        except json.JSONDecodeError as e:
            return {'success': False, 'error': f'Failed to parse grype output: {e}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _run_syft(cls, image_ref: str) -> Dict:
        if not cls.syft_installed():
            install = cls.install_syft()
            if not install['success']:
                return install
        try:
            result = subprocess.run(
                [SYFT_BIN, image_ref, '-o', 'spdx-json'],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode != 0:
                return {'success': False, 'error': result.stderr[:500] or f'syft exited {result.returncode}'}
            data = json.loads(result.stdout)
            return {'success': True, 'data': data}
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'syft scan timed out after 5 minutes'}
        except json.JSONDecodeError as e:
            return {'success': False, 'error': f'Failed to parse syft output: {e}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _parse_grype_counts(cls, data: Dict) -> Dict:
        counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'negligible': 0, 'unknown': 0}
        for match in data.get('matches', []):
            sev = match.get('vulnerability', {}).get('severity', 'unknown')
            sev = sev.lower()
            if sev in counts:
                counts[sev] += 1
            else:
                counts['unknown'] += 1
        return counts

    @classmethod
    def _normalize_findings(cls, data: Dict) -> List[Dict]:
        findings = []
        for match in data.get('matches', []):
            vuln = match.get('vulnerability', {})
            artifact = match.get('artifact', {})
            findings.append({
                'id': vuln.get('id'),
                'severity': vuln.get('severity', 'unknown'),
                'cvss': vuln.get('cvss', []),
                'fix_versions': vuln.get('fix', {}).get('versions', []),
                'artifact_name': artifact.get('name'),
                'artifact_version': artifact.get('version'),
                'artifact_type': artifact.get('type'),
                'description': vuln.get('description'),
                'urls': vuln.get('urls', []),
            })
        return findings

    @classmethod
    def scan_application(cls, application_id: int) -> Dict:
        """Run a CVE scan for the Docker image of an application."""
        # query_active: a scan spawns Grype and pulls from the registry.
        app = Application.query_active().filter_by(id=application_id).first()
        if not app:
            return {'success': False, 'error': 'Application not found'}
        image_ref = app.docker_image or app.container_id
        if not image_ref:
            return {'success': False, 'error': 'Application has no Docker image or container'}

        scan = ImageVulnerabilityScan(
            application_id=application_id,
            image_ref=image_ref,
            status='running'
        )
        db.session.add(scan)
        db.session.commit()

        def _run():
            try:
                result = cls._run_grype(image_ref)
                scan.completed_at = datetime.utcnow()
                if not result['success']:
                    scan.status = 'failed'
                    scan.error_message = result.get('error')
                else:
                    data = result['data']
                    scan.status = 'completed'
                    scan.scanner_version = data.get('descriptor', {}).get('version')
                    scan.set_counts(cls._parse_grype_counts(data))
                    scan.set_findings(cls._normalize_findings(data))
                db.session.commit()
            except Exception as e:
                logger.exception('Image scan failed')
                scan.status = 'failed'
                scan.error_message = str(e)
                scan.completed_at = datetime.utcnow()
                db.session.commit()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return {'success': True, 'scan_id': scan.id, 'status': 'running'}

    @classmethod
    def generate_sbom(cls, application_id: int) -> Dict:
        """Generate and persist an SPDX SBOM for an application image."""
        # query_active: Syft pulls/inspects the image out of process.
        app = Application.query_active().filter_by(id=application_id).first()
        if not app:
            return {'success': False, 'error': 'Application not found'}
        image_ref = app.docker_image or app.container_id
        if not image_ref:
            return {'success': False, 'error': 'Application has no Docker image or container'}

        result = cls._run_syft(image_ref)
        if not result['success']:
            return result

        data = result['data']
        sbom = SbomArtifact(
            application_id=application_id,
            image_ref=image_ref,
            generator_version=data.get('spdxVersion'),
            sbom_json=json.dumps(data)
        )
        db.session.add(sbom)
        db.session.commit()
        return {'success': True, 'sbom_id': sbom.id, 'sbom': sbom.to_dict(include_sbom=False)}

    @classmethod
    def latest_scan(cls, application_id: int) -> Optional[ImageVulnerabilityScan]:
        return ImageVulnerabilityScan.query.filter_by(application_id=application_id).order_by(
            ImageVulnerabilityScan.started_at.desc()).first()

    @classmethod
    def scan_history(cls, application_id: int, limit: int = 20) -> List[Dict]:
        scans = ImageVulnerabilityScan.query.filter_by(application_id=application_id).order_by(
            ImageVulnerabilityScan.started_at.desc()).limit(limit).all()
        return [s.to_dict() for s in scans]

    @classmethod
    def check_deploy_gate(cls, application_id: int, allowed_severities: Optional[List[str]] = None) -> Dict:
        """Return whether the latest scan allows deployment."""
        allowed_severities = allowed_severities or ['low', 'negligible', 'unknown']
        scan = cls.latest_scan(application_id)
        if not scan:
            return {'allowed': True, 'reason': 'No scan available'}
        if scan.status != 'completed':
            return {'allowed': False, 'reason': f'Scan status is {scan.status}'}
        counts = scan.get_counts()
        blocking = {sev: count for sev, count in counts.items() if sev not in allowed_severities and count > 0}
        if blocking:
            return {'allowed': False, 'reason': 'Image exceeds vulnerability threshold', 'blocking': blocking}
        return {'allowed': True, 'reason': 'Image passes vulnerability threshold'}
