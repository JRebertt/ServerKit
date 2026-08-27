"""Postfix virtual-map add ↔ remove round trip (#117 bug class).

add_domain deduped with a raw substring test (`domain not in content`), so
with sub.example.com already mapped, adding example.com no-opped while still
reporting success; remove_domain filtered alias lines with `@{domain} in l`,
which also deleted example.com.br entries; and appends went through tee -a
with no trailing-newline guard, gluing entries onto a truncated last line.
These tests drive the maps through an in-memory privileged-file store and
assert the join both ways.
"""
import types

import pytest

from app.services import postfix_service as pf_module
from app.services.postfix_service import PostfixService


@pytest.fixture
def map_store(monkeypatch):
    """In-memory stand-in for the privileged read/write doors."""
    store = {}

    def fake_run(cmd, **kwargs):
        if cmd[0] == 'cat':
            return types.SimpleNamespace(
                returncode=0, stdout=store.get(cmd[1], ''), stderr='')
        # postmap / postfix reload are no-ops here
        return types.SimpleNamespace(returncode=0, stdout='', stderr='')

    def fake_write(path, content, append=False, **kwargs):
        store[path] = (store.get(path, '') + content) if append else content
        return {'success': True}

    monkeypatch.setattr(pf_module, 'run_privileged', fake_run)
    monkeypatch.setattr(pf_module, 'write_privileged_file', fake_write)
    return store


def _domains(store):
    return store.get(PostfixService.VIRTUAL_DOMAINS_FILE, '')


def test_add_domain_not_fooled_by_subdomain_substring(map_store):
    assert PostfixService.add_domain('sub.example.com')['success']
    assert PostfixService.add_domain('example.com')['success']

    lines = _domains(map_store).split()
    assert 'example.com' in lines
    assert 'sub.example.com' in lines


def test_add_domain_dedupes_exact_domain(map_store):
    PostfixService.add_domain('example.com')
    PostfixService.add_domain('example.com')
    assert _domains(map_store).count('example.com OK') == 1


def test_remove_domain_spares_superstring_domains(map_store):
    PostfixService.add_alias('admin@example.com', 'root@example.com')
    PostfixService.add_alias('admin@example.com.br', 'root@example.com.br')
    PostfixService.add_mailbox('user@example.com', 'example.com', 'user')
    PostfixService.add_mailbox('user@example.com.br', 'example.com.br', 'user')

    assert PostfixService.remove_domain('example.com')['success']

    aliases = map_store[PostfixService.VIRTUAL_ALIASES_FILE]
    mailboxes = map_store[PostfixService.VIRTUAL_MAILBOXES_FILE]
    assert 'admin@example.com ' not in aliases
    assert 'admin@example.com.br' in aliases
    assert 'user@example.com ' not in mailboxes
    assert 'user@example.com.br' in mailboxes


def test_remove_domain_spares_subdomain_addresses(map_store):
    PostfixService.add_mailbox('user@mail.example.com', 'mail.example.com', 'user')
    PostfixService.add_mailbox('user@example.com', 'example.com', 'user')

    PostfixService.remove_domain('example.com')

    mailboxes = map_store[PostfixService.VIRTUAL_MAILBOXES_FILE]
    assert 'user@mail.example.com' in mailboxes
    assert 'user@example.com ' not in mailboxes


def test_append_heals_missing_trailing_newline(map_store):
    # A map whose last line lost its newline must not have the next entry
    # glued onto it — glued entries are unmatchable on removal.
    map_store[PostfixService.VIRTUAL_ALIASES_FILE] = 'old@a.com dest@a.com'

    PostfixService.add_alias('new@b.com', 'dest@b.com')

    lines = map_store[PostfixService.VIRTUAL_ALIASES_FILE].splitlines()
    assert 'old@a.com dest@a.com' in lines
    assert 'new@b.com dest@b.com' in lines


def test_full_domain_lifecycle(map_store):
    PostfixService.add_domain('shop.test')
    PostfixService.add_mailbox('owner@shop.test', 'shop.test', 'owner')
    PostfixService.add_alias('sales@shop.test', 'owner@shop.test')

    assert PostfixService.remove_domain('shop.test')['success']

    assert 'shop.test' not in _domains(map_store)
    assert 'shop.test' not in map_store[PostfixService.VIRTUAL_MAILBOXES_FILE]
    assert 'shop.test' not in map_store[PostfixService.VIRTUAL_ALIASES_FILE]
