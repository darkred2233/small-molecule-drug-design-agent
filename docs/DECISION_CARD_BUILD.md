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
- `rule_filter_results`
- `conformer_results`
- `docking_results`
- `admet_results`
- `synthesis_routes`
- `rankings`

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
DB:RULE_FILTER:{molecule_id}
DB:DOCKING:{molecule_id}
DB:ADMET:{molecule_id}
DB:SYNTHESIS:{molecule_id}
DB:RANK:{molecule_id}
```

This means the card can be traced to local database records, but it is not yet linked to RAG evidence chunks.

## Decision Logic

### `structure_validated`

Decision:

```text
advance_to_rule_filter
```

The card says the molecule can proceed to basic rule filtering, while clearly warning that RDKit or Datamol validation is still pending.

### `passed_filter`

Decision:

```text
advance_to_candidate_assessment
```

The card says the molecule can proceed to integrated conformer, docking, ADMET, synthesis, and ranking checks.

### `failed_filter`

Decision:

```text
reject_by_rule_filter
```

The card reports rule-filter blockers and recommends scaffold correction or regeneration before downstream assessment.

### `candidate_assessed`

Decision:

```text
advance_ranked_candidate
watch_ranked_candidate
reserve_ranked_candidate
deprioritize_ranked_candidate
reject_ranked_candidate
```

The exact card follows the ranking record or ranking label. It includes downstream evidence from rule filtering, conformer generation, docking, ADMET, synthesis, and ranking when those records exist.

### `failed_assessment` and `rejected_by_ranking`

Decision:

```text
reject_after_assessment
reject_ranked_candidate
```

The card reports downstream blockers instead of asking for structure validation again.

### `invalid_structure`

Decision:

```text
reject_for_structure
```

The card says the molecule should be fixed or removed before downstream filtering and ranking.

### Other Statuses Without Validation Evidence

Decision:

```text
needs_structure_validation
```

The card asks the user or pipeline to run molecule validation first.

If a molecule has validation/property evidence but a non-canonical status, the generator emits `advance_to_rule_filter` with a workflow-reconciliation warning instead of claiming that no validation record exists.

## Idempotency

Repeated generation updates the existing trace and card for the same:

```text
project_id + molecule_id + molecule_validation_decision
```

It does not create duplicate rows.

## Current Limitations

- No RAG evidence is attached yet.
- Confidence values are conservative placeholders based on workflow stage, not calibrated scientific probabilities.
- Cards are generated from current database status, so they should be regenerated after validation, filtering, docking, ADMET, or ranking changes.
- Stale early labels such as `requires_structure_validation` are ignored once validation or property evidence exists.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```
