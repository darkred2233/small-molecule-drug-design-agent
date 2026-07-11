# Runtime Configs

This directory is the final project-level home for non-secret runtime
configuration. The legacy `config.yaml` at the repository root is still kept
as a compatibility entry point while code is migrated incrementally.

Planned files:

- `models.yaml`: model routing and default model names.
- `scoring.yaml`: multi-objective ranking weights and penalties.
- `filters.yaml`: molecule filtering thresholds.
- `tools.yaml`: external scientific tool paths, images, and timeouts.

Do not put API keys or credentials here. Use `.env` with the `MEDAGENT_`
environment variable prefix for secrets.

