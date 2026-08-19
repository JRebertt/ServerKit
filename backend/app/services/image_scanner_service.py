"""Image vulnerability scanning and SBOM generation using Anchore grype/syft."""
import json
import logging
import os
import platform
import threading
from datetime import datetime
from typing import Dict, List, Optional

from app import db
from app.utils.system import run_checked
from app.models import Application, ImageVulnerabilityScan, SbomArtifact

logger = logging.getLogger(__name__)

SCANNERS_DIR = '/var/lib/serverkit/scanners'
GRYPE_BIN = os.path.join(SCANNERS_DIR, 'grype')
SYFT_BIN = os.path.join(SCANNERS_DIR, 'syft')
IMAGE_SCAN_JOB_KIND = 'security.image_scan'


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
                download = run_checked(['curl', '-fsSL', url, '-o', tmp_tar],
                                       timeout=None)
                if not download['success']:
                    return {'success': False,
                            'error': f"Failed to download grype: {download['error'][:200]}"}
                extract = run_checked(
                    ['tar', '-xzf', tmp_tar, '-C', SCANNERS_DIR, 'grype'],
                    timeout=None)
                if not extract['success']:
                    return {'success': False,
                            'error': f"Failed to unpack grype: {extract['error'][:200]}"}
                os.chmod(GRYPE_BIN, 0o755)
                version_out = run_checked([GRYPE_BIN, 'version'], timeout=None)
                return {
                    'success': True,
                    'message': 'grype installed',
                    'version': (version_out['output'].strip().splitlines() or [version])[0]
                               if version_out['success'] else version,
                }
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
                download = run_checked(['curl', '-fsSL', url, '-o', tmp_tar],
                                       timeout=None)
                if not download['success']:
                    return {'success': False,
                            'error': f"Failed to download syft: {download['error'][:200]}"}
                extract = run_checked(
                    ['tar', '-xzf', tmp_tar, '-C', SCANNERS_DIR, 'syft'],
                    timeout=None)
                if not extract['success']:
                    return {'success': False,
                            'error': f"Failed to unpack syft: {extract['error'][:200]}"}
                os.chmod(SYFT_BIN, 0o755)
                version_out = run_checked([SYFT_BIN, 'version'], timeout=None)
                return {
                    'success': True,
                    'message': 'syft installed',
                    'version': (version_out['output'].strip().splitlines() or [version])[0]
                               if version_out['success'] else version,
                }
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
            result = run_checked(
                [GRYPE_BIN, image_ref, '-o', 'json', '--quiet'],
                timeout=600,
                env={**os.environ,
                     'GRYPE_DB_CACHE_DIR': os.path.join(SCANNERS_DIR, 'grype-db')})
            # 0 = clean, 1 = vulnerabilities FOUND. Only anything else is a
            # failed scan — read the code, not result['success'].
            if result['returncode'] not in (0, 1):
                return {'success': False, 'error': result['error'][:500]}
            data = json.loads(result['output'])
            return {'success': True, 'data': data}
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
            result = run_checked([SYFT_BIN, image_ref, '-o', 'spdx-json'], timeout=300)
            if not result['success']:
                return {'success': False, 'error': result['error'][:500]}
            data = json.loads(result['output'])
            return {'success': True, 'data': data}
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
        """Queue a CVE scan for the Docker image of an application.

        ``scan_id`` and ``status`` are retained for callers of the legacy
        thread-backed surface; ``job_id`` and ``kind`` expose the durable job
        that now owns execution, retries, and observability.
        """
        from app.jobs.service import JobService

        # query_active: a queued scan pulls from the registry after this request.
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

        cls.register_jobs()
        try:
            job = JobService.enqueue(
                IMAGE_SCAN_JOB_KIND,
                payload={
                    'scan_id': scan.id,
                    'application_id': application_id,
                    'image_ref': image_ref,
                },
                owner_type='application',
                owner_id=application_id,
            )
        except Exception as exc:
            scan.status = 'failed'
            scan.error_message = f'Could not enqueue image scan: {exc}'
            scan.completed_at = datetime.utcnow()
            db.session.commit()
            logger.exception('Could not enqueue image scan %s', scan.id)
            return {'success': False, 'error': scan.error_message, 'scan_id': scan.id}

        return {
            'success': True,
            'scan_id': scan.id,
            'status': 'running',
            'job_id': job.id,
            'kind': job.kind,
        }

    @classmethod
    def run_image_scan_job(cls, job) -> Dict:
        """Execute one persisted image scan job."""
        payload = job.get_payload() or {}
        scan_id = payload.get('scan_id')
        if scan_id is None:
            raise ValueError('security.image_scan payload requires scan_id')

        scan = db.session.get(ImageVulnerabilityScan, scan_id)
        if not scan:
            raise ValueError(f'Image scan {scan_id} not found')

        image_ref = payload.get('image_ref') or scan.image_ref
        scan.status = 'running'
        scan.error_message = None
        scan.completed_at = None
        db.session.commit()

        try:
            result = cls._run_grype(image_ref)
            if not result.get('success'):
                raise RuntimeError(result.get('error') or 'Image scanner failed')

            data = result['data']
            scan.status = 'completed'
            scan.scanner_version = data.get('descriptor', {}).get('version')
            scan.set_counts(cls._parse_grype_counts(data))
            scan.set_findings(cls._normalize_findings(data))
            scan.completed_at = datetime.utcnow()
            db.session.commit()
            return {
                'success': True,
                'scan_id': scan.id,
                'application_id': scan.application_id,
                'status': scan.status,
                'severity_counts': scan.get_counts(),
            }
        except Exception as exc:
            db.session.rollback()
            scan = db.session.get(ImageVulnerabilityScan, scan_id)
            if scan:
                scan.status = 'failed'
                scan.error_message = str(exc)
                scan.completed_at = datetime.utcnow()
                db.session.commit()
            logger.exception('Image scan %s failed', scan_id)
            raise

    @classmethod
    def register_jobs(cls) -> None:
        """Register the durable image-scan handler (safe to call repeatedly)."""
        from app.jobs import registry
        registry.register(IMAGE_SCAN_JOB_KIND, cls.run_image_scan_job, replace=True)

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
