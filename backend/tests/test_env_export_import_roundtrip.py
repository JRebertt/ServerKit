"""Env export → import round trip.

export_to_env_format escaped quotes/backslashes that parse_env_file never
unescaped (values grew literal backslashes each cycle), and wrote the
user-supplied description as a raw ``# ...`` comment line — a newline in a
description injected brand-new KEY=value lines into the re-import. Same
write/read join hardening as the cron #117 fix: the cycle must be lossless
and user text must not be able to fabricate entries.
"""
from app import db
from app.services.env_service import EnvService


def _seed(app, pairs):
    from factories import make_application, make_user

    user = make_user(db, role='admin')
    application = make_application(db, name='env-rt-app', user_id=user.id)
    for key, value, desc in pairs:
        EnvService.set_env_var(application.id, key, value,
                               description=desc, user_id=user.id)
    return application


def _roundtrip(app, pairs):
    with app.app_context():
        application = _seed(app, pairs)
        content = EnvService.export_to_env_format(application.id)
    parsed, errors = EnvService.parse_env_file(content)
    return content, parsed, errors


def test_quotes_and_backslashes_survive_one_cycle(app):
    value = 'say "hi" via C:\\temp and a $HOME too'
    _, parsed, errors = _roundtrip(app, [('GREETING', value, None)])
    assert errors == []
    assert parsed == {'GREETING': value}


def test_cycle_is_stable_not_compounding(app):
    # The old parser kept the export-side escapes, so every cycle grew
    # literal backslashes. Two cycles must equal one.
    value = 'quote " backslash \\ end'
    content, parsed, _ = _roundtrip(app, [('V', value, None)])
    assert parsed == {'V': value}
    reparsed, errors = EnvService.parse_env_file(content)
    assert errors == []
    assert reparsed == parsed


def test_newline_value_stays_one_line_and_round_trips(app):
    value = 'line one\nline two'
    content, parsed, errors = _roundtrip(app, [('MULTI', value, None)])
    assert errors == []
    assert parsed == {'MULTI': value}
    # The value must be encoded onto a single line, not written as a raw
    # multiline quote the parser mangles.
    assert 'MULTI="line one\\nline two"' in content


def test_description_newline_cannot_inject_variables(app):
    evil = 'looks harmless\nINJECTED_TOKEN=attacker'
    _, parsed, _ = _roundtrip(app, [('SAFE', 'ok', evil)])
    assert 'INJECTED_TOKEN' not in parsed
    assert parsed == {'SAFE': 'ok'}


def test_description_still_exported_as_comment(app):
    content, _, _ = _roundtrip(app, [('DB_URL', 'sqlite://x y', 'where data lives')])
    assert '# where data lives\n' in content


def test_none_value_exports_as_empty(app):
    with app.app_context():
        application = _seed(app, [('EMPTYABLE', 'x', None)])
        from app.models import EnvironmentVariable
        ev = EnvironmentVariable.query.filter_by(
            application_id=application.id, key='EMPTYABLE').first()
        ev.value = None
        db.session.commit()
        content = EnvService.export_to_env_format(application.id)
    parsed, errors = EnvService.parse_env_file(content)
    assert errors == []
    assert parsed == {'EMPTYABLE': ''}


def test_hand_written_windows_path_not_mangled():
    # Unknown backslash sequences in hand-authored files stay as written.
    parsed, errors = EnvService.parse_env_file('DIR="C:\\projects\\app"\n')
    assert errors == []
    assert parsed == {'DIR': 'C:\\projects\\app'}
