"""The stub kit's own contract (plan 75 §G7).

A shared test helper that is wrong is worse than twelve private ones: every
suite that adopts it inherits the same blind spot. So the properties this kit
claims are tested here, not assumed — particularly the two that exist to stop
a stub from manufacturing facts.
"""

import os
import subprocess

import pytest
from unittest.mock import patch

from subprocess_stub import (FakePopen, FakeProc, ScriptedSubprocess,
                             UnscriptedCommand, normalize_argv)


def _ufw_absent():
    """Make the sbin guard see 'ufw' as absent on this machine.

    These tests use ufw as an arbitrary example argv for the DISPATCH
    mechanics; on machines where ufw really exists sbin-only (CI runners)
    the popen guard would fire first and test the wrong thing.
    """
    return patch('popen_guard.shutil.which', return_value=None)


class TestNormalisation:
    """One scripted rule must match on a root box, a sudo box, and a dev box."""

    def test_strips_sudo_and_its_flags(self):
        assert normalize_argv(['sudo', '-n', 'nginx', '-t']) == ['nginx', '-t']

    def test_strips_sudo_user_flag_with_its_value(self):
        assert normalize_argv(['sudo', '-u', 'www-data', 'php', '-v']) == ['php', '-v']

    def test_argv0_compared_by_basename(self):
        # run_privileged absolutises argv[0] only when $PATH misses it, so the
        # same call is spelled two ways on two machines.
        assert normalize_argv(['/usr/sbin/nginx', '-t']) == ['nginx', '-t']

    def test_does_not_strip_a_command_merely_containing_sudo(self):
        assert normalize_argv(['sudoedit', '-f']) == ['sudoedit', '-f']

    def test_string_form_and_empty_are_not_argv(self):
        assert normalize_argv('ls -la') == []
        assert normalize_argv([]) == []


class TestUnscriptedIsAnError:
    def test_unscripted_command_raises(self, fake_subprocess):
        with pytest.raises(UnscriptedCommand):
            subprocess.run(['docker', 'ps'])

    def test_message_names_the_command_and_what_was_scripted(self, fake_subprocess):
        fake_subprocess.script(['git', 'status'])
        try:
            subprocess.run(['docker', 'ps'])
        except UnscriptedCommand as exc:
            assert 'docker' in str(exc) and 'git' in str(exc)
        else:  # pragma: no cover - the raise above is the point
            pytest.fail('unscripted command returned a result')

    def test_a_blanket_except_cannot_eat_it(self, fake_subprocess):
        """The whole reason it is a BaseException.

        Services wrap subprocess in ``except Exception`` and convert it to
        ``{'success': False}``. If this were an AssertionError the test author
        would see a plausible failure dict instead of "you forgot to script
        this" — plan 74's bug class, reproduced inside the test harness.
        """
        def service_style_call():
            try:
                return subprocess.run(['ufw', 'status'])
            except Exception:
                return {'success': False, 'error': 'not installed'}

        with _ufw_absent(), pytest.raises(UnscriptedCommand):
            service_style_call()


class TestDispatch:
    def test_prefix_match_returns_scripted_result(self, fake_subprocess):
        fake_subprocess.script(['docker', 'ps'], stdout='CONTAINER ID\n')
        result = subprocess.run(['docker', 'ps', '-a'], capture_output=True)
        assert result.stdout == 'CONTAINER ID\n'
        assert result.returncode == 0

    def test_longest_prefix_wins_regardless_of_order(self, fake_subprocess):
        fake_subprocess.script(['docker'], stdout='broad')
        fake_subprocess.script(['docker', 'inspect'], stdout='narrow')
        assert subprocess.run(['docker', 'inspect', 'x']).stdout == 'narrow'
        assert subprocess.run(['docker', 'ps']).stdout == 'broad'

    def test_narrow_rule_wins_even_when_scripted_first(self, fake_subprocess):
        fake_subprocess.script(['docker', 'inspect'], stdout='narrow')
        fake_subprocess.script(['docker'], stdout='broad')
        assert subprocess.run(['docker', 'inspect', 'x']).stdout == 'narrow'

    def test_raises_scripts_an_exception(self, fake_subprocess):
        fake_subprocess.script(['ufw'], raises=FileNotFoundError)
        with _ufw_absent(), pytest.raises(FileNotFoundError):
            subprocess.run(['ufw', 'status'])

    def test_raises_accepts_an_instance(self, fake_subprocess):
        fake_subprocess.script(['ufw'], raises=subprocess.TimeoutExpired('ufw', 5))
        with _ufw_absent(), pytest.raises(subprocess.TimeoutExpired):
            subprocess.run(['ufw', 'status'])

    def test_when_gives_the_responder_argv_and_kwargs(self, fake_subprocess):
        seen = {}

        def responder(argv, kwargs):
            seen['argv'] = argv
            seen['input'] = kwargs.get('input')
            return FakeProc(returncode=0)

        fake_subprocess.when(['docker', 'login'], responder)
        subprocess.run(['docker', 'login', 'ghcr.io'], input='secret')
        assert seen['argv'] == ['docker', 'login', 'ghcr.io']
        assert seen['input'] == 'secret'


class TestEveryEntryPointIsPatched:
    """``run`` is not the only door — ``check_output`` and friends bypass it."""

    def test_check_output_returns_stdout(self, fake_subprocess):
        fake_subprocess.script(['git', 'rev-parse'], stdout='abc123\n')
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD']) == 'abc123\n'

    def test_check_output_raises_on_nonzero(self, fake_subprocess):
        fake_subprocess.script(['git'], returncode=128, stderr='fatal')
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(['git', 'status'])

    def test_call_returns_the_code(self, fake_subprocess):
        fake_subprocess.script(['git'], returncode=1)
        assert subprocess.call(['git', 'status']) == 1

    def test_check_call_raises_on_nonzero(self, fake_subprocess):
        fake_subprocess.script(['git'], returncode=1)
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_call(['git', 'status'])

    def test_popen_streams_lines_not_characters(self, fake_subprocess):
        fake_subprocess.script(['docker', 'compose'], stdout='one\ntwo\n')
        proc = subprocess.Popen(['docker', 'compose', 'up'])
        assert list(proc.stdout) == ['one\n', 'two\n']
        assert proc.wait() == 0


class TestItCoversTheWrappersToo:
    """The point of patching the module, not a service's imported name."""

    def test_run_privileged_goes_through_the_script(self, fake_subprocess):
        from app.utils.system import run_privileged
        fake_subprocess.script(['nginx', '-t'], returncode=0, stdout='ok')
        result = run_privileged(['nginx', '-t'])
        assert result.stdout == 'ok'
        # matched despite whatever sudo/absolutisation the helper applied
        assert fake_subprocess.ran(['nginx', '-t'])

    def test_run_unprivileged_goes_through_the_script(self, fake_subprocess):
        from app.utils.system import run_unprivileged
        fake_subprocess.script(['dig'], stdout='1.2.3.4\n')
        assert run_unprivileged(['dig', '+short', 'a.test'])['stdout'] == '1.2.3.4\n'


class TestRecording:
    def test_commands_are_recorded_in_order(self, fake_subprocess):
        fake_subprocess.script(['docker'], stdout='')
        subprocess.run(['docker', 'login'])
        subprocess.run(['docker', 'pull', 'x'])
        subprocess.run(['docker', 'logout'])
        assert fake_subprocess.commands() == [
            ['docker', 'login'], ['docker', 'pull', 'x'], ['docker', 'logout'],
        ]

    def test_argv_for_returns_the_raw_argv(self, fake_subprocess):
        """Raw on purpose: 'the secret is on stdin and NOWHERE on the argv'
        is an assertion about the real argv, not a normalised one."""
        fake_subprocess.script(['docker', 'login'])
        subprocess.run(['docker', 'login', '-u', 'bot', '--password-stdin'],
                       input='tok')
        assert fake_subprocess.argv_for(['docker', 'login']) == [
            'docker', 'login', '-u', 'bot', '--password-stdin']
        assert fake_subprocess.kwargs_for(['docker'])['input'] == 'tok'

    def test_ran_is_false_for_a_command_never_issued(self, fake_subprocess):
        fake_subprocess.script(['docker'], stdout='')
        subprocess.run(['docker', 'ps'])
        assert fake_subprocess.ran(['docker', 'ps'])
        assert not fake_subprocess.ran(['docker', 'rm'])


class TestWritesAccessor:
    """`writes()` reads the privileged-write door's argv shape in one place."""

    def test_collects_path_to_content(self, fake_subprocess):
        from app.utils.system import write_privileged_file
        fake_subprocess.script(['tee'])
        write_privileged_file('/etc/nginx/sites-available/a', 'server {}')
        assert fake_subprocess.writes() == {'/etc/nginx/sites-available/a': 'server {}'}

    def test_append_accumulates_rather_than_replacing(self, fake_subprocess):
        from app.utils.system import write_privileged_file
        fake_subprocess.script(['tee'])
        write_privileged_file('/etc/postfix/main.cf', 'a=1\n', append=True)
        write_privileged_file('/etc/postfix/main.cf', 'b=2\n', append=True)
        assert fake_subprocess.writes() == {'/etc/postfix/main.cf': 'a=1\nb=2\n'}

    def test_a_truncating_write_replaces_what_append_accumulated(self, fake_subprocess):
        from app.utils.system import write_privileged_file
        fake_subprocess.script(['tee'])
        write_privileged_file('/etc/x', 'old\n', append=True)
        write_privileged_file('/etc/x', 'new\n')
        assert fake_subprocess.writes() == {'/etc/x': 'new\n'}

    def test_non_write_commands_are_not_collected(self, fake_subprocess):
        fake_subprocess.script(['systemctl'])
        subprocess.run(['systemctl', 'reload', 'nginx'])
        assert fake_subprocess.writes() == {}


class TestStubbingIsNotAGuardExemption:
    """Patching subprocess removes the §B2 runtime guard for the test's
    duration. The kit re-applies it, so a scripted command cannot smuggle a
    bare-name sbin-only exec past the check the suite otherwise enforces."""

    @pytest.mark.skipif(os.name != 'posix', reason='sbin semantics are POSIX')
    def test_bare_name_sbin_only_exec_still_refused(self, fake_subprocess, monkeypatch):
        import shutil

        from popen_guard import SbinPathError, sanitized_path

        real_which = shutil.which

        def fake_which(cmd, path=None, **kw):
            if cmd == 'fakesbintool':
                # resolves on the normal PATH, not on the sbin-less one:
                # exactly the shape of the plan 74 outage.
                return None if path == sanitized_path() else '/usr/sbin/fakesbintool'
            return real_which(cmd, path=path, **kw) if path is None else real_which(cmd, path=path)

        monkeypatch.setattr('popen_guard.shutil.which', fake_which)
        fake_subprocess.script(['fakesbintool'], stdout='')
        with pytest.raises(SbinPathError):
            subprocess.run(['fakesbintool', 'status'])


class TestFakeProcShape:
    def test_check_returncode_is_quiet_on_success(self):
        FakeProc(returncode=0).check_returncode()

    def test_check_returncode_raises_with_the_output_attached(self):
        proc = FakeProc(returncode=2, stdout='out', stderr='err', args=['x'])
        with pytest.raises(subprocess.CalledProcessError) as exc:
            proc.check_returncode()
        assert exc.value.stderr == 'err'

    def test_popen_stdout_is_empty_not_none_when_no_output(self):
        assert list(FakePopen(FakeProc()).stdout) == []

    def test_install_binds_the_module_to_this_script(self, fake_subprocess):
        assert getattr(subprocess.run, '__self__', None) is fake_subprocess

    def test_patch_does_not_leak_to_a_test_without_the_fixture(self):
        """If install() leaked, every later test in the session would silently
        run against a stub that answers nothing."""
        assert not isinstance(getattr(subprocess.run, '__self__', None),
                              ScriptedSubprocess)
