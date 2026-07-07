# Database Artifacts

This directory stores portable relational database artifacts.

| File | Purpose |
|---|---|
| `medagent_seed.sqlite` | SQLite seed snapshot with schema plus built-in MVP target-drug data. |

Regenerate the snapshot from source seed data:

```powershell
$env:PYTHONPATH='src'
python -m medagent.cli db snapshot --output database/medagent_seed.sqlite
```
