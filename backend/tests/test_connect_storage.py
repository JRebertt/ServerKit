"""The panel half of the Storage Hub and the signed-command
runner it rides on. No network: commands are signed with a real
Ed25519 key and verified against a JWKS built from it, and the S3 client is
replaced by the test.
"""
import base64
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services import connect_commands, connect_storage
from app.services.storage_provider_service import StorageProviderService

DEVICE = 'dev_abc123'


@pytest.fixture
def signer():
    """(sign(claims) -> token, jwks) for a throwaway command key."""
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes_raw()
    jwks = {'keys': [{'kty': 'OKP', 'crv': 'Ed25519', 'kid': 'k1',
                      'x': base64.urlsafe_b64encode(raw).decode().rstrip('=')}]}
    pem = key.private_bytes_raw()

    from cryptography.hazmat.primitives import serialization
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    assert pem  # the raw form is what ServerKit Cloud stores; the PEM is what PyJWT signs with

    def sign(**claims):
        body = {'cmd_id': 'cmd_1', 'device_id': DEVICE, 'action': 'storage.test',
                'args': {}, 'scopes': ['storage.manage'], 'nonce': f'n{time.time_ns()}',
                'iat': int(time.time()), 'exp': int(time.time()) + 600}
        body.update(claims)
        return jwt.encode(body, private_pem, algorithm='EdDSA', headers={'kid': 'k1'})

    return sign, jwks


@pytest.fixture(autouse=True)
def storage_file(tmp_path, monkeypatch):
    """storage.json in a temp dir; every test starts with no destination."""
    monkeypatch.setattr(StorageProviderService, 'CONFIG_FILE',
                        str(tmp_path / 'storage.json'))
    connect_commands.NONCES._seen.clear()
    return tmp_path


# ---------- verification ----------


def test_a_valid_command_verifies(signer):
    sign, jwks = signer
    claims = connect_commands.verify(sign(), jwks, DEVICE)
    assert claims['action'] == 'storage.test'


def test_a_command_for_another_server_is_refused(signer):
    sign, jwks = signer
    with pytest.raises(connect_commands.CommandRejected) as e:
        connect_commands.verify(sign(device_id='dev_someone_else'), jwks, DEVICE)
    assert 'different server' in str(e.value)


def test_an_expired_command_is_refused(signer):
    sign, jwks = signer
    with pytest.raises(connect_commands.CommandRejected) as e:
        connect_commands.verify(sign(exp=int(time.time()) - 5), jwks, DEVICE)
    assert 'expired' in str(e.value)


def test_a_command_runs_at_most_once(signer):
    sign, jwks = signer
    token = sign()
    connect_commands.verify(token, jwks, DEVICE)
    with pytest.raises(connect_commands.CommandRejected) as e:
        connect_commands.verify(token, jwks, DEVICE)
    assert 'already been run' in str(e.value)


def test_a_command_signed_by_a_stranger_is_refused(signer):
    _, jwks = signer
    other = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    pem = other.private_bytes(encoding=serialization.Encoding.PEM,
                             format=serialization.PrivateFormat.PKCS8,
                             encryption_algorithm=serialization.NoEncryption())
    token = jwt.encode({'cmd_id': 'c', 'device_id': DEVICE, 'action': 'storage.test',
                        'scopes': ['storage.manage'], 'nonce': 'n1',
                        'exp': int(time.time()) + 60},
                       pem, algorithm='EdDSA', headers={'kid': 'k1'})
    with pytest.raises(connect_commands.CommandRejected) as e:
        connect_commands.verify(token, jwks, DEVICE)
    assert 'did not verify' in str(e.value)


def test_a_command_without_its_consent_scope_is_refused(signer):
    sign, jwks = signer
    with pytest.raises(connect_commands.CommandRejected) as e:
        connect_commands.verify(sign(scopes=['metrics.read']), jwks, DEVICE)
    assert 'storage.manage' in str(e.value)


def test_with_no_jwks_nothing_runs(signer):
    sign, _ = signer
    with pytest.raises(connect_commands.CommandRejected) as e:
        connect_commands.verify(sign(), None, DEVICE)
    assert 'signing keys' in str(e.value)


def test_an_unknown_action_fails_with_a_sentence_the_operator_can_act_on():
    out = connect_commands.run({'action': 'policy.apply', 'args': {}})
    assert out['ok'] is False
    assert 'does not know how to run policy.apply' in out['summary']


def test_a_handler_that_raises_becomes_a_failed_result():
    @connect_commands.handler('test.explode')
    def _boom(args, app=None):
        raise RuntimeError('disk on fire')
    try:
        out = connect_commands.run({'action': 'test.explode', 'args': {}})
        assert out['ok'] is False
        assert 'disk on fire' in out['summary']
    finally:
        connect_commands.HANDLERS.pop('test.explode', None)


# ---------- storage.assign ----------


def _cloud_args(prefix='serverkit/dev_abc123/'):
    return {'bucket': 'sk-backups', 'region': 'auto', 'endpoint': 'https://acct.example.com',
            'key_id': 'AKIA', 'secret': 'shh', 'prefix': prefix, 'provider': 'r2'}


def test_assign_writes_the_destination_only_after_the_test_passes(monkeypatch):
    monkeypatch.setattr(StorageProviderService, 'test_connection',
                        classmethod(lambda cls, config=None: {'success': True, 'message': 'ok'}))
    out = connect_storage.assign(_cloud_args())
    assert out['ok'] is True
    config = StorageProviderService.get_config()
    assert config['provider'] == 's3'
    assert config['managed_by_cloud'] is True
    assert config['s3']['bucket'] == 'sk-backups'
    assert config['s3']['path_prefix'] == 'serverkit/dev_abc123'


def test_a_destination_the_panel_cannot_reach_is_not_saved(monkeypatch):
    monkeypatch.setattr(StorageProviderService, 'test_connection',
                        classmethod(lambda cls, config=None: {'success': False,
                                                              'error': 'AccessDenied'}))
    out = connect_storage.assign(_cloud_args())
    assert out['ok'] is False
    assert 'AccessDenied' in out['summary']
    assert StorageProviderService.get_config().get('managed_by_cloud') is not True


def test_assign_keeps_the_operators_own_settings(monkeypatch):
    StorageProviderService.save_config({'provider': 'local', 'auto_upload': True,
                                        'keep_local_copy': False})
    monkeypatch.setattr(StorageProviderService, 'test_connection',
                        classmethod(lambda cls, config=None: {'success': True}))
    connect_storage.assign(_cloud_args())
    config = StorageProviderService.get_config()
    assert config['auto_upload'] is True
    assert config['keep_local_copy'] is False


def test_an_incomplete_destination_is_refused_with_what_is_missing():
    args = _cloud_args()
    del args['secret']
    out = connect_storage.assign(args)
    assert out['ok'] is False
    assert 'secret' in out['summary']


def test_a_deleted_cloud_connection_changes_nothing_here():
    out = connect_storage.assign({'error': 'connection_gone'})
    assert out['ok'] is False
    assert StorageProviderService.get_config().get('managed_by_cloud') is not True


# ---------- storage.unassign ----------


def test_unassign_hands_the_destination_back_and_drops_the_cloud_credential(monkeypatch):
    monkeypatch.setattr(StorageProviderService, 'test_connection',
                        classmethod(lambda cls, config=None: {'success': True}))
    connect_storage.assign(_cloud_args())
    out = connect_storage.unassign({})
    assert out['ok'] is True
    config = StorageProviderService.get_config()
    assert config['provider'] == 'local'
    assert not config.get('managed_by_cloud')
    assert 's3' not in config
    assert 'deleted' in out['summary']


def test_unassigning_something_we_never_managed_changes_nothing():
    StorageProviderService.save_config({'provider': 's3', 's3': {'bucket': 'mine'}})
    out = connect_storage.unassign({})
    assert out['ok'] is True
    assert StorageProviderService.get_config()['s3']['bucket'] == 'mine'


# ---------- the status snapshot ----------


def test_the_snapshot_carries_the_destination_and_what_is_stored(monkeypatch):
    monkeypatch.setattr(StorageProviderService, 'test_connection',
                        classmethod(lambda cls, config=None: {'success': True}))
    monkeypatch.setattr(StorageProviderService, 'get_remote_stats',
                        classmethod(lambda cls: {'remote_size': 4096, 'remote_count': 7}))
    connect_storage.assign(_cloud_args())
    snap = connect_storage.build_status()
    assert snap['type'] == 'status'
    assert snap['destination'] == 'sk-backups/serverkit/dev_abc123/'
    assert snap['prefix'] == 'serverkit/dev_abc123/'
    assert snap['remote_bytes'] == 4096
    assert snap['remote_objects'] == 7
    assert snap['managed_by_cloud'] is True


def test_a_destination_that_cannot_be_listed_says_so_rather_than_reporting_zero(monkeypatch):
    monkeypatch.setattr(StorageProviderService, 'test_connection',
                        classmethod(lambda cls, config=None: {'success': True}))

    def boom(cls):
        raise RuntimeError('NoSuchBucket')
    monkeypatch.setattr(StorageProviderService, 'get_remote_stats', classmethod(boom))
    connect_storage.assign(_cloud_args())
    snap = connect_storage.build_status()
    assert 'remote_bytes' not in snap
    assert 'NoSuchBucket' in snap['error']


def test_a_local_only_panel_still_reports():
    snap = connect_storage.build_status()
    assert snap['type'] == 'status'
    assert snap['destination'] is None
    assert snap['managed_by_cloud'] is False


def test_the_status_frame_is_the_storage_stream():
    frame = connect_storage.status_frame('sto1', {'type': 'status'})
    assert frame == {'s': 'sto1', 't': 'open', 'k': 'storage', 'p': {'type': 'status'}}


def test_is_managed_by_cloud_tracks_the_config(monkeypatch):
    assert connect_storage.is_managed_by_cloud() is False
    monkeypatch.setattr(StorageProviderService, 'test_connection',
                        classmethod(lambda cls, config=None: {'success': True}))
    connect_storage.assign(_cloud_args())
    assert connect_storage.is_managed_by_cloud() is True


# ---------- result frames ----------


def test_the_result_frame_is_what_cloud_ingests():
    frame = connect_commands.result_frame('cmd_9', 'succeeded',
                                          {'ok': True, 'code': 0, 'summary': 'done'})
    assert frame['k'] == 'command_result'
    assert frame['p'] == {'cmd_id': 'cmd_9', 'state': 'succeeded',
                          'result_code': 0, 'result_summary': 'done'}


def test_the_running_ack_carries_no_result():
    frame = connect_commands.result_frame('cmd_9', 'running')
    assert frame['p'] == {'cmd_id': 'cmd_9', 'state': 'running'}
    assert json.dumps(frame)
