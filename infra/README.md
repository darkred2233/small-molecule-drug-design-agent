# Infrastructure

This directory is the final project-level home for deployment assets.

Current compatibility layout:

- `docker-compose.yml` still lives at the repository root so existing
  `docker compose up -d` commands keep working.
- `docker/` still lives at the repository root and contains the scientific
  tool Dockerfiles.
- `docs/postgres-init.sql` still contains the current PostgreSQL init script.

The subdirectories here document the target split and provide stable landing
places for future moves:

- `docker/`: scientific tool and app Dockerfiles.
- `postgres/`: PostgreSQL and pgvector initialization.
- `minio/`: bucket initialization and object storage policy.
- `prefect/`: future workflow runner configuration.

