"""Service for generating OpenAPI 3.0 specification."""
import re

from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from flask import current_app


class OpenAPIService:
    """Auto-generates OpenAPI 3.0 spec from registered Flask routes."""

    # Blueprint name to tag mapping
    TAG_MAP = {
        'auth': 'Authentication',
        'apps': 'Applications',
        'domains': 'Domains',
        'docker': 'Docker',
        'databases': 'Databases',
        'system': 'System',
        'processes': 'Processes',
        'logs': 'Logs',
        'nginx': 'Nginx',
        'ssl': 'SSL Certificates',
        'php': 'PHP',
        'wordpress': 'WordPress',
        'wordpress_sites': 'WordPress Sites',
        'python': 'Python',
        'monitoring': 'Monitoring',
        'notifications': 'Notifications',
        'backups': 'Backups',
        'deploy': 'Deployment',
        'builds': 'Builds',
        'templates': 'Templates',
        'files': 'File Manager',
        'ftp': 'FTP Server',
        'firewall': 'Firewall',
        'git': 'Git Server',
        'security': 'Security',
        'cron': 'Cron Jobs',
        'email': 'Email',
        'uptime': 'Uptime',
        'admin': 'Admin',
        'metrics': 'Metrics',
        'workflows': 'Workflows',
        'servers': 'Servers',
        'api_keys': 'API Keys',
        'api_analytics': 'API Analytics',
        'event_subscriptions': 'Event Subscriptions',
        'two_factor': 'Two-Factor Auth',
        'sso': 'SSO / OAuth',
        'migrations': 'Database Migrations',
        'env_vars': 'Environment Variables',
        'private_urls': 'Private URLs',
    }

    @staticmethod
    def generate_spec():
        """Generate the full OpenAPI 3.0 spec."""
        app = current_app

        spec = {
            'openapi': '3.0.3',
            'info': {
                'title': 'ServerKit API',
                'description': 'Server control panel API for managing web applications, databases, Docker containers, and security.',
                'version': '1.0.0',
                'contact': {
                    'name': 'ServerKit',
                },
            },
            'servers': [
                {
                    'url': '/api/v1',
                    'description': 'API v1',
                },
            ],
            'components': {
                'securitySchemes': {
                    'BearerAuth': {
                        'type': 'http',
                        'scheme': 'bearer',
                        'bearerFormat': 'JWT',
                        'description': 'JWT access token',
                    },
                    'ApiKeyAuth': {
                        'type': 'apiKey',
                        'in': 'header',
                        'name': 'X-API-Key',
                        'description': 'API key (sk_...)',
                    },
                },
                'schemas': {
                    'Error': {
                        'type': 'object',
                        'required': ['error', 'status', 'code', 'request_id'],
                        'properties': {
                            'error': {
                                'type': 'string',
                                'description': 'Error message',
                            },
                            'status': {'type': 'integer'},
                            'code': {'type': 'string'},
                            'details': {
                                'type': 'object',
                                'additionalProperties': True,
                            },
                            'request_id': {'type': 'string'},
                        },
                    },
                    'Message': {
                        'type': 'object',
                        'properties': {
                            'message': {
                                'type': 'string',
                                'description': 'Success message',
                            },
                        },
                    },
                },
                'responses': {
                    '401': {
                        'description': 'Unauthorized',
                        'content': {
                            'application/json': {
                                'schema': {'$ref': '#/components/schemas/Error'},
                            },
                        },
                    },
                    '403': {
                        'description': 'Forbidden',
                        'content': {
                            'application/json': {
                                'schema': {'$ref': '#/components/schemas/Error'},
                            },
                        },
                    },
                    '404': {
                        'description': 'Not found',
                        'content': {
                            'application/json': {
                                'schema': {'$ref': '#/components/schemas/Error'},
                            },
                        },
                    },
                },
            },
            'security': [
                {'BearerAuth': []},
                {'ApiKeyAuth': []},
            ],
            'paths': {},
            'tags': [],
        }

        # Collect tags and paths from registered routes
        tags_seen = set()
        paths = {}
        marshmallow_plugin = MarshmallowPlugin()
        schema_spec = APISpec(
            title='ServerKit endpoint schemas',
            version='1.0.0',
            openapi_version='3.0.3',
            plugins=[marshmallow_plugin],
        )

        def schema_ref(schema_type):
            """Register a Marshmallow schema once and return its OpenAPI ref."""
            name = schema_type.__name__
            # The Marshmallow plugin registers nested schemas recursively, so
            # consult the component registry itself rather than a parallel set.
            if name not in schema_spec.components.schemas:
                schema_spec.components.schema(name, schema=schema_type)
            generated = schema_spec.to_dict().get('components', {}).get('schemas', {})
            spec['components']['schemas'].update(generated)
            return {'$ref': f'#/components/schemas/{name}'}

        def query_parameters(schema_type):
            """Expand a query-object schema into ordinary OpenAPI parameters."""
            schema_ref(schema_type)
            document = spec['components']['schemas'][schema_type.__name__]
            required = set(document.get('required', ()))
            return [
                {
                    'name': name,
                    'in': 'query',
                    'required': name in required,
                    'schema': field_schema,
                }
                for name, field_schema in document.get('properties', {}).items()
            ]

        for rule in app.url_map.iter_rules():
            # Only include API routes
            if not rule.rule.startswith('/api/v1/'):
                continue

            # Skip static and internal routes
            if rule.endpoint == 'static' or rule.rule.endswith('/openapi.json'):
                continue

            # Get blueprint name
            parts = rule.endpoint.split('.')
            bp_name = parts[0] if len(parts) > 1 else None

            # Convert Flask URL params to OpenAPI format
            path = rule.rule.replace('/api/v1', '')
            path = re.sub(r'<(?:int:|string:|float:)?(\w+)>', r'{\1}', path)

            # Get tag
            tag = OpenAPIService.TAG_MAP.get(bp_name, bp_name or 'Other')
            if tag not in tags_seen:
                tags_seen.add(tag)

            # Get view function docstring
            view_func = app.view_functions.get(rule.endpoint)
            contract = getattr(view_func, '__api_contract__', None)
            description = ''
            if view_func and view_func.__doc__:
                description = view_func.__doc__.strip()

            # Build path item
            if path not in paths:
                paths[path] = {}

            methods = [m.lower() for m in rule.methods if m not in ('HEAD', 'OPTIONS')]
            for method in methods:
                operation = {
                    'tags': [tag],
                    'summary': description or f'{method.upper()} {path}',
                    'operationId': rule.endpoint.replace('.', '_'),
                    'responses': {
                        '200': {
                            'description': 'Success',
                            'content': {
                                'application/json': {
                                    'schema': {'type': 'object'},
                                },
                            },
                        },
                        '401': {'$ref': '#/components/responses/401'},
                        '403': {'$ref': '#/components/responses/403'},
                    },
                }

                if contract and contract.responses:
                    operation['responses'].pop('200', None)
                    for status, response_contract in contract.responses.items():
                        operation['responses'][str(status)] = {
                            'description': response_contract.description,
                            'content': {
                                'application/json': {
                                    'schema': schema_ref(response_contract.schema),
                                },
                            },
                        }

                # Add path parameters
                params = re.findall(r'\{(\w+)\}', path)
                if params:
                    operation['parameters'] = []
                    for param in params:
                        operation['parameters'].append({
                            'name': param,
                            'in': 'path',
                            'required': True,
                            'schema': {'type': 'integer' if param.endswith('_id') or param == 'id' else 'string'},
                        })

                if contract and contract.query:
                    operation.setdefault('parameters', []).extend(
                        query_parameters(contract.query)
                    )

                # Add request body for POST/PUT/PATCH
                if contract and contract.body:
                    operation['requestBody'] = {
                        'required': True,
                        'content': {
                            'application/json': {
                                'schema': schema_ref(contract.body),
                            },
                        },
                    }
                elif method in ('post', 'put', 'patch'):
                    operation['requestBody'] = {
                        'content': {
                            'application/json': {
                                'schema': {'type': 'object'},
                            },
                        },
                    }

                if len(methods) > 1:
                    operation['operationId'] = f'{rule.endpoint.replace(".", "_")}_{method}'

                paths[path][method] = operation

        spec['paths'] = dict(sorted(paths.items()))
        spec['tags'] = [{'name': t} for t in sorted(tags_seen)]

        return spec
