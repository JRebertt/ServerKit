"""Unit tests for the typed endpoint-contract and response-envelope boundary."""

import pytest
from flask import Flask
from marshmallow import fields

from app.api.contracts import ApiSchema, api_contract
from app.api.responses import data_response, list_response
from app.exceptions import ValidationError
from app.services.openapi_service import OpenAPIService


class ExampleQuery(ApiSchema):
    limit = fields.Integer(required=True)


class ExampleBody(ApiSchema):
    name = fields.String(required=True)


class ExampleResponse(ApiSchema):
    data = fields.Nested(ExampleBody, required=True)


def test_contract_loads_typed_query_and_json_body():
    app = Flask(__name__)

    @api_contract(query=ExampleQuery, body=ExampleBody)
    def endpoint(query, body):
        return query, body

    with app.test_request_context('/?limit=3', method='POST', json={'name': 'demo'}):
        query, body = endpoint()

    assert query == {'limit': 3}
    assert body == {'name': 'demo'}


def test_contract_raises_shared_typed_validation_error():
    app = Flask(__name__)

    @api_contract(query=ExampleQuery)
    def endpoint(query):
        return query

    with app.test_request_context('/?limit=nope'):
        with pytest.raises(ValidationError) as raised:
            endpoint()

    assert raised.value.code == 'invalid_query'
    assert raised.value.details == {
        'fields': {'limit': ['Not a valid integer.']},
    }


def test_response_helpers_emit_one_canonical_shape():
    app = Flask(__name__)
    with app.app_context():
        response, status = data_response({'id': 1}, status=201, message='Created')
        assert status == 201
        assert response.get_json() == {
            'data': {'id': 1},
            'message': 'Created',
        }

        response, status = list_response(
            [{'id': 1}], total=4, meta={'skip': 0}, legacy_key='items',
        )
        assert status == 200
        assert response.get_json() == {
            'data': [{'id': 1}],
            'meta': {'skip': 0, 'total': 4},
            'items': [{'id': 1}],
        }


def test_openapi_uses_endpoint_contract_instead_of_generic_objects():
    app = Flask(__name__)

    @app.post('/api/v1/examples')
    @api_contract(
        query=ExampleQuery,
        body=ExampleBody,
        responses={201: ExampleResponse},
    )
    def endpoint(query, body):
        return {'data': body}, 201

    with app.app_context():
        spec = OpenAPIService.generate_spec()

    operation = spec['paths']['/examples']['post']
    assert operation['requestBody']['content']['application/json']['schema'] == {
        '$ref': '#/components/schemas/ExampleBody',
    }
    assert operation['responses']['201']['content']['application/json']['schema'] == {
        '$ref': '#/components/schemas/ExampleResponse',
    }
    assert operation['parameters'] == [{
        'name': 'limit',
        'in': 'query',
        'required': True,
        'schema': {'type': 'integer'},
    }]
    assert spec['components']['schemas']['ExampleBody']['required'] == ['name']
