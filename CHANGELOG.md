# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-02

### Added

- Pipeline orchestrator with stage-based execution and verify-owns-transitions design
- Sentry intake source for importing issues as pipeline work items
- Multi-reviewer code review stage with configurable consensus modes
- Worktree isolation for code-modifying stages (implement, prove)
- CLI interface with commands: `run`, `status`, `prompt`, `push`, `archive`, `init`
- Stage resolution system with source-specific and project-level overrides
- Configuration merging: built-in defaults < user config < project config
- Extending guide for adding custom stages and sources
