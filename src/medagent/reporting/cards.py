"""
Decision card formatting and display utilities.

This module formats ReasoningTrace and DecisionCard objects
for frontend display and PDF reports.
"""

from typing import Any

from medagent.db.models import DecisionCard, Molecule, ReasoningTrace


def format_decision_card(card: DecisionCard, molecule: Molecule | None = None) -> dict[str, Any]:
    """
    Format a DecisionCard for frontend display.

    Args:
        card: DecisionCard database object
        molecule: Optional Molecule object for additional context

    Returns:
        Formatted card dictionary
    """
    return {
        "decision_id": card.decision_id,
        "molecule_id": card.molecule_id,
        "title": card.title or _generate_title(card),
        "summary": card.summary or _generate_summary(card),
        "confidence_label": _confidence_label(card.confidence),
        "confidence": card.confidence,
        "decision": card.decision,
        "display_sections": card.display_sections or {},
        "smiles": molecule.smiles if molecule else None,
        "created_at": card.created_at.isoformat() if card.created_at else None,
    }


def format_reasoning_trace(trace: ReasoningTrace) -> dict[str, Any]:
    """
    Format a ReasoningTrace for detailed inspection.

    Args:
        trace: ReasoningTrace database object

    Returns:
        Formatted trace dictionary
    """
    return {
        "trace_id": trace.trace_id,
        "molecule_id": trace.molecule_id,
        "agent_run_id": trace.agent_run_id,
        "claim": trace.claim,
        "decision_type": trace.decision_type,
        "confidence": trace.confidence,
        "supporting_factors": trace.supporting_factors or [],
        "opposing_factors": trace.opposing_factors or [],
        "uncertainties": trace.uncertainties or [],
        "recommended_next_actions": trace.recommended_next_actions or [],
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
    }


def format_decision_card_compact(card: DecisionCard) -> dict[str, Any]:
    """
    Format decision card in compact form for tables and lists.

    Args:
        card: DecisionCard database object

    Returns:
        Compact card dictionary
    """
    sections = card.display_sections or {}
    support = sections.get("support", [])
    risk = sections.get("risk", [])

    return {
        "decision_id": card.decision_id,
        "molecule_id": card.molecule_id,
        "decision": card.decision,
        "confidence": card.confidence,
        "support_count": len(support) if isinstance(support, list) else 0,
        "risk_count": len(risk) if isinstance(risk, list) else 0,
        "summary": _truncate(card.summary or "", 100),
    }


def group_cards_by_decision(cards: list[DecisionCard]) -> dict[str, list[DecisionCard]]:
    """
    Group decision cards by decision type.

    Args:
        cards: List of DecisionCard objects

    Returns:
        Dictionary mapping decision type to list of cards
    """
    groups: dict[str, list[DecisionCard]] = {}
    for card in cards:
        decision = card.decision or "unspecified"
        groups.setdefault(decision, []).append(card)
    return groups


def generate_decision_summary(cards: list[DecisionCard]) -> dict[str, Any]:
    """
    Generate aggregate statistics for a set of decision cards.

    Args:
        cards: List of DecisionCard objects

    Returns:
        Summary statistics dictionary
    """
    if not cards:
        return {
            "total_count": 0,
            "decision_counts": {},
            "avg_confidence": 0.0,
            "high_confidence_count": 0,
            "medium_confidence_count": 0,
            "low_confidence_count": 0,
        }

    decision_counts: dict[str, int] = {}
    confidence_sum = 0.0
    confidence_levels = {"high": 0, "medium": 0, "low": 0}

    for card in cards:
        decision = card.decision or "unspecified"
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

        if card.confidence is not None:
            confidence_sum += card.confidence
            level = _confidence_label(card.confidence)
            if level in confidence_levels:
                confidence_levels[level] += 1

    avg_confidence = confidence_sum / len(cards) if cards else 0.0

    return {
        "total_count": len(cards),
        "decision_counts": decision_counts,
        "avg_confidence": round(avg_confidence, 2),
        "high_confidence_count": confidence_levels["high"],
        "medium_confidence_count": confidence_levels["medium"],
        "low_confidence_count": confidence_levels["low"],
    }


def _generate_title(card: DecisionCard) -> str:
    """Generate a title if not provided."""
    decision = card.decision or "unspecified"
    confidence = _confidence_label(card.confidence)
    return f"{decision.replace('_', ' ').title()} ({confidence} confidence)"


def _generate_summary(card: DecisionCard) -> str:
    """Generate a summary if not provided."""
    sections = card.display_sections or {}
    support = sections.get("support", [])
    risk = sections.get("risk", [])

    parts = []
    if support:
        parts.append(f"{len(support)} supporting factors")
    if risk:
        parts.append(f"{len(risk)} risk factors")

    if not parts:
        return "No detailed information available"

    return ", ".join(parts)


def _confidence_label(confidence: float | None) -> str:
    """Convert numeric confidence to label."""
    if confidence is None:
        return "unknown"
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.50:
        return "medium"
    return "low"


def _truncate(text: str, max_length: int) -> str:
    """Truncate text to max length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


# Card display templates for different contexts

def card_to_html(card: DecisionCard, molecule: Molecule | None = None) -> str:
    """
    Convert decision card to HTML for email or web display.

    Args:
        card: DecisionCard database object
        molecule: Optional Molecule object

    Returns:
        HTML string
    """
    formatted = format_decision_card(card, molecule)
    sections = formatted.get("display_sections", {})

    html_parts = [
        f"<div class='decision-card confidence-{formatted['confidence_label']}'>",
        f"  <h3>{formatted['title']}</h3>",
        f"  <p class='summary'>{formatted['summary']}</p>",
    ]

    if molecule:
        html_parts.append(f"  <p class='smiles'><code>{molecule.smiles}</code></p>")

    html_parts.append(f"  <p class='confidence'>Confidence: {formatted['confidence']:.2f}</p>")

    if sections.get("support"):
        html_parts.append("  <div class='support'>")
        html_parts.append("    <h4>Supporting Factors</h4>")
        html_parts.append("    <ul>")
        for item in sections["support"]:
            html_parts.append(f"      <li>{item}</li>")
        html_parts.append("    </ul>")
        html_parts.append("  </div>")

    if sections.get("risk"):
        html_parts.append("  <div class='risk'>")
        html_parts.append("    <h4>Risk Factors</h4>")
        html_parts.append("    <ul>")
        for item in sections["risk"]:
            html_parts.append(f"      <li>{item}</li>")
        html_parts.append("    </ul>")
        html_parts.append("  </div>")

    if sections.get("next"):
        html_parts.append("  <div class='next-actions'>")
        html_parts.append("    <h4>Recommended Next Steps</h4>")
        html_parts.append("    <ul>")
        for item in sections["next"]:
            html_parts.append(f"      <li>{item}</li>")
        html_parts.append("    </ul>")
        html_parts.append("  </div>")

    html_parts.append("</div>")

    return "\n".join(html_parts)


def card_to_markdown(card: DecisionCard, molecule: Molecule | None = None) -> str:
    """
    Convert decision card to Markdown for documentation.

    Args:
        card: DecisionCard database object
        molecule: Optional Molecule object

    Returns:
        Markdown string
    """
    formatted = format_decision_card(card, molecule)
    sections = formatted.get("display_sections", {})

    md_parts = [
        f"### {formatted['title']}",
        "",
        formatted["summary"],
        "",
    ]

    if molecule:
        md_parts.extend([f"**SMILES:** `{molecule.smiles}`", ""])

    md_parts.append(f"**Confidence:** {formatted['confidence']:.2f} ({formatted['confidence_label']})")
    md_parts.append("")

    if sections.get("support"):
        md_parts.append("#### Supporting Factors")
        md_parts.append("")
        for item in sections["support"]:
            md_parts.append(f"- {item}")
        md_parts.append("")

    if sections.get("risk"):
        md_parts.append("#### Risk Factors")
        md_parts.append("")
        for item in sections["risk"]:
            md_parts.append(f"- {item}")
        md_parts.append("")

    if sections.get("next"):
        md_parts.append("#### Recommended Next Steps")
        md_parts.append("")
        for item in sections["next"]:
            md_parts.append(f"- {item}")
        md_parts.append("")

    return "\n".join(md_parts)
