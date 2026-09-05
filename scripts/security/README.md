# Security scan exceptions

Security Scan runs weekly and on relevant changes. Bandit scans backend and
builtin-extension Python sources; the full report is uploaded even if the gate
fails. HIGH severity / HIGH confidence findings block CI. Lower-level findings
remain visible in the report.

Run the same gate locally with Python 3.11 and Bandit 1.9.3:

```sh
python -m unittest discover -s scripts/security -p 'test_*.py'
bandit -r backend/app builtin-extensions -f json -o bandit-report.json --exit-zero
python scripts/check-bandit-report.py bandit-report.json
```

The gate evaluates git-tracked source files; locally installed copies of
extensions are excluded because their canonical source is in `builtin-extensions`.
The exception file accepts two specific findings in the existing admin-only FTP
connection probe. FTP still transmits credentials without encryption; this is a
documented compatibility limitation, not an assertion that the protocol is safe.

Each exception binds its rule to one function's AST fingerprint and one finding.
Changing the function, adding another finding, or fixing an accepted finding
requires reviewing and updating/removing the entry. Do not regenerate exceptions
from an entire report or suppress a Bandit category. Review the function, its
callers and guards, record the justification/date, and update only that entry.
