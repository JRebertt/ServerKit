"""
YARA Web-Shell Scan Service

Runs a curated web-shell / injected-code rule set against a path (typically an
application docroot). Two engines, best-effort and Linux-friendly:

* Real ``yara`` CLI when installed (adds support for arbitrary custom ``.yar``
  rule files dropped in :attr:`YaraScanService.CUSTOM_RULES_DIR`).
* A built-in pure-Python fallback matcher covering the curated set, so the
  feature works everywhere without yara installed. Custom ``.yar`` files are
  NOT evaluated by the fallback (real YARA is required for those).

The curated rules ship both as Python metadata (below — the source of truth
for severity/description) and as ``yara_rules/webshells.yar`` for the CLI.
Indicator strings in this module are assembled from fragments so this file
does not itself trip content scanners.

Result shape (both engines):
    [{'rule', 'severity', 'file', 'matched', 'description', 'source': 'yara'}]
"""

import os
import re
import subprocess

from app.utils.system import run_checked
import logging
from typing import Dict, List, Optional

from app.utils.system import is_command_available

logger = logging.getLogger(__name__)

# Fragment-assembled indicators (keeps literal signatures out of this file).
_B64 = 'base64_' + 'decode'
_APF = 'auto_prepend_' + 'file'
_FMAN = 'Files' + 'Man'

_REQ_SOURCES = r'\$_(REQUEST|GET|POST|COOKIE)\b'

# Extensions treated as scannable script/config content by the fallback engine.
SCRIPT_EXTENSIONS = {
    '.php', '.phtml', '.php3', '.php4', '.php5', '.php7', '.phps',
    '.inc', '.cgi', '.pl', '.py', '.sh', '.js', '.html', '.htm', '.txt',
    '.ini', '.conf',
}
IMAGE_EXTENSIONS = {'.ico', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'}
CONFIG_BASENAMES = {'.htaccess', '.user.ini'}

# Contextual rules only apply to certain files. Applied as a post-filter for
# BOTH engines (plain YARA cannot express filename conditions).
FILE_CONSTRAINTS = {
    'php_in_image': lambda p: os.path.splitext(p)[1].lower() in IMAGE_EXTENSIONS,
    'htaccess_auto_prepend': lambda p: os.path.basename(p).lower() in CONFIG_BASENAMES,
}

# Curated builtin rules — source of truth for names/severity/description.
# ``patterns`` are regexes; ``require_all`` means every pattern must match
# (combo rules). Names match yara_rules/webshells.yar.
BUILTIN_RULES: List[Dict] = [
    {
        'name': 'php_eval_base64',
        'severity': 'critical',
        'description': 'eval() of base64-decoded payload (classic obfuscated backdoor loader)',
        'patterns': [r'eval\s*\(\s*@?\s*' + _B64 + r'\s*\('],
    },
    {
        'name': 'php_gzinflate_base64',
        'severity': 'critical',
        'description': 'gzinflate(base64_decode(...)) double-obfuscated payload',
        'patterns': [r'gzinflate\s*\(\s*@?\s*' + _B64 + r'\s*\('],
    },
    {
        'name': 'php_gzuncompress_base64',
        'severity': 'critical',
        'description': 'gzuncompress/str_rot13 of base64-decoded payload',
        'patterns': [r'(gzuncompress|str_rot13)\s*\(\s*@?\s*' + _B64 + r'\s*\('],
    },
    {
        'name': 'preg_replace_e_eval',
        'severity': 'critical',
        'description': 'preg_replace() with the /e modifier (evaluates the replacement as PHP)',
        'patterns': [r'preg_replace\s*\(\s*["\'][^"\']{0,60}/[imsxu]{0,4}e[imsxu]{0,4}["\']\s*,'],
    },
    {
        'name': 'assert_request_input',
        'severity': 'critical',
        'description': 'assert() fed directly from request input (code execution primitive)',
        'patterns': [r'assert\s*\(\s*@?\s*' + _REQ_SOURCES],
    },
    {
        'name': 'system_request_input',
        'severity': 'critical',
        'description': 'system() executing raw request input',
        'patterns': [r'system\s*\(\s*@?\s*' + _REQ_SOURCES],
    },
    {
        'name': 'passthru_request_input',
        'severity': 'critical',
        'description': 'passthru() executing raw request input',
        'patterns': [r'passthru\s*\(\s*@?\s*' + _REQ_SOURCES],
    },
    {
        'name': 'shell_exec_request_input',
        'severity': 'critical',
        'description': 'shell_exec() executing raw request input',
        'patterns': [r'shell_exec\s*\(\s*@?\s*' + _REQ_SOURCES],
    },
    {
        'name': 'eval_request_input',
        'severity': 'critical',
        'description': 'eval() fed directly from request input',
        'patterns': [r'eval\s*\(\s*@?\s*' + _REQ_SOURCES],
    },
    {
        'name': 'upload_chmod_777_combo',
        'severity': 'high',
        'description': 'move_uploaded_file combined with chmod 777 in the same file (dropper pattern)',
        'patterns': [r'move_uploaded_file\s*\(', r'chmod\s*\([^)]{0,120}0?777'],
        'require_all': True,
    },
    {
        'name': 'c99_shell_marker',
        'severity': 'critical',
        'description': 'c99 web shell family marker',
        'patterns': [r'c99(sh(ell)?|_launcher|madshell)'],
    },
    {
        'name': 'r57_shell_marker',
        'severity': 'critical',
        'description': 'r57 web shell family marker',
        'patterns': [r'r57(shell|_tricks|\s+shell)'],
    },
    {
        'name': 'wso_shell_marker',
        'severity': 'critical',
        'description': 'WSO (web shell by orb) family marker',
        'patterns': [r'(wso_version|wsoshell|wso\s*2\.[0-9]|\$wso\b)'],
    },
    {
        'name': 'filesman_marker',
        'severity': 'critical',
        'description': 'FilesMan backdoor file-manager marker',
        'patterns': [_FMAN],
        'case_sensitive': True,
    },
    {
        'name': 'php_in_image',
        'severity': 'high',
        'description': 'PHP open tag inside an image file (mismatched extension dropper)',
        'patterns': [r'<\?php'],
    },
    {
        'name': 'htaccess_auto_prepend',
        'severity': 'high',
        'description': 'auto_prepend_file injection via .htaccess/.user.ini',
        'patterns': [_APF],
    },
]

_RULE_META = {r['name']: r for r in BUILTIN_RULES}


class YaraScanService:
    """Curated YARA web-shell pass with a pure-Python fallback engine."""

    # Bundled curated rules for the real yara CLI.
    BUILTIN_RULES_FILE = os.path.join(os.path.dirname(__file__), 'yara_rules', 'webshells.yar')
    # Operator-supplied extra rules (real yara only). Class attr so it can be
    # pointed elsewhere (tests, containers).
    CUSTOM_RULES_DIR = os.environ.get('SERVERKIT_YARA_CUSTOM_DIR',
                                      '/var/serverkit/security/yara-custom')
    MAX_CUSTOM_RULE_SIZE = 64 * 1024          # 64 KB per .yar file
    MAX_SCAN_FILE_SIZE = 2 * 1024 * 1024      # fallback engine skips bigger files
    MAX_FILES = 50000                         # fallback engine hard cap
    SNIPPET_CAP = 160                         # matched-snippet length cap

    # ------------------------------------------------------------------ #
    # Engine selection
    # ------------------------------------------------------------------ #
    @classmethod
    def yara_available(cls) -> bool:
        return is_command_available('yara')

    @classmethod
    def engine(cls) -> str:
        return 'yara' if cls.yara_available() else 'fallback'

    # ------------------------------------------------------------------ #
    # Scanning
    # ------------------------------------------------------------------ #
    @classmethod
    def scan_path(cls, path: str) -> List[Dict]:
        """Run the curated rules (plus custom .yar with real yara) against
        ``path`` (file or directory). Returns the merged findings list."""
        if not os.path.exists(path):
            raise ValueError(f'Path not found: {path}')

        if cls.yara_available():
            findings = cls._scan_with_cli(path)
        else:
            findings = cls._scan_with_fallback(path)

        return [f for f in findings if cls._passes_file_constraint(f)]

    @classmethod
    def _passes_file_constraint(cls, finding: Dict) -> bool:
        constraint = FILE_CONSTRAINTS.get(finding.get('rule'))
        if constraint is None:
            return True
        try:
            return bool(constraint(finding.get('file') or ''))
        except Exception:
            return False

    # ---- real yara CLI ------------------------------------------------ #
    @classmethod
    def _rule_files(cls) -> List[str]:
        files = [cls.BUILTIN_RULES_FILE]
        try:
            if os.path.isdir(cls.CUSTOM_RULES_DIR):
                for name in sorted(os.listdir(cls.CUSTOM_RULES_DIR)):
                    if name.endswith('.yar'):
                        files.append(os.path.join(cls.CUSTOM_RULES_DIR, name))
        except OSError:
            pass
        return files

    @classmethod
    def _scan_with_cli(cls, path: str) -> List[Dict]:
        findings = []
        for rules_file in cls._rule_files():
            result = run_checked(['yara', '-r', '-s', '-w', rules_file, path],
                                 timeout=1800)
            if result['returncode'] is None:
                logger.warning('yara run failed for %s: %s', rules_file, result['error'])
                continue
            if result['returncode'] not in (0, 1):
                logger.warning('yara error on %s: %s', rules_file, result['error'][:300])
                continue
            findings.extend(cls._parse_cli_output(result['output']))
        return findings

    @classmethod
    def _parse_cli_output(cls, output: str) -> List[Dict]:
        """Parse ``yara -s`` output: ``rule file`` lines followed by
        ``0xOFFSET:$id: matched data`` lines."""
        findings = []
        current = None
        for line in output.splitlines():
            if not line:
                continue
            string_match = re.match(r'^0x[0-9a-fA-F]+:\$\w+:\s?(.*)$', line)
            if string_match and current is not None:
                if not current['matched']:
                    current['matched'] = string_match.group(1)[:cls.SNIPPET_CAP]
                continue
            parts = line.split(' ', 1)
            if len(parts) == 2:
                rule_name, file_path = parts[0], parts[1].strip()
                meta = _RULE_META.get(rule_name, {})
                current = {
                    'rule': rule_name,
                    'severity': meta.get('severity', 'medium'),
                    'file': file_path,
                    'matched': '',
                    'description': meta.get('description', 'Custom YARA rule match'),
                    'source': 'yara',
                }
                findings.append(current)
        return findings

    # ---- pure-Python fallback ----------------------------------------- #
    @classmethod
    def _compiled_rules(cls) -> List[Dict]:
        compiled = []
        for rule in BUILTIN_RULES:
            flags = 0 if rule.get('case_sensitive') else re.IGNORECASE
            compiled.append({
                **rule,
                'compiled': [re.compile(p, flags) for p in rule['patterns']],
            })
        return compiled

    @classmethod
    def _iter_candidate_files(cls, path: str):
        if os.path.isfile(path):
            yield path
            return
        count = 0
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules')]
            for name in files:
                count += 1
                if count > cls.MAX_FILES:
                    logger.warning('YARA fallback scan hit the %s-file cap under %s',
                                   cls.MAX_FILES, path)
                    return
                yield os.path.join(root, name)

    @classmethod
    def _is_scannable(cls, file_path: str) -> bool:
        base = os.path.basename(file_path).lower()
        if base in CONFIG_BASENAMES:
            return True
        ext = os.path.splitext(file_path)[1].lower()
        return ext in SCRIPT_EXTENSIONS or ext in IMAGE_EXTENSIONS

    @classmethod
    def _scan_with_fallback(cls, path: str) -> List[Dict]:
        rules = cls._compiled_rules()
        findings = []
        for file_path in cls._iter_candidate_files(path):
            if not cls._is_scannable(file_path):
                continue
            try:
                if os.path.getsize(file_path) > cls.MAX_SCAN_FILE_SIZE:
                    continue
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read()
            except (OSError, PermissionError):
                continue
            for rule in rules:
                matches = [rx.search(content) for rx in rule['compiled']]
                hit = all(matches) if rule.get('require_all') else any(matches)
                if not hit:
                    continue
                first = next((m for m in matches if m), None)
                findings.append({
                    'rule': rule['name'],
                    'severity': rule['severity'],
                    'file': file_path,
                    'matched': (first.group(0) if first else '')[:cls.SNIPPET_CAP],
                    'description': rule['description'],
                    'source': 'yara',
                })
        return findings

    # ------------------------------------------------------------------ #
    # Rules management (builtin listing + custom .yar upload/delete)
    # ------------------------------------------------------------------ #
    _SAFE_NAME = re.compile(r'^[A-Za-z0-9._-]+$')

    @classmethod
    def list_rules(cls) -> Dict:
        builtin = [{'name': r['name'], 'severity': r['severity'],
                    'description': r['description']} for r in BUILTIN_RULES]
        custom = []
        try:
            if os.path.isdir(cls.CUSTOM_RULES_DIR):
                for name in sorted(os.listdir(cls.CUSTOM_RULES_DIR)):
                    if not name.endswith('.yar'):
                        continue
                    full = os.path.join(cls.CUSTOM_RULES_DIR, name)
                    try:
                        stat = os.stat(full)
                        custom.append({'name': name, 'size': stat.st_size})
                    except OSError:
                        continue
        except OSError:
            pass
        return {
            'success': True,
            'engine': cls.engine(),
            'builtin': builtin,
            'builtin_count': len(builtin),
            'custom': custom,
            'custom_rules_dir': cls.CUSTOM_RULES_DIR,
            # Fallback engine only evaluates the curated set; real yara
            # additionally loads custom .yar files.
            'custom_rules_active': cls.yara_available(),
        }

    @classmethod
    def save_custom_rule(cls, filename: str, content: str) -> Dict:
        filename = (filename or '').strip()
        if not filename or not cls._SAFE_NAME.match(filename):
            return {'success': False, 'error': 'Invalid rule filename'}
        if not filename.endswith('.yar'):
            return {'success': False, 'error': 'Only .yar rule files are accepted'}
        if not content or not content.strip():
            return {'success': False, 'error': 'Rule content is empty'}
        if len(content.encode('utf-8', errors='ignore')) > cls.MAX_CUSTOM_RULE_SIZE:
            return {'success': False,
                    'error': f'Rule file exceeds {cls.MAX_CUSTOM_RULE_SIZE // 1024} KB limit'}
        if 'rule ' not in content:
            return {'success': False, 'error': 'Content does not look like a YARA rule file'}
        try:
            os.makedirs(cls.CUSTOM_RULES_DIR, exist_ok=True)
            full = os.path.join(cls.CUSTOM_RULES_DIR, filename)
            with open(full, 'w', encoding='utf-8') as fh:
                fh.write(content)
            return {'success': True, 'message': f'Rule file {filename} saved',
                    'custom_rules_active': cls.yara_available()}
        except OSError as exc:
            return {'success': False, 'error': str(exc)}

    @classmethod
    def delete_custom_rule(cls, filename: str) -> Dict:
        filename = (filename or '').strip()
        if not filename or not cls._SAFE_NAME.match(filename) or not filename.endswith('.yar'):
            return {'success': False, 'error': 'Invalid rule filename'}
        full = os.path.abspath(os.path.join(cls.CUSTOM_RULES_DIR, filename))
        if not full.startswith(os.path.abspath(cls.CUSTOM_RULES_DIR)):
            return {'success': False, 'error': 'Invalid rule path'}
        if not os.path.exists(full):
            return {'success': False, 'error': 'Rule file not found'}
        try:
            os.remove(full)
            return {'success': True, 'message': f'Rule file {filename} deleted'}
        except OSError as exc:
            return {'success': False, 'error': str(exc)}
