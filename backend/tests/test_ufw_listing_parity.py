"""ufw listing ↔ removal-guard parser parity (#117 bug class).

The rule listing and the SSH-removal guard each parsed `ufw status numbered`
with their own regex, and the listing's omitted LIMIT — so a `ufw limit
22/tcp` rule was invisible in the panel's rule table while the guard still
counted it, and delete-by-number targeted rows the user could not see. Both
paths now share _UFW_NUMBERED_RE; these tests pin that the two views agree.
"""
import types

import pytest

from app.services import firewall_service as fw_module
from app.services.firewall_service import FirewallService


UFW_OUTPUT = """Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     LIMIT IN    Anywhere
[ 2] 80/tcp                     ALLOW IN    Anywhere
[ 3] 443/tcp                    ALLOW IN    Anywhere
[ 4] 8443                       DENY IN     10.0.0.0/8
[ 5] 22/tcp (v6)                LIMIT IN    Anywhere (v6)
"""


@pytest.fixture
def ufw_status(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ['ufw', 'status', 'numbered']
        return types.SimpleNamespace(returncode=0, stdout=UFW_OUTPUT, stderr='')
    monkeypatch.setattr(fw_module, 'run_privileged', fake_run)


def test_listing_sees_limit_rules(ufw_status):
    result = FirewallService._get_ufw_rules()
    assert result['success']
    by_number = {r['number']: r for r in result['rules']}
    assert by_number[1]['action'] == 'LIMIT'
    assert by_number[1]['port'] == '22/tcp'
    assert by_number[5]['action'] == 'LIMIT'


def test_listing_and_guard_agree_on_every_row(ufw_status):
    listed = FirewallService._get_ufw_rules()['rules']
    guarded = FirewallService._ufw_numbered_rules()

    assert [r['number'] for r in listed] == [r['number'] for r in guarded] == [1, 2, 3, 4, 5]
    for shown, checked in zip(listed, guarded):
        assert shown['action'] == checked['action']
        assert shown['port'].strip() == checked['to']


def test_no_phantom_gaps_in_numbering(ufw_status):
    # The old listing regex dropped LIMIT rows, so the visible numbers had
    # holes and delete-by-number pointed at rules the table never showed.
    numbers = [r['number'] for r in FirewallService._get_ufw_rules()['rules']]
    assert numbers == list(range(1, len(numbers) + 1))
