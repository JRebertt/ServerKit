# Connection provider SDK

ServerKit's Connections page reads credentials from several persistence models.
Those models do not need to be collapsed into one table, but their behavior must
cross one service contract before new providers are added.

The contract lives in `backend/app/services/connection_provider_sdk.py` and has
six named operations:

- `validate(payload, partial=False)` validates credential shape without storing it.
- `test(ref)` performs a live, read-only authentication check.
- `list_resources(ref)` returns provider-owned resources when the API supports it.
- `health(ref)` returns the last normalized health observation.
- `rotate(ref, payload)` tests replacement credentials before committing them.
- `disconnect(ref)` removes the connection and its stored secret material.

Every operation returns a `ProviderResult`. Failures use
`ProviderOperationError` so HTTP status, retryability, `Retry-After`, rate-limit
state, and field errors do not depend on the provider's native response shape.
Safe read operations can opt into bounded retries with `max_attempts`; a response
carrying `retry_after` is returned immediately rather than sleeping in a request.

## Adding an adapter

1. Subclass `ConnectionProvider` under `app/services/connection_providers/`.
2. Set a stable `kind`, JSON-style `credential_schema`, and least-privilege
   `permission_scopes`.
3. Override only operations the provider can actually support. Capability
   discovery is derived from these overrides; unsupported operations remain
   explicit in the schema.
4. Decorate the class with `@ConnectionProviderRegistry.register` and import it
   from `connection_providers/__init__.py`.
5. Keep raw credentials inside the adapter/service boundary. Exceptions, audit
   details, health messages, and `ProviderResult.data` must be secret-free.
6. Add contract tests for validation, failed rotation rollback, health, rate
   limits, permissions, and disconnect.

The admin API is rooted at `/api/v1/connections/providers`. Mutating operations
and live tests produce `connection.provider.<operation>` audit rows with one
secret-free details shape. Existing provider-specific routes can remain during
migration, but should delegate to the SDK as the container-registry routes do.

## Migration rule

`GET /api/v1/connections` marks entries with `sdk_managed`. A provider family is
not fully migrated until this flag is true and its advertised capability map is
backed by tests. Do not claim `list_resources` or rotation support by returning
an empty success response; leave the capability false until it is real.
