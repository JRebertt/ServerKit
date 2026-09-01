"""One door for delete semantics on NOT NULL child FKs.

SQLAlchemy's default when a parent row is deleted is to NULL the child's FK —
dynamic relationships included. For a child whose FK is NOT NULL that default
is not a policy, it is a crash: the UPDATE violates the constraint and the
delete dies with IntegrityError (this is how Recycle Bin purge broke in the
field, then user/server/workspace deletes in the audit that followed).

Rather than every model remembering to write cascade='all, delete-orphan' on
every such relationship — and every reviewer remembering to check — this module
applies it automatically at mapper-configuration time: any one-to-many whose
child FK is NOT NULL gets the delete cascade, because with a NOT NULL FK the
children *cannot* outlive the parent; the only question is whether the delete
works or crashes.

A relationship where the parent delete should be REFUSED instead (the children
are too valuable to cascade) opts out here, and the code path that deletes the
parent must guard explicitly. `test_application_soft_delete.py` pins both
halves: the sweep proves the door leaves no offenders beyond this registry, and
a test per entry proves its guard exists.

Plugin/extension models are covered too: registering a new model triggers a
fresh configure_mappers() run, which fires this hook again (it is idempotent).
"""
from sqlalchemy import event
from sqlalchemy.orm import Mapper

# 'Parent.relationship' -> why cascading would be wrong. Every entry needs a
# guard on the parent's delete path; an entry without one just moves the crash.
DELIBERATELY_UNCASCADED = {
    'User.applications':
        'apps own containers/volumes that must go through app delete + '
        'Recycle Bin purge; delete_user refuses (409) while the user owns any',
    'CloudProvider.servers':
        'no code path deletes a CloudProvider row today; silently dropping '
        'the inventory of provisioned (billing!) VMs must stay a deliberate, '
        'guarded decision if one is ever added',
}


def _needs_delete_cascade(rel):
    if rel.direction.name != 'ONETOMANY' or rel.viewonly:
        return False
    fk_cols = [c for c in rel.remote_side if c.foreign_keys]
    if not fk_cols or all(c.nullable for c in fk_cols):
        return False
    return 'delete' not in rel.cascade


@event.listens_for(Mapper, 'after_configured')
def apply_delete_cascades():
    from app import db
    for mapper in db.Model.registry.mappers:
        for rel in mapper.relationships:
            if not _needs_delete_cascade(rel):
                continue
            if f'{mapper.class_.__name__}.{rel.key}' in DELIBERATELY_UNCASCADED:
                continue
            rel.cascade = 'all, delete-orphan'
