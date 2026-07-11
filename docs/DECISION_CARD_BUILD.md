# ReasoningTrace and DecisionCard Build

Date: 2026-07-09

This stage adds user-visible, database-backed decision records for candidate molecules. It does not expose hidden model reasoning and does not claim RAG, docking, ADMET, or experimental evidence.

## What Was Added

- `reasoning_traces` ORM table
- `decision_cards` ORM table
- `POST /projects/{project_id}/decision-cards/generate`
- `GET /projects/{project_id}/reasoning-traces`
- `GET /projects/{project_id}/decision-cards`
- `GET /projects/{project_id}/molecules/{molecule_id}/decision-cards`

## Current Generator

The current generator is deterministic and evidence-conservative. It reads:

- `molecules`
- `molecule_properties`

For each molecule it creates or updates one reasoning trace and one decision card with:

- claim
- supporting factors
- opposing or risk factors
- uncertainty
- next steps
- confidence
- database provenance

The `evidence_ids` field currently stores database provenance references such as:

```text
DB:MOL:{molecule_id}
DB:PROP:{molecule_id}
```

This means the card can be traced to local database records, but it is not yet linked to RAG evidence chunks.

## Decision Logic

### `structure_validated`

Decision:

```text
advance_to_rule_filter
```

The card says the molecule can proceed to basic rule filtering, while clearly warning that RDKit or Datamol validation is still pending.

### `invalid_structure`

Decision:

```text
reject_for_structure
```

The card says the molecule should be fixed or removed before downstream filtering and ranking.

### Other Statuses

Decision:

```text
needs_structure_validation
```

The card asks the user or pipeline to run molecule validation first.

## Idempotency

Repeated generation updates the existing trace and card for the same:

```text
project_id + molecule_id + molecule_validation_decision
```

It does not create duplicate rows.

## Current Limitations

- No RAG evidence is attached yet.
- No RDKit/Datamol descriptors are calculated yet.
- Confidence values are conservative placeholders based on workflow stage, not calibrated scientific probabilities.
- Cards are generated from current database status, so they should be regenerated after validation, filtering, docking, ADMET, or ranking changes.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```
