import ipaddress
import logging
from datetime import datetime
from app import db
from app.exceptions import AuthenticationError, ValidationError
from app.models.ddns_host import DdnsHost
from app.models.dns_zone import DNSZone, DNSRecord
from app.services.dns_zone_service import DNSZoneService

logger = logging.getLogger(__name__)


class DdnsService:
    """Dynamic DNS: token-authenticated A/AAAA record updates for hosts whose
    public IP changes (home servers, residential connections, etc.)."""

    @staticmethod
    def list_hosts():
        return DdnsHost.query.order_by(DdnsHost.created_at.desc()).all()

    @staticmethod
    def get_host(host_id):
        return DdnsHost.query.get(host_id)

    @staticmethod
    def create_host(data):
        zone_id = data.get('zone_id')
        zone = DNSZone.query.get(zone_id) if zone_id else None
        if not zone:
            raise ValidationError('Valid zone_id required')

        record_name = (data.get('record_name') or '@').strip() or '@'
        host = DdnsHost(
            zone_id=zone.id,
            record_name=record_name,
            label=(data.get('label') or '').strip() or None,
            token=DdnsHost.generate_token(),
            enabled=bool(data.get('enabled', True)),
        )
        db.session.add(host)
        db.session.commit()
        return host

    @staticmethod
    def delete_host(host_id):
        host = DdnsHost.query.get(host_id)
        if not host:
            return False
        db.session.delete(host)
        db.session.commit()
        return True

    @staticmethod
    def regenerate_token(host_id):
        host = DdnsHost.query.get(host_id)
        if not host:
            return None
        host.token = DdnsHost.generate_token()
        db.session.commit()
        return host

    @staticmethod
    def _record_type_for(ip):
        # Raises ValueError on anything that isn't a valid IP.
        return 'AAAA' if ipaddress.ip_address(ip).version == 6 else 'A'

    @staticmethod
    def update_ip(token, ip):
        """Apply a new IP to the host's record and return (status, host) where
        status is 'updated' or 'unchanged'. Reuses DNSZoneService so any
        configured provider (e.g. Cloudflare) is synced automatically."""
        host = DdnsHost.query.filter_by(token=token, enabled=True).first()
        if not host:
            raise AuthenticationError('Invalid or disabled token')

        ip = (ip or '').strip()
        try:
            record_type = DdnsService._record_type_for(ip)
        except ValueError as e:
            raise ValidationError(f'Invalid IP address: {ip}') from e

        record = DNSRecord.query.filter_by(
            zone_id=host.zone_id, record_type=record_type, name=host.record_name
        ).first()

        changed = False
        if record is None:
            DNSZoneService.create_record(host.zone_id, {
                'record_type': record_type, 'name': host.record_name,
                'content': ip, 'ttl': 60,
            })
            changed = True
        elif record.content != ip:
            DNSZoneService.update_record(record.id, {'content': ip})
            changed = True

        host.last_ip = ip
        host.last_update_at = datetime.utcnow()
        db.session.commit()
        logger.info('DDNS %s -> %s (%s)', host.hostname, ip, 'changed' if changed else 'noop')
        return ('updated' if changed else 'unchanged', host)
