"""增强的自我反驳服务 - 引入 LLM 反驳但限制只能引用数据库证据。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from medagent.core.config import get_settings
from medagent.db.models import (
    ADMETResult,
    DockingResult,
    EvidenceLink,
    Molecule,
    Project,
    RagChunk,
    RuleFilterResult,
    SynthesisRoute,
)
from medagent.llm.client import LLMClient, LLMMessage, get_llm_client


def generate_llm_critique(
    db: Session,
    project: Project,
    molecule: Molecule,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """使用 LLM 生成分子的反驳意见，但仅引用数据库已有证据。

    Args:
        db: 数据库会话
        project: 项目对象
        molecule: 分子对象
        llm_client: LLM 客户端

    Returns:
        反驳意见字典
    """
    client = llm_client or get_llm_client()
    settings = get_settings()
    provider = settings.self_refutation_provider
    model = settings.self_refutation_model

    # 收集数据库证据
    evidence = _collect_molecule_evidence(db, project, molecule)

    # 如果没有足够证据，返回空反驳
    if not _has_sufficient_evidence(evidence):
        return {
            "molecule_id": molecule.molecule_id,
            "has_critique": False,
            "reason": "insufficient_evidence",
            "message": "数据库中尚无足够评估证据，无法生成反驳意见",
        }

    # 构建 LLM 提示词
    prompt = _build_critique_prompt(project, molecule, evidence)

    # 调用 LLM
    try:
        messages = [
            LLMMessage(role="system", content="你是一个严谨的药物化学专家，负责对候选分子进行批判性评估。"),
            LLMMessage(role="user", content=prompt),
        ]

        response = client.complete(
            messages=messages,
            provider=provider,
            model=model,
            temperature=0.3,
            max_tokens=1000,
        )

        critique_text = response.content.strip()

        # 解析反驳意见
        critique = _parse_critique_response(critique_text, evidence)

        return {
            "molecule_id": molecule.molecule_id,
            "has_critique": True,
            "critique": critique,
            "evidence_sources": _list_evidence_sources(evidence),
            "llm_provider": provider,
            "llm_model": model,
        }

    except Exception as e:
        return {
            "molecule_id": molecule.molecule_id,
            "has_critique": False,
            "reason": "llm_error",
            "message": f"LLM 调用失败: {str(e)}",
            "llm_provider": provider,
            "llm_model": model,
        }


def _collect_molecule_evidence(
    db: Session,
    project: Project,
    molecule: Molecule,
) -> dict[str, Any]:
    """收集分子的所有数据库证据。"""
    evidence: dict[str, Any] = {
        "molecule": {
            "molecule_id": molecule.molecule_id,
            "smiles": molecule.smiles,
            "status": molecule.status,
            "labels": molecule.labels or [],
            "source_agent": molecule.source_agent,
        }
    }

    # 规则过滤结果
    rule_query = db.query(RuleFilterResult).filter_by(molecule_id=molecule.molecule_id)
    if molecule.round_id:
        rule_query = rule_query.filter(RuleFilterResult.round_id == molecule.round_id)
    rule_filters = rule_query.all()
    if rule_filters:
        evidence["rule_filters"] = [
            {
                "rule_set": result.rule_set,
                "decision": result.decision,
                "failed_rules": result.failed_rules or [],
                "warnings": result.warnings or [],
                "properties": result.properties_snapshot or {},
            }
            for result in rule_filters
        ]

    # 对接结果
    docking_query = db.query(DockingResult).filter_by(molecule_id=molecule.molecule_id)
    if molecule.round_id:
        docking_query = docking_query.filter(DockingResult.round_id == molecule.round_id)
    docking_results = docking_query.all()
    if docking_results:
        evidence["docking"] = [
            {
                "tool": (result.raw_output or {}).get("tool_name")
                or result.tool_run_id
                or "docking",
                "vina_score": result.vina_score,
                "cnn_score": result.cnn_score,
                "diffdock_confidence": result.diffdock_confidence,
                "key_hbond_count": result.key_hbond_count,
                "clash_count": result.clash_count,
                "labels": result.labels or [],
            }
            for result in docking_results
        ]

    # ADMET 结果
    admet_query = db.query(ADMETResult).filter_by(molecule_id=molecule.molecule_id)
    if molecule.round_id:
        admet_query = admet_query.filter(ADMETResult.round_id == molecule.round_id)
    admet_results = admet_query.all()
    if admet_results:
        evidence["admet"] = [
            {
                "tool": (result.raw_output or {}).get("tool_name") or "admet",
                "properties": {
                    "hERG_probability": result.hERG_probability,
                    "hERG_risk": result.hERG_risk,
                    "Ames_probability": result.Ames_probability,
                    "Ames_risk": result.Ames_risk,
                    "solubility": result.solubility,
                    "permeability": result.permeability,
                    "admet_risk_score": result.admet_risk_score,
                },
                "warnings": result.labels or [],
            }
            for result in admet_results
        ]

    # 合成路线
    synthesis_query = db.query(SynthesisRoute).filter_by(molecule_id=molecule.molecule_id)
    if molecule.round_id:
        synthesis_query = synthesis_query.filter(SynthesisRoute.round_id == molecule.round_id)
    synthesis_routes = synthesis_query.all()
    if synthesis_routes:
        evidence["synthesis"] = [
            {
                "tool": (result.route_json or {}).get("tool_name") or "synthesis",
                "route_found": result.route_found,
                "route_steps": result.route_steps,
                "route_confidence": result.route_confidence,
                "buyable_building_blocks": result.buyable_building_blocks,
                "warnings": result.labels or [],
            }
            for result in synthesis_routes
        ]

    # RAG 证据链接
    evidence_links = db.query(EvidenceLink).filter_by(
        molecule_id=molecule.molecule_id
    ).all()
    if evidence_links:
        rag_evidence = []
        for link in evidence_links:
            if link.chunk_id:
                chunk = db.query(RagChunk).filter_by(chunk_id=link.chunk_id).first()
                if chunk:
                    rag_evidence.append({
                        "claim_type": link.claim_type,
                        "confidence": link.confidence,
                        "rationale": link.rationale,
                        "chunk_content": chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
                    })
        if rag_evidence:
            evidence["rag_evidence"] = rag_evidence

    return evidence


def _has_sufficient_evidence(evidence: dict[str, Any]) -> bool:
    """检查是否有足够的证据生成反驳。"""
    # 至少需要对接或 ADMET 或合成评估之一
    return any(
        key in evidence
        for key in ["docking", "admet", "synthesis", "rule_filters"]
    )


def _build_critique_prompt(
    project: Project,
    molecule: Molecule,
    evidence: dict[str, Any],
) -> str:
    """构建 LLM 反驳提示词。"""
    import json

    prompt_parts = [
        "# 分子批判性评估任务",
        "",
        "## 项目背景",
        f"- 项目目标：{project.objective or '未指定'}",
        f"- 靶点：{project.target_id}",
        "",
        "## 候选分子信息",
        f"- 分子 ID：{molecule.molecule_id}",
        f"- SMILES：{molecule.smiles}",
        f"- 来源：{molecule.source_agent}",
        f"- 状态：{molecule.status}",
        "",
        "## 数据库评估证据",
        "",
    ]

    # 添加规则过滤证据
    if "rule_filters" in evidence:
        prompt_parts.append("### 规则过滤结果")
        for rule in evidence["rule_filters"]:
            detail = ", ".join(rule["failed_rules"] or rule["warnings"]) or "无异常"
            prompt_parts.append(
                f"- {rule['rule_set']}: {rule['decision']} - {detail}"
            )
        prompt_parts.append("")

    # 添加对接证据
    if "docking" in evidence:
        prompt_parts.append("### 对接评估结果")
        for dock in evidence["docking"]:
            prompt_parts.append(
                f"- {dock['tool']}: Vina {dock['vina_score']}, CNN {dock['cnn_score']}, "
                f"氢键 {dock['key_hbond_count']}, 冲突 {dock['clash_count']}"
            )
        prompt_parts.append("")

    # 添加 ADMET 证据
    if "admet" in evidence:
        prompt_parts.append("### ADMET 评估结果")
        for admet in evidence["admet"]:
            prompt_parts.append(f"- 工具: {admet['tool']}")
            if admet["warnings"]:
                prompt_parts.append(f"  警告: {', '.join(admet['warnings'])}")
            if admet["properties"]:
                prompt_parts.append(f"  性质: {json.dumps(admet['properties'], ensure_ascii=False)}")
        prompt_parts.append("")

    # 添加合成证据
    if "synthesis" in evidence:
        prompt_parts.append("### 合成可行性评估")
        for synth in evidence["synthesis"]:
            prompt_parts.append(
                f"- {synth['tool']}: 路线 {synth['route_found']}, "
                f"步数 {synth['route_steps']}, 置信度 {synth['route_confidence']}"
            )
        prompt_parts.append("")

    # 添加 RAG 证据
    if "rag_evidence" in evidence:
        prompt_parts.append("### 文献/知识库证据")
        for rag in evidence["rag_evidence"]:
            prompt_parts.append(
                f"- {rag['claim_type']}: {rag['rationale']} (置信度 {rag['confidence']})"
            )
        prompt_parts.append("")

    # 任务说明
    prompt_parts.extend([
        "## 任务要求",
        "",
        "请基于以上**数据库中已有的评估证据**，对该候选分子进行批判性评估：",
        "",
        "1. **主要风险点**：指出该分子存在的主要问题（如对接评分差、ADMET 风险高、合成困难等）",
        "2. **证据支持**：每个风险点必须引用上述数据库证据，不得编造",
        "3. **严重程度**：评估风险是致命性的（应淘汰）还是可改进的（可优化）",
        "4. **改进建议**：如果可改进，给出具体的优化方向",
        "",
        "输出格式：",
        "```",
        "主要风险：",
        "1. [风险描述] - 证据：[引用具体评估结果]",
        "2. ...",
        "",
        "严重程度：[致命/中等/轻微]",
        "",
        "改进建议：",
        "[具体建议]",
        "```",
        "",
        "注意：只能引用上述数据库证据，不得基于推测或外部知识添加风险点。",
    ])

    return "\n".join(prompt_parts)


def _parse_critique_response(critique_text: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """解析 LLM 反驳响应。"""
    # 简单解析，提取关键信息
    lines = critique_text.split("\n")

    risks = []
    severity = "medium"
    suggestions = []

    in_risks_section = False
    in_suggestions_section = False

    for line in lines:
        line = line.strip()

        if "主要风险" in line or "风险点" in line:
            in_risks_section = True
            in_suggestions_section = False
            continue
        elif "严重程度" in line:
            in_risks_section = False
            if "致命" in line:
                severity = "critical"
            elif "轻微" in line:
                severity = "minor"
            continue
        elif "改进建议" in line or "优化建议" in line:
            in_suggestions_section = True
            in_risks_section = False
            continue

        if in_risks_section and line and (line[0].isdigit() or line.startswith("-")):
            risks.append(line.lstrip("0123456789.-) "))
        elif in_suggestions_section and line:
            suggestions.append(line.lstrip("-• "))

    return {
        "risks": risks,
        "severity": severity,
        "suggestions": suggestions,
        "full_text": critique_text,
    }


def _list_evidence_sources(evidence: dict[str, Any]) -> list[str]:
    """列出所有证据来源。"""
    sources = []

    if "rule_filters" in evidence:
        sources.append("rule_filter")
    if "docking" in evidence:
        sources.extend([f"docking_{d['tool']}" for d in evidence["docking"]])
    if "admet" in evidence:
        sources.extend([f"admet_{a['tool']}" for a in evidence["admet"]])
    if "synthesis" in evidence:
        sources.extend([f"synthesis_{s['tool']}" for s in evidence["synthesis"]])
    if "rag_evidence" in evidence:
        sources.append("rag_evidence")

    return sources
