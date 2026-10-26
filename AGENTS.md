# Department Agent

Created: 2026-10-27

This is the independently curated public-source repository for the integrated clinical, knowledge and prescription workbench. It must remain separate from live deployments and private backups.

- Preserve all three modules and the latest Chinese UI. Use synthetic fixtures for public demonstrations and tests.
- Never commit patient data, derived private HTML/CSV, full copyrighted literature, translation corpora, credentials, runtime databases, local receipts, model weights or personal filesystem paths.
- Keep human review, source attribution, versioned persistence, local-only defaults and module boundaries intact.
- Runtime artifacts belong in ignored `work/` directories. Use a real Git checkout for the prescription ignore guard.
- Python 3.11 or newer; use `uv` for dependency installation. Tests and launch commands are defined in the root README and pyproject.toml.
- Scripts and configuration use ASCII text. Product UI is simplified Chinese; technical documentation and code comments are English.
- Preserve upstream licenses and third-party notices. Verify the Git index and run the release check before publishing.
- Do not modify or stop the original workspaces, backups or existing local services.

No general project instruction or memory template was present; this minimal project-specific file was created directly.
