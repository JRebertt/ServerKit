"""Firewall management service for firewalld and ufw."""

import os
import subprocess
import re
from typing import Dict, List, Optional
from datetime import datetime

from app.utils.system import (
    PROBE_TIMEOUT,
    PackageManager,
    ServiceControl,
    is_command_available,
    run_privileged,
)


class FirewallService:
    """Service for managing firewall (firewalld or ufw)."""

    @classmethod
    def get_status(cls) -> Dict:
        """Get firewall status and detect which firewall is in use."""
        firewalld = cls._check_firewalld()
        ufw = cls._check_ufw()

        active_firewall = None
        if firewalld['installed'] and firewalld['running']:
            active_firewall = 'firewalld'
        elif ufw['installed'] and ufw['active']:
            active_firewall = 'ufw'
        elif firewalld['installed']:
            active_firewall = 'firewalld'
        elif ufw['installed']:
            active_firewall = 'ufw'

        return {
            'firewalld': firewalld,
            'ufw': ufw,
            'active_firewall': active_firewall,
            'any_installed': firewalld['installed'] or ufw['installed'],
            'any_active': firewalld['running'] or ufw['active']
        }

    @classmethod
    def _check_firewalld(cls) -> Dict:
        """Check firewalld status."""
        try:
            installed = PackageManager.is_installed('firewalld') or is_command_available('firewall-cmd')
        except Exception:
            installed = False

        # Same separation as _check_ufw: a probe that fails must not be able to
        # unsay an `installed` that was already determined correctly.
        running = False
        default_zone = None
        if installed:
            try:
                result = run_privileged(['firewall-cmd', '--state'])
                running = 'running' in (result.stdout or '').lower()

                if running:
                    result = run_privileged(['firewall-cmd', '--get-default-zone'])
                    default_zone = (result.stdout or '').strip()
            except Exception:
                running = False
                default_zone = None

        return {
            'installed': installed,
            'running': running,
            'default_zone': default_zone
        }

    @classmethod
    def _check_ufw(cls) -> Dict:
        """Check ufw status.

        The two questions are answered independently on purpose. A single
        try/except around both let a failure in the *status* probe discard an
        ``installed`` that had already been determined correctly, so a working
        install was reported as "No Firewall Installed" — the probe raised
        FileNotFoundError because ufw lives in /usr/sbin, which is absent from
        the panel unit's PATH. Not knowing whether it is running says nothing
        about whether it is there.
        """
        try:
            installed = PackageManager.is_installed('ufw') or is_command_available('ufw')
        except Exception:
            installed = False

        active = False
        if installed:
            try:
                result = run_privileged(['ufw', 'status'])
                active = 'Status: active' in (result.stdout or '')
            except Exception:
                active = False

        return {
            'installed': installed,
            'active': active
        }

    # ------------------------------------------------------------------
    # SSH lockout preflight
    # ------------------------------------------------------------------
    #: ufw's own `enable` asks "Command may disrupt existing ssh connections.
    #: Proceed?" — and `--force enable`, which this service uses because nothing
    #: here is attached to a terminal, suppresses exactly that prompt. Without a
    #: replacement check the panel will happily lock an operator out of a remote
    #: box in one click, with no way back in.

    @classmethod
    def ssh_ports(cls) -> Optional[List[int]]:
        """Ports sshd is actually listening on, or None if undeterminable.

        ``sshd -T`` is the authority: it resolves Includes, Match blocks and
        compiled-in defaults, which parsing sshd_config by hand does not.

        Returns None — never a guessed ``[22]`` — when sshd cannot be asked. A
        wrong guess here is a lockout, so "I don't know" has to stay a distinct
        answer the caller can refuse to act on.
        """
        try:
            result = run_privileged(['sshd', '-T'], timeout=PROBE_TIMEOUT)
        except Exception:
            return None
        if result.returncode != 0:
            return None

        ports = []
        for line in (result.stdout or '').splitlines():
            match = re.match(r'^\s*port\s+(\d+)\s*$', line, re.I)
            if match:
                ports.append(int(match.group(1)))
        return sorted(set(ports)) or None

    @classmethod
    def _ufw_default_incoming_allow(cls) -> bool:
        """True when ufw's default inbound policy is ACCEPT (no lockout risk)."""
        try:
            with open('/etc/default/ufw', 'r') as handle:
                for line in handle:
                    match = re.match(r'^\s*DEFAULT_INPUT_POLICY\s*=\s*"?(\w+)"?',
                                     line)
                    if match:
                        return match.group(1).upper() == 'ACCEPT'
        except Exception:
            pass
        return False

    @classmethod
    def _ufw_allowed_ports(cls) -> set:
        """Ports covered by a staged ufw *allow* rule.

        Reads `ufw show added`, which lists rules staged while the firewall is
        still inactive — the only rules that will exist the instant it comes up.
        Named application profiles (``ufw allow OpenSSH``) are resolved through
        ``ufw app info`` rather than assumed, since guessing in the permissive
        direction is what would cause the lockout this check exists to prevent.
        """
        allowed = set()
        try:
            result = run_privileged(['ufw', 'show', 'added'], timeout=PROBE_TIMEOUT)
        except Exception:
            return allowed
        if result.returncode != 0:
            return allowed

        for line in (result.stdout or '').splitlines():
            line = line.strip()
            if 'allow' not in line:
                continue
            numbers = re.findall(r'\b(\d{1,5})(?:/(?:tcp|udp))?\b', line)
            allowed.update(int(n) for n in numbers if 0 < int(n) <= 65535)

            profile = re.search(r'allow\s+([A-Za-z][\w .-]*)$', line)
            if profile:
                allowed.update(cls._app_profile_ports(profile.group(1).strip()))
        return allowed

    @classmethod
    def _app_profile_ports(cls, profile: str) -> set:
        """Ports behind a ufw application profile name."""
        ports = set()
        try:
            result = run_privileged(['ufw', 'app', 'info', profile],
                                    timeout=PROBE_TIMEOUT)
        except Exception:
            return ports
        if result.returncode != 0:
            return ports
        for match in re.finditer(r'\b(\d{1,5})(?:/(?:tcp|udp))?\b',
                                 (result.stdout or '')):
            ports.add(int(match.group(1)))
        return ports

    @classmethod
    def check_ssh_lockout(cls, firewall: str = 'ufw') -> Dict:
        """Would enabling *firewall* right now cut off SSH?

        Returns ``{'safe': bool, 'reason': str, 'ssh_ports': [...] | None,
        'allowed_ports': [...]}``. Advisory data — ``enable()`` decides.
        """
        if firewall != 'ufw':
            # firewalld's default zone keeps the ssh service open, and enabling
            # it does not flush existing rules the way `ufw enable` applies a
            # fresh default-deny.
            return {'safe': True, 'reason': 'not applicable to firewalld',
                    'ssh_ports': None, 'allowed_ports': []}

        if cls._ufw_default_incoming_allow():
            return {'safe': True, 'reason': 'default incoming policy is ACCEPT',
                    'ssh_ports': None, 'allowed_ports': []}

        ports = cls.ssh_ports()
        allowed = cls._ufw_allowed_ports()

        if ports is None:
            return {
                'safe': False,
                'reason': ('Could not determine which port sshd is listening on, '
                           'so there is no way to confirm it stays reachable.'),
                'ssh_ports': None,
                'allowed_ports': sorted(allowed),
            }

        uncovered = [p for p in ports if p not in allowed]
        if uncovered:
            listed = ', '.join(str(p) for p in uncovered)
            return {
                'safe': False,
                'reason': (f'No ufw rule allows SSH on port {listed}. Enabling now '
                           f'applies a default-deny and closes your own session. '
                           f'Add a rule first: ufw allow {uncovered[0]}/tcp'),
                'ssh_ports': ports,
                'allowed_ports': sorted(allowed),
            }

        return {'safe': True, 'reason': 'SSH port is covered by an allow rule',
                'ssh_ports': ports, 'allowed_ports': sorted(allowed)}

    @classmethod
    def enable(cls, firewall: str = None, force: bool = False) -> Dict:
        """Enable the firewall.

        Refuses when the preflight cannot prove SSH survives. ``force=True`` is
        the operator saying they accept the risk (console access, a rule the
        probe could not see); it is never set by default.
        """
        if firewall is None:
            status = cls.get_status()
            firewall = status['active_firewall']

        if firewall not in ('firewalld', 'ufw'):
            return {'success': False, 'error': 'No firewall detected'}

        if not force:
            preflight = cls.check_ssh_lockout(firewall)
            if not preflight['safe']:
                return {
                    'success': False,
                    'error': preflight['reason'],
                    'blocked_by': 'ssh_lockout',
                    'ssh_ports': preflight['ssh_ports'],
                    'allowed_ports': preflight['allowed_ports'],
                    'override': 'Send force=true to enable anyway.',
                }

        if firewall == 'firewalld':
            return cls._enable_firewalld()
        return cls._enable_ufw()

    @classmethod
    def _enable_firewalld(cls) -> Dict:
        """Enable firewalld."""
        try:
            ServiceControl.enable('firewalld')
            result = ServiceControl.start('firewalld')
            if result.returncode == 0:
                return {'success': True, 'message': 'Firewalld enabled and started'}
            return {'success': False, 'error': result.stderr or 'Failed to start firewalld'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _enable_ufw(cls) -> Dict:
        """Enable ufw."""
        try:
            result = run_privileged(['ufw', '--force', 'enable'])
            if result.returncode == 0:
                return {'success': True, 'message': 'UFW enabled'}
            return {'success': False, 'error': result.stderr or 'Failed to enable UFW'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def disable(cls, firewall: str = None) -> Dict:
        """Disable the firewall."""
        if firewall is None:
            status = cls.get_status()
            firewall = status['active_firewall']

        if firewall == 'firewalld':
            return cls._disable_firewalld()
        elif firewall == 'ufw':
            return cls._disable_ufw()
        else:
            return {'success': False, 'error': 'No firewall detected'}

    @classmethod
    def _disable_firewalld(cls) -> Dict:
        """Disable firewalld."""
        try:
            result = ServiceControl.stop('firewalld')
            if result.returncode == 0:
                return {'success': True, 'message': 'Firewalld stopped'}
            return {'success': False, 'error': result.stderr or 'Failed to stop firewalld'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _disable_ufw(cls) -> Dict:
        """Disable ufw."""
        try:
            result = run_privileged(['ufw', 'disable'])
            if result.returncode == 0:
                return {'success': True, 'message': 'UFW disabled'}
            return {'success': False, 'error': result.stderr or 'Failed to disable UFW'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def get_rules(cls, firewall: str = None) -> Dict:
        """Get all firewall rules."""
        if firewall is None:
            status = cls.get_status()
            firewall = status['active_firewall']

        if firewall == 'firewalld':
            return cls._get_firewalld_rules()
        elif firewall == 'ufw':
            return cls._get_ufw_rules()
        else:
            return {'success': False, 'error': 'No firewall detected'}

    @classmethod
    def _get_firewalld_rules(cls) -> Dict:
        """Get firewalld rules."""
        try:
            rules = []

            # Get default zone
            result = run_privileged(['firewall-cmd', '--get-default-zone'])
            default_zone = result.stdout.strip()

            # Get services
            result = run_privileged(['firewall-cmd', '--list-services'])
            services = result.stdout.strip().split() if result.stdout.strip() else []
            for service in services:
                rules.append({
                    'type': 'service',
                    'service': service,
                    'zone': default_zone,
                    'permanent': True
                })

            # Get ports
            result = run_privileged(['firewall-cmd', '--list-ports'])
            ports = result.stdout.strip().split() if result.stdout.strip() else []
            for port in ports:
                port_num, protocol = port.split('/') if '/' in port else (port, 'tcp')
                rules.append({
                    'type': 'port',
                    'port': port_num,
                    'protocol': protocol,
                    'zone': default_zone,
                    'permanent': True
                })

            # Get rich rules (includes IP blocks)
            result = run_privileged(['firewall-cmd', '--list-rich-rules'])
            rich_rules = result.stdout.strip().split('\n') if result.stdout.strip() else []
            for rule in rich_rules:
                if rule:
                    rules.append({
                        'type': 'rich',
                        'rule': rule,
                        'zone': default_zone
                    })

            return {
                'success': True,
                'firewall': 'firewalld',
                'default_zone': default_zone,
                'rules': rules
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _get_ufw_rules(cls) -> Dict:
        """Get ufw rules."""
        try:
            result = run_privileged(['ufw', 'status', 'numbered'])

            rules = []
            lines = result.stdout.strip().split('\n')

            for line in lines:
                # Parse rules like: [ 1] 22/tcp ALLOW IN Anywhere
                match = re.match(r'\[\s*(\d+)\]\s+(.+?)\s+(ALLOW|DENY|REJECT)\s+(IN|OUT)?\s*(.+)?', line)
                if match:
                    rules.append({
                        'number': int(match.group(1)),
                        'port': match.group(2),
                        'action': match.group(3),
                        'direction': match.group(4) or 'IN',
                        'from': match.group(5) or 'Anywhere'
                    })

            return {
                'success': True,
                'firewall': 'ufw',
                'rules': rules
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def add_rule(cls, rule_type: str, **kwargs) -> Dict:
        """Add a firewall rule."""
        status = cls.get_status()
        firewall = status['active_firewall']

        if firewall == 'firewalld':
            return cls._add_firewalld_rule(rule_type, **kwargs)
        elif firewall == 'ufw':
            return cls._add_ufw_rule(rule_type, **kwargs)
        else:
            return {'success': False, 'error': 'No firewall detected'}

    @classmethod
    def _add_firewalld_rule(cls, rule_type: str, **kwargs) -> Dict:
        """Add a firewalld rule."""
        try:
            permanent = kwargs.get('permanent', True)
            perm_flag = ['--permanent'] if permanent else []

            if rule_type == 'service':
                service = kwargs.get('service')
                if not service:
                    return {'success': False, 'error': 'Service name required'}
                cmd = ['firewall-cmd'] + perm_flag + [f'--add-service={service}']

            elif rule_type == 'port':
                port = kwargs.get('port')
                protocol = kwargs.get('protocol', 'tcp')
                if not port:
                    return {'success': False, 'error': 'Port number required'}
                cmd = ['firewall-cmd'] + perm_flag + [f'--add-port={port}/{protocol}']

            elif rule_type == 'block_ip':
                ip = kwargs.get('ip')
                if not ip:
                    return {'success': False, 'error': 'IP address required'}
                cmd = ['firewall-cmd'] + perm_flag + [
                    f'--add-rich-rule=rule family="ipv4" source address="{ip}" reject'
                ]

            elif rule_type == 'allow_ip':
                ip = kwargs.get('ip')
                port = kwargs.get('port')
                if not ip:
                    return {'success': False, 'error': 'IP address required'}
                if port:
                    cmd = ['firewall-cmd'] + perm_flag + [
                        f'--add-rich-rule=rule family="ipv4" source address="{ip}" port port="{port}" protocol="tcp" accept'
                    ]
                else:
                    cmd = ['firewall-cmd'] + perm_flag + [
                        f'--add-rich-rule=rule family="ipv4" source address="{ip}" accept'
                    ]

            else:
                return {'success': False, 'error': f'Unknown rule type: {rule_type}'}

            result = run_privileged(cmd)

            if result.returncode == 0:
                # Reload if permanent
                if permanent:
                    run_privileged(['firewall-cmd', '--reload'])
                return {'success': True, 'message': 'Rule added successfully'}

            return {'success': False, 'error': result.stderr or 'Failed to add rule'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _add_ufw_rule(cls, rule_type: str, **kwargs) -> Dict:
        """Add a ufw rule."""
        try:
            if rule_type == 'port':
                port = kwargs.get('port')
                protocol = kwargs.get('protocol', 'tcp')
                action = kwargs.get('action', 'allow')
                if not port:
                    return {'success': False, 'error': 'Port number required'}
                cmd = ['ufw', action, f'{port}/{protocol}']

            elif rule_type == 'service':
                service = kwargs.get('service')
                action = kwargs.get('action', 'allow')
                if not service:
                    return {'success': False, 'error': 'Service name required'}
                cmd = ['ufw', action, service]

            elif rule_type == 'block_ip':
                ip = kwargs.get('ip')
                if not ip:
                    return {'success': False, 'error': 'IP address required'}
                cmd = ['ufw', 'deny', 'from', ip]

            elif rule_type == 'allow_ip':
                ip = kwargs.get('ip')
                port = kwargs.get('port')
                if not ip:
                    return {'success': False, 'error': 'IP address required'}
                if port:
                    cmd = ['ufw', 'allow', 'from', ip, 'to', 'any', 'port', str(port)]
                else:
                    cmd = ['ufw', 'allow', 'from', ip]

            else:
                return {'success': False, 'error': f'Unknown rule type: {rule_type}'}

            result = run_privileged(cmd)

            if result.returncode == 0:
                return {'success': True, 'message': 'Rule added successfully'}

            return {'success': False, 'error': result.stderr or 'Failed to add rule'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # Removal preflight — the other way to lock yourself out
    # ------------------------------------------------------------------
    #: enable() guards the moment the firewall comes up. This guards every
    #: moment after it: with ufw already active and a default-deny policy,
    #: deleting the rule that admits SSH closes the session executing the
    #: delete. `deny_port()` routes through here too — denying a port is
    #: implemented as removing its allow rule, so it is the same hazard.

    @classmethod
    def _ufw_numbered_rules(cls) -> List[Dict]:
        """Active ufw rules with the numbers `ufw delete <n>` refers to.

        Deleting by number is the dangerous spelling: the caller passes an
        opaque index, so the only way to know what is about to be removed is to
        resolve it here first.
        """
        rules = []
        try:
            result = run_privileged(['ufw', 'status', 'numbered'],
                                    timeout=PROBE_TIMEOUT)
        except Exception:
            return rules
        if result.returncode != 0:
            return rules

        pattern = re.compile(
            r'^\[\s*(\d+)\]\s+(.+?)\s+(ALLOW|DENY|REJECT|LIMIT)(?:\s+(?:IN|OUT))?\s*(.*)$'
        )
        for line in (result.stdout or '').splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue
            rules.append({
                'number': int(match.group(1)),
                'to': match.group(2).strip(),
                'action': match.group(3).upper(),
                'from': (match.group(4) or '').strip(),
            })
        return rules

    #: `ufw status numbered` marks IPv6 rows as `22/tcp (v6)`. Left in, the "6"
    #: parses as a port number — harmless for SSH on 22, wrong for anyone whose
    #: sshd listens on 6.
    _ADDRESS_FAMILY_SUFFIX = re.compile(r'\((?:v6|v4)\)')

    @classmethod
    def _ports_in(cls, field: str) -> set:
        """Ports named by a rule's destination, resolving app profiles."""
        field = cls._ADDRESS_FAMILY_SUFFIX.sub('', field or '').strip()
        ports = {int(n) for n in re.findall(r'\b(\d{1,5})(?:/(?:tcp|udp))?\b', field)
                 if 0 < int(n) <= 65535}
        # 'Anywhere' is ufw's wildcard destination, not an application profile —
        # looking it up would just cost a subprocess to learn nothing.
        if not ports and field.lower() != 'anywhere' \
                and re.match(r'^[A-Za-z][\w .-]*$', field):
            ports = cls._app_profile_ports(field)
        return ports

    @classmethod
    def _firewalld_ssh_coverage(cls, ssh_ports: List[int]) -> set:
        """What currently admits SSH under firewalld: {'service:ssh', 22, ...}."""
        coverage = set()
        for flag, kind in (('--list-services', 'service'), ('--list-ports', 'port')):
            try:
                result = run_privileged(['firewall-cmd', flag], timeout=PROBE_TIMEOUT)
            except Exception:
                continue
            if result.returncode != 0:
                continue
            for token in (result.stdout or '').split():
                if kind == 'service' and token == 'ssh':
                    coverage.add('service:ssh')
                elif kind == 'port':
                    for port in cls._ports_in(token):
                        if port in ssh_ports:
                            coverage.add(port)
        return coverage

    @classmethod
    def check_ssh_rule_removal(cls, rule_type: str = None, **kwargs) -> Dict:
        """Would removing this rule cut off SSH *right now*?

        Only meaningful while the firewall is active — on an inactive one
        nothing is being enforced, and enable() runs its own preflight before
        anything starts being denied.

        Returns ``{'safe', 'reason', 'ssh_ports', 'targets'}``.
        """
        status = cls.get_status()
        firewall = status.get('active_firewall')

        if not status.get('any_active'):
            return {'safe': True, 'reason': 'firewall is not active',
                    'ssh_ports': None, 'targets': []}

        if firewall == 'ufw' and cls._ufw_default_incoming_allow():
            return {'safe': True, 'reason': 'default incoming policy is ACCEPT',
                    'ssh_ports': None, 'targets': []}

        ssh = cls.ssh_ports()
        if ssh is None:
            return {
                'safe': False,
                'reason': ('Could not determine which port sshd is listening on, '
                           'so there is no way to confirm this removal keeps it '
                           'reachable.'),
                'ssh_ports': None,
                'targets': [],
            }

        if firewall == 'ufw':
            return cls._check_ufw_removal(ssh, rule_type, **kwargs)
        if firewall == 'firewalld':
            return cls._check_firewalld_removal(ssh, rule_type, **kwargs)
        return {'safe': True, 'reason': 'no active firewall',
                'ssh_ports': ssh, 'targets': []}

    @classmethod
    def _check_ufw_removal(cls, ssh: List[int], rule_type: str, **kwargs) -> Dict:
        rules = cls._ufw_numbered_rules()
        number = kwargs.get('number')

        if number:
            target = next((r for r in rules if r['number'] == int(number)), None)
            if target is None:
                # Unknown index: ufw would reject it anyway, and refusing on a
                # rule we could not read would block harmless deletes.
                return {'safe': True, 'reason': f'no active rule numbered {number}',
                        'ssh_ports': ssh, 'targets': []}
            targets = [target]
        else:
            port = kwargs.get('port')
            if port is None:
                return {'safe': True, 'reason': 'removal does not name a port',
                        'ssh_ports': ssh, 'targets': []}
            if int(port) not in ssh:
                return {'safe': True, 'reason': 'port is not an SSH port',
                        'ssh_ports': ssh, 'targets': []}
            targets = [r for r in rules if int(port) in cls._ports_in(r['to'])]

        removed_numbers = {r['number'] for r in targets}
        covers_ssh = [r for r in targets
                      if r['action'] == 'ALLOW' and cls._ports_in(r['to']) & set(ssh)]
        if not covers_ssh:
            return {'safe': True, 'reason': 'rule does not admit SSH',
                    'ssh_ports': ssh, 'targets': [r['to'] for r in targets]}

        # Another allow rule may still admit SSH after this one goes — deleting
        # a duplicate is harmless and must not be blocked.
        remaining = [r for r in rules
                     if r['number'] not in removed_numbers
                     and r['action'] == 'ALLOW'
                     and cls._ports_in(r['to']) & set(ssh)]
        if remaining:
            return {'safe': True,
                    'reason': f'SSH stays open via rule {remaining[0]["number"]} '
                              f'({remaining[0]["to"]})',
                    'ssh_ports': ssh, 'targets': [r['to'] for r in covers_ssh]}

        listed = ', '.join(str(p) for p in ssh)
        return {
            'safe': False,
            'reason': (f'This is the only active rule admitting SSH on port {listed}. '
                       f'Removing it closes your own session — the firewall is '
                       f'active and denying by default.'),
            'ssh_ports': ssh,
            'targets': [r['to'] for r in covers_ssh],
        }

    @classmethod
    def _check_firewalld_removal(cls, ssh: List[int], rule_type: str, **kwargs) -> Dict:
        coverage = cls._firewalld_ssh_coverage(ssh)
        removing = set()

        if rule_type == 'service' and kwargs.get('service') == 'ssh':
            removing.add('service:ssh')
        elif rule_type == 'port':
            port = kwargs.get('port')
            if port is not None and int(port) in ssh:
                removing.add(int(port))

        if not removing:
            return {'safe': True, 'reason': 'rule does not admit SSH',
                    'ssh_ports': ssh, 'targets': []}

        if coverage - removing:
            return {'safe': True, 'reason': 'SSH stays open via another rule',
                    'ssh_ports': ssh, 'targets': sorted(str(t) for t in removing)}

        listed = ', '.join(str(p) for p in ssh)
        return {
            'safe': False,
            'reason': (f'This is the only rule admitting SSH on port {listed}. '
                       f'Removing it closes your own session.'),
            'ssh_ports': ssh,
            'targets': sorted(str(t) for t in removing),
        }

    @classmethod
    def remove_rule(cls, rule_type: str, force: bool = False, **kwargs) -> Dict:
        """Remove a firewall rule.

        Refuses when the rule is the last one admitting SSH on a firewall that
        is currently enforcing. ``force=True`` is the operator accepting it.
        """
        status = cls.get_status()
        firewall = status['active_firewall']

        if firewall not in ('firewalld', 'ufw'):
            return {'success': False, 'error': 'No firewall detected'}

        if not force:
            preflight = cls.check_ssh_rule_removal(rule_type, **kwargs)
            if not preflight['safe']:
                return {
                    'success': False,
                    'error': preflight['reason'],
                    'blocked_by': 'ssh_lockout',
                    'ssh_ports': preflight['ssh_ports'],
                    'targets': preflight['targets'],
                    'override': 'Send force=true to remove it anyway.',
                }

        if firewall == 'firewalld':
            return cls._remove_firewalld_rule(rule_type, **kwargs)
        return cls._remove_ufw_rule(rule_type, **kwargs)

    @classmethod
    def _remove_firewalld_rule(cls, rule_type: str, **kwargs) -> Dict:
        """Remove a firewalld rule."""
        try:
            permanent = kwargs.get('permanent', True)
            perm_flag = ['--permanent'] if permanent else []

            if rule_type == 'service':
                service = kwargs.get('service')
                cmd = ['firewall-cmd'] + perm_flag + [f'--remove-service={service}']

            elif rule_type == 'port':
                port = kwargs.get('port')
                protocol = kwargs.get('protocol', 'tcp')
                cmd = ['firewall-cmd'] + perm_flag + [f'--remove-port={port}/{protocol}']

            elif rule_type == 'block_ip':
                ip = kwargs.get('ip')
                cmd = ['firewall-cmd'] + perm_flag + [
                    f'--remove-rich-rule=rule family="ipv4" source address="{ip}" reject'
                ]

            elif rule_type == 'rich':
                rule = kwargs.get('rule')
                cmd = ['firewall-cmd'] + perm_flag + [f'--remove-rich-rule={rule}']

            else:
                return {'success': False, 'error': f'Unknown rule type: {rule_type}'}

            result = run_privileged(cmd)

            if result.returncode == 0:
                if permanent:
                    run_privileged(['firewall-cmd', '--reload'])
                return {'success': True, 'message': 'Rule removed successfully'}

            return {'success': False, 'error': result.stderr or 'Failed to remove rule'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def _remove_ufw_rule(cls, rule_type: str, **kwargs) -> Dict:
        """Remove a ufw rule."""
        try:
            rule_number = kwargs.get('number')
            if rule_number:
                result = run_privileged(['ufw', '--force', 'delete', str(rule_number)])
            else:
                if rule_type == 'port':
                    port = kwargs.get('port')
                    protocol = kwargs.get('protocol', 'tcp')
                    action = kwargs.get('action', 'allow')
                    result = run_privileged(['ufw', 'delete', action, f'{port}/{protocol}'])
                elif rule_type == 'block_ip':
                    ip = kwargs.get('ip')
                    result = run_privileged(['ufw', 'delete', 'deny', 'from', ip])
                else:
                    return {'success': False, 'error': 'Rule number or specification required'}

            if result.returncode == 0:
                return {'success': True, 'message': 'Rule removed successfully'}

            return {'success': False, 'error': result.stderr or 'Failed to remove rule'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def block_ip(cls, ip: str, permanent: bool = True) -> Dict:
        """Quick method to block an IP address."""
        # Validate IP format
        if not cls._is_valid_ip(ip):
            return {'success': False, 'error': 'Invalid IP address format'}

        return cls.add_rule('block_ip', ip=ip, permanent=permanent)

    @classmethod
    def unblock_ip(cls, ip: str, permanent: bool = True) -> Dict:
        """Quick method to unblock an IP address."""
        return cls.remove_rule('block_ip', ip=ip, permanent=permanent)

    @classmethod
    def allow_port(cls, port: int, protocol: str = 'tcp', permanent: bool = True) -> Dict:
        """Quick method to allow a port."""
        return cls.add_rule('port', port=port, protocol=protocol, permanent=permanent)

    @classmethod
    def deny_port(cls, port: int, protocol: str = 'tcp', permanent: bool = True,
                  force: bool = False) -> Dict:
        """Quick method to deny a port.

        Routes through remove_rule, so denying the SSH port hits the same
        lockout guard as deleting its rule — it is the same outcome.
        """
        return cls.remove_rule('port', force=force, port=port, protocol=protocol,
                               permanent=permanent)

    @classmethod
    def get_blocked_ips(cls) -> Dict:
        """Get list of blocked IP addresses."""
        status = cls.get_status()
        firewall = status['active_firewall']

        blocked_ips = []

        if firewall == 'firewalld':
            result = run_privileged(['firewall-cmd', '--list-rich-rules'])
            for line in result.stdout.strip().split('\n'):
                if 'reject' in line.lower() or 'drop' in line.lower():
                    match = re.search(r'source address="([^"]+)"', line)
                    if match:
                        blocked_ips.append({
                            'ip': match.group(1),
                            'rule': line
                        })

        elif firewall == 'ufw':
            result = run_privileged(['ufw', 'status', 'numbered'])
            for line in result.stdout.strip().split('\n'):
                if 'DENY' in line:
                    # Parse IP from rule
                    match = re.search(r'from\s+(\d+\.\d+\.\d+\.\d+(?:/\d+)?)', line)
                    if match:
                        blocked_ips.append({
                            'ip': match.group(1),
                            'rule': line
                        })

        return {
            'success': True,
            'firewall': firewall,
            'blocked_ips': blocked_ips
        }

    @classmethod
    def get_zones(cls) -> Dict:
        """Get firewalld zones (firewalld only)."""
        try:
            result = run_privileged(['firewall-cmd', '--get-zones'])
            zones = result.stdout.strip().split()

            result = run_privileged(['firewall-cmd', '--get-default-zone'])
            default_zone = result.stdout.strip()

            zone_details = []
            for zone in zones:
                result = run_privileged(['firewall-cmd', f'--zone={zone}', '--list-all'])
                zone_details.append({
                    'name': zone,
                    'is_default': zone == default_zone,
                    'details': result.stdout
                })

            return {
                'success': True,
                'zones': zone_details,
                'default_zone': default_zone
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def set_default_zone(cls, zone: str) -> Dict:
        """Set default firewalld zone."""
        try:
            result = run_privileged(['firewall-cmd', f'--set-default-zone={zone}'])
            if result.returncode == 0:
                return {'success': True, 'message': f'Default zone set to {zone}'}
            return {'success': False, 'error': result.stderr or 'Failed to set default zone'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @classmethod
    def install_firewall(cls, firewall: str = 'ufw') -> Dict:
        """Install a firewall."""
        if firewall not in ['ufw', 'firewalld']:
            return {'success': False, 'error': 'Invalid firewall. Use ufw or firewalld'}

        try:
            result = PackageManager.install(firewall)

            if result.returncode == 0:
                return {'success': True, 'message': f'{firewall} installed successfully'}
            return {'success': False, 'error': result.stderr or 'Installation failed'}

        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Installation timed out'}
        except RuntimeError as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def _is_valid_ip(ip: str) -> bool:
        """Validate IP address format."""
        # IPv4 pattern
        ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$'
        # IPv6 pattern (simplified)
        ipv6_pattern = r'^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(/\d{1,3})?$'

        if re.match(ipv4_pattern, ip):
            # Validate each octet
            parts = ip.split('/')[0].split('.')
            return all(0 <= int(part) <= 255 for part in parts)

        return bool(re.match(ipv6_pattern, ip))
