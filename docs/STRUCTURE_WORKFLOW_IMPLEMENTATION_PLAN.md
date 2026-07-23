# Project Structure Workflow Implementation Plan

## Goal

Provide one traceable project workflow from an experimental receptor structure to tool-ready
inputs:

1. Import an RCSB PDB entry or register a project-owned uploaded PDB.
2. Validate and preserve the receptor in project-controlled storage.
3. Record source metadata and SHA-256.
4. Run P2Rank against the selected project structure.
5. Persist every pocket and require explicit pocket selection.
6. Prepare a receptor PDBQT from the same receptor coordinate set.
7. Expose a readiness bundle consumed by TargetDiff, AutoGrow4, Vina and GNINA.

Protein structure prediction from sequence is out of scope. There is no AlphaFold or local
Boltz fallback. P2Rank remains a computational pocket predictor.

## Public Interfaces

The implementation is tested through these seams:

- Project structure HTTP interface: collect, list, activate and inspect structures.
- Structure readiness HTTP interface: run P2Rank, prepare PDBQT, select a pocket and inspect
  readiness.
- Strategy validation interface: accept only a persisted binding site owned by the project and
  produced from its active structure.

## Domain Model

### Project

Add nullable `active_structure_id` and `active_binding_site_id`. These are mutable workspace
selections only. Every execution round still freezes its selected IDs and artifact hashes.

### ProjectStructure

A project-scoped, immutable source record:

- `structure_id`
- `project_id`, `target_id`
- `source`: `rcsb_pdb` or `upload`
- `source_identifier`: PDB ID or uploaded file ID
- `source_url`, `assembly_id`
- `source_file_id`: project-owned `UploadedFile`
- `status`: `collected`, `validated`, `pocket_predicted`, `ready`, `failed`
- `metadata_json`: experimental metadata, PDB summary, warnings and provenance

The source file is never overwritten. Derived artifacts are stored under the structure directory.

### BindingSite

Every newly predicted project site must carry `structure_id`. A site may be selected only when
its `project_id` and `structure_id` match the project selections and its pocket/grid artifacts are
complete.

## Controlled Storage

```text
{storage_root}/{project_id}/structures/{structure_id}/
  original/{source}.pdb
  prepared/receptor.pdbqt
{storage_root}/{project_id}/p2rank_runs/{run_id}/...
```

The database records SHA-256 and size for every collected or produced file. Remote content is
written to a temporary file, validated, and atomically moved into place.

## RCSB Rules

- Accept only canonical four-character PDB IDs.
- Construct RCSB URLs server-side; never fetch a user-provided arbitrary URL.
- Fetch entry metadata from the RCSB Data API.
- Download the experimental PDB from `files.rcsb.org`.
- Reject empty content, HTML/error content, or structures without protein `ATOM` records.
- Preserve HTTP/source metadata and acquisition time.
- A download failure is explicit and never invokes structure prediction.

## Structure Processing Rules

- P2Rank and receptor PDBQT preparation resolve the same active `ProjectStructure` source.
- Open Babel is a recorded conversion adapter, not an implicit structural-curation policy.
- Commands, versions, warnings and hashes remain auditable.
- P2Rank creates all pockets and never silently selects one.
- User selection is required before a structure is reported ready for structure-conditioned tools.

## Readiness Bundle

The project exposes one deterministic bundle containing:

- `structure_id`
- source receptor artifact and SHA-256
- prepared receptor PDBQT and SHA-256
- selected `binding_site_id`
- pocket PDB and SHA-256
- grid center and size
- per-tool readiness and reason codes

TargetDiff requires the pocket PDB. AutoGrow4, Vina and GNINA require the prepared receptor and
grid. AutoGrow4 additionally requires eligible seed/source compounds.

## Frontend

The project data page gains a receptor workflow with these states:

`source -> collected -> validated -> pockets predicted -> pocket selected -> receptor ready`

It supports PDB-ID import, uploaded-PDB registration, structure history, activation, P2Rank,
pocket comparison, explicit selection, receptor preparation and readiness display. Paths are not
editable in the browser.

## Compatibility

- Existing file upload remains available for documents and ligands.
- Existing `source_file_id` P2Rank and receptor preparation calls remain temporarily supported.
- New UI and new orchestration use `structure_id` exclusively.
- Existing target-level binding sites remain readable but cannot be selected as a project
  structure site without an explicit project structure association.

## Acceptance Criteria

- RCSB import creates a project-owned file, structure record, SHA-256 and active selection.
- Uploaded PDB registration provides the same structure contract.
- Invalid or cross-project structure/site IDs are rejected.
- P2Rank pockets reference the exact structure used as input.
- Receptor PDBQT and selected pocket originate from the same structure.
- No Agent can invent a binding-site ID or rely on automatic fallback selection.
- The frontend can complete the workflow without entering server paths or grid coordinates.
- Focused backend tests, frontend type checking and the repository test suite pass.
