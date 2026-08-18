"""Webhook event-subscription HTTP boundary."""

from flask import Blueprint, jsonify

from app.api.contracts import api_contract
from app.api.schemas.event_subscriptions import (
    CreateEventSubscriptionSchema,
    DeliveryListQuerySchema,
    UpdateEventSubscriptionSchema,
)
from app.middleware.rbac import (
    auth_required,
    developer_required,
    get_current_user,
)
from app.services import event_subscription_service
from app.services.event_service import EventService


event_subscriptions_bp = Blueprint('event_subscriptions', __name__)


@event_subscriptions_bp.route('/', methods=['GET'])
@developer_required
def list_subscriptions():
    """List webhook subscriptions visible to the caller."""
    subscriptions = event_subscription_service.list_for_user(get_current_user())
    return jsonify({'subscriptions': [item.to_dict() for item in subscriptions]})


@event_subscriptions_bp.route('/', methods=['POST'])
@developer_required
@api_contract(body=CreateEventSubscriptionSchema)
def create_subscription(body):
    """Create a new webhook subscription."""
    result = event_subscription_service.create(get_current_user(), body)
    return jsonify(result), 201


@event_subscriptions_bp.route('/events', methods=['GET'])
@auth_required()
def list_events():
    """List available event types."""
    return jsonify({'events': EventService.get_available_events()})


@event_subscriptions_bp.route('/<int:sub_id>', methods=['GET'])
@auth_required()
def get_subscription(sub_id):
    """Get subscription details."""
    subscription = event_subscription_service.get_for_user(
        get_current_user(), sub_id
    )
    return jsonify(subscription.to_dict())


@event_subscriptions_bp.route('/<int:sub_id>', methods=['PUT'])
@auth_required()
@api_contract(body=UpdateEventSubscriptionSchema)
def update_subscription(sub_id, body):
    """Update a webhook subscription."""
    subscription = event_subscription_service.update(
        get_current_user(), sub_id, body
    )
    return jsonify(subscription.to_dict())


@event_subscriptions_bp.route('/<int:sub_id>', methods=['DELETE'])
@auth_required()
def delete_subscription(sub_id):
    """Delete a webhook subscription."""
    event_subscription_service.delete(get_current_user(), sub_id)
    return jsonify({'message': 'Subscription deleted'})


@event_subscriptions_bp.route('/<int:sub_id>/test', methods=['POST'])
@auth_required()
def test_subscription(sub_id):
    """Queue a test event for a subscription."""
    delivery = event_subscription_service.send_test(get_current_user(), sub_id)
    return jsonify(delivery.to_dict())


@event_subscriptions_bp.route('/<int:sub_id>/deliveries', methods=['GET'])
@auth_required()
@api_contract(query=DeliveryListQuerySchema)
def list_deliveries(sub_id, query):
    """Get delivery history for a subscription."""
    pagination = event_subscription_service.list_deliveries(
        get_current_user(),
        sub_id,
        page=query['page'],
        per_page=query['per_page'],
    )
    return jsonify({
        'deliveries': [delivery.to_dict() for delivery in pagination.items],
        'total': pagination.total,
        'page': query['page'],
        'per_page': query['per_page'],
        'pages': pagination.pages,
    })


@event_subscriptions_bp.route(
    '/<int:sub_id>/deliveries/<int:delivery_id>/retry',
    methods=['POST'],
)
@auth_required()
def retry_delivery(sub_id, delivery_id):
    """Reset and enqueue a failed delivery."""
    delivery = event_subscription_service.retry_delivery(
        get_current_user(), sub_id, delivery_id
    )
    return jsonify(delivery.to_dict())
