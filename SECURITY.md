# Security Policy

## Reporting a Vulnerability

If you believe you have found a security issue in interlocks, open a private security advisory at <https://github.com/0xjgv/interlocks/security/advisories/new>. Do not file a public issue or PR for security-sensitive findings.

We aim to acknowledge receipt within five business days. There is no embargo policy: once a fix is ready, we ship and credit the reporter unless they prefer otherwise.

## Threat Model

interlocks is a local CLI that orchestrates third-party quality tools (`ruff`, `basedpyright`, `pytest`, `coverage.py`, `mutmut`, `deptry`, `import-linter`, `pip-audit`, `lizard`). Its threat model is bounded by what a developer would already trust running on their workstation or in their CI runner.

### Never leave the machine

By construction, interlocks does not transmit any of the following anywhere:

- Source code, file contents, or local variables
- Environment variables or `sys.argv` values
- Hostnames or usernames (paths are scrubbed to `~/...` or project-relative before any rendering)
- Credentials, tokens, or any value the user has not explicitly chosen to put in a URL/issue body
- Telemetry, analytics events, or anonymized "metrics" of any kind

There is **no opt-out toggle that enables background network egress** — interlocks itself never opens a network connection. The only network actor that ever sees a crash payload is the user's browser, after the user confirms the crash-report prompt and reviews the pre-filled GitHub issue.

### Always OK to do locally

- Read project files under the configured `src_dir` and `test_dir`
- Spawn the third-party quality tools listed above as subprocesses
- Read and write the cache at `$XDG_CACHE_HOME/interlocks/` (or `~/.cache/interlocks/` on macOS/Linux)
- Open a URL in the user's default browser via `webbrowser.open` (best-effort; failures are swallowed)

### Crash reporting specifics

Crash reports are user-confirmed, not automated:

1. The boundary classifier in `interlocks/crash/boundary.py` catches only interlocks-internal exceptions (frames whose `co_filename` is inside the installed `interlocks/` package). User errors like `InterlockUserError` and external tool failures never reach the capture path.
2. The payload, defined in `interlocks/crash/payload.py`, is built from a fixed allowlist: `interlocks_version`, `python_version`, `platform_system`, `platform_machine`, `subcommand`, `exception_type`, `frames`, `timestamp_utc`, `ci`, `fingerprint`.
3. Interactive terminals ask `Report this crash to the interlocks maintainers? Y/n`. Non-interactive runs skip reporting and keep the local payload only.
4. The transport in `interlocks/crash/transport.py` builds a `https://github.com/.../issues/new?title=...&body=...&labels=crash-report` URL, prints it to stderr, and *attempts* `webbrowser.open` only after the user accepts. The only HTTP client that ever runs is the user's browser.
5. Local files live at `~/.cache/interlocks/crashes/<fingerprint>.json` (mode 0600 in mode 0700 dir). A `dedup.json` window of 30 days prevents repeat URL prompts for the same fingerprint.

### Explicit non-goals

interlocks **will not**:

- Ship credentials, API keys, install tokens, or sentry/posthog DSNs in the package
- Add an SDK that captures locals, `sys.argv`, environment variables, or function arguments by default
- Add a "diagnostic mode" that POSTs to `interlocks.dev/...` or any other domain
- Auto-open issues, auto-PR, or otherwise contact GitHub on the user's behalf — only the user's browser does, only after the user clicks
- Recommend or default to a third-party error-reporting SDK; the trade-off has been considered and recorded in `STRATEGY.md`

## Cryptographic Material

interlocks ships no keys or certificates. The fingerprint hash (`SHA-256`, truncated to 16 hex chars in `interlocks/crash/fingerprint.py`) is non-cryptographic in intent — it exists to deduplicate identical crash signatures, not to authenticate anything.

## Supply Chain

Dependencies are pinned in `pyproject.toml` and locked in `uv.lock`. New transitive dependencies are visible in PR diffs of `uv.lock`. CI runs `pip-audit` (`interlocks audit`) on every PR.
