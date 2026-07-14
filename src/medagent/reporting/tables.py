"""
Table generation utilities for reports and exports.

This module generates formatted tables for:
- Molecule rankings
- Property comparisons
- Evidence summaries
- Agent run statistics
"""

from typing import Any

from medagent.db.models import (
    AdvisorSuggestion,
    AgentRun,
    Critique,
    Molecule,
    OptimizationConstraint,
    Ranking,
)


def generate_ranking_table(
    rankings: list[Ranking],
    molecules: dict[str, Molecule],
    critiques: dict[str, Critique] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate molecule ranking table.

    Args:
        rankings: List of Ranking objects
        molecules: Dictionary mapping molecule_id to Molecule
        critiques: Optional dictionary mapping molecule_id to Critique

    Returns:
        List of row dictionaries
    """
    if critiques is None:
        critiques = {}

    rows = []
    for ranking in rankings:
        molecule = molecules.get(ranking.molecule_id)
        critique = critiques.get(ranking.molecule_id)

        if molecule is None:
            continue

        row = {
            "rank": ranking.rank,
            "molecule_id": ranking.molecule_id,
            "smiles": molecule.smiles,
            "overall_score": round(ranking.overall_score, 2) if ranking.overall_score else None,
            "pro_score": round(ranking.pro_score, 2) if ranking.pro_score else None,
            "con_score": round(ranking.con_score, 2) if ranking.con_score else None,
            "final_decision": ranking.final_decision,
            "risk_level": critique.risk_level if critique else None,
            "status": molecule.status,
        }
        rows.append(row)

    return rows


def generate_molecule_property_table(molecules: list[Molecule]) -> list[dict[str, Any]]:
    """
    Generate molecule property comparison table.

    Args:
        molecules: List of Molecule objects

    Returns:
        List of row dictionaries with properties
    """
    rows = []
    for molecule in molecules:
        props = molecule.properties or {}
        row = {
            "molecule_id": molecule.molecule_id,
            "smiles": molecule.smiles,
            "mw": props.get("MW"),
            "logp": props.get("cLogP"),
            "tpsa": props.get("TPSA"),
            "hbd": props.get("HBD"),
            "hba": props.get("HBA"),
            "rotatable_bonds": props.get("RotB"),
            "aromatic_rings": props.get("AromaticRings"),
            "qed": props.get("QED"),
            "sa_score": props.get("SA_Score"),
        }
        rows.append(row)

    return rows


def generate_constraint_table(constraints: list[OptimizationConstraint]) -> list[dict[str, Any]]:
    """
    Generate optimization constraint table.

    Args:
        constraints: List of OptimizationConstraint objects

    Returns:
        List of row dictionaries
    """
    rows = []
    for constraint in constraints:
        row = {
            "constraint_id": constraint.constraint_id,
            "label": constraint.label,
            "field": constraint.field,
            "operator": constraint.operator,
            "value": constraint.value,
            "priority": constraint.priority,
            "is_active": constraint.is_active,
            "source": constraint.source,
        }
        rows.append(row)

    return rows


def generate_agent_run_table(runs: list[AgentRun]) -> list[dict[str, Any]]:
    """
    Generate agent run statistics table.

    Args:
        runs: List of AgentRun objects

    Returns:
        List of row dictionaries
    """
    rows = []
    for run in runs:
        duration = None
        if run.started_at and run.ended_at:
            duration = (run.ended_at - run.started_at).total_seconds()

        row = {
            "agent_run_id": run.agent_run_id,
            "agent_name": run.agent_name,
            "model_name": run.model_name,
            "status": run.status,
            "duration_seconds": round(duration, 2) if duration else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
            "error_message": run.error_message,
        }
        rows.append(row)

    return rows


def generate_critique_summary_table(critiques: list[Critique]) -> list[dict[str, Any]]:
    """
    Generate critique summary table.

    Args:
        critiques: List of Critique objects

    Returns:
        List of row dictionaries
    """
    rows = []
    for critique in critiques:
        row = {
            "critique_id": critique.critique_id,
            "molecule_id": critique.molecule_id,
            "con_score": round(critique.con_score, 2) if critique.con_score else None,
            "risk_level": critique.risk_level,
            "refutation_decision": critique.refutation_decision,
            "reason_summary": _truncate(critique.reason or "", 100),
            "evidence_count": len(critique.evidence_ids) if critique.evidence_ids else 0,
        }
        rows.append(row)

    return rows


def generate_advisor_table(suggestions: list[AdvisorSuggestion]) -> list[dict[str, Any]]:
    """
    Generate advisor suggestion history table.

    Args:
        suggestions: List of AdvisorSuggestion objects

    Returns:
        List of row dictionaries
    """
    rows = []
    for suggestion in suggestions:
        row = {
            "suggestion_id": suggestion.suggestion_id,
            "summary": _truncate(suggestion.summary or "", 100),
            "suggestion_count": len(suggestion.suggestions) if suggestion.suggestions else 0,
            "constraint_count": (
                len(suggestion.next_round_constraints) if suggestion.next_round_constraints else 0
            ),
            "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        }
        rows.append(row)

    return rows


def table_to_csv(rows: list[dict[str, Any]]) -> str:
    """
    Convert table rows to CSV string.

    Args:
        rows: List of row dictionaries

    Returns:
        CSV string
    """
    if not rows:
        return ""

    import csv
    import io

    output = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames)

    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    return output.getvalue()


def table_to_markdown(rows: list[dict[str, Any]], headers: list[str] | None = None) -> str:
    """
    Convert table rows to Markdown table.

    Args:
        rows: List of row dictionaries
        headers: Optional custom header labels (defaults to keys)

    Returns:
        Markdown table string
    """
    if not rows:
        return ""

    if headers is None:
        headers = list(rows[0].keys())

    # Header row
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    # Data rows
    for row in rows:
        values = [_format_cell_value(row.get(key)) for key in rows[0].keys()]
        lines.append("| " + " | ".join(values) + " |")

    return "\n".join(lines)


def table_to_html(rows: list[dict[str, Any]], headers: list[str] | None = None) -> str:
    """
    Convert table rows to HTML table.

    Args:
        rows: List of row dictionaries
        headers: Optional custom header labels (defaults to keys)

    Returns:
        HTML table string
    """
    if not rows:
        return "<table></table>"

    if headers is None:
        headers = list(rows[0].keys())

    html_parts = ["<table>", "  <thead>", "    <tr>"]

    # Header row
    for header in headers:
        html_parts.append(f"      <th>{_escape_html(str(header))}</th>")

    html_parts.extend(["    </tr>", "  </thead>", "  <tbody>"])

    # Data rows
    for row in rows:
        html_parts.append("    <tr>")
        for key in rows[0].keys():
            value = _format_cell_value(row.get(key))
            html_parts.append(f"      <td>{_escape_html(value)}</td>")
        html_parts.append("    </tr>")

    html_parts.extend(["  </tbody>", "</table>"])

    return "\n".join(html_parts)


def _format_cell_value(value: Any) -> str:
    """Format a cell value for display."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "✓" if value else "✗"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _truncate(text: str, max_length: int) -> str:
    """Truncate text to max length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


# Statistical summary functions


def calculate_table_statistics(rows: list[dict[str, Any]], numeric_fields: list[str]) -> dict[str, Any]:
    """
    Calculate statistics for numeric fields in a table.

    Args:
        rows: List of row dictionaries
        numeric_fields: List of field names to calculate stats for

    Returns:
        Dictionary of statistics
    """
    stats: dict[str, Any] = {}

    for field in numeric_fields:
        values = [row.get(field) for row in rows if isinstance(row.get(field), (int, float))]

        if not values:
            stats[field] = {"count": 0}
            continue

        stats[field] = {
            "count": len(values),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "mean": round(sum(values) / len(values), 2),
            "median": round(sorted(values)[len(values) // 2], 2),
        }

    return stats
