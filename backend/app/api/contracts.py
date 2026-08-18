"""Typed request validation and OpenAPI metadata for API endpoints.

The route is still an ordinary Flask function.  This module owns only the HTTP
boundary: it loads query/JSON input through a Marshmallow schema, raises the
shared application ``ValidationError`` on bad input, and records enough
metadata for ``OpenAPIService`` to document the real contract.

Usage::

    @blueprint.route('', methods=['POST'])
    @auth_required()
    @api_contract(body=CreateWidgetSchema, responses={201: WidgetEnvelopeSchema})
    def create_widget(body):
        return data_response(widget_service.create(body), status=201)

Decorators that use ``functools.wraps`` (including ServerKit's authentication
decorators) preserve ``__api_contract__`` when they wrap this one.
"""

from dataclasses import dataclass
from functools import wraps
from typing import Mapping

from flask import request
from marshmallow import RAISE, Schema, ValidationError as SchemaValidationError

from app.exceptions import ValidationError


class ApiSchema(Schema):
    """Strict base schema for an HTTP request or response contract."""

    class Meta:
        unknown = RAISE


@dataclass(frozen=True)
class ResponseContract:
    """One documented response body."""

    schema: type[Schema]
    description: str = 'Success'


@dataclass(frozen=True)
class EndpointContract:
    """Metadata attached to a validated Flask view."""

    query: type[Schema] | None
    body: type[Schema] | None
    responses: Mapping[int, ResponseContract]


def _schema_type(schema):
    if schema is None:
        return None
    if isinstance(schema, type) and issubclass(schema, Schema):
        return schema
    raise TypeError('API contracts require a marshmallow Schema class')


def _response_contracts(responses):
    normalized = {}
    for status, value in (responses or {}).items():
        if isinstance(value, ResponseContract):
            normalized[int(status)] = value
        else:
            normalized[int(status)] = ResponseContract(_schema_type(value))
    return normalized


def _load(schema_type, raw, *, location):
    try:
        return schema_type().load(raw)
    except SchemaValidationError as exc:
        label = 'query parameters' if location == 'query' else 'JSON body'
        raise ValidationError(
            f'Invalid {label}',
            code=f'invalid_{location}',
            details={'fields': exc.messages},
        ) from exc


def api_contract(*, query=None, body=None, responses=None):
    """Validate endpoint input and publish its machine-readable contract.

    Validated values are passed as the ``query`` and/or ``body`` keyword
    arguments.  Request schemas are instantiated per call so custom schema
    state cannot leak between concurrent requests.
    """

    query_type = _schema_type(query)
    body_type = _schema_type(body)
    contract = EndpointContract(
        query=query_type,
        body=body_type,
        responses=_response_contracts(responses),
    )

    def decorate(view):
        @wraps(view)
        def validated_view(*args, **kwargs):
            if query_type is not None:
                raw_query = request.args.to_dict(flat=True)
                kwargs['query'] = _load(query_type, raw_query, location='query')

            if body_type is not None:
                raw_body = request.get_json(silent=True)
                kwargs['body'] = _load(
                    body_type,
                    {} if raw_body is None else raw_body,
                    location='body',
                )

            return view(*args, **kwargs)

        validated_view.__api_contract__ = contract
        return validated_view

    return decorate
