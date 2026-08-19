"""Use cases for user-owned webhook event subscriptions."""

from app import db
from app.exceptions import (
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.models.event_subscription import EventDelivery, EventSubscription
from app.services.event_service import EventService
from app.services.unit_of_work import unit_of_work


def _require_user(user):
    if user is None:
        raise AuthenticationError()
    return user


def get_for_user(user, subscription_id):
    """Resolve one subscription and apply its ownership policy once."""

    user = _require_user(user)
    subscription = db.session.get(EventSubscription, subscription_id)
    if subscription is None:
        raise NotFoundError(
            'Subscription not found', code='event_subscription_not_found'
        )
    if not user.is_admin and subscription.user_id != user.id:
        raise PermissionDeniedError()
    return subscription


def list_for_user(user):
    user = _require_user(user)
    if not user.is_developer:
        raise PermissionDeniedError('Developer access required')
    query = EventSubscription.query
    if not user.is_admin:
        query = query.filter_by(user_id=user.id)
    return query.order_by(EventSubscription.created_at.desc()).all()


def create(user, data):
    user = _require_user(user)
    if not user.is_developer:
        raise PermissionDeniedError('Developer access required')
    if not data.get('name') or not data.get('url'):
        raise ValidationError('Name and URL are required')
    if not data.get('events'):
        raise ValidationError('At least one event type is required')

    subscription = EventSubscription(
        user_id=user.id,
        name=data['name'],
        url=data['url'],
        retry_count=data.get('retry_count', 3),
        timeout_seconds=data.get('timeout_seconds', 10),
    )
    subscription.set_events(data['events'])
    if data.get('generate_secret', True):
        subscription.secret = EventSubscription.generate_secret()
    if data.get('headers'):
        subscription.set_headers(data['headers'])

    with unit_of_work() as session:
        session.add(subscription)

    result = subscription.to_dict()
    if subscription.secret:
        result['secret'] = subscription.secret
    return result


def update(user, subscription_id, data):
    subscription = get_for_user(user, subscription_id)
    scalar_fields = (
        'name', 'url', 'is_active', 'retry_count', 'timeout_seconds',
    )
    with unit_of_work():
        for field in scalar_fields:
            if field in data:
                setattr(subscription, field, data[field])
        if 'events' in data:
            subscription.set_events(data['events'])
        if 'headers' in data:
            subscription.set_headers(data['headers'])
    return subscription


def delete(user, subscription_id):
    subscription = get_for_user(user, subscription_id)
    with unit_of_work() as session:
        session.delete(subscription)


def send_test(user, subscription_id):
    subscription = get_for_user(user, subscription_id)
    delivery = EventService.send_test(subscription.id)
    if delivery is None:
        raise NotFoundError('Subscription not found')
    return delivery


def list_deliveries(user, subscription_id, *, page, per_page):
    subscription = get_for_user(user, subscription_id)
    return EventService.get_deliveries(subscription.id, page, per_page)


def retry_delivery(user, subscription_id, delivery_id):
    subscription = get_for_user(user, subscription_id)
    delivery = EventDelivery.query.filter_by(
        id=delivery_id,
        subscription_id=subscription.id,
    ).first()
    if delivery is None:
        raise NotFoundError('Delivery not found', code='event_delivery_not_found')
    return EventService.retry_delivery(delivery)
