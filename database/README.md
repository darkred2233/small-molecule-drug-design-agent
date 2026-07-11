# Database Artifacts

This directory stores portable relational database artifacts.

| File | Purpose |
|---|---|
| `medagent_seed.sqlite` | SQLite seed snapshot with schema plus built-in MVP target-drug data. |
| `chembl22_sa2.db` | CReM fragment replacement database used by the molecule generator. This file is large and should move with the project when migrating environments. |

Regenerate the snapshot from source seed data:

```powershell
$env:PYTHONPATH='src'
python -m medagent.cli db snapshot --output database/medagent_seed.sqlite
```
