"""Contracts for the unified entity search endpoint."""

from marshmallow import fields, post_load

from app.api.contracts import ApiSchema


class SearchQuerySchema(ApiSchema):
    q = fields.String(load_default='')
    workspace_id = fields.String(load_default=None, allow_none=True)

    @post_load
    def normalize(self, data, **_kwargs):
        data['q'] = data['q'].strip()
        if data.get('workspace_id') is not None:
            data['workspace_id'] = data['workspace_id'].strip() or None
        return data


class SearchResultSchema(ApiSchema):
    type = fields.String(required=True)
    label = fields.String(required=True)
    sublabel = fields.String(required=True)
    path = fields.String(required=True)


class ListMetaSchema(ApiSchema):
    total = fields.Integer(required=True)


class SearchResponseSchema(ApiSchema):
    data = fields.List(fields.Nested(SearchResultSchema), required=True)
    meta = fields.Nested(ListMetaSchema, required=True)
    # Additive compatibility field. Remove after external clients have migrated
    # to ``data`` and the frontend compatibility adapter is no longer needed.
    results = fields.List(fields.Nested(SearchResultSchema), required=True)
