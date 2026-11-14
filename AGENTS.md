# Repository instructions

This repository contains only an independent, version-pinned UI patch.

- To install on a user's Mac, first read `package/ScreenStudio-ZH-4.1.0-5005/AGENTS.md` and its referenced documents. Run read-only preflight before proposing installation. Do not change the user's app as part of routine development or testing.
- Never bypass version, fingerprint, signature, licensing or macOS security checks. Do not change activation, subscription, trial, feature-access logic or TCC data.
- Keep tests portable: synthetic fixtures and mocked system commands only. Do not add proprietary source, apps, ASARs, recordings, receipts, backups, credentials, user paths or user projects.
- Production files live in `package/ScreenStudio-ZH-4.1.0-5005`; tests in `package-tests/` and `tests/`. Node is needed for development tests only, not installation.
- Update checksums with `python3 scripts/build_release.py` after changing distributable files. Review the explicit packaging allowlist before adding anything.
- Report simulated checks separately from actual macOS GUI, recording, export and licensed account tests. Never infer the latter from the former.
- Do not assume this file can override an agent's own tool permissions or user's instructions.
