"""SAR → Generation Constraints bridge.

Converts SARAgent output into structured generation constraints
that can be consumed by _satisfies_generation_constraints() and
passed to generation agents via AgentTask.constraints.
"""

from __future__ import annotations

import re
from typing import Any

from medagent.agents.sar import (
    OptimizationSuggestion,
    Pharmacophore,
    SARAnalysisReport,
    SARPattern,
)


def sar_to_generation_constraints(
    sar_report: SARAnalysisReport,
) -> dict[str, Any]:
    """Convert a SAR analysis report into generation constraints + context strings.

    Returns a dict with two keys:
      - "constraints": dict[str, Any] — mergeable into AgentTask.constraints
      - "sar_context": list[str] — text descriptions for Agent LLM reference
    """
    constraints: dict[str, Any] = {}
    context_lines: list[str] = []

    # 1. Protected motifs from SAR patterns
    protected = _extract_protected_motifs(sar_report.sar_patterns)
    if protected:
        constraints["protected_motifs"] = protected
        context_lines.append(f"sar_protected_motifs: {', '.join(protected)}")

    # 2. Pharmacophore features
    features = _extract_pharmacophore_features(sar_report.pharmacophores)
    if features:
        constraints["required_pharmacophore_features"] = features
        context_lines.append(f"sar_required_features: {', '.join(features)}")

    # 3. Optimization suggestions → property constraints
    for suggestion in sar_report.optimization_suggestions:
        derived = _suggestion_to_constraints(suggestion)
        for key, value in derived.items():
            constraints.setdefault(key, value)
        desc = _suggestion_to_context(suggestion)
        if desc:
            context_lines.append(desc)

    # 4. Key findings as context
    for finding in sar_report.key_findings:
        context_lines.append(f"sar_finding: {finding}")

    return {"constraints": constraints, "sar_context": context_lines}


# ---------------------------------------------------------------------------
# Protected motifs
# ---------------------------------------------------------------------------

def _extract_protected_motifs(patterns: list[SARPattern]) -> list[str]:
    """Extract SMARTS-like scaffold descriptions from SAR patterns.

    SAR patterns describe structural changes and score shifts.
    We treat the structural_change field as a heuristic source of
    scaffold identifiers.  Downstream, _satisfies_generation_constraints
    will attempt to parse these as RDKit SMARTS; anything unparseable
    is silently skipped.
    """
    motifs: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        raw = (pattern.structural_change or "").strip()
        if not raw:
            continue
        # Try to extract SMILES/SMARTS fragments from the description
        for token in _extract_smarts_tokens(raw):
            if token not in seen:
                seen.add(token)
                motifs.append(token)
    return motifs


_SMARTS_RE = re.compile(r"[A-Za-z0-9@+\-\[\]\(\)=#\\/%.]{3,}")


def _extract_smarts_tokens(text: str) -> list[str]:
    """Heuristically extract SMILES/SMARTS-like tokens from free text."""
    tokens: list[str] = []
    for match in _SMARTS_RE.finditer(text):
        token = match.group(0)
        # Skip common English words that look like SMILES
        if len(token) < 4:
            continue
        if token[0].isalpha() and not any(c in token for c in "=[#()"):
            continue
        tokens.append(token)
    return tokens


# ---------------------------------------------------------------------------
# Pharmacophore features
# ---------------------------------------------------------------------------

_KNOWN_FEATURES = frozenset({
    "HBD", "HBA", "Hydrophobic", "Aromatic",
    "PositiveIonizable", "NegativeIonizable",
    "Donor", "Acceptor",
})


def _extract_pharmacophore_features(pharmacophores: list[Pharmacophore]) -> list[str]:
    """Collect unique pharmacophore features from high-importance hypotheses."""
    features: list[str] = []
    seen: set[str] = set()
    for pharma in pharmacophores:
        if pharma.importance_score < 0.4:
            continue
        for feature in pharma.features:
            normalized = _normalize_feature(feature)
            if normalized and normalized not in seen:
                seen.add(normalized)
                features.append(normalized)
    return features


def _normalize_feature(raw: str) -> str | None:
    """Map free-text feature names to canonical labels."""
    lower = raw.strip().lower()
    if not lower:
        return None
    if "hbd" in lower or "donor" in lower:
        return "HBD"
    if "hba" in lower or "acceptor" in lower:
        return "HBA"
    if "hydrophob" in lower or "lipophil" in lower:
        return "Hydrophobic"
    if "aromat" in lower or "ring" in lower:
        return "Aromatic"
    if "positive" in lower or "basic" in lower:
        return "PositiveIonizable"
    if "negative" in lower or "acidic" in lower:
        return "NegativeIonizable"
    return raw.strip()


# ---------------------------------------------------------------------------
# Optimization suggestions → property constraints
# ---------------------------------------------------------------------------

def _suggestion_to_constraints(suggestion: OptimizationSuggestion) -> dict[str, Any]:
    """Derive numeric property constraints from an optimization suggestion."""
    constraints: dict[str, Any] = {}
    rationale = (suggestion.rationale or "").lower()
    improvement = (suggestion.expected_improvement or "").lower()
    combined = f"{rationale} {improvement}"

    if any(kw in combined for kw in ("lipophilic", "logp", "lipophilicity")):
        if "reduce" in combined or "lower" in combined or "decrease" in combined:
            constraints.setdefault("max_logp", 4.0)

    if any(kw in combined for kw in ("solubil", "dissolution", "tpsa")):
        if "improve" in combined or "increase" in combined or "enhance" in combined:
            constraints.setdefault("min_tpsa", 60.0)

    if "molecular weight" in combined or " mw " in combined:
        if "reduce" in combined or "lower" in combined:
            constraints.setdefault("max_mw", 450.0)

    return constraints


def _suggestion_to_context(suggestion: OptimizationSuggestion) -> str | None:
    """Convert an optimization suggestion into a human-readable context line."""
    parts: list[str] = []
    if suggestion.modification_type:
        parts.append(suggestion.modification_type)
    if suggestion.target_position:
        parts.append(f"at {suggestion.target_position}")
    if suggestion.rationale:
        parts.append(f"({suggestion.rationale})")
    if not parts:
        return None
    return f"sar_suggestion: {' '.join(parts)}"
