"""Restore-point adapter for the local host firewall.

The payload intentionally contains only the panel's supported, replayable
firewall vocabulary.  Runtime bans and Docker-managed chains remain outside
the checkpoint, as stated by the frozen coverage text.
"""

import re

from flask import has_request_context

from app.services.firewall_service import FirewallService
from app.utils.system import PROBE_TIMEOUT, run_privileged


coverage = [
    'Restore converges persisted panel-supported UFW rules and firewalld '
    'service, port, and rich-rule families, including matching manually '
    'created rules. Other firewalld families, interfaces, sources, runtime '
    'bans, and Docker-managed iptables chains are left alone.',
]


def _run(argv):
    result = run_privileged(argv, timeout=PROBE_TIMEOUT)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or 'command failed').strip()
        raise RuntimeError(f'{" ".join(argv)}: {message}')
    return result.stdout or ''


def _ufw_rules():
    lines = _run(['ufw', 'show', 'added']).splitlines()
    rules = []
    for line in lines:
        line = line.strip()
        if not line.lower().startswith('ufw '):
            continue
        argv = line.split()[1:]
        if argv:
            rules.append({'kind': 'ufw', 'argv': argv})
    return sorted(rules, key=_rule_key)


def _firewalld_rules(running, zones):
    command = 'firewall-cmd' if running else 'firewall-offline-cmd'
    persistent = ['--permanent'] if running else []
    rules = []
    for zone_name in sorted(set(zones)):
        zone = [f'--zone={zone_name}']
        for value in _run([command] + persistent + zone + ['--list-services']).split():
            rules.append({
                'kind': 'service', 'service': value, 'zone': zone_name,
                'permanent': True,
            })
        for value in _run([command] + persistent + zone + ['--list-ports']).split():
            port, _, protocol = value.partition('/')
            rules.append({
                'kind': 'port', 'port': port, 'protocol': protocol or 'tcp',
                'zone': zone_name, 'permanent': True,
            })
        rich = _run([command] + persistent + zone + ['--list-rich-rules'])
        for value in rich.splitlines():
            if value.strip():
                rules.append({
                    'kind': 'rich', 'rule': value.strip(), 'zone': zone_name,
                    'permanent': True,
                })
    return sorted(rules, key=_rule_key)


def capture(scope_id, server_id=None):
    if str(scope_id) != 'firewall':
        raise ValueError('the firewall adapter only supports scope_id=firewall')
    if server_id is not None:
        raise ValueError('remote firewall restore points are not supported')
    status = FirewallService.get_status()
    firewall = status.get('active_firewall')
    if firewall not in ('ufw', 'firewalld'):
        raise RuntimeError('no supported local firewall is installed')

    if firewall == 'ufw':
        active = status.get('ufw', {}).get('active')
        if active is None:
            raise RuntimeError('could not determine whether ufw is active')
        default_policy = FirewallService._ufw_default_incoming_policy()
        if default_policy is None:
            raise RuntimeError('could not read the UFW default incoming policy')
        return {
            'version': 1,
            'firewall': 'ufw',
            'enabled': bool(active),
            'default_zone': None,
            'default_incoming_allow': default_policy,
            'rules': _ufw_rules(),
        }

    running = status.get('firewalld', {}).get('running')
    if running is None:
        raise RuntimeError('could not determine whether firewalld is running')
    command = 'firewall-cmd' if running else 'firewall-offline-cmd'
    default_zone = (status.get('firewalld', {}).get('default_zone') or
                    _run([command, '--get-default-zone']).strip())
    if not default_zone:
        raise RuntimeError('could not determine the firewalld default zone')
    zones = _run([command] + (['--permanent'] if running else []) + [
        '--get-zones',
    ]).split()
    if default_zone not in zones:
        zones.append(default_zone)
    return {
        'version': 1,
        'firewall': 'firewalld',
        'enabled': bool(running),
        'default_zone': default_zone,
        'default_incoming_allow': None,
        'rules': _firewalld_rules(bool(running), zones),
    }


def _rule_key(rule):
    return repr(sorted(rule.items()))


def _ufw_spec(rule):
    argv = list(rule.get('argv') or [])
    if not argv:
        return None
    action = argv[0].lower()
    if action in ('allow', 'deny') and len(argv) == 2:
        target = argv[1]
        match = re.fullmatch(r'(\d{1,5})(?:/(tcp|udp))?', target, re.I)
        if match:
            return ('port', {
                'port': int(match.group(1)),
                'protocol': (match.group(2) or 'tcp').lower(),
                'action': action,
            })
        return ('service', {'service': target, 'action': action})
    if len(argv) >= 3 and argv[1].lower() == 'from':
        address = argv[2]
        if action == 'deny' and len(argv) == 3:
            return ('block_ip', {'ip': address})
        if action == 'allow':
            values = {'ip': address}
            if 'port' in [part.lower() for part in argv]:
                index = [part.lower() for part in argv].index('port')
                if index + 1 < len(argv):
                    values['port'] = int(argv[index + 1])
            return ('allow_ip', values)
    return None


def _door_spec(rule):
    if rule.get('kind') == 'ufw':
        return _ufw_spec(rule)
    kind = rule.get('kind')
    values = {
        key: rule[key]
        for key in ('service', 'port', 'protocol', 'rule', 'zone', 'permanent')
        if key in rule
    }
    return (kind, values) if kind in ('service', 'port', 'rich') else None


def _ssh_coverage(payload, ssh_ports):
    if payload.get('firewall') == 'ufw':
        if payload.get('default_incoming_allow'):
            return set(ssh_ports)
        covered = set()
        for rule in payload.get('rules') or []:
            spec = _ufw_spec(rule)
            if not spec:
                continue
            kind, values = spec
            if values.get('action', 'allow') != 'allow':
                continue
            if kind == 'port' and int(values['port']) in ssh_ports:
                covered.add(int(values['port']))
            elif kind == 'service':
                covered.update(
                    FirewallService._app_profile_ports(values['service']) & set(ssh_ports)
                )
        return covered

    covered = set()
    for rule in payload.get('rules') or []:
        if rule.get('zone') != payload.get('default_zone'):
            continue
        if rule.get('kind') == 'service' and rule.get('service') == 'ssh':
            covered.update(ssh_ports)
        elif rule.get('kind') == 'port':
            try:
                port = int(rule.get('port'))
            except (TypeError, ValueError):
                continue
            if port in ssh_ports:
                covered.add(port)
    return covered


def _blocked_networks(payload):
    for rule in payload.get('rules') or []:
        if rule.get('kind') == 'ufw':
            spec = _ufw_spec(rule)
            if spec and spec[0] == 'block_ip':
                yield spec[1]['ip']
        elif rule.get('kind') == 'rich':
            text = rule.get('rule') or ''
            if re.search(r'\b(reject|drop)\b', text, re.I):
                match = re.search(r'source\s+address="([^"]+)"', text, re.I)
                if match:
                    yield match.group(1)


def validate_restore(scope_id, payload, current_payload, actor=None, server_id=None):
    refusals = []
    if payload.get('version') != 1:
        refusals.append('The firewall restore-point format is unsupported.')
    if payload.get('firewall') not in ('ufw', 'firewalld'):
        refusals.append('The checkpoint does not name a supported firewall.')
    if payload.get('firewall') != current_payload.get('firewall'):
        refusals.append('Restoring across different firewall implementations is refused.')
    unsupported = [rule for rule in payload.get('rules') or [] if not _door_spec(rule)]
    if unsupported:
        refusals.append('The checkpoint contains firewall rules the panel cannot replay safely.')

    if payload.get('enabled'):
        ssh_ports = FirewallService.ssh_ports()
        if ssh_ports is None:
            refusals.append(
                'Could not determine the live SSH ports, so enabling this ruleset is unsafe.'
            )
        elif set(ssh_ports) - _ssh_coverage(payload, ssh_ports):
            missing = ', '.join(str(port) for port in sorted(
                set(ssh_ports) - _ssh_coverage(payload, ssh_ports)
            ))
            refusals.append(f'The target ruleset does not admit SSH on port {missing}.')

    protected = {'127.0.0.1', '::1'} | FirewallService.active_ssh_peers()
    if has_request_context():
        from app.utils.client_ip import get_client_ip
        if get_client_ip():
            protected.add(get_client_ip())
    for network in _blocked_networks(payload):
        conflicts = [address for address in sorted(protected)
                     if FirewallService._covers_address(network, address)]
        if conflicts:
            refusals.append(
                f'The target ruleset blocks a protected live address ({", ".join(conflicts)}).'
            )
    return refusals


def _apply(rule, removing=False):
    spec = _door_spec(rule)
    if spec is None:
        raise RuntimeError('firewall rule is not replayable')
    kind, values = spec
    operation = FirewallService.remove_rule if removing else FirewallService.add_rule
    if removing:
        result = operation(kind, force=True, **values)
    else:
        result = operation(kind, **values)
    if not result.get('success'):
        raise RuntimeError(result.get('error') or 'firewall rule replay failed')


def _is_ssh_admission(rule, ssh_ports):
    if rule.get('kind') == 'service' and rule.get('service') == 'ssh':
        return True
    spec = _door_spec(rule)
    if not spec:
        return False
    kind, values = spec
    return (kind == 'port' and values.get('action', 'allow') == 'allow'
            and int(values.get('port')) in set(ssh_ports or []))


def restore(scope_id, payload, actor=None, server_id=None):
    current = capture(scope_id, server_id=server_id)
    target_rules = {_rule_key(rule): rule for rule in payload.get('rules') or []}
    current_rules = {_rule_key(rule): rule for rule in current.get('rules') or []}
    additions = [target_rules[key] for key in sorted(target_rules.keys() - current_rules.keys())]
    removals = [current_rules[key] for key in sorted(current_rules.keys() - target_rules.keys())]

    disabled_first = False
    if not payload.get('enabled') and current.get('enabled'):
        result = FirewallService.disable(payload.get('firewall'))
        if not result.get('success'):
            raise RuntimeError(result.get('error') or 'firewall disable failed')
        disabled_first = True

    ssh_ports = FirewallService.ssh_ports() or []
    additions.sort(key=lambda rule: (not _is_ssh_admission(rule, ssh_ports), _rule_key(rule)))
    for rule in additions:
        _apply(rule)

    if payload.get('firewall') == 'firewalld' \
            and payload.get('default_zone') != current.get('default_zone'):
        result = FirewallService.set_default_zone(payload['default_zone'], force=True)
        if not result.get('success'):
            raise RuntimeError(result.get('error') or 'default-zone restore failed')
    elif payload.get('firewall') == 'ufw' \
            and payload.get('default_incoming_allow') != current.get('default_incoming_allow'):
        result = FirewallService.set_default_incoming(
            bool(payload.get('default_incoming_allow')),
        )
        if not result.get('success'):
            raise RuntimeError(result.get('error') or 'default-policy restore failed')

    for rule in removals:
        _apply(rule, removing=True)

    if bool(payload.get('enabled')) != bool(current.get('enabled')):
        operation = FirewallService.enable if payload.get('enabled') else FirewallService.disable
        result = operation(payload.get('firewall'), force=True) \
            if payload.get('enabled') else (
                {'success': True} if disabled_first else operation(payload.get('firewall'))
            )
        if not result.get('success'):
            raise RuntimeError(result.get('error') or 'firewall state restore failed')

    return {'success': True, 'rules_added': len(additions), 'rules_removed': len(removals)}
