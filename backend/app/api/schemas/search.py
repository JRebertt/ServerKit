"""Contracts for the unified entity search endpoint."""

from marshmallow import fields, post_load, validate

from app.api.contracts import ApiSchema


class SearchQuerySchema(ApiSchema):
    q = fields.String(load_default='')
    workspace_id = fields.String(load_default=None, allow_none=True)
    project_id = fields.Integer(load_default=None, allow_none=True)
    environment_id = fields.Integer(load_default=None, allow_none=True)
    types = fields.String(load_default=None, allow_none=True)
    capabilities = fields.String(load_default=None, allow_none=True)
    cursor = fields.String(
        load_default=None,
        allow_none=True,
        validate=validate.Length(max=256),
    )
    limit = fields.Integer(
        load_default=None,
        allow_none=True,
        validate=validate.Range(min=1, max=100),
    )

    @post_load
    def normalize(self, data, **_kwargs):
        data['q'] = data['q'].strip()
        if data.get('workspace_id') is not None:
            data['workspace_id'] = data['workspace_id'].strip() or None
        for key in ('types', 'capabilities'):
            raw = data.get(key)
            if raw is None:
                continue
            values = []
            for value in raw.split(','):
                value = value.strip()
                if value and value not in values:
                    values.append(value)
            data[key] = values or None
        if data.get('cursor') is not None:
            data['cursor'] = data['cursor'].strip() or None
        return data


class SearchScopeSchema(ApiSchema):
    workspace_id = fields.Integer(required=False, allow_none=True)
    project_id = fields.Integer(required=False, allow_none=True)
    environment_id = fields.Integer(required=False, allow_none=True)


class SearchResultSchema(ApiSchema):
    type = fields.String(required=True)
    id = fields.String(required=True)
    label = fields.String(required=True)
    sublabel = fields.String(required=True)
    path = fields.String(required=True)
    scope = fields.Nested(SearchScopeSchema, required=True)
    status = fields.String(required=False, allow_none=True)
    capabilities = fields.List(fields.String(), required=True)


class ListMetaSchema(ApiSchema):
    total = fields.Integer(required=True)
    next_cursor = fields.String(required=False, allow_none=True)


class SearchResponseSchema(ApiSchema):
    data = fields.List(fields.Nested(SearchResultSchema), required=True)
    meta = fields.Nested(ListMetaSchema, required=True)
    # Additive compatibility field. Remove after external clients have migrated
    # to ``data`` and the frontend compatibility adapter is no longer needed.
    results = fields.List(fields.Nested(SearchResultSchema), required=True)
