"""Email service orchestrator — delegates to sub-services for each component."""
import logging
import subprocess
from typing import Dict, List, Optional

from app import db
from app.models.email import EmailDomain, EmailAccount, EmailAlias, EmailForwardingRule
from app.services.postfix_service import PostfixService
from app.utils.system import PackageManager, ServiceControl
from .dovecot_service import DovecotService
from .dkim_service import DKIMService
from .spamassassin_service import SpamAssassinService
from .roundcube_service import RoundcubeService

logger = logging.getLogger(__name__)


class EmailService:
    """High-level email service that coordinates Postfix, Dovecot, DKIM, and SpamAssassin."""

    COMPONENTS = {
        'postfix': PostfixService,
        'dovecot': DovecotService,
        'opendkim': DKIMService,
        'spamassassin': SpamAssassinService,
    }

    # ── Status ──

    @classmethod
    def get_status(cls) -> Dict:
        """Get aggregate email server status."""
        postfix = PostfixService.get_status()
        dovecot = DovecotService.get_status()
        dkim = DKIMService.get_status()
        spam = SpamAssassinService.get_status()

        all_installed = postfix['installed'] and dovecot['installed']
        # bool(): a component whose probe could not run reports running=None
        # (see DovecotService.get_status), and `True and None` is None — the
        # top-level flag is documented as a boolean, so keep it one. The
        # honest per-component tri-state is still in the nested dicts.
        all_running = bool(postfix.get('running', False) and dovecot.get('running', False))

        return {
            'installed': all_installed,
            'running': all_running,
            'postfix': postfix,
            'dovecot': dovecot,
            'dkim': dkim,
            'spamassassin': spam,
        }

    # ── Installation ──

    @classmethod
    def install_all(cls, hostname: str = None) -> Dict:
        """Install and configure all email components."""
        results = {}

        # 1. Install Postfix
        results['postfix'] = PostfixService.install(hostname=hostname)
        if not results['postfix'].get('success'):
            return {'success': False, 'error': 'Postfix installation failed', 'results': results}

        # 2. Configure Postfix
        postfix_config = PostfixService.configure(hostname=hostname)
        if not postfix_config.get('success'):
            logger.warning(f"Postfix configuration warning: {postfix_config.get('error')}")

        # 3. Install Dovecot
        results['dovecot'] = DovecotService.install()
        if not results['dovecot'].get('success'):
            return {'success': False, 'error': 'Dovecot installation failed', 'results': results}

        # 4. Configure Dovecot
        dovecot_config = DovecotService.configure()
        if not dovecot_config.get('success'):
            logger.warning(f"Dovecot configuration warning: {dovecot_config.get('error')}")

        # 5. Install OpenDKIM
        results['dkim'] = DKIMService.install()
        if not results['dkim'].get('success'):
            logger.warning(f"DKIM installation warning: {results['dkim'].get('error')}")

        # 6. Install SpamAssassin
        results['spamassassin'] = SpamAssassinService.install()
        if not results['spamassassin'].get('success'):
            logger.warning(f"SpamAssassin installation warning: {results['spamassassin'].get('error')}")

        all_ok = all(r.get('success') for r in results.values())
        return {
            'success': all_ok,
            'message': 'All email components installed' if all_ok else 'Some components had issues',
            'results': results,
        }

    # ── Service Control ──

    @classmethod
    def control_service(cls, component: str, action: str) -> Dict:
        """Start/stop/restart an email component."""
        if component not in cls.COMPONENTS and component != 'roundcube':
            return {'success': False, 'error': f'Unknown component: {component}'}

        if action not in ('start', 'stop', 'restart', 'reload'):
            return {'success': False, 'error': f'Invalid action: {action}'}

        try:
            if component == 'roundcube':
                actions = {
                    'start': RoundcubeService.start,
                    'stop': RoundcubeService.stop,
                    'restart': RoundcubeService.restart,
                    'reload': RoundcubeService.restart,
                }
                return actions[action]()

            service_name = component
            if action == 'start':
                result = ServiceControl.start(service_name, timeout=30)
            elif action == 'stop':
                result = ServiceControl.stop(service_name, timeout=30)
            elif action == 'restart':
                result = ServiceControl.restart(service_name, timeout=30)
            elif action == 'reload':
                result = ServiceControl.reload(service_name, timeout=30)

            if result.returncode == 0:
                return {'success': True, 'message': f'{component} {action} successful'}
            return {'success': False, 'error': result.stderr or f'{action} failed'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ── Domains ──

    @classmethod
    def get_domains(cls) -> List[Dict]:
        """List all email domains."""
        domains = EmailDomain.query.all()
        return [d.to_dict() for d in domains]

    @classmethod
    def add_domain(cls, name: str, dns_provider_id: int = None, dns_zone_id: str = None) -> Dict:
        """Add an email domain."""
        try:
            existing = EmailDomain.query.filter_by(name=name).first()
            if existing:
                return {'success': False, 'error': f'Domain {name} already exists'}

            domain = EmailDomain(
                name=name,
                dns_provider_id=dns_provider_id,
                dns_zone_id=dns_zone_id,
            )
            db.session.add(domain)
            db.session.commit()

            # Add to Postfix virtual domains
            PostfixService.add_domain(name)

            # Generate DKIM key
            dkim_result = DKIMService.generate_key(name)
            if dkim_result.get('success'):
                domain.dkim_selector = 'default'
                domain.dkim_private_key_path = dkim_result.get('private_key_path')
                domain.dkim_public_key = dkim_result.get('public_key')
                domain.spf_record = f'v=spf1 mx a ~all'
                domain.dmarc_record = f'v=DMARC1; p=quarantine; rua=mailto:dmarc@{name}; pct=100'
                DKIMService.add_domain(name)
                db.session.commit()

            return {'success': True, 'domain': domain.to_dict(), 'message': f'Domain {name} added'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    @classmethod
    def get_domain(cls, domain_id: int) -> Dict:
        """Get domain details."""
        domain = EmailDomain.query.get(domain_id)
        if not domain:
            return {'success': False, 'error': 'Domain not found'}
        return {'success': True, 'domain': domain.to_dict()}

    @classmethod
    def remove_domain(cls, domain_id: int) -> Dict:
        """Remove an email domain and all its accounts/aliases."""
        try:
            domain = EmailDomain.query.get(domain_id)
            if not domain:
                return {'success': False, 'error': 'Domain not found'}

            domain_name = domain.name

            # Remove accounts from Dovecot/Postfix
            for account in domain.accounts:
                DovecotService.delete_mailbox(account.email, domain_name, account.username, remove_files=True)
                PostfixService.remove_mailbox(account.email)

            # Remove aliases from Postfix
            for alias in domain.aliases:
                PostfixService.remove_alias(alias.source)

            # Remove from DKIM
            DKIMService.remove_domain(domain_name)

            # Remove from Postfix virtual domains
            PostfixService.remove_domain(domain_name)

            # Delete from database
            db.session.delete(domain)
            db.session.commit()

            return {'success': True, 'message': f'Domain {domain_name} removed'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    @classmethod
    def verify_dns(cls, domain_id: int) -> Dict:
        """Verify DNS records for a domain."""
        domain = EmailDomain.query.get(domain_id)
        if not domain:
            return {'success': False, 'error': 'Domain not found'}

        results = {}
        name = domain.name

        # Check MX record
        try:
            result = subprocess.run(['dig', '+short', 'MX', name], capture_output=True, text=True, timeout=10)
            results['mx'] = {
                'found': bool(result.stdout.strip()),
                'value': result.stdout.strip() or None,
            }
        except Exception:
            results['mx'] = {'found': False, 'error': 'DNS lookup failed'}

        # Check SPF record
        try:
            result = subprocess.run(['dig', '+short', 'TXT', name], capture_output=True, text=True, timeout=10)
            spf_found = 'v=spf1' in (result.stdout or '')
            results['spf'] = {
                'found': spf_found,
                'value': result.stdout.strip() or None,
            }
        except Exception:
            results['spf'] = {'found': False, 'error': 'DNS lookup failed'}

        # Check DKIM record
        selector = domain.dkim_selector or 'default'
        try:
            dkim_name = f'{selector}._domainkey.{name}'
            result = subprocess.run(['dig', '+short', 'TXT', dkim_name], capture_output=True, text=True, timeout=10)
            dkim_found = 'v=DKIM1' in (result.stdout or '')
            results['dkim'] = {
                'found': dkim_found,
                'value': result.stdout.strip() or None,
                'name': dkim_name,
            }
        except Exception:
            results['dkim'] = {'found': False, 'error': 'DNS lookup failed'}

        # Check DMARC record
        try:
            dmarc_name = f'_dmarc.{name}'
            result = subprocess.run(['dig', '+short', 'TXT', dmarc_name], capture_output=True, text=True, timeout=10)
            dmarc_found = 'v=DMARC1' in (result.stdout or '')
            results['dmarc'] = {
                'found': dmarc_found,
                'value': result.stdout.strip() or None,
            }
        except Exception:
            results['dmarc'] = {'found': False, 'error': 'DNS lookup failed'}

        all_ok = all(r.get('found') for r in results.values())
        return {
            'success': True,
            'domain': name,
            'all_verified': all_ok,
            'records': results,
        }

    # ── Accounts ──

    @classmethod
    def get_accounts(cls, domain_id: int) -> List[Dict]:
        """List email accounts for a domain."""
        accounts = EmailAccount.query.filter_by(domain_id=domain_id).all()
        return [a.to_dict() for a in accounts]

    @classmethod
    def add_account(cls, domain_id: int, username: str, password: str, quota_mb: int = 1024) -> Dict:
        """Create an email account."""
        try:
            domain = EmailDomain.query.get(domain_id)
            if not domain:
                return {'success': False, 'error': 'Domain not found'}

            email = f'{username}@{domain.name}'

            existing = EmailAccount.query.filter_by(email=email).first()
            if existing:
                return {'success': False, 'error': f'Account {email} already exists'}

            # Create mailbox in Dovecot
            dovecot_result = DovecotService.create_mailbox(email, password, domain.name, username, quota_mb)
            if not dovecot_result.get('success'):
                return dovecot_result

            # Add to Postfix virtual mailboxes
            PostfixService.add_mailbox(email, domain.name, username)

            # Get password hash for storage
            password_hash = dovecot_result.get('password_hash', 'stored_in_dovecot')

            account = EmailAccount(
                email=email,
                username=username,
                password_hash=password_hash,
                domain_id=domain_id,
                quota_mb=quota_mb,
            )
            db.session.add(account)
            db.session.commit()

            return {'success': True, 'account': account.to_dict(), 'message': f'Account {email} created'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    @classmethod
    def update_account(cls, account_id: int, quota_mb: int = None, is_active: bool = None) -> Dict:
        """Update account settings."""
        try:
            account = EmailAccount.query.get(account_id)
            if not account:
                return {'success': False, 'error': 'Account not found'}

            if quota_mb is not None:
                account.quota_mb = quota_mb
                DovecotService.set_quota(account.email, quota_mb)

            if is_active is not None:
                account.is_active = is_active

            db.session.commit()
            return {'success': True, 'account': account.to_dict(), 'message': 'Account updated'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    @classmethod
    def delete_account(cls, account_id: int) -> Dict:
        """Delete an email account."""
        try:
            account = EmailAccount.query.get(account_id)
            if not account:
                return {'success': False, 'error': 'Account not found'}

            email = account.email
            domain_name = account.domain.name if account.domain else ''
            username = account.username

            # Remove from Dovecot
            DovecotService.delete_mailbox(email, domain_name, username, remove_files=True)

            # Remove from Postfix
            PostfixService.remove_mailbox(email)

            db.session.delete(account)
            db.session.commit()

            return {'success': True, 'message': f'Account {email} deleted'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    @classmethod
    def change_password(cls, account_id: int, new_password: str) -> Dict:
        """Change an account password."""
        try:
            account = EmailAccount.query.get(account_id)
            if not account:
                return {'success': False, 'error': 'Account not found'}

            result = DovecotService.change_password(account.email, new_password)
            if not result.get('success'):
                return result

            account.password_hash = 'updated_in_dovecot'
            db.session.commit()

            return {'success': True, 'message': 'Password changed successfully'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    # ── Aliases ──

    @classmethod
    def get_aliases(cls, domain_id: int) -> List[Dict]:
        """List email aliases for a domain."""
        aliases = EmailAlias.query.filter_by(domain_id=domain_id).all()
        return [a.to_dict() for a in aliases]

    @classmethod
    def add_alias(cls, domain_id: int, source: str, destination: str) -> Dict:
        """Create an email alias."""
        try:
            domain = EmailDomain.query.get(domain_id)
            if not domain:
                return {'success': False, 'error': 'Domain not found'}

            # Add @ domain if not already qualified
            if '@' not in source:
                source = f'{source}@{domain.name}'

            alias = EmailAlias(
                source=source,
                destination=destination,
                domain_id=domain_id,
            )
            db.session.add(alias)
            db.session.commit()

            # Add to Postfix virtual aliases
            PostfixService.add_alias(source, destination)

            return {'success': True, 'alias': alias.to_dict(), 'message': f'Alias {source} created'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    @classmethod
    def remove_alias(cls, alias_id: int) -> Dict:
        """Delete an email alias."""
        try:
            alias = EmailAlias.query.get(alias_id)
            if not alias:
                return {'success': False, 'error': 'Alias not found'}

            PostfixService.remove_alias(alias.source)

            db.session.delete(alias)
            db.session.commit()

            return {'success': True, 'message': 'Alias removed'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    # ── Forwarding Rules ──

    @classmethod
    def get_forwarding(cls, account_id: int) -> List[Dict]:
        """List forwarding rules for an account."""
        rules = EmailForwardingRule.query.filter_by(account_id=account_id).all()
        return [r.to_dict() for r in rules]

    @classmethod
    def add_forwarding(cls, account_id: int, destination: str, keep_copy: bool = True) -> Dict:
        """Create a forwarding rule."""
        try:
            account = EmailAccount.query.get(account_id)
            if not account:
                return {'success': False, 'error': 'Account not found'}

            rule = EmailForwardingRule(
                account_id=account_id,
                destination=destination,
                keep_copy=keep_copy,
            )
            db.session.add(rule)
            db.session.commit()

            # Update Postfix aliases for forwarding
            cls._sync_forwarding_aliases(account)

            return {'success': True, 'rule': rule.to_dict(), 'message': 'Forwarding rule created'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    @classmethod
    def update_forwarding(cls, rule_id: int, destination: str = None,
                          keep_copy: bool = None, is_active: bool = None) -> Dict:
        """Update a forwarding rule."""
        try:
            rule = EmailForwardingRule.query.get(rule_id)
            if not rule:
                return {'success': False, 'error': 'Forwarding rule not found'}

            if destination is not None:
                rule.destination = destination
            if keep_copy is not None:
                rule.keep_copy = keep_copy
            if is_active is not None:
                rule.is_active = is_active

            db.session.commit()

            # Re-sync Postfix aliases
            cls._sync_forwarding_aliases(rule.account)

            return {'success': True, 'rule': rule.to_dict(), 'message': 'Forwarding rule updated'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    @classmethod
    def remove_forwarding(cls, rule_id: int) -> Dict:
        """Delete a forwarding rule."""
        try:
            rule = EmailForwardingRule.query.get(rule_id)
            if not rule:
                return {'success': False, 'error': 'Forwarding rule not found'}

            account = rule.account
            db.session.delete(rule)
            db.session.commit()

            # Re-sync Postfix aliases
            cls._sync_forwarding_aliases(account)

            return {'success': True, 'message': 'Forwarding rule removed'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'error': str(e)}

    @classmethod
    def _sync_forwarding_aliases(cls, account: EmailAccount):
        """Sync forwarding rules to Postfix virtual aliases for an account."""
        active_rules = [r for r in account.forwarding_rules if r.is_active]

        if not active_rules:
            # Remove any forwarding alias
            PostfixService.remove_alias(account.email)
            return

        # Build destination list
        destinations = [r.destination for r in active_rules]
        # If any rule wants to keep a copy, include the original mailbox
        if any(r.keep_copy for r in active_rules):
            destinations.append(account.email)

        # Remove old alias and add new one
        PostfixService.remove_alias(account.email)
        PostfixService.add_alias(account.email, ', '.join(destinations))
