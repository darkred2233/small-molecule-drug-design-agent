"""
PDF report generation utilities.

This module generates PDF reports from project data using ReportLab.
Install with: pip install reportlab
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from medagent.db.models import Molecule, Project, Ranking
from medagent.reporting.tables import (
    generate_agent_run_table,
    generate_constraint_table,
    generate_molecule_property_table,
    generate_ranking_table,
)


def generate_pdf_report(
    db: Session,
    project: Project,
    output_path: Path | None = None,
) -> Path:
    """
    Generate PDF report for a project.

    Args:
        db: Database session
        project: Project object
        output_path: Optional output path (defaults to .local/reports/)

    Returns:
        Path to generated PDF file
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise ImportError(
            "reportlab is required for PDF generation. Install with: pip install reportlab"
        ) from exc

    if output_path is None:
        output_dir = Path(".local") / "reports" / _safe_path_part(project.project_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"report_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.pdf"

    # Create PDF document
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18,
    )

    # Container for the 'Flowable' objects
    elements = []

    # Define styles
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading1_style = styles["Heading1"]
    heading2_style = styles["Heading2"]
    normal_style = styles["Normal"]

    # Title page
    elements.append(Paragraph("小分子药物设计项目报告", title_style))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"项目: {project.name}", heading2_style))
    elements.append(Paragraph(f"项目ID: {project.project_id}", normal_style))
    elements.append(Paragraph(f"靶点: {project.target_id or 'N/A'}", normal_style))
    elements.append(Paragraph(f"状态: {project.status}", normal_style))
    elements.append(
        Paragraph(
            f"生成时间: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            normal_style,
        )
    )
    elements.append(Spacer(1, 24))
    elements.append(PageBreak())

    # Section 1: Project Summary
    elements.append(Paragraph("1. 项目摘要", heading1_style))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"目标: {project.objective or 'N/A'}", normal_style))
    elements.append(Spacer(1, 12))

    # Section 2: Constraints
    elements.append(Paragraph("2. 优化约束", heading1_style))
    elements.append(Spacer(1, 12))

    from medagent.db.models import OptimizationConstraint

    constraints = (
        db.query(OptimizationConstraint)
        .filter_by(project_id=project.project_id)
        .order_by(OptimizationConstraint.priority.desc())
        .all()
    )

    if constraints:
        constraint_data = generate_constraint_table(constraints)
        constraint_table_data = [["标签", "字段", "操作符", "值", "优先级"]]
        for row in constraint_data[:10]:  # Limit to 10 for PDF
            constraint_table_data.append(
                [
                    row.get("label", ""),
                    row.get("field", ""),
                    row.get("operator", ""),
                    str(row.get("value", "")),
                    row.get("priority", ""),
                ]
            )

        t = Table(constraint_table_data)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        elements.append(t)
    else:
        elements.append(Paragraph("无约束配置", normal_style))

    elements.append(Spacer(1, 24))

    # Section 3: Top Candidates
    elements.append(Paragraph("3. Top 候选分子", heading1_style))
    elements.append(Spacer(1, 12))

    rankings = (
        db.query(Ranking)
        .filter_by(project_id=project.project_id)
        .order_by(Ranking.rank.asc())
        .limit(20)
        .all()
    )

    molecules = (
        db.query(Molecule)
        .filter_by(project_id=project.project_id)
        .all()
    )
    molecules_dict = {m.molecule_id: m for m in molecules}

    if rankings:
        ranking_data = generate_ranking_table(rankings, molecules_dict)
        ranking_table_data = [["排名", "分子ID", "总分", "Pro分", "Con分", "决策"]]
        for row in ranking_data[:20]:  # Top 20
            ranking_table_data.append(
                [
                    str(row.get("rank", "")),
                    row.get("molecule_id", ""),
                    str(row.get("overall_score", "")),
                    str(row.get("pro_score", "")),
                    str(row.get("con_score", "")),
                    row.get("final_decision", ""),
                ]
            )

        t = Table(ranking_table_data)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        elements.append(t)
    else:
        elements.append(Paragraph("暂无排名数据", normal_style))

    elements.append(Spacer(1, 24))
    elements.append(PageBreak())

    # Section 4: Molecule Properties
    elements.append(Paragraph("4. 分子性质概览", heading1_style))
    elements.append(Spacer(1, 12))

    if molecules:
        property_data = generate_molecule_property_table(molecules[:10])  # Top 10
        property_table_data = [["分子ID", "MW", "LogP", "TPSA", "HBD", "HBA"]]
        for row in property_data:
            property_table_data.append(
                [
                    row.get("molecule_id", ""),
                    str(row.get("mw", "") or ""),
                    str(row.get("logp", "") or ""),
                    str(row.get("tpsa", "") or ""),
                    str(row.get("hbd", "") or ""),
                    str(row.get("hba", "") or ""),
                ]
            )

        t = Table(property_table_data)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        elements.append(t)
    else:
        elements.append(Paragraph("暂无分子数据", normal_style))

    elements.append(Spacer(1, 24))

    # Section 5: Technical Appendix
    elements.append(PageBreak())
    elements.append(Paragraph("5. 技术附录", heading1_style))
    elements.append(Spacer(1, 12))

    from medagent.db.models import AgentRun

    agent_runs = (
        db.query(AgentRun)
        .filter_by(project_id=project.project_id)
        .order_by(AgentRun.started_at.asc())
        .all()
    )

    if agent_runs:
        run_data = generate_agent_run_table(agent_runs)
        run_table_data = [["Agent", "模型", "状态", "耗时(秒)"]]
        for row in run_data:
            run_table_data.append(
                [
                    row.get("agent_name", ""),
                    row.get("model_name", ""),
                    row.get("status", ""),
                    str(row.get("duration_seconds", "") or ""),
                ]
            )

        t = Table(run_table_data)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        elements.append(t)
    else:
        elements.append(Paragraph("暂无运行记录", normal_style))

    # Build PDF
    doc.build(elements)

    return output_path


def _safe_path_part(value: str) -> str:
    """Convert string to safe filesystem path component."""
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return safe.strip("._") or "project"
