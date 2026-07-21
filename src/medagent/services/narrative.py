from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import AgentRun, Molecule, Project
from medagent.services.ids import new_id


MOLECULE_NARRATIVE_AGENT = "molecule_narrative_agent"
FINAL_REPORT_AGENT = "final_report_agent"
NARRATIVE_MODEL_NAME = "deterministic-evidence-grounded-narrative"
NARRATIVE_SCHEMA_VERSION = "1.0"


def attach_narrative_layer(report: dict[str, Any]) -> dict[str, Any]:
    narratives = build_molecule_narratives_from_report(report)
    narratives_by_id = {item["molecule_id"]: item for item in narratives}
    for candidate in report.get("top_candidates") or []:
        molecule_id = candidate.get("molecule_id")
        if molecule_id in narratives_by_id:
            candidate["narrative"] = narratives_by_id[molecule_id]

    report["molecule_narratives"] = narratives
    report["final_report"] = build_final_report_from_report(report, narratives)
    technical_appendix = dict(report.get("technical_appendix") or {})
    technical_appendix["narrative_schema_version"] = NARRATIVE_SCHEMA_VERSION
    technical_appendix["narrative_source"] = MOLECULE_NARRATIVE_AGENT
    technical_appendix["final_report_source"] = FINAL_REPORT_AGENT
    report["technical_appendix"] = technical_appendix
    return report


def build_molecule_narratives_from_report(
    report: dict[str, Any],
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    candidates = list(report.get("top_candidates") or [])
    if top_n is not None:
        candidates = candidates[:top_n]
    return [_build_candidate_narrative(candidate, report) for candidate in candidates]


def build_project_molecule_narrative(
    db: Session,
    project: Project,
    molecule_id: str,
) -> dict[str, Any]:
    from medagent.reporting.project_report import build_project_report

    report = build_project_report(db, project)
    for candidate in report.get("top_candidates") or []:
        if candidate.get("molecule_id") == molecule_id:
            return candidate["narrative"]

    molecule = db.query(Molecule).filter_by(project_id=project.project_id, molecule_id=molecule_id).one_or_none()
    if molecule is None:
        raise ValueError("molecule_not_found")
    fallback_candidate = {
        "rank": None,
        "molecule_id": molecule.molecule_id,
        "smiles": molecule.smiles,
        "generation_source_agent": molecule.source_agent,
        "generation_method": _generation_method_from_labels(molecule),
        "overall_score": None,
        "final_decision": molecule.status,
        "rule_filter": [],
        "docking": None,
        "admet": None,
        "synthesis": None,
        "evidence_chain": [],
        "refutation_chain": None,
    }
    return _build_candidate_narrative(fallback_candidate, report)


def persist_project_molecule_narratives(
    db: Session,
    project: Project,
    report: dict[str, Any],
    *,
    top_n: int | None = None,
) -> AgentRun:
    narratives = build_molecule_narratives_from_report(report, top_n=top_n)
    output = {
        "project_id": project.project_id,
        "agent": MOLECULE_NARRATIVE_AGENT,
        "model_name": NARRATIVE_MODEL_NAME,
        "narrative_schema_version": NARRATIVE_SCHEMA_VERSION,
        "molecule_narratives": narratives,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        agent_name=MOLECULE_NARRATIVE_AGENT,
        model_name=NARRATIVE_MODEL_NAME,
        status="completed",
        input_json={
            "project_id": project.project_id,
            "top_n": top_n,
            "source_report_schema_version": (report.get("technical_appendix") or {}).get(
                "report_schema_version"
            ),
        },
        output_json=output,
    )
    db.add(run)
    db.commit()
    return run


def persist_project_final_report(
    db: Session,
    project: Project,
    report: dict[str, Any],
) -> AgentRun:
    final_report = report.get("final_report") or build_final_report_from_report(
        report,
        build_molecule_narratives_from_report(report),
    )
    output = {
        **report,
        "final_report": final_report,
    }
    run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        agent_name=FINAL_REPORT_AGENT,
        model_name=NARRATIVE_MODEL_NAME,
        status="completed",
        input_json={
            "project_id": project.project_id,
            "source_report_schema_version": (report.get("technical_appendix") or {}).get(
                "report_schema_version"
            ),
            "narrative_schema_version": NARRATIVE_SCHEMA_VERSION,
        },
        output_json=output,
    )
    db.add(run)
    db.commit()
    return run


def build_final_report_from_report(
    report: dict[str, Any],
    narratives: list[dict[str, Any]],
) -> dict[str, Any]:
    project_summary = report.get("project_summary") or {}
    candidate_summary = report.get("candidate_summary") or {}
    advisor = report.get("advisor_suggestions") or {}
    top_narratives = narratives[:5]
    citations = _final_report_citations(top_narratives)
    round_summaries = _round_summaries(report)
    uncertainties = _uncertainties(report, narratives)
    next_steps = _next_steps(advisor, narratives)

    return {
        "title": f"{project_summary.get('name') or project_summary.get('project_id')} 最终设计报告",
        "language": "zh-CN",
        "generation_mode": "evidence_grounded_deterministic",
        "schema_version": NARRATIVE_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "project_objective": project_summary.get("objective"),
        "executive_summary": [
            (
                f"本项目共记录 {candidate_summary.get('molecule_count', 0)} 个候选分子，"
                f"其中 {candidate_summary.get('ranking_count', 0)} 个进入排序。"
            ),
            _top_candidate_sentence(top_narratives),
            "以下结论只基于系统中已存在的 docking、ADMET、合成、RAG 和排序证据。",
        ],
        "execution_config_summary": _execution_config_summary(report),
        "round_summaries": round_summaries,
        "top_molecules": [
            {
                "molecule_id": item["molecule_id"],
                "rank": item.get("rank"),
                "summary": item["summary"],
                "strengths": item["strengths"],
                "risks": item["risks"],
                "next_round_suggestions": item["next_round_suggestions"],
                "evidence_refs": item["evidence_refs"],
            }
            for item in top_narratives
        ],
        "sar_summary": _sar_summary(report),
        "docking_summary": _docking_summary(narratives),
        "admet_summary": _admet_summary(narratives),
        "synthesis_summary": _synthesis_report_summary(report, narratives),
        "rag_evidence_summary": _rag_summary(report, citations),
        "failures_and_uncertainties": uncertainties,
        "next_steps": next_steps,
        "citations": citations,
        "provenance": {
            "source": FINAL_REPORT_AGENT,
            "model_name": NARRATIVE_MODEL_NAME,
            "score_policy": "raw_tool_scores_are_not_modified_by_narrative_layer",
        },
    }


def _build_candidate_narrative(
    candidate: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    molecule_id = candidate.get("molecule_id")
    strengths = _strengths(candidate)
    risks = _risks(candidate)
    suggestions = _suggestions(candidate, risks)
    evidence_refs = _evidence_refs(candidate)
    summary = _candidate_summary(candidate, strengths, risks)
    return {
        "molecule_id": molecule_id,
        "rank": candidate.get("rank"),
        "summary": summary,
        "why_it_matters": _why_it_matters(candidate, report),
        "structure_change": _structure_change(candidate),
        "strengths": strengths,
        "risks": risks,
        "next_round_suggestions": suggestions,
        "evidence_refs": evidence_refs,
        "provenance": {
            "source": MOLECULE_NARRATIVE_AGENT,
            "model_name": NARRATIVE_MODEL_NAME,
            "generated_at": datetime.now(UTC).isoformat(),
            "score_policy": "narrative_explains_existing_scores_without_overwriting_them",
            "input_fields": [
                "ranking",
                "docking",
                "admet",
                "synthesis",
                "rule_filter",
                "evidence_chain",
                "refutation_chain",
            ],
        },
    }


def _candidate_summary(
    candidate: dict[str, Any],
    strengths: list[str],
    risks: list[str],
) -> str:
    rank = candidate.get("rank")
    rank_text = f"第 {rank} 名" if rank is not None else "未排序"
    score = _format_number(candidate.get("overall_score"), digits=2)
    method = candidate.get("generation_method") or candidate.get("generation_source_agent") or "未知来源"
    if strengths:
        support = strengths[0]
    else:
        support = "当前缺少足够的正向工具证据。"
    if risks:
        risk = risks[0]
    else:
        risk = "暂未看到明确的高风险信号。"
    return f"{rank_text}候选分子来自 {method}，综合评分 {score}。{support}{risk}"


def _why_it_matters(candidate: dict[str, Any], report: dict[str, Any]) -> str:
    objective = (report.get("project_summary") or {}).get("objective")
    decision = candidate.get("final_decision") or "未给出决策"
    if objective:
        return f"它被纳入重点候选，是因为当前排序和证据链显示它与项目目标“{objective}”相关，最终决策为 {decision}。"
    return f"它被纳入重点候选，是因为当前排序和证据链显示它值得继续比较，最终决策为 {decision}。"


def _structure_change(candidate: dict[str, Any]) -> str:
    method = candidate.get("generation_method") or candidate.get("generation_source_agent")
    smiles = candidate.get("smiles")
    if method in {"seed_ligand_import", "seed"}:
        return "该分子来自种子或导入集合，当前记录中没有生成式结构改造说明。"
    if method:
        return f"该分子由 {method} 产生；结构差异以保存的 SMILES 为准：{_short_text(smiles, 96)}"
    return f"当前没有明确的生成方法记录；结构以 SMILES 为准：{_short_text(smiles, 96)}"


def _strengths(candidate: dict[str, Any]) -> list[str]:
    strengths: list[str] = []
    score = _as_float(candidate.get("overall_score"))
    if score is not None:
        strengths.append(f"综合评分为 {_format_number(score, digits=2)}，可用于同批候选的相对比较。")
    docking = candidate.get("docking") or {}
    if docking.get("pose_artifact_available"):
        strengths.append("存在可追溯的 docking pose 文件，可用于后续人工检查。")
    if docking.get("best_pose_confirmed"):
        strengths.append("当前最佳 pose 已按工具输出确认。")
    admet = candidate.get("admet") or {}
    herg = (admet.get("hERG") or {}).get("risk")
    if herg and str(herg).lower() in {"low", "lower", "低"}:
        strengths.append("hERG 预测风险较低。")
    synthesis = candidate.get("synthesis") or {}
    if synthesis.get("route_found") or synthesis.get("estimated_route_feasible"):
        strengths.append("合成可行性评估显示存在可行路线或可行性估计。")
    if candidate.get("evidence_chain"):
        strengths.append("存在 RAG 文献或项目证据链，可展开追溯原始依据。")
    return strengths


def _risks(candidate: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    rule_filters = candidate.get("rule_filter") or []
    for result in rule_filters:
        failed = result.get("failed_rules") or []
        if failed:
            risks.append(f"规则过滤提示 {', '.join(str(item) for item in failed[:3])} 需要复核。")
            break
    docking = candidate.get("docking") or {}
    if not docking:
        risks.append("缺少 docking 结果，结合模式仍不确定。")
    elif not docking.get("pose_artifact_available"):
        risks.append("docking pose 文件不可用，无法检查三维构象证据。")
    admet = candidate.get("admet") or {}
    for key in ("hERG", "Ames"):
        risk = (admet.get(key) or {}).get("risk")
        if risk and str(risk).lower() not in {"low", "lower", "低"}:
            risks.append(f"{key} 预测风险为 {risk}。")
    if admet.get("admet_risk_score") is not None and _as_float(admet.get("admet_risk_score")):
        risks.append(f"ADMET 总风险分为 {_format_number(admet.get('admet_risk_score'), digits=2)}。")
    synthesis = candidate.get("synthesis") or {}
    if synthesis and not synthesis.get("route_found") and not synthesis.get("estimated_route_feasible"):
        risks.append("外部路线或合成可行性未给出明确可行结论。")
    refutation = candidate.get("refutation_chain") or {}
    if refutation.get("risk_level"):
        risks.append(f"自反驳模块风险等级为 {refutation.get('risk_level')}。")
    return risks


def _suggestions(candidate: dict[str, Any], risks: list[str]) -> list[str]:
    suggestions: list[str] = []
    risk_text = " ".join(risks)
    if "hERG" in risk_text:
        suggestions.append("下一轮优先降低 hERG 风险，避免过度脂溶和可疑碱性片段。")
    if "Ames" in risk_text:
        suggestions.append("下一轮避开潜在诱变警示片段，并保留可解释的替换记录。")
    if "合成" in risk_text or "路线" in risk_text:
        suggestions.append("下一轮把可合成性作为硬约束，优先保留可购买砌块路径。")
    if "docking" in risk_text or "pose" in risk_text:
        suggestions.append("下一轮补充可靠 receptor/grid 或重新确认 pose 文件。")
    if not suggestions:
        suggestions.append("可作为下一轮 seed，围绕当前骨架做小步 SAR 优化。")
    return suggestions


def _evidence_refs(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    molecule_id = candidate.get("molecule_id")
    refs: list[dict[str, Any]] = []
    if candidate.get("overall_score") is not None:
        refs.append(
            {
                "type": "ranking_score",
                "source": "ranker_agent",
                "molecule_id": molecule_id,
                "summary": f"综合评分 {_format_number(candidate.get('overall_score'), digits=2)}",
                "score": candidate.get("overall_score"),
            }
        )
    docking = candidate.get("docking") or {}
    if docking:
        refs.append(
            {
                "type": "docking_pose",
                "source": _first_label_or_default(docking.get("labels"), "docking"),
                "molecule_id": molecule_id,
                "summary": _docking_ref_summary(docking),
                "artifact_path": docking.get("pose_file"),
                "score": docking.get("vina_score")
                if docking.get("vina_score") is not None
                else docking.get("diffdock_confidence"),
                "metadata": {
                    "selected_pose_rank": docking.get("selected_pose_rank"),
                    "pose_count": docking.get("pose_count"),
                    "best_pose_confirmed": docking.get("best_pose_confirmed"),
                },
            }
        )
    admet = candidate.get("admet") or {}
    if admet:
        refs.append(
            {
                "type": "admet_prediction",
                "source": admet.get("tool_name") or admet.get("adapter_mode") or "admet",
                "molecule_id": molecule_id,
                "summary": _admet_ref_summary(admet),
                "score": admet.get("admet_risk_score"),
            }
        )
    synthesis = candidate.get("synthesis") or {}
    if synthesis:
        refs.append(
            {
                "type": "synthesis_score",
                "source": synthesis.get("adapter_mode") or "synthesis",
                "molecule_id": molecule_id,
                "summary": _synthesis_ref_summary(synthesis),
                "score": synthesis.get("route_confidence")
                if synthesis.get("route_confidence") is not None
                else synthesis.get("SA_score"),
                "metadata": {
                    "route_found": synthesis.get("route_found"),
                    "route_steps": synthesis.get("route_steps"),
                    "estimated_route_feasible": synthesis.get("estimated_route_feasible"),
                },
            }
        )
    for evidence in candidate.get("evidence_chain") or []:
        refs.append(
            {
                "type": "rag_reference",
                "source": evidence.get("document_title")
                or evidence.get("filename")
                or evidence.get("document_id")
                or "rag",
                "molecule_id": molecule_id,
                "summary": evidence.get("rationale") or _short_text(evidence.get("content"), 160),
                "score": evidence.get("evidence_confidence"),
                "metadata": {
                    "evidence_id": evidence.get("evidence_id"),
                    "document_id": evidence.get("document_id"),
                    "chunk_id": evidence.get("chunk_id"),
                    "page_number": evidence.get("page_number"),
                    "section": evidence.get("section"),
                },
            }
        )
    return refs


def _execution_config_summary(report: dict[str, Any]) -> dict[str, Any]:
    project_summary = report.get("project_summary") or {}
    return {
        "project_id": project_summary.get("project_id"),
        "objective": project_summary.get("objective"),
        "status": project_summary.get("status"),
        "note": "轮次执行配置快照保存在 ProjectRound.execution_config_snapshot_json；本报告只复述已入库证据。",
    }


def _round_summaries(report: dict[str, Any]) -> list[dict[str, Any]]:
    rounds = report.get("round_summaries") or []
    return rounds if isinstance(rounds, list) else []


def _sar_summary(report: dict[str, Any]) -> dict[str, Any]:
    sar = report.get("sar_overview") or {}
    stats = sar.get("rule_filter_statistics") or {}
    return {
        "rule_count": len(sar.get("target_sar_rules") or []),
        "rule_filter_result_count": stats.get("result_count", 0),
        "notable_failed_rules": list((stats.get("failed_rule_counts") or {}).keys())[:5],
    }


def _docking_summary(narratives: list[dict[str, Any]]) -> dict[str, Any]:
    refs = [
        ref
        for narrative in narratives
        for ref in narrative.get("evidence_refs") or []
        if ref.get("type") == "docking_pose"
    ]
    return {
        "molecule_count_with_docking_evidence": len(refs),
        "pose_artifact_count": sum(1 for ref in refs if ref.get("artifact_path")),
        "top_docking_refs": refs[:5],
    }


def _admet_summary(narratives: list[dict[str, Any]]) -> dict[str, Any]:
    risk_lines = [
        risk
        for narrative in narratives
        for risk in narrative.get("risks") or []
        if "hERG" in risk or "Ames" in risk or "ADMET" in risk
    ]
    return {"notable_risks": risk_lines[:8]}


def _synthesis_report_summary(
    report: dict[str, Any],
    narratives: list[dict[str, Any]],
) -> dict[str, Any]:
    overview = report.get("synthesis_overview") or {}
    route_refs = [
        ref
        for narrative in narratives
        for ref in narrative.get("evidence_refs") or []
        if ref.get("type") == "synthesis_score"
    ]
    return {
        "route_found_count": overview.get("route_found_count", 0),
        "route_missing_count": overview.get("route_missing_count", 0),
        "top_synthesis_refs": route_refs[:5],
    }


def _rag_summary(report: dict[str, Any], citations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "evidence_link_count": len(report.get("evidence_links") or []),
        "citation_count": len(citations),
        "citations": citations[:10],
    }


def _final_report_citations(narratives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for narrative in narratives:
        for ref in narrative.get("evidence_refs") or []:
            if ref.get("type") != "rag_reference":
                continue
            metadata = ref.get("metadata") or {}
            key = str(metadata.get("evidence_id") or metadata.get("chunk_id") or ref.get("source"))
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                {
                    "source": ref.get("source"),
                    "summary": ref.get("summary"),
                    "document_id": metadata.get("document_id"),
                    "chunk_id": metadata.get("chunk_id"),
                    "page_number": metadata.get("page_number"),
                    "section": metadata.get("section"),
                }
            )
    return citations


def _uncertainties(report: dict[str, Any], narratives: list[dict[str, Any]]) -> list[str]:
    uncertainties: list[str] = []
    if not report.get("evidence_links"):
        uncertainties.append("当前报告没有 RAG 文献证据链接。")
    if not any("docking_pose" == ref.get("type") for item in narratives for ref in item.get("evidence_refs", [])):
        uncertainties.append("Top 分子缺少 docking pose 证据。")
    if not any("synthesis_score" == ref.get("type") for item in narratives for ref in item.get("evidence_refs", [])):
        uncertainties.append("Top 分子缺少合成可行性证据。")
    for item in narratives[:5]:
        for risk in item.get("risks") or []:
            uncertainties.append(f"{item.get('molecule_id')}: {risk}")
    return _dedupe(uncertainties)[:12]


def _next_steps(advisor: dict[str, Any], narratives: list[dict[str, Any]]) -> list[str]:
    steps: list[str] = []
    for item in advisor.get("suggestions") or []:
        if isinstance(item, dict):
            text = item.get("action") or item.get("summary") or item.get("rationale")
        else:
            text = str(item)
        if text:
            steps.append(text)
    for narrative in narratives[:3]:
        steps.extend(narrative.get("next_round_suggestions") or [])
    if not steps:
        steps.append("选择排名靠前且证据较完整的分子作为下一轮 seed，继续小步优化。")
    return _dedupe(steps)[:8]


def _top_candidate_sentence(narratives: list[dict[str, Any]]) -> str:
    if not narratives:
        return "当前还没有可解读的 Top 分子。"
    top = narratives[0]
    return f"当前首位候选为 {top.get('molecule_id')}，解释层摘要为：{top.get('summary')}"


def _docking_ref_summary(docking: dict[str, Any]) -> str:
    if docking.get("vina_score") is not None:
        return f"Vina score {_format_number(docking.get('vina_score'), digits=2)}"
    if docking.get("diffdock_confidence") is not None:
        return f"DiffDock confidence {_format_number(docking.get('diffdock_confidence'), digits=2)}"
    return "存在 docking 结果。"


def _admet_ref_summary(admet: dict[str, Any]) -> str:
    herg = (admet.get("hERG") or {}).get("risk")
    ames = (admet.get("Ames") or {}).get("risk")
    parts = []
    if herg:
        parts.append(f"hERG={herg}")
    if ames:
        parts.append(f"Ames={ames}")
    if admet.get("admet_risk_score") is not None:
        parts.append(f"risk_score={_format_number(admet.get('admet_risk_score'), digits=2)}")
    return "ADMET " + ", ".join(parts) if parts else "存在 ADMET 预测结果。"


def _synthesis_ref_summary(synthesis: dict[str, Any]) -> str:
    if synthesis.get("route_found"):
        return f"找到路线，步数 {synthesis.get('route_steps') or '未知'}。"
    if synthesis.get("estimated_route_feasible"):
        return "启发式合成可行性估计为可行。"
    if synthesis.get("SA_score") is not None:
        return f"SA score {_format_number(synthesis.get('SA_score'), digits=2)}。"
    return "存在合成可行性评估。"


def _generation_method_from_labels(molecule: Molecule) -> str | None:
    for label in molecule.labels or []:
        if label.startswith("generator_strategy_"):
            return label.removeprefix("generator_strategy_")
    return molecule.source_agent


def _first_label_or_default(labels: Any, default: str) -> str:
    if isinstance(labels, list) and labels:
        return str(labels[0])
    return default


def _short_text(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: Any, *, digits: int) -> str:
    parsed = _as_float(value)
    if parsed is None:
        return "未评分"
    return f"{parsed:.{digits}f}"


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value in deduped:
            continue
        deduped.append(value)
    return deduped
