"""Request contracts for event-subscription management."""

from marshmallow import fields, validate

from app.api.contracts import ApiSchema


class CreateEventSubscriptionSchema(ApiSchema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    url = fields.String(required=True, validate=validate.Length(min=1, max=2048))
    events = fields.List(
        fields.String(validate=validate.Length(min=1, max=100)),
        required=True,
        validate=validate.Length(min=1),
    )
    retry_count = fields.Integer(load_default=3, validate=validate.Range(min=0, max=20))
    timeout_seconds = fields.Integer(
        load_default=10,
        validate=validate.Range(min=1, max=300),
    )
    generate_secret = fields.Boolean(load_default=True)
    headers = fields.Dict(load_default=None, allow_none=True)


class UpdateEventSubscriptionSchema(ApiSchema):
    name = fields.String(validate=validate.Length(min=1, max=100))
    url = fields.String(validate=validate.Length(min=1, max=2048))
    events = fields.List(
        fields.String(validate=validate.Length(min=1, max=100)),
        validate=validate.Length(min=1),
    )
    is_active = fields.Boolean()
    retry_count = fields.Integer(validate=validate.Range(min=0, max=20))
    timeout_seconds = fields.Integer(validate=validate.Range(min=1, max=300))
    headers = fields.Dict(allow_none=True)


class DeliveryListQuerySchema(ApiSchema):
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Integer(
        load_default=50,
        validate=validate.Range(min=1, max=200),
    )
