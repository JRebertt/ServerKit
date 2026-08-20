"""Inbound webhook gateway service with HMAC verification and delivery logging."""
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import requests

from app import db
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import WebhookEndpoint, WebhookDelivery
from app.utils.slug import unique_slug

logger = logging.getLogger(__name__)


class WebhookGatewayService:
    """Receive, inspect, route, and replay inbound webhooks."""

    @classmethod
    def list_endpoints(cls, workspace_id: int = None) -> List[Dict]:
        query = WebhookEndpoint.query
        if workspace_id is not None:
            query = query.filter(WebhookEndpoint.workspace_id == workspace_id)
        return [e.to_dict() for e in query.order_by(WebhookEndpoint.name).all()]

    @classmethod
    def get_endpoint(cls, endpoint_id: int) -> Optional[WebhookEndpoint]:
        return WebhookEndpoint.query.get(endpoint_id)

    @classmethod
    def get_endpoint_by_slug(cls, slug: str) -> Optional[WebhookEndpoint]:
        return WebhookEndpoint.query.filter_by(slug=slug, is_active=True).first()

    @classmethod
    def _unique_slug(cls, name: str) -> str:
        return unique_slug(
            name,
            lambda s: WebhookEndpoint.query.filter_by(slug=s).first() is not None,
            default='endpoint',
        )

    @classmethod
    def create_endpoint(cls, name: str, secret: str = None, forward_url: str = None,
                        filter_paths: List[str] = None, retry_count: int = 3,
                        user_id: int = None, workspace_id: int = None) -> Dict:
        if WebhookEndpoint.query.filter_by(name=name).first():
            raise ConflictError('Endpoint name already exists')
        endpoint = WebhookEndpoint(
            name=name,
            slug=cls._unique_slug(name),
            secret=secret or secrets.token_urlsafe(32),
            forward_url=forward_url,
            retry_count=retry_count,
            created_by=user_id,
            workspace_id=workspace_id,
        )
        if filter_paths:
            endpoint.set_filter_paths(filter_paths)
        db.session.add(endpoint)
        db.session.commit()
        return endpoint.to_dict()

    @classmethod
    def update_endpoint(cls, endpoint_id: int, name: str = None, forward_url: str = None,
                        filter_paths: List[str] = None, retry_count: int = None,
                        is_active: bool = None) -> Dict:
        endpoint = cls.get_endpoint(endpoint_id)
        if not endpoint:
            raise NotFoundError('Endpoint not found')
        if name is not None:
            existing = WebhookEndpoint.query.filter(WebhookEndpoint.name == name, WebhookEndpoint.id != endpoint_id).first()
            if existing:
                raise ConflictError('Endpoint name already exists')
            endpoint.name = name
        if forward_url is not None:
            endpoint.forward_url = forward_url
        if filter_paths is not None:
            endpoint.set_filter_paths(filter_paths)
        if retry_count is not None:
            endpoint.retry_count = retry_count
        if is_active is not None:
            endpoint.is_active = is_active
        db.session.commit()
        return endpoint.to_dict()

    @classmethod
    def delete_endpoint(cls, endpoint_id: int) -> Dict:
        endpoint = cls.get_endpoint(endpoint_id)
        if not endpoint:
            raise NotFoundError('Endpoint not found')
        db.session.delete(endpoint)
        db.session.commit()

    @classmethod
    def regenerate_secret(cls, endpoint_id: int) -> Dict:
        endpoint = cls.get_endpoint(endpoint_id)
        if not endpoint:
            raise NotFoundError('Endpoint not found')
        endpoint.secret = secrets.token_urlsafe(32)
        db.session.commit()
        return {'endpoint': endpoint.to_dict(), 'secret': endpoint.secret}

    @classmethod
    def _extract_signature(cls, headers: Dict) -> tuple:
        for key, value in headers.items():
            if key.lower() == 'x-hub-signature-256' and isinstance(value, str):
                return value, 'sha256'
            if key.lower() == 'x-hub-signature' and isinstance(value, str):
                return value, 'sha1'
            if key.lower() == 'x-signature' and isinstance(value, str):
                return value, 'sha256'
        return '', ''

    @classmethod
    def _matches_filters(cls, payload: Dict, filter_paths: List[str]) -> bool:
        """Simple dotted-path filter. Returns True if no filters or any filter matches."""
        if not filter_paths:
            return True
        for path in filter_paths:
            parts = path.strip('.').split('.')
            node = payload
            try:
                for part in parts:
                    if isinstance(node, dict):
                        node = node[part]
                    elif isinstance(node, list) and part.isdigit():
                        node = node[int(part)]
                    else:
                        break
                else:
                    return True
            except (KeyError, IndexError, TypeError):
                continue
        return False

    @classmethod
    def receive(cls, slug: str, payload: bytes, headers: Dict) -> Dict:
        """Receive an inbound webhook, verify signature, log, and optionally forward."""
        endpoint = cls.get_endpoint_by_slug(slug)
        if not endpoint:
            return {'success': False, 'error': 'Endpoint not found'}, 404

        event_id = headers.get('X-Webhook-Event-ID') or headers.get('x-webhook-event-id') or str(uuid.uuid4())

        # Avoid duplicate deliveries
        if WebhookDelivery.query.filter_by(event_id=event_id).first():
            return {'success': True, 'message': 'Duplicate delivery ignored', 'event_id': event_id}, 200

        signature_header, algorithm = cls._extract_signature(headers)
        signature_valid = endpoint.verify_signature(payload, signature_header, algorithm)

        delivery = WebhookDelivery(
            endpoint_id=endpoint.id,
            event_id=event_id,
            payload=payload.decode('utf-8', errors='replace') if payload else None,
            signature_valid=signature_valid,
        )
        delivery.set_headers(headers)
        db.session.add(delivery)
        db.session.commit()

        # Reject unconditionally: every endpoint has a secret, so a request with
        # a missing OR wrong signature is equally unauthenticated. The old
        # `and signature_header` clause let unsigned requests through.
        if not signature_valid:
            delivery.status = 'failed'
            delivery.error_message = 'Invalid signature' if signature_header else 'Missing signature'
            delivery.completed_at = datetime.utcnow()
            db.session.commit()
            return {'success': False, 'error': delivery.error_message, 'event_id': event_id}, 401

        try:
            payload_json = json.loads(payload.decode('utf-8', errors='replace')) if payload else {}
        except Exception:
            payload_json = {}

        if not cls._matches_filters(payload_json, endpoint.get_filter_paths()):
            delivery.status = 'filtered'
            delivery.completed_at = datetime.utcnow()
            db.session.commit()
            return {'success': True, 'message': 'Filtered', 'event_id': event_id}, 200

        if endpoint.forward_url:
            forwarded = cls._forward(endpoint, delivery, payload, headers)
            delivery.response_status = forwarded.get('status')
            delivery.response_body = forwarded.get('body', '')[:2000]
            if forwarded.get('success'):
                delivery.status = 'forwarded'
            else:
                delivery.status = 'failed'
                delivery.error_message = forwarded.get('error')
        else:
            delivery.status = 'received'

        delivery.completed_at = datetime.utcnow()
        db.session.commit()
        return {'success': True, 'event_id': event_id, 'status': delivery.status}, 200

    @classmethod
    def _forward(cls, endpoint: WebhookEndpoint, delivery: WebhookDelivery,
                 payload: bytes, headers: Dict) -> Dict:
        forward_headers = {
            'Content-Type': headers.get('Content-Type', 'application/json'),
            'X-Webhook-Event-ID': delivery.event_id,
            'X-Webhook-Source': 'serverkit-gateway',
        }
        for attempt in range(max(1, endpoint.retry_count)):
            try:
                resp = requests.post(
                    endpoint.forward_url,
                    data=payload,
                    headers=forward_headers,
                    timeout=30,
                    verify=True,
                )
                return {
                    'success': 200 <= resp.status_code < 300,
                    'status': resp.status_code,
                    'body': resp.text[:1000]
                }
            except Exception as e:
                if attempt == max(1, endpoint.retry_count) - 1:
                    return {'success': False, 'error': str(e)}
        return {'success': False, 'error': 'Forward failed'}

    @classmethod
    def list_deliveries(cls, endpoint_id: int, limit: int = 50, status: str = None) -> List[Dict]:
        query = WebhookDelivery.query.filter_by(endpoint_id=endpoint_id)
        if status:
            query = query.filter_by(status=status)
        deliveries = query.order_by(WebhookDelivery.received_at.desc()).limit(limit).all()
        return [d.to_dict() for d in deliveries]

    @classmethod
    def get_delivery(cls, delivery_id: int) -> Optional[WebhookDelivery]:
        return WebhookDelivery.query.get(delivery_id)

    @classmethod
    def replay_delivery(cls, delivery_id: int) -> Dict:
        delivery = cls.get_delivery(delivery_id)
        if not delivery:
            raise NotFoundError('Delivery not found')
        endpoint = delivery.endpoint
        if not endpoint or not endpoint.forward_url:
            raise ValidationError('Endpoint has no forward URL')
        payload = (delivery.payload or '').encode('utf-8')
        headers = delivery.get_headers()
        result = cls._forward(endpoint, delivery, payload, headers)
        delivery.response_status = result.get('status')
        delivery.response_body = result.get('body', '')[:2000]
        delivery.status = 'forwarded' if result.get('success') else 'failed'
        delivery.error_message = result.get('error')
        delivery.completed_at = datetime.utcnow()
        db.session.commit()
        return {'forwarded': result.get('success', False), 'delivery': delivery.to_dict()}
