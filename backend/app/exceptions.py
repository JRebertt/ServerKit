"""Typed application errors rendered consistently at the HTTP boundary.

Services may raise these errors when a caller can act on the failure.  Flask
owns their JSON representation; service code therefore does not need to know
about ``jsonify`` or duplicate status-code mapping.

The subclasses of built-in exception types are intentional compatibility
bridges.  Existing callers that catch ``ValueError`` or ``LookupError`` keep
working while a feature is migrated incrementally to the typed contract.
"""

from collections.abc import Mapping


class ApplicationError(Exception):
    """Base class for expected, client-safe application failures."""

    status_code = 500
    code = 'application_error'
    default_message = 'Application error'

    def __init__(self, message=None, *, code=None, details=None):
        self.message = str(message or self.default_message)
        self.code = code or type(self).code
        self.details = dict(details) if isinstance(details, Mapping) else None
        super().__init__(self.message)

    def to_dict(self, *, request_id=None):
        """Return the stable public error body used by API handlers."""
        payload = {
            'error': self.message,
            'status': self.status_code,
            'code': self.code,
        }
        if self.details:
            payload['details'] = self.details
        if request_id:
            payload['request_id'] = request_id
        return payload


class ValidationError(ApplicationError, ValueError):
    status_code = 400
    code = 'validation_error'
    default_message = 'Invalid request'


class AuthenticationError(ApplicationError):
    status_code = 401
    code = 'authentication_required'
    default_message = 'Authentication required'


class PermissionDeniedError(ApplicationError, PermissionError):
    status_code = 403
    code = 'permission_denied'
    default_message = 'Access denied'


class NotFoundError(ApplicationError, LookupError):
    status_code = 404
    code = 'not_found'
    default_message = 'Resource not found'


class ConflictError(ApplicationError):
    status_code = 409
    code = 'conflict'
    default_message = 'Resource conflict'


class DependencyUnavailableError(ApplicationError):
    status_code = 503
    code = 'dependency_unavailable'
    default_message = 'Dependency unavailable'
