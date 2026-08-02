# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Forger, please report it privately by emailing **przemyslaw.kukulski@gmail.com**.

Do **not** open a public GitHub issue for security vulnerabilities.

You should receive a response within 48 hours acknowledging receipt. A fix will be developed privately and released as a patch version.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Security Considerations

### Custom verify modules

Forger loads and executes custom `verify.py` modules from project `.forger/stages/` directories using `importlib`. These modules run with the full privileges of the Python interpreter. Only use verify modules from trusted sources.

### Runner commands

Forger invokes runner commands (e.g., `claude -p ...`) as subprocesses. Command templates are defined in configuration files. Shell metacharacters in model names, tool names, and environment variable values are validated and rejected to prevent injection.

### GitHub operations

The `push` stage uses the `gh` CLI to create issues and PRs. It requires `gh auth` to be configured. Forger filters token lines from `gh auth status` output, but treats `gh` CLI output format as unstable.
