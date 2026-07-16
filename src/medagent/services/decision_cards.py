from dataclasses import dataclass

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    ConformerResult,
    DecisionCard,
    DockingResult,
    Molecule,
    MoleculeProperty,
    Project,
    Ranking,
    ReasoningTrace,
    RuleFilterResult,
    SynthesisRoute,
)
from medagent.services.ids import new_id


TRACE_TYPE = "molecule_validation_decision"
CARD_TYPE = "molecule_validation_decision"
SOURCE_AGENT = "decision_card_generator"
VALIDATED_OR_LATER_STATUSES = {
    "structure_validated",
    "passed_filter",
    "failed_filter",
    "candidate_assessed",
    "failed_assessment",
    "rejected_by_ranking",
}
ASSESSMENT_STATUSES = {"candidate_assessed", "failed_assessment", "rejected_by_ranking"}
VALIDATION_COMPLETE_LABELS = {
    "light_validation_passed",
    "rdkit_validation_passed",
    "datamol_standardized",
    "structure_standardized",
}


@dataclass
class DecisionBlueprint:
    title: str
    decision: str
    summary: str
    claim: str
    support: list[str]
    risk: list[str]
    next_steps: list[str]
    uncertainty: str
    confidence: float | None
    evidence_ids: list[str]
    provenance: dict


@dataclass
class DecisionEvidence:
    properties: MoleculeProperty | None = None
    rule_filter: RuleFilterResult | None = None
    conformer: ConformerResult | None = None
    docking: DockingResult | None = None
    admet: ADMETResult | None = None
    synthesis: SynthesisRoute | None = None
    ranking: Ranking | None = None


def generate_project_decision_cards(db: Session, project: Project) -> dict:
    molecules = (
        db.query(Molecule)
        .filter_by(project_id=project.project_id)
        .order_by(Molecule.id.asc())
        .all()
    )
    trace_ids: list[str] = []
    decision_card_ids: list[str] = []

    for molecule in molecules:
        evidence = load_decision_evidence(db, project, molecule)
        blueprint = build_decision_blueprint(project, molecule, evidence)
        apply_evidence_semantics(blueprint, molecule, evidence)
        trace = upsert_reasoning_trace(db, project, molecule, blueprint)
        db.flush()
        card = upsert_decision_card(db, project, molecule, trace, blueprint)
        trace_ids.append(trace.trace_id)
        decision_card_ids.append(card.decision_id)

    db.commit()
    return {
        "generated_count": len(decision_card_ids),
        "trace_count": len(trace_ids),
        "decision_card_ids": decision_card_ids,
        "trace_ids": trace_ids,
    }


def load_decision_evidence(db: Session, project: Project, molecule: Molecule) -> DecisionEvidence:
    return DecisionEvidence(
        properties=db.query(MoleculeProperty).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        rule_filter=db.query(RuleFilterResult).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        conformer=db.query(ConformerResult).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        docking=db.query(DockingResult).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        admet=db.query(ADMETResult).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        synthesis=db.query(SynthesisRoute).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        ranking=(
            db.query(Ranking)
            .filter_by(project_id=project.project_id, molecule_id=molecule.molecule_id)
            .one_or_none()
        ),
    )


def apply_evidence_semantics(
    blueprint: DecisionBlueprint,
    molecule: Molecule,
    evidence: DecisionEvidence,
) -> None:
    substantive_records = [
        evidence.properties,
        evidence.rule_filter,
        evidence.conformer,
        evidence.docking,
        evidence.admet,
        evidence.synthesis,
        evidence.ranking,
    ]
    has_validation_result = bool(
        molecule.status in VALIDATED_OR_LATER_STATUSES
        or molecule.status == "invalid_structure"
        or set(molecule.labels or []).intersection(VALIDATION_COMPLETE_LABELS)
    )
    evidence_supported = has_validation_result or any(
        record is not None for record in substantive_records
    )
    claim_status = "evidence_supported" if evidence_supported else "hypothesis"
    blueprint.provenance = {
        **blueprint.provenance,
        "claim_status": claim_status,
        "confidence_semantics": (
            "heuristic_not_probability" if evidence_supported else "not_calibrated"
        ),
        "evidence_scope": "computational_or_database_records_not_experimental",
        "substantive_evidence_count": sum(
            record is not None for record in substantive_records
        ),
    }
    if not evidence_supported:
        blueprint.confidence = None


def build_decision_blueprint(
    project: Project,
    molecule: Molecule,
    evidence: DecisionEvidence,
) -> DecisionBlueprint:
    evidence_ids = [f"DB:MOL:{molecule.molecule_id}"]
    records = [{"table": "molecules", "id": molecule.molecule_id}]
    tool_outputs: list[str] = []
    properties = evidence.properties
    if properties is not None:
        evidence_ids.append(f"DB:PROP:{molecule.molecule_id}")
        records.append({"table": "molecule_properties", "id": molecule.molecule_id})
        validator = (properties.tool_metadata or {}).get("validator")
        if validator:
            tool_outputs.append(validator)
    if evidence.rule_filter is not None:
        evidence_ids.append(f"DB:RULE_FILTER:{molecule.molecule_id}")
        records.append({"table": "rule_filter_results", "id": molecule.molecule_id})
    if evidence.conformer is not None:
        evidence_ids.append(f"DB:CONFORMER:{molecule.molecule_id}")
        records.append({"table": "conformer_results", "id": molecule.molecule_id})
    if evidence.docking is not None:
        evidence_ids.append(f"DB:DOCKING:{molecule.molecule_id}")
        records.append({"table": "docking_results", "id": molecule.molecule_id})
    if evidence.admet is not None:
        evidence_ids.append(f"DB:ADMET:{molecule.molecule_id}")
        records.append({"table": "admet_results", "id": molecule.molecule_id})
    if evidence.synthesis is not None:
        evidence_ids.append(f"DB:SYNTHESIS:{molecule.molecule_id}")
        records.append({"table": "synthesis_routes", "id": molecule.molecule_id})
    if evidence.ranking is not None:
        evidence_ids.append(f"DB:RANK:{molecule.molecule_id}")
        records.append({"table": "rankings", "id": molecule.molecule_id})

    provenance = {
        "basis": "database_records",
        "records": records,
        "tool_outputs": tool_outputs,
        "rag_evidence_available": False,
        "target_id": project.target_id,
    }

    labels = molecule.labels or []
    validation_complete = _has_structure_validation_evidence(molecule, evidence)
    support_label_factors, risk_label_factors = _label_factor_buckets(labels, validation_complete)
    descriptor_factors = _descriptor_support_factors(properties)

    if molecule.status == "invalid_structure":
        support = [f"status={molecule.status}", *support_label_factors]
        risk = [
            *risk_label_factors,
            "该分子当前标记为结构无效，不能进入下游排序。",
            "结构修正前不应使用其化学描述符做可靠判断。",
        ]
        if properties is None:
            risk.append("尚未生成分子性质记录。")
        return DecisionBlueprint(
            title="结构异常，暂不推进",
            decision="reject_for_structure",
            summary=(
                "当前结构验证阶段将该分子标记为无效结构，需要修正或移除后再进入规则过滤和排序。"
            ),
            claim="该分子暂不具备进入下游药物设计流程的条件。",
            support=support,
            risk=risk,
            next_steps=[
                "修正或替换 SMILES 记录。",
                "修正后重新运行结构验证。",
            ],
            uncertainty="当前淘汰依据来自结构验证记录，修正结构后结论可能变化。",
            confidence=0.72,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    if molecule.status in ASSESSMENT_STATUSES:
        return _assessment_blueprint(
            project=project,
            molecule=molecule,
            evidence=evidence,
            support=_assessment_support_factors(molecule, evidence),
            risk=_assessment_risk_factors(molecule, evidence),
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    if molecule.status == "failed_filter":
        return DecisionBlueprint(
            title="规则过滤未通过",
            decision="reject_by_rule_filter",
            summary=(
                "该分子已有结构与性质证据，但药物化学规则过滤记录了阻断性问题。"
            ),
            claim="规则过滤失败项解决前，该分子不应继续推进。",
            support=[f"status={molecule.status}", *support_label_factors, *descriptor_factors],
            risk=[
                *risk_label_factors,
                *_rule_filter_risk_factors(evidence.rule_filter),
            ],
            next_steps=[
                "复核 Lipinski、Veber、PAINS、Brenk 或反应性基团等失败规则。",
                "重新生成或编辑骨架，移除阻断性结构片段。",
            ],
            uncertainty="规则过滤是启发式筛选，仍需结合靶点背景复核。",
            confidence=0.66,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    if molecule.status == "passed_filter":
        return DecisionBlueprint(
            title="进入候选评估",
            decision="advance_to_candidate_assessment",
            summary=(
                "该分子已有结构/性质证据并通过规则过滤，可以进入构象、对接、ADMET、合成和排序评估。"
            ),
            claim="该分子可以进入综合候选评估。",
            support=[
                f"status={molecule.status}",
                *support_label_factors,
                *descriptor_factors,
                *_rule_filter_support_factors(evidence.rule_filter),
            ],
            risk=[*risk_label_factors, *_rule_filter_risk_factors(evidence.rule_filter)],
            next_steps=[
                "运行候选评估，生成构象、对接、ADMET、合成和排序证据。",
                "将结果与项目约束和靶点特异证据进行对照。",
            ],
            uncertainty="规则过滤通过不等于已确认结合、ADMET 安全性或合成可行性。",
            confidence=0.64,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    if molecule.status == "structure_validated":
        support = [f"status={molecule.status}", *support_label_factors, *descriptor_factors]

        risk = [*risk_label_factors]
        if "needs_rdkit_validation" in labels:
            risk.append("RDKit 级标准化和验证仍待完成。")
        if properties is None:
            risk.append("尚未生成描述符记录。")
        else:
            metadata = properties.tool_metadata or {}
            if metadata.get("validator") == "rdkit":
                risk.append("RDKit 描述符尚不包含对接或 ADMET 证据。")
            if properties.logp is None:
                risk.append("LogP 暂不可用。")
            if properties.tpsa is None:
                risk.append("TPSA 暂不可用。")

        return DecisionBlueprint(
            title="进入规则过滤",
            decision="advance_to_rule_filter",
            summary=(
                "该分子已通过结构检查并具备初步性质记录，可以进入下一步药物化学规则过滤。"
            ),
            claim="该分子可以进入基础药物化学规则过滤。",
            support=support,
            risk=risk,
            next_steps=[
                "运行 RDKit 或 Datamol 标准化。",
                "应用 Lipinski、Veber、PAINS、Brenk 和反应性基团过滤规则。",
            ],
            uncertainty=(
                "当前描述符可能仍是轻量估计，正式科学判断前应以 RDKit 计算结果刷新。"
            ),
            confidence=0.58,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    if validation_complete:
        return DecisionBlueprint(
            title="进入规则过滤",
            decision="advance_to_rule_filter",
            summary=(
                "该分子已有验证或性质证据，虽然流程状态尚未完全对齐到标准结构验证状态。"
            ),
            claim="该分子已有足够结构证据进入规则过滤。",
            support=[f"status={molecule.status}", *support_label_factors, *descriptor_factors],
            risk=[
                *risk_label_factors,
                "流程状态需要与已记录的验证证据保持一致。",
            ],
            next_steps=[
                "运行规则过滤，或根据已记录的验证输出刷新分子状态。",
            ],
            uncertainty="当前卡片依赖数据库证据判断，因为状态与标签尚未完全一致。",
            confidence=0.55,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    return DecisionBlueprint(
        title="需要结构验证",
        decision="needs_structure_validation",
        summary=(
            "该分子已进入项目候选池，但尚未记录结构验证结论。"
        ),
        claim="该分子需要先完成结构验证，之后才能进行化学判断。",
        support=[f"status={molecule.status}", *support_label_factors],
        risk=["尚无结构验证或性质记录。"],
        next_steps=[f"调用 POST /projects/{project.project_id}/molecules/validate。"],
        uncertainty="结构验证完成前不应做正式化学决策。",
        confidence=0.4,
        evidence_ids=evidence_ids,
        provenance=provenance,
    )


def _assessment_support_factors(molecule: Molecule, evidence: DecisionEvidence) -> list[str]:
    factors: list[str] = [f"流程状态：{_status_cn(molecule.status)}。"]

    if evidence.properties is not None:
        metadata = evidence.properties.tool_metadata or {}
        hbd = evidence.properties.hbd if evidence.properties.hbd is not None else "-"
        hba = evidence.properties.hba if evidence.properties.hba is not None else "-"
        descriptor_parts = [
            f"MW {_fmt_number(evidence.properties.mw)}",
            f"LogP {_fmt_number(evidence.properties.logp)}",
            f"TPSA {_fmt_number(evidence.properties.tpsa)}",
            f"HBD/HBA {hbd}/{hba}",
        ]
        rotatable_bond_count = metadata.get("rotatable_bond_count")
        if rotatable_bond_count is not None:
            descriptor_parts.append(f"RotB {rotatable_bond_count}")
        qed = metadata.get("qed")
        if qed is not None:
            descriptor_parts.append(f"QED {_fmt_number(qed, 3)}")
        factors.append("结构与理化性质：" + "，".join(descriptor_parts) + "。")

    if evidence.rule_filter is not None:
        decision = "通过" if evidence.rule_filter.decision in {"passed", "passed_with_warnings"} else evidence.rule_filter.decision
        warning_count = len(evidence.rule_filter.warnings or [])
        warning_text = f"，{warning_count} 条提示" if warning_count else ""
        factors.append(f"规则过滤：{decision}（{evidence.rule_filter.rule_set}{warning_text}）。")

    docking_parts: list[str] = []
    if evidence.conformer is not None:
        conformer_text = "构象生成成功" if evidence.conformer.conformer_generated else "构象生成未完成"
        if evidence.conformer.lowest_energy is not None:
            conformer_text += f"，最低能量 {_fmt_number(evidence.conformer.lowest_energy)}"
        docking_parts.append(conformer_text)
    if evidence.docking is not None:
        if evidence.docking.vina_score is not None:
            docking_parts.append(f"Vina {_fmt_number(evidence.docking.vina_score)}")
        if evidence.docking.cnn_score is not None:
            docking_parts.append(f"GNINA CNN {_fmt_number(evidence.docking.cnn_score)}")
        if evidence.docking.diffdock_confidence is not None:
            docking_parts.append(
                f"DiffDock confidence {_fmt_number(evidence.docking.diffdock_confidence)}"
            )
        if evidence.docking.key_hbond_count is not None:
            docking_parts.append(f"关键氢键 {evidence.docking.key_hbond_count} 个")
    if docking_parts:
        factors.append("构象与对接：" + "，".join(docking_parts) + "。")

    if evidence.admet is not None:
        admet_parts = []
        if evidence.admet.hERG_risk:
            admet_parts.append(f"hERG {_risk_cn(evidence.admet.hERG_risk)}")
        if evidence.admet.Ames_risk:
            admet_parts.append(f"Ames {_risk_cn(evidence.admet.Ames_risk)}")
        if evidence.admet.admet_risk_score is not None:
            admet_parts.append(f"综合风险 {_fmt_number(evidence.admet.admet_risk_score, 3)}")
        if admet_parts:
            factors.append("ADMET：" + "，".join(admet_parts) + "。")

    if evidence.synthesis is not None:
        route_text = "找到可行路线" if evidence.synthesis.route_found else "未找到可靠路线"
        synthesis_parts = [route_text]
        if evidence.synthesis.route_steps is not None:
            synthesis_parts.append(f"{evidence.synthesis.route_steps} 步")
        if evidence.synthesis.route_confidence is not None:
            synthesis_parts.append(f"路线置信度 {_fmt_number(evidence.synthesis.route_confidence, 3)}")
        if evidence.synthesis.buyable_building_blocks is not None:
            synthesis_parts.append(f"可购买砌块 {evidence.synthesis.buyable_building_blocks} 个")
        factors.append("合成可行性：" + "，".join(synthesis_parts) + "。")

    if evidence.ranking is not None:
        ranking_parts = [
            f"第 {evidence.ranking.rank} 名",
            f"总分 {_fmt_number(evidence.ranking.overall_score)}",
            f"证据置信度 {_fmt_number(evidence.ranking.evidence_confidence, 3)}",
            f"排序结论为{_ranking_decision_cn(evidence.ranking.final_decision)}",
        ]
        factors.append("综合排名：" + "，".join(ranking_parts) + "。")

    return _dedupe(factors)


def _assessment_risk_factors(molecule: Molecule, evidence: DecisionEvidence) -> list[str]:
    labels = set(molecule.labels or [])
    risks: list[str] = []

    docking_labels = set(evidence.docking.labels or []) if evidence.docking is not None else set()
    has_external_docking = "external_docking_adapter_used" in docking_labels
    all_docking_labels = docking_labels | labels
    if "stereo_undefined" in labels:
        risks.append("立体化学未完全定义，推进前需要确认目标异构体。")
    if "external_docking_setup_incomplete" in all_docking_labels and not has_external_docking:
        missing_parts = []
        if "external_docking_receptor_missing" in all_docking_labels:
            missing_parts.append("受体文件")
        if "external_docking_grid_missing" in all_docking_labels:
            missing_parts.append("对接网格")
        missing_text = "和".join(missing_parts) if missing_parts else "必要输入"
        risks.append(f"外部对接未执行：缺少{missing_text}，当前对接证据来自替代模型。")
    elif "external_docking_tools_unavailable" in all_docking_labels and not has_external_docking:
        risks.append("外部对接工具当前不可用，当前对接证据来自替代模型。")
    elif "external_docking_adapter_pending" in docking_labels or (
        "external_docking_adapter_pending" in labels and not has_external_docking
    ):
        risks.append("外部对接工具尚未接入，当前对接证据来自替代模型。")
    if "docking_weak" in docking_labels or ("docking_weak" in labels and not has_external_docking):
        if has_external_docking:
            risks.append("外部对接分数偏弱，需要人工检查姿态或使用更严格对接协议复核。")
        else:
            risks.append("对接信号偏弱，需要用外部对接或人工检查姿态确认。")
    if evidence.docking is not None and (evidence.docking.clash_count or 0) > 0:
        risks.append(f"对接姿态存在 {evidence.docking.clash_count} 个碰撞，需要复核。")

    if evidence.admet is not None:
        if evidence.admet.hERG_risk == "high_risk":
            risks.append("hERG 预测为高风险。")
        elif evidence.admet.hERG_risk == "medium_risk":
            risks.append("hERG 预测为中等风险。")
        if evidence.admet.Ames_risk == "high_risk":
            risks.append("Ames 致突变性预测为高风险。")
        elif evidence.admet.Ames_risk == "medium_risk":
            risks.append("Ames 致突变性预测为中等风险。")

    if evidence.synthesis is not None:
        synthesis_labels = set(evidence.synthesis.labels or [])
        has_external_synthesis = "external_retrosynthesis_adapter_used" in synthesis_labels
        if "external_retrosynthesis_adapter_pending" in synthesis_labels or (
            "external_retrosynthesis_adapter_pending" in labels and not has_external_synthesis
        ):
            risks.append("外部逆合成工具尚未接入，当前路线来自替代合成评估。")
        if not evidence.synthesis.route_found:
            risks.append("未找到可信合成路线。")
        route_json = evidence.synthesis.route_json or {}
        for route_risk in route_json.get("route_risks", []):
            normalized = str(route_risk).strip()
            if _is_non_risk_route_note(normalized):
                continue
            risks.append(f"合成路线提示：{normalized}")

    if evidence.rule_filter is not None:
        for failed_rule in evidence.rule_filter.failed_rules or []:
            risks.append(f"规则过滤失败：{failed_rule}")
        for warning in evidence.rule_filter.warnings or []:
            risks.append(f"规则过滤提示：{warning}")

    if evidence.ranking is None:
        risks.append("尚未生成排序记录，综合优先级不完整。")

    return _dedupe(risks)


def _assessment_blueprint(
    project: Project,
    molecule: Molecule,
    evidence: DecisionEvidence,
    support: list[str],
    risk: list[str],
    evidence_ids: list[str],
    provenance: dict,
) -> DecisionBlueprint:
    labels = set(molecule.labels or [])
    ranking_decision = evidence.ranking.final_decision if evidence.ranking is not None else None
    decision_signal = ranking_decision or _ranking_label_signal(labels)

    if molecule.status == "failed_assessment" or "assessment_failed" in labels:
        return DecisionBlueprint(
            title="暂缓推进候选物",
            decision="reject_after_assessment",
            summary=(
                "该分子已完成前置结构处理，但候选评估记录了阻断因素，暂不适合作为推进候选。"
            ),
            claim="该分子需要先解决评估阻断因素，再考虑进入下一轮优化。",
            support=support,
            risk=risk or ["候选评估阶段标记为未通过。"],
            next_steps=[
                "核查对接姿态、ADMET 和合成路线中的阻断因素。",
                "将阻断因素转化为下一轮生成或结构改造约束。",
            ],
            uncertainty="当前评估混合了替代模型和可用外部工具输出，需要结合人工复核。",
            confidence=0.7,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    if molecule.status == "rejected_by_ranking" or decision_signal == "reject":
        return DecisionBlueprint(
            title="淘汰排序候选物",
            decision="reject_ranked_candidate",
            summary=(
                "该分子已进入排序阶段，但综合排序结论不支持继续推进。"
            ),
            claim="该分子应被淘汰或重新设计后再进入后续投入。",
            support=support,
            risk=risk or ["排序器给出淘汰结论。"],
            next_steps=[
                "查看排序分数拆解和反证证据。",
                "把主要扣分项加入下一轮生成约束。",
            ],
            uncertainty="排序结论仍依赖启发式模型，若有更强外部或实验数据应重新评估。",
            confidence=0.72,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    if decision_signal == "deprioritize":
        return DecisionBlueprint(
            title="降低优先级候选物",
            decision="deprioritize_ranked_candidate",
            summary=(
                "该分子已完成候选评估，但综合证据不足以支持近期优先推进。"
            ),
            claim="该分子应排在证据更强的候选物之后。",
            support=support,
            risk=risk or ["排序器给出降低优先级结论。"],
            next_steps=[
                "与排名更高的候选物比较分数拆解。",
                "仅保留能解决项目约束的有用子结构。",
            ],
            uncertainty="补充更强对接、ADMET 或合成证据后，优先级仍可能变化。",
            confidence=0.68,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    if decision_signal == "watch":
        return DecisionBlueprint(
            title="观察候选物",
            decision="watch_ranked_candidate",
            summary=(
                "该分子已完成候选评估，具备保留观察价值，但当前证据还不足以明确推进。"
            ),
            claim="该分子适合进入观察列表，等待更强证据确认。",
            support=support,
            risk=risk or ["排序器给出观察结论。"],
            next_steps=[
                "补充外部对接、ADMET 或合成可行性证据。",
                "比较近邻类似物，寻找风险更干净的替代结构。",
            ],
            uncertainty="观察状态对证据置信度和项目取舍较敏感。",
            confidence=0.66,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    if decision_signal == "reserve":
        return DecisionBlueprint(
            title="储备候选物",
            decision="reserve_ranked_candidate",
            summary=(
                "该分子已完成候选评估，可作为备选保留，等待更高优先级候选物进一步确认。"
            ),
            claim="该分子是储备候选物，不是当前最优先推进对象。",
            support=support,
            risk=risk or ["排序器给出储备结论。"],
            next_steps=[
                "保留为后续比较的备选候选物。",
                "在补充证据或生成新类似物后刷新排序。",
            ],
            uncertainty="储备状态会随候选集合和证据置信度变化。",
            confidence=0.64,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    return DecisionBlueprint(
        title="推进优化候选物",
        decision="advance_ranked_candidate",
        summary=(
            "该分子已完成结构验证、规则过滤、候选评估和排序，可作为下一轮优化或专家复核的优先候选。"
        ),
        claim="该分子可以进入下一轮优化或复核，但仍需补充外部工具证据后再做最终化学决策。",
        support=support,
        risk=risk,
        next_steps=[
            "结合对接、ADMET、合成路线和排序拆解复核该 Top 候选物。",
            "在正式提名前补跑外部对接、ADMET 或逆合成工具。",
            "围绕风险项设计类似物优化或实验验证计划。",
        ],
        uncertainty="当证据仍包含替代模型或外部工具待接入项时，该推荐应视为条件推进。",
        confidence=0.76,
        evidence_ids=evidence_ids,
        provenance=provenance,
    )


def _has_structure_validation_evidence(molecule: Molecule, evidence: DecisionEvidence) -> bool:
    labels = set(molecule.labels or [])
    return bool(
        evidence.properties is not None
        or molecule.status in VALIDATED_OR_LATER_STATUSES
        or labels.intersection(VALIDATION_COMPLETE_LABELS)
    )


def _label_factor_buckets(labels: list[str], validation_complete: bool) -> tuple[list[str], list[str]]:
    support: list[str] = []
    risk: list[str] = []
    label_set = set(labels)
    for label in labels:
        if _is_stale_validation_label(label, label_set, validation_complete):
            continue
        factor = f"label={label}"
        if _is_risk_label(label):
            risk.append(factor)
        else:
            support.append(factor)
    return support, risk


def _is_stale_validation_label(label: str, labels: set[str], validation_complete: bool) -> bool:
    if label == "requires_structure_validation" and validation_complete:
        return True
    if label == "needs_rdkit_validation" and labels.intersection(
        {"rdkit_validation_passed", "datamol_standardized", "structure_standardized"}
    ):
        return True
    return False


def _is_risk_label(label: str) -> bool:
    risk_tokens = [
        "pending",
        "weak",
        "failed",
        "failure",
        "invalid",
        "blocker",
        "bad_pose",
        "high_risk",
        "medium_risk",
        "route_not_found",
        "hard_to_synthesize",
        "too_many_steps",
        "hazardous",
        "unavailable",
        "reject",
        "deprioritize",
        "warning",
    ]
    return any(token in label for token in risk_tokens)


def _descriptor_support_factors(properties: MoleculeProperty | None) -> list[str]:
    if properties is None:
        return []
    factors: list[str] = []
    metadata = properties.tool_metadata or {}
    heavy_atom_count = metadata.get("heavy_atom_count")
    if heavy_atom_count is not None:
        factors.append(f"heavy_atom_count={heavy_atom_count}")
    if properties.mw is not None:
        factors.append(f"estimated_mw={round(properties.mw, 3)}")
    if properties.logp is not None:
        factors.append(f"logp={round(properties.logp, 3)}")
    if properties.tpsa is not None:
        factors.append(f"tpsa={round(properties.tpsa, 3)}")
    if properties.hbd is not None:
        factors.append(f"hbd={properties.hbd}")
    if properties.hba is not None:
        factors.append(f"hba={properties.hba}")
    return factors


def _rule_filter_support_factors(rule_filter: RuleFilterResult | None) -> list[str]:
    if rule_filter is None:
        return []
    return [
        f"rule_filter_decision={rule_filter.decision}",
        f"rule_set={rule_filter.rule_set}",
    ]


def _rule_filter_risk_factors(rule_filter: RuleFilterResult | None) -> list[str]:
    if rule_filter is None:
        return []
    risks = [f"failed_rule={rule}" for rule in (rule_filter.failed_rules or [])]
    risks.extend(f"rule_warning={warning}" for warning in (rule_filter.warnings or []))
    return risks


def _ranking_label_signal(labels: set[str]) -> str | None:
    for signal in ["advance", "watch", "reserve", "deprioritize", "reject"]:
        if f"ranking_{signal}" in labels:
            return signal
    return None


def _is_non_risk_route_note(value: str) -> bool:
    return value in {
        "No major surrogate route risk detected.",
        "No major AiZynthFinder route risk detected.",
    }


def _status_cn(status: str) -> str:
    return {
        "candidate_assessed": "候选评估完成",
        "failed_assessment": "候选评估未通过",
        "rejected_by_ranking": "排序淘汰",
        "passed_filter": "规则过滤通过",
        "failed_filter": "规则过滤失败",
        "structure_validated": "结构验证通过",
    }.get(status, status)


def _risk_cn(risk: str) -> str:
    return {
        "low_risk": "低风险",
        "medium_risk": "中等风险",
        "high_risk": "高风险",
    }.get(risk, risk)


def _ranking_decision_cn(decision: str) -> str:
    return {
        "advance": "推进",
        "watch": "观察",
        "reserve": "储备",
        "deprioritize": "降低优先级",
        "reject": "淘汰",
    }.get(decision, decision)


def _fmt_number(value: float | int | None, digits: int = 3) -> str:
    if value is None:
        return "-"
    rounded = round(float(value), digits)
    text = f"{rounded:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def _dedupe(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def upsert_reasoning_trace(
    db: Session,
    project: Project,
    molecule: Molecule,
    blueprint: DecisionBlueprint,
) -> ReasoningTrace:
    trace = (
        db.query(ReasoningTrace)
        .filter_by(
            project_id=project.project_id,
            molecule_id=molecule.molecule_id,
            trace_type=TRACE_TYPE,
        )
        .one_or_none()
    )
    if trace is None:
        trace = ReasoningTrace(
            trace_id=new_id("TRACE"),
            project_id=project.project_id,
            molecule_id=molecule.molecule_id,
            trace_type=TRACE_TYPE,
        )
        db.add(trace)

    trace.claim = blueprint.claim
    trace.supporting_factors = blueprint.support
    trace.opposing_factors = blueprint.risk
    trace.evidence_ids = blueprint.evidence_ids
    trace.uncertainty = blueprint.uncertainty
    trace.next_actions = blueprint.next_steps
    trace.confidence = blueprint.confidence
    trace.source_agent = SOURCE_AGENT
    trace.provenance = blueprint.provenance
    return trace


def upsert_decision_card(
    db: Session,
    project: Project,
    molecule: Molecule,
    trace: ReasoningTrace,
    blueprint: DecisionBlueprint,
) -> DecisionCard:
    card = (
        db.query(DecisionCard)
        .filter_by(
            project_id=project.project_id,
            molecule_id=molecule.molecule_id,
            card_type=CARD_TYPE,
        )
        .one_or_none()
    )
    if card is None:
        card = DecisionCard(
            decision_id=new_id("DEC"),
            project_id=project.project_id,
            molecule_id=molecule.molecule_id,
            card_type=CARD_TYPE,
        )
        db.add(card)

    card.trace_id = trace.trace_id
    card.title = blueprint.title
    card.decision = blueprint.decision
    card.summary = blueprint.summary
    card.support = blueprint.support
    card.risk = blueprint.risk
    card.next_steps = blueprint.next_steps
    card.evidence_ids = blueprint.evidence_ids
    card.confidence = blueprint.confidence
    card.provenance = blueprint.provenance
    return card
