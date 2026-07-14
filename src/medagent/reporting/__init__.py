"""Reporting module."""

from medagent.reporting.cards import (
    card_to_html,
    card_to_markdown,
    format_decision_card,
    format_decision_card_compact,
    format_reasoning_trace,
    generate_decision_summary,
    group_cards_by_decision,
)
from medagent.reporting.pdf import generate_pdf_report
from medagent.reporting.project_report import REPORT_SECTIONS, build_project_report
from medagent.reporting.tables import (
    calculate_table_statistics,
    generate_agent_run_table,
    generate_constraint_table,
    generate_molecule_property_table,
    generate_ranking_table,
    table_to_csv,
    table_to_html,
    table_to_markdown,
)

__all__ = [
    "REPORT_SECTIONS",
    "build_project_report",
    "generate_pdf_report",
    "format_decision_card",
    "format_decision_card_compact",
    "format_reasoning_trace",
    "group_cards_by_decision",
    "generate_decision_summary",
    "card_to_html",
    "card_to_markdown",
    "generate_ranking_table",
    "generate_molecule_property_table",
    "generate_constraint_table",
    "generate_agent_run_table",
    "table_to_csv",
    "table_to_html",
    "table_to_markdown",
    "calculate_table_statistics",
]

