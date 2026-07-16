import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import metadata, util
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import AgentRun, Molecule, Project, SeedLigand, TargetDrugLibrary
from medagent.services.ids import new_id
from medagent.services.molecule_import import is_lightly_valid_smiles, normalize_smiles


GENERATOR_AGENT_NAME = "generator_agent"
GENERATION_STRATEGIES = ("reinvent4", "crem", "autogrow4")
TOOLCHAIN_MODE = "rdkit_datamol_generation_toolchain"
TARGET_FALLBACK_SEED_SMILES = {
    "TGT-EGFR": [
        "COc1cc(N(C)CCN(C)C)c(NC(=O)C=C)c2ncnc(Nc3ccc(F)c(Cl)c3)c12",
    ],
    "default": ["c1ccccc1"],
}


@dataclass(frozen=True)
class GenerationCandidate:
    smiles: str
    strategy: str
    seed_smiles: str
    rationale: str
    labels: tuple[str, ...] = ()
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationBatch:
    candidates: list[GenerationCandidate]
    adapter_mode: str
    tool_status: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    candidate_source_counts: dict[str, int] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyGenerationSummary:
    requested_count: int = 0
    proposed_count: int = 0
    stored_count: int = 0
    duplicate_count: int = 0
    invalid_count: int = 0
    seed_count: int = 0
    molecule_ids: list[str] = field(default_factory=list)
    adapter_mode: str = "not_run"
    tool_status: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    candidate_source_counts: dict[str, int] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_count": self.requested_count,
            "proposed_count": self.proposed_count,
            "stored_count": self.stored_count,
            "duplicate_count": self.duplicate_count,
            "invalid_count": self.invalid_count,
            "seed_count": self.seed_count,
            "molecule_ids": self.molecule_ids,
            "adapter_mode": self.adapter_mode,
            "tool_status": self.tool_status,
            "warnings": self.warnings,
            "candidate_source_counts": self.candidate_source_counts,
            "provenance": self.provenance,
        }


@dataclass
class MoleculeGenerationSummary:
    agent_run_id: str
    requested_count: int
    generated_count: int = 0
    stored_count: int = 0
    duplicate_count: int = 0
    invalid_count: int = 0
    seed_count: int = 0
    failed_reason_summary: dict[str, int] = field(default_factory=dict)
    molecule_ids: list[str] = field(default_factory=list)
    strategy_summaries: dict[str, StrategyGenerationSummary] = field(default_factory=dict)
    adapter_mode: str = TOOLCHAIN_MODE
    tool_status: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_run_id": self.agent_run_id,
            "requested_count": self.requested_count,
            "generated_count": self.generated_count,
            "stored_count": self.stored_count,
            "duplicate_count": self.duplicate_count,
            "invalid_count": self.invalid_count,
            "seed_count": self.seed_count,
            "failed_reason_summary": self.failed_reason_summary,
            "molecule_ids": self.molecule_ids,
            "strategy_summaries": {
                strategy: summary.as_dict()
                for strategy, summary in self.strategy_summaries.items()
            },
            "adapter_mode": self.adapter_mode,
            "tool_status": self.tool_status,
            "warnings": self.warnings,
        }


class RdkitScoredReinvent4Strategy:
    name = "reinvent4"

    def generate(
        self,
        seeds: list[str],
        requested_count: int,
        constraints: dict[str, Any],
    ) -> GenerationBatch:
        from medagent.services.reinvent4_adapter import (
            Reinvent4Request,
            run_reinvent4_generation,
        )

        tool_status = generation_tool_status()
        reinvent4_status = tool_status["reinvent4"]
        fallback_warnings: list[str] = []

        # Try real REINVENT4 if available
        if reinvent4_status.get("available"):
            try:
                import tempfile
                with tempfile.TemporaryDirectory(prefix="reinvent4_gen_") as tmp_dir:
                    request = Reinvent4Request(
                        seed_smiles=seeds[:5],
                        output_dir=tmp_dir,
                        num_molecules=requested_count,
                        timeout_seconds=int(
                            reinvent4_status.get("configured_timeout_seconds") or 600
                        ),
                    )
                    result = run_reinvent4_generation(request, reinvent4_status)
                    fallback_warnings.extend(result.warnings)

                    if result.success and result.generated_smiles:
                        candidates = _external_generation_candidates(
                            strategy=self.name,
                            source="reinvent4_external_prior_sampling",
                            generated_smiles=result.generated_smiles,
                            scores=result.scores,
                            seeds=seeds,
                            constraints=constraints,
                            rationale="REINVENT4 prior-model sampling",
                            labels=result.labels,
                            adapter_mode=result.adapter_mode,
                            provenance=result.provenance,
                        )
                        if candidates:
                            return GenerationBatch(
                                candidates=candidates[:requested_count],
                                adapter_mode=result.adapter_mode,
                                tool_status=_strategy_tool_status(
                                    tool_status, ["rdkit", "datamol", "reinvent4"]
                                ),
                                warnings=list(dict.fromkeys(result.warnings)),
                                candidate_source_counts=_candidate_source_counts(candidates),
                                provenance=result.provenance,
                            )
                        fallback_warnings.append(
                            "reinvent4_external_candidates_rejected_by_generation_constraints"
                        )
                    else:
                        fallback_warnings.append(
                            f"reinvent4_external_adapter_failed:{result.adapter_mode}"
                        )
            except Exception as exc:
                fallback_warnings.append(
                    f"reinvent4_external_adapter_exception:{type(exc).__name__}"
                )
        else:
            fallback_warnings.append(
                str(reinvent4_status.get("warning") or "reinvent4_external_adapter_not_installed")
            )

        # RDKit surrogate fallback
        labels = _candidate_tool_labels(
            tool_status,
            external_pending_label="external_reinvent4_pending",
        )
        candidates = _generate_from_libraries(
            strategy=self.name,
            seeds=seeds,
            requested_count=requested_count,
            constraints=constraints,
            aliphatic_library=_reinvent4_aliphatic_library(),
            aromatic_library=_reinvent4_aromatic_library(),
            rationale="REINVENT4-style optimization scored with RDKit/Datamol",
            source_label="rdkit_scored_reinvent4_surrogate",
            labels=labels,
        )
        return GenerationBatch(
            candidates=candidates,
            adapter_mode="rdkit_datamol_scored_reinvent4_surrogate",
            tool_status=_strategy_tool_status(tool_status, ["rdkit", "datamol", "reinvent4"]),
            warnings=list(
                dict.fromkeys(
                    fallback_warnings
                    + (
                        ["reinvent4_detected_but_rdkit_surrogate_adapter_used"]
                        if tool_status["reinvent4"]["available"]
                        else []
                    )
                )
            ),
            candidate_source_counts=_candidate_source_counts(candidates),
            provenance={
                "execution_mode": "surrogate_fallback",
                "external_tool_status": reinvent4_status,
                "fallback_toolchain": ["rdkit", "datamol"],
            },
        )


class CremFragmentStrategy:
    name = "crem"

    def generate(
        self,
        seeds: list[str],
        requested_count: int,
        constraints: dict[str, Any],
    ) -> GenerationBatch:
        tool_status = generation_tool_status()
        candidates: list[GenerationCandidate] = []
        warnings: list[str] = []
        adapter_mode = "rdkit_datamol_crem_fragment_surrogate"

        if tool_status["crem"]["database_available"]:
            try:
                candidates = _generate_with_crem_database(
                    seeds=seeds,
                    requested_count=requested_count,
                    constraints=constraints,
                    db_path=tool_status["crem"]["database_path"],
                )
                adapter_mode = "crem_fragment_database"
            except Exception as exc:  # pragma: no cover - depends on external CReM DB.
                warnings.append(f"crem_database_generation_failed:{type(exc).__name__}")

        crem_candidate_count = len(candidates)
        if len(candidates) < requested_count:
            if not tool_status["crem"]["database_available"]:
                warnings.append("crem_fragment_database_not_configured")
            elif crem_candidate_count == 0:
                warnings.append("crem_database_returned_no_candidates")
            labels = _candidate_tool_labels(
                tool_status,
                external_pending_label="crem_fragment_database_pending",
            )
            candidates.extend(
                _generate_from_libraries(
                    strategy=self.name,
                    seeds=seeds,
                    requested_count=requested_count - len(candidates),
                    constraints=constraints,
                    aliphatic_library=_crem_aliphatic_library(),
                    aromatic_library=_crem_aromatic_library(),
                    rationale="CReM-style fragment replacement scored with RDKit/Datamol",
                    source_label="rdkit_fragment_replacement_surrogate",
                    labels=labels,
                    excluded_smiles={candidate.smiles for candidate in candidates},
                )
            )
            adapter_mode = (
                "crem_fragment_database_with_rdkit_surrogate_fill"
                if crem_candidate_count
                else "rdkit_datamol_crem_fragment_surrogate"
            )

        return GenerationBatch(
            candidates=candidates[:requested_count],
            adapter_mode=adapter_mode,
            tool_status=_strategy_tool_status(tool_status, ["rdkit", "datamol", "crem"]),
            warnings=warnings,
            candidate_source_counts=_candidate_source_counts(candidates),
        )


class RdkitGrowLinkAutoGrow4Strategy:
    name = "autogrow4"

    def generate(
        self,
        seeds: list[str],
        requested_count: int,
        constraints: dict[str, Any],
    ) -> GenerationBatch:
        from medagent.services.autogrow4_adapter import (
            AutoGrow4Request,
            run_autogrow4_generation,
        )

        tool_status = generation_tool_status()
        autogrow4_status = tool_status["autogrow4"]
        fallback_warnings: list[str] = []

        # Try real AutoGrow4 if available
        if autogrow4_status.get("available"):
            try:
                import tempfile
                from pathlib import Path

                # Find a receptor file for docking-guided generation
                receptor_file = constraints.get("receptor_file")
                if receptor_file and Path(receptor_file).exists():
                    with tempfile.TemporaryDirectory(prefix="autogrow4_gen_") as tmp_dir:
                        request = AutoGrow4Request(
                            seed_smiles=seeds[:5],
                            receptor_file=receptor_file,
                            output_dir=tmp_dir,
                            num_generations=5,
                            population_size=requested_count,
                            constraints=constraints,
                            timeout_seconds=int(
                                autogrow4_status.get("configured_timeout_seconds") or 1200
                            ),
                        )
                        result = run_autogrow4_generation(request, autogrow4_status)
                        fallback_warnings.extend(result.warnings)

                        if result.success and result.generated_smiles:
                            candidates = _external_generation_candidates(
                                strategy=self.name,
                                source="autogrow4_external_docking_guided",
                                generated_smiles=result.generated_smiles,
                                scores=result.scores,
                                seeds=seeds,
                                constraints=constraints,
                                rationale="AutoGrow4 docking-guided genetic optimization",
                                labels=result.labels,
                                adapter_mode=result.adapter_mode,
                                provenance=result.provenance,
                            )
                            if candidates:
                                return GenerationBatch(
                                    candidates=candidates[:requested_count],
                                    adapter_mode=result.adapter_mode,
                                    tool_status=_strategy_tool_status(
                                        tool_status, ["rdkit", "datamol", "autogrow4"]
                                    ),
                                    warnings=list(dict.fromkeys(result.warnings)),
                                    candidate_source_counts=_candidate_source_counts(candidates),
                                    provenance=result.provenance,
                                )
                            fallback_warnings.append(
                                "autogrow4_external_candidates_rejected_by_generation_constraints"
                            )
                        else:
                            fallback_warnings.append(
                                f"autogrow4_external_adapter_failed:{result.adapter_mode}"
                            )
                elif receptor_file:
                    fallback_warnings.append("autogrow4_receptor_file_not_found")
                else:
                    fallback_warnings.append("autogrow4_receptor_file_not_configured")
            except Exception as exc:
                fallback_warnings.append(
                    f"autogrow4_external_adapter_exception:{type(exc).__name__}"
                )
        else:
            fallback_warnings.append(
                str(autogrow4_status.get("warning") or "autogrow4_external_adapter_not_installed")
            )

        # RDKit surrogate fallback
        labels = _candidate_tool_labels(
            tool_status,
            external_pending_label="external_autogrow4_pending",
        )
        candidates = _generate_from_libraries(
            strategy=self.name,
            seeds=seeds,
            requested_count=requested_count,
            constraints=constraints,
            aliphatic_library=_autogrow4_aliphatic_library(),
            aromatic_library=_autogrow4_aromatic_library(),
            rationale="AutoGrow4-style grow/link enumeration scored with RDKit/Datamol",
            source_label="rdkit_grow_link_autogrow4_surrogate",
            labels=labels,
        )
        return GenerationBatch(
            candidates=candidates,
            adapter_mode="rdkit_datamol_grow_link_autogrow4_surrogate",
            tool_status=_strategy_tool_status(tool_status, ["rdkit", "datamol", "autogrow4"]),
            warnings=list(
                dict.fromkeys(
                    fallback_warnings
                    + (
                        ["autogrow4_detected_but_rdkit_surrogate_adapter_used"]
                        if tool_status["autogrow4"]["available"]
                        else []
                    )
                )
            ),
            candidate_source_counts=_candidate_source_counts(candidates),
            provenance={
                "execution_mode": "surrogate_fallback",
                "external_tool_status": autogrow4_status,
                "fallback_toolchain": ["rdkit", "datamol"],
            },
        )


STRATEGY_ADAPTERS = {
    RdkitScoredReinvent4Strategy.name: RdkitScoredReinvent4Strategy(),
    CremFragmentStrategy.name: CremFragmentStrategy(),
    RdkitGrowLinkAutoGrow4Strategy.name: RdkitGrowLinkAutoGrow4Strategy(),
}


def generate_project_molecules(
    db: Session,
    project: Project,
    generation_size: int,
    strategies: list[str] | None = None,
    strategy_counts: dict[str, int] | None = None,
    constraints: dict[str, Any] | None = None,
    include_target_library_seeds: bool = True,
    agent_run_name: str = GENERATOR_AGENT_NAME,
) -> dict[str, Any]:
    selected_strategies = _normalize_strategies(strategies)
    requested_by_strategy = _resolve_strategy_counts(
        generation_size,
        selected_strategies,
        strategy_counts,
    )
    selected_strategies = [
        strategy for strategy in selected_strategies if requested_by_strategy.get(strategy, 0) > 0
    ]
    generation_size = sum(requested_by_strategy[strategy] for strategy in selected_strategies)
    normalized_constraints = constraints or {}
    tool_status = generation_tool_status()
    seeds = collect_generation_seed_smiles(
        db,
        project,
        include_target_library_seeds=include_target_library_seeds,
    )
    if not seeds:
        raise ValueError("generation_requires_at_least_one_seed_ligand")

    agent_run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        agent_name=agent_run_name,
        model_name="tool-adapter",
        status="running",
        input_json={
            "project_id": project.project_id,
            "generation_size": generation_size,
            "strategies": selected_strategies,
            "strategy_counts": requested_by_strategy,
            "constraints": normalized_constraints,
            "seed_count": len(seeds),
            "include_target_library_seeds": include_target_library_seeds,
            "tool_status": tool_status,
        },
        output_json={},
    )
    db.add(agent_run)
    db.flush()

    summary = MoleculeGenerationSummary(
        agent_run_id=agent_run.agent_run_id,
        requested_count=generation_size,
        seed_count=len(seeds),
        strategy_summaries={
            strategy: StrategyGenerationSummary(
                requested_count=requested_by_strategy[strategy],
                seed_count=len(seeds),
            )
            for strategy in selected_strategies
        },
        tool_status=tool_status,
    )
    existing_smiles = {
        _standardize_or_normalize_smiles(row[0])
        for row in db.query(Molecule.smiles).filter_by(project_id=project.project_id).all()
    }
    seen_in_batch: set[str] = set()

    for strategy_name in selected_strategies:
        strategy_summary = summary.strategy_summaries[strategy_name]
        batch = STRATEGY_ADAPTERS[strategy_name].generate(
            seeds=seeds,
            requested_count=requested_by_strategy[strategy_name],
            constraints=normalized_constraints,
        )
        strategy_summary.adapter_mode = batch.adapter_mode
        strategy_summary.tool_status = batch.tool_status
        strategy_summary.warnings = batch.warnings
        strategy_summary.candidate_source_counts = batch.candidate_source_counts
        strategy_summary.provenance = batch.provenance
        strategy_summary.proposed_count = len(batch.candidates)
        summary.generated_count += len(batch.candidates)
        summary.warnings.extend(
            warning for warning in batch.warnings if warning not in summary.warnings
        )

        for candidate in batch.candidates:
            normalized_smiles = _standardize_or_normalize_smiles(candidate.smiles)
            if not is_lightly_valid_smiles(normalized_smiles):
                _count_failure(summary, strategy_summary, "invalid_smiles")
                continue
            if normalized_smiles in existing_smiles or normalized_smiles in seen_in_batch:
                _count_failure(summary, strategy_summary, "duplicate")
                continue

            molecule = Molecule(
                molecule_id=new_id("MOL"),
                project_id=project.project_id,
                smiles=normalized_smiles,
                inchi_key=None,
                scaffold=None,
                source_agent=f"{GENERATOR_AGENT_NAME}:{strategy_name}",
                status="generated",
                labels=_merge_labels(
                    [
                        "generated",
                        "candidate_generated",
                        "requires_structure_validation",
                        f"generator_strategy_{strategy_name}",
                    ],
                    list(candidate.labels),
                ),
            )
            db.add(molecule)
            db.flush()

            existing_smiles.add(normalized_smiles)
            seen_in_batch.add(normalized_smiles)
            summary.stored_count += 1
            summary.molecule_ids.append(molecule.molecule_id)
            strategy_summary.stored_count += 1
            strategy_summary.molecule_ids.append(molecule.molecule_id)

    agent_run.status = "success"
    agent_run.output_json = {
        **summary.as_dict(),
        "toolchain_mode": TOOLCHAIN_MODE,
        "external_adapters_connected": {
            "reinvent4": bool(tool_status["reinvent4"]["available"]),
            "crem_database": bool(tool_status["crem"]["database_available"]),
            "autogrow4": bool(tool_status["autogrow4"]["available"]),
        },
    }
    project.status = "molecules_generated"
    db.commit()
    return summary.as_dict()


def collect_generation_seed_smiles(
    db: Session,
    project: Project,
    include_target_library_seeds: bool = True,
) -> list[str]:
    seed_smiles = [
        row[0]
        for row in (
            db.query(SeedLigand.smiles)
            .filter_by(project_id=project.project_id)
            .order_by(SeedLigand.id.asc())
            .all()
        )
    ]

    if include_target_library_seeds and project.target_id:
        target_library_smiles = [
            smiles
            for row in (
                db.query(
                    TargetDrugLibrary.smiles,
                    TargetDrugLibrary.canonical_smiles,
                    TargetDrugLibrary.isomeric_smiles,
                )
                .filter_by(target_id=project.target_id)
                .order_by(TargetDrugLibrary.id.asc())
                .all()
            )
            for smiles in row
            if smiles
        ]
        if target_library_smiles:
            seed_smiles.extend(target_library_smiles)
        else:
            seed_smiles.extend(
                TARGET_FALLBACK_SEED_SMILES.get(
                    project.target_id,
                    TARGET_FALLBACK_SEED_SMILES["default"],
                )
            )

    return _unique_valid_smiles(seed_smiles)


def generation_tool_status() -> dict[str, Any]:
    from medagent.services.autogrow4_adapter import autogrow4_tool_status
    from medagent.services.reinvent4_adapter import reinvent4_tool_status

    crem_database_path = _resolve_crem_database_path()
    return {
        "rdkit": _package_status("rdkit"),
        "datamol": _package_status("datamol"),
        "crem": {
            **_package_status("crem"),
            "database_available": crem_database_path is not None,
            "database_path": str(crem_database_path) if crem_database_path else None,
            "database_env_vars": ["MEDAGENT_CREM_DB", "CREM_DB"],
        },
        "reinvent4": reinvent4_tool_status(),
        "autogrow4": autogrow4_tool_status(),
    }


def _generate_with_crem_database(
    seeds: list[str],
    requested_count: int,
    constraints: dict[str, Any],
    db_path: str | None,
) -> list[GenerationCandidate]:
    if requested_count <= 0 or db_path is None:
        return []

    from crem.crem import mutate_mol
    from rdkit import Chem

    raw_smiles: list[str] = []
    for seed_index, seed in enumerate(seeds):
        mol = Chem.MolFromSmiles(seed)
        if mol is None:
            continue
        for generated in mutate_mol(
            mol,
            db_path,
            radius=2,
            max_replacements=max(requested_count * 4, 20),
            return_mol=False,
            ncores=1,
            seed=seed_index,
        ):
            raw_smiles.append(str(generated))
            if len(raw_smiles) >= requested_count * 6:
                break
        if len(raw_smiles) >= requested_count * 6:
            break

    return _select_candidates(
        strategy="crem",
        seed_smiles=seeds,
        raw_smiles=raw_smiles,
        requested_count=requested_count,
        constraints=constraints,
        rationale="CReM fragment replacement from configured fragment database",
        source_label="crem_fragment_database",
        labels=("crem_fragment_database", "rdkit_scored", "datamol_standardized"),
    )


def _generate_from_libraries(
    strategy: str,
    seeds: list[str],
    requested_count: int,
    constraints: dict[str, Any],
    aliphatic_library: list[str],
    aromatic_library: list[str],
    rationale: str,
    source_label: str,
    labels: tuple[str, ...],
    excluded_smiles: set[str] | None = None,
) -> list[GenerationCandidate]:
    if requested_count <= 0:
        return []

    protected_core = bool(constraints.get("keep_core") or constraints.get("protected_motif"))
    raw_smiles: list[tuple[str, str]] = []

    for seed_index, seed in enumerate(seeds):
        library = aromatic_library if protected_core or _looks_aromatic(seed) else aliphatic_library
        for smiles in _rotate(library, seed_index):
            raw_smiles.append((smiles, seed))

    for seed in seeds:
        for smiles in [*aliphatic_library, *aromatic_library]:
            raw_smiles.append((smiles, seed))

    return _select_candidates(
        strategy=strategy,
        seed_smiles=seeds,
        raw_smiles=[smiles for smiles, _seed in raw_smiles],
        requested_count=requested_count,
        constraints=constraints,
        rationale=rationale,
        source_label=source_label,
        labels=labels,
        seed_by_raw_smiles=dict(raw_smiles),
        excluded_smiles=excluded_smiles,
    )


def _select_candidates(
    strategy: str,
    seed_smiles: list[str],
    raw_smiles: list[str],
    requested_count: int,
    constraints: dict[str, Any],
    rationale: str,
    source_label: str,
    labels: tuple[str, ...],
    seed_by_raw_smiles: dict[str, str] | None = None,
    excluded_smiles: set[str] | None = None,
) -> list[GenerationCandidate]:
    candidates: list[GenerationCandidate] = []
    seen: set[str] = set()
    excluded = {_standardize_or_normalize_smiles(smiles) for smiles in excluded_smiles or set()}

    for raw_smiles_item in raw_smiles:
        normalized = _standardize_or_normalize_smiles(raw_smiles_item)
        if (
            not normalized
            or normalized in seen
            or normalized in excluded
            or normalized in seed_smiles
            or not _is_rdkit_valid_or_lightly_valid(normalized)
            or not _satisfies_generation_constraints(normalized, seed_smiles, constraints)
        ):
            continue

        seed = (seed_by_raw_smiles or {}).get(raw_smiles_item, seed_smiles[0])
        score = _candidate_score(normalized, seed_smiles)
        candidates.append(
            GenerationCandidate(
                smiles=normalized,
                strategy=strategy,
                seed_smiles=seed,
                rationale=rationale,
                labels=labels,
                score=score,
                metadata={
                    "candidate_source": source_label,
                    "max_tanimoto_to_seed": _max_tanimoto_to_seed(normalized, seed_smiles),
                },
            )
        )
        seen.add(normalized)
        if len(candidates) >= requested_count:
            return candidates

    return candidates


def _normalize_strategies(strategies: list[str] | None) -> list[str]:
    if not strategies:
        return list(GENERATION_STRATEGIES)

    normalized = []
    for strategy in strategies:
        value = strategy.lower().strip()
        if value not in STRATEGY_ADAPTERS:
            raise ValueError(f"unsupported_generation_strategy:{strategy}")
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("generation_requires_at_least_one_strategy")
    return normalized


def _split_generation_size(generation_size: int, strategies: list[str]) -> dict[str, int]:
    base_count, remainder = divmod(generation_size, len(strategies))
    return {
        strategy: base_count + (1 if index < remainder else 0)
        for index, strategy in enumerate(strategies)
    }


def _resolve_strategy_counts(
    generation_size: int,
    strategies: list[str],
    strategy_counts: dict[str, int] | None,
) -> dict[str, int]:
    if not strategies:
        return {}
    if not strategy_counts:
        return _split_generation_size(generation_size, strategies)

    resolved: dict[str, int] = {}
    for strategy in strategies:
        value = strategy_counts.get(strategy, 0)
        try:
            count = int(value)
        except (TypeError, ValueError):
            count = 0
        resolved[strategy] = max(0, min(count, 500))
    return resolved


def _unique_valid_smiles(smiles_values: Iterable[str | None]) -> list[str]:
    unique = []
    seen = set()
    for smiles in smiles_values:
        normalized = _standardize_or_normalize_smiles(smiles)
        if normalized in seen or not is_lightly_valid_smiles(normalized):
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _standardize_or_normalize_smiles(smiles: str | None) -> str:
    normalized = normalize_smiles(smiles)
    if not normalized:
        return ""

    datamol_smiles = _standardize_with_datamol(normalized)
    if datamol_smiles:
        return datamol_smiles

    rdkit_smiles = _canonicalize_with_rdkit(normalized)
    if rdkit_smiles:
        return rdkit_smiles

    return normalized


def _standardize_with_datamol(smiles: str) -> str | None:
    try:
        import datamol as dm
    except ImportError:
        return None

    try:
        mol = dm.to_mol(smiles)
        if mol is None:
            return None
        if hasattr(dm, "standardize_mol"):
            mol = dm.standardize_mol(mol)
        return dm.to_smiles(mol, canonical=True)
    except Exception:
        return None


def _canonicalize_with_rdkit(smiles: str) -> str | None:
    try:
        from rdkit import Chem
    except ImportError:
        return None

    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        Chem.SanitizeMol(mol)
        return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
    except Exception:
        return None


def _is_rdkit_valid_or_lightly_valid(smiles: str) -> bool:
    if _canonicalize_with_rdkit(smiles):
        return True
    return is_lightly_valid_smiles(smiles)


def _satisfies_generation_constraints(
    smiles: str,
    seeds: list[str],
    constraints: dict[str, Any],
) -> bool:
    descriptors = _generation_descriptors(smiles)
    if descriptors is not None:
        if not _within_numeric_constraint(descriptors, "mw", constraints, "min_mw", "max_mw"):
            return False
        if not _within_numeric_constraint(descriptors, "logp", constraints, "min_logp", "max_logp"):
            return False
        if not _within_numeric_constraint(descriptors, "tpsa", constraints, "min_tpsa", "max_tpsa"):
            return False
        if not _within_numeric_constraint(descriptors, "hbd", constraints, "min_hbd", "max_hbd"):
            return False
        if not _within_numeric_constraint(descriptors, "hba", constraints, "min_hba", "max_hba"):
            return False

    max_tanimoto = _optional_float(constraints.get("max_tanimoto_to_seed"))
    min_tanimoto = _optional_float(constraints.get("min_tanimoto_to_seed"))
    if max_tanimoto is None and min_tanimoto is None:
        return True

    similarity = _max_tanimoto_to_seed(smiles, seeds)
    if similarity is None:
        return True
    if max_tanimoto is not None and similarity > max_tanimoto:
        return False
    if min_tanimoto is not None and similarity < min_tanimoto:
        return False
    return True


def _within_numeric_constraint(
    descriptors: dict[str, Any],
    descriptor_key: str,
    constraints: dict[str, Any],
    min_key: str,
    max_key: str,
) -> bool:
    value = descriptors.get(descriptor_key)
    if value is None:
        return True
    minimum = _optional_float(constraints.get(min_key))
    maximum = _optional_float(constraints.get(max_key))
    if minimum is not None and float(value) < minimum:
        return False
    if maximum is not None and float(value) > maximum:
        return False
    return True


def _candidate_score(smiles: str, seeds: list[str]) -> float | None:
    descriptors = _generation_descriptors(smiles)
    if descriptors is None:
        return None

    similarity = _max_tanimoto_to_seed(smiles, seeds) or 0.0
    mw = float(descriptors.get("mw") or 0.0)
    logp = float(descriptors.get("logp") or 0.0)
    tpsa = float(descriptors.get("tpsa") or 0.0)
    lead_like_penalty = abs(mw - 300.0) / 500.0 + max(logp - 4.0, 0.0) / 5.0 + max(tpsa - 120, 0.0) / 140.0
    return round((1.0 - abs(similarity - 0.45)) - lead_like_penalty, 6)


def _generation_descriptors(smiles: str) -> dict[str, Any] | None:
    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
    except ImportError:
        return None

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    try:
        Chem.SanitizeMol(mol)
    except Exception:
        return None
    return {
        "mw": float(Descriptors.MolWt(mol)),
        "logp": float(Crippen.MolLogP(mol)),
        "tpsa": float(rdMolDescriptors.CalcTPSA(mol)),
        "hbd": int(Lipinski.NumHDonors(mol)),
        "hba": int(Lipinski.NumHAcceptors(mol)),
        "heavy_atom_count": int(mol.GetNumHeavyAtoms()),
    }


def _max_tanimoto_to_seed(smiles: str, seeds: list[str]) -> float | None:
    try:
        from rdkit import Chem, DataStructs
        from rdkit.Chem import rdFingerprintGenerator
    except ImportError:
        return None

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    candidate_fp = generator.GetFingerprint(mol)
    similarities = []
    for seed in seeds:
        seed_mol = Chem.MolFromSmiles(seed)
        if seed_mol is None:
            continue
        seed_fp = generator.GetFingerprint(seed_mol)
        similarities.append(float(DataStructs.TanimotoSimilarity(candidate_fp, seed_fp)))
    if not similarities:
        return None
    return round(max(similarities), 6)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _looks_aromatic(smiles: str) -> bool:
    return "c1" in smiles or "n1" in smiles or "c2" in smiles or "n2" in smiles


def _rotate(items: list[str], offset: int) -> list[str]:
    if not items:
        return []
    shift = offset % len(items)
    return [*items[shift:], *items[:shift]]


def _count_failure(
    summary: MoleculeGenerationSummary,
    strategy_summary: StrategyGenerationSummary,
    reason: str,
) -> None:
    summary.failed_reason_summary[reason] = summary.failed_reason_summary.get(reason, 0) + 1
    if reason == "invalid_smiles":
        summary.invalid_count += 1
        strategy_summary.invalid_count += 1
    elif reason == "duplicate":
        summary.duplicate_count += 1
        strategy_summary.duplicate_count += 1


def _candidate_tool_labels(
    tool_status: dict[str, Any],
    external_pending_label: str,
) -> tuple[str, ...]:
    labels = [
        "external_generation_adapter_pending",
        "external_generation_fallback_used",
        external_pending_label,
    ]
    if tool_status["rdkit"]["available"]:
        labels.append("rdkit_generated")
        labels.append("rdkit_scored")
    if tool_status["datamol"]["available"]:
        labels.append("datamol_standardized")
    return tuple(labels)


def _candidate_source_counts(candidates: list[GenerationCandidate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        source = str(candidate.metadata.get("candidate_source", "unknown"))
        counts[source] = counts.get(source, 0) + 1
    return counts


def _external_generation_candidates(
    *,
    strategy: str,
    source: str,
    generated_smiles: list[str],
    scores: list[float | None],
    seeds: list[str],
    constraints: dict[str, Any],
    rationale: str,
    labels: list[str],
    adapter_mode: str,
    provenance: dict[str, Any],
) -> list[GenerationCandidate]:
    candidates: list[GenerationCandidate] = []
    for index, smiles in enumerate(generated_smiles):
        normalized = _standardize_or_normalize_smiles(smiles)
        rdkit_validated = _canonicalize_with_rdkit(normalized)
        if not rdkit_validated:
            continue
        normalized = rdkit_validated
        if not _satisfies_generation_constraints(normalized, seeds, constraints):
            continue
        candidates.append(
            GenerationCandidate(
                smiles=normalized,
                strategy=strategy,
                seed_smiles=seeds[0] if seeds else "",
                rationale=rationale,
                labels=tuple(labels),
                score=scores[index] if index < len(scores) else None,
                metadata={
                    "adapter_mode": adapter_mode,
                    "candidate_source": source,
                    "tool_score_semantics": provenance.get("score_semantics"),
                    "tool_provenance": provenance,
                },
            )
        )
    return candidates


def _strategy_tool_status(tool_status: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: tool_status[key] for key in keys}


def _merge_labels(primary: list[str], secondary: list[str]) -> list[str]:
    merged = []
    for label in [*primary, *secondary]:
        if label and label not in merged:
            merged.append(label)
    return merged


def _package_status(package_name: str) -> dict[str, Any]:
    available = util.find_spec(package_name) is not None
    version = None
    if available:
        try:
            version = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            version = None
    return {"available": available, "version": version}


def _any_package_status(package_names: list[str]) -> dict[str, Any]:
    checked = [_package_status(name) | {"package_name": name} for name in package_names]
    available_package = next((item for item in checked if item["available"]), None)
    return {
        "available": available_package is not None,
        "package_name": available_package["package_name"] if available_package else None,
        "version": available_package["version"] if available_package else None,
        "checked_package_names": package_names,
    }


def _resolve_crem_database_path() -> Path | None:
    for env_var in ("MEDAGENT_CREM_DB", "CREM_DB"):
        value = os.environ.get(env_var)
        if value:
            path = Path(value).expanduser()
            if path.exists():
                return path

    for default_path in (
        Path("database") / "chembl22_sa2.db",
        Path("database") / "crem_replacements.db",
        Path(".local") / "crem_replacements.db",
    ):
        if default_path.exists():
            return default_path
    return None


def _reinvent4_aliphatic_library() -> list[str]:
    return _unique_library(
        [
            "CCN",
            "CCCO",
            "CCOC",
            "CC(C)O",
            "CC(=O)O",
            "CCS",
            "CC(C)N",
            "CCC(=O)O",
            "COCCO",
            "CCNCC",
            *_linear_analogs(max_chain_length=36, hetero_atoms=("O", "N", "F", "Cl")),
        ]
    )


def _reinvent4_aromatic_library() -> list[str]:
    return _unique_library(
        [
            "Cc1ccccc1",
            "COc1ccccc1",
            "Nc1ccccc1",
            "O=C(O)c1ccccc1",
            "CC(=O)Nc1ccccc1",
            "O=C(N)c1ccccc1",
            "COc1ccc(C)cc1",
            "Nc1ccc(C)cc1",
            "CC(C)c1ccccc1",
            "COc1ccc(OC)cc1",
            *_substituted_aromatic_analogs(),
        ]
    )


def _crem_aliphatic_library() -> list[str]:
    return _unique_library(
        [
            "CCF",
            "CCCl",
            "CCBr",
            "CC(=O)N",
            "COC",
            "CC(C)C",
            "CC(C)(C)O",
            "CC(C)CO",
            "NCCO",
            "CCN(C)C",
            *_linear_analogs(max_chain_length=36, hetero_atoms=("F", "Cl", "Br", "N")),
        ]
    )


def _crem_aromatic_library() -> list[str]:
    return _unique_library(
        [
            "Fc1ccccc1",
            "Clc1ccccc1",
            "Oc1ccccc1",
            "Cc1ccc(F)cc1",
            "COc1ccc(F)cc1",
            "Nc1ccc(F)cc1",
            "CC(=O)Oc1ccccc1",
            "O=C(O)c1ccc(F)cc1",
            "O=C(N)c1ccc(F)cc1",
            "CCc1ccccc1",
            *_substituted_aromatic_analogs(second_substituents=("F", "Cl", "C", "OC")),
        ]
    )


def _autogrow4_aliphatic_library() -> list[str]:
    return _unique_library(
        [
            "CCN(CC)CC",
            "CCN(CCO)CC",
            "CCOC(=O)NCC",
            "CC(C)NC(=O)CC",
            "O=C(NCCO)CC",
            "CCN(CC)C(=O)CC",
            *_linear_analogs(max_chain_length=36, hetero_atoms=("O", "N")),
        ]
    )


def _autogrow4_aromatic_library() -> list[str]:
    return _unique_library(
        [
            "CCOc1ccccc1",
            "CCNc1ccccc1",
            "CCOC(=O)c1ccccc1",
            "O=C(NCCO)c1ccccc1",
            "CC(C)NC(=O)c1ccccc1",
            "CCN(CC)C(=O)c1ccccc1",
            "CCOC(=O)Nc1ccccc1",
            "CCOc1ccc(F)cc1",
            "CCNc1ccc(F)cc1",
            "CCOC(=O)c1ccc(F)cc1",
            *_substituted_aromatic_analogs(prefixes=("CCO", "CCN", "CCOC(=O)", "O=C(NCCO)")),
        ]
    )


def _linear_analogs(max_chain_length: int, hetero_atoms: tuple[str, ...]) -> list[str]:
    analogs: list[str] = []
    for chain_length in range(1, max_chain_length + 1):
        chain = "C" * chain_length
        for atom in hetero_atoms:
            analogs.append(f"{chain}{atom}")
        analogs.append(f"{chain}C(=O)O")
        analogs.append(f"{chain}C(=O)N")
        analogs.append(f"N{chain}O")
    return analogs


def _substituted_aromatic_analogs(
    prefixes: tuple[str, ...] = (
        "C",
        "CC",
        "CCC",
        "CO",
        "CCO",
        "N",
        "CN",
        "O",
        "F",
        "Cl",
        "Br",
        "C(=O)O",
        "C(=O)N",
    ),
    second_substituents: tuple[str, ...] = ("F", "Cl", "C", "OC", "N", "O"),
) -> list[str]:
    analogs: list[str] = []
    for prefix in prefixes:
        analogs.append(f"{prefix}c1ccccc1")
        for substituent in second_substituents:
            analogs.append(f"{prefix}c1ccc({substituent})cc1")
    return analogs


def _unique_library(smiles_values: Iterable[str]) -> list[str]:
    unique = []
    seen = set()
    for smiles in smiles_values:
        normalized = _standardize_or_normalize_smiles(smiles)
        if not normalized or normalized in seen or not _is_rdkit_valid_or_lightly_valid(normalized):
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique
