from dataclasses import dataclass

from sqlalchemy.orm import Session

from medagent.db.models import DecisionCard, Molecule, MoleculeProperty, Project, ReasoningTrace
from medagent.services.ids import new_id


TRACE_TYPE = "molecule_validation_decision"
CARD_TYPE = "molecule_validation_decision"
SOURCE_AGENT = "decision_card_generator"


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
    confidence: float
    evidence_ids: list[str]
    provenance: dict


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
        properties = db.query(MoleculeProperty).filter_by(molecule_id=molecule.molecule_id).one_or_none()
        blueprint = build_decision_blueprint(project, molecule, properties)
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


def build_decision_blueprint(
    project: Project,
    molecule: Molecule,
    properties: MoleculeProperty | None,
) -> DecisionBlueprint:
    evidence_ids = [f"DB:MOL:{molecule.molecule_id}"]
    records = [{"table": "molecules", "id": molecule.molecule_id}]
    tool_outputs: list[str] = []
    if properties is not None:
        evidence_ids.append(f"DB:PROP:{molecule.molecule_id}")
        records.append({"table": "molecule_properties", "id": molecule.molecule_id})
        validator = (properties.tool_metadata or {}).get("validator")
        if validator:
            tool_outputs.append(validator)

    provenance = {
        "basis": "database_records",
        "records": records,
        "tool_outputs": tool_outputs,
        "rag_evidence_available": False,
        "target_id": project.target_id,
    }

    labels = molecule.labels or []
    label_factors = [f"label={label}" for label in labels]

    if molecule.status == "invalid_structure":
        support = [f"status={molecule.status}", *label_factors]
        risk = [
            "The molecule cannot enter downstream ranking while marked invalid.",
            "No reliable chemistry descriptors should be used for this structure.",
        ]
        if properties is None:
            risk.append("No molecule property record was generated.")
        return DecisionBlueprint(
            title="Reject for structure review",
            decision="reject_for_structure",
            summary=(
                "The current validation stage marked this molecule as structurally invalid, "
                "so it should be fixed or removed before filtering and ranking."
            ),
            claim="This molecule is not ready for downstream drug-design steps.",
            support=support,
            risk=risk,
            next_steps=[
                "Fix or replace the SMILES record.",
                "Run structure validation again after correction.",
            ],
            uncertainty="The rejection is based on lightweight SMILES checks, not RDKit validation.",
            confidence=0.72,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    if molecule.status == "structure_validated":
        support = [f"status={molecule.status}", *label_factors]
        if properties is not None:
            metadata = properties.tool_metadata or {}
            heavy_atom_count = metadata.get("heavy_atom_count")
            if heavy_atom_count is not None:
                support.append(f"heavy_atom_count={heavy_atom_count}")
            if properties.mw is not None:
                support.append(f"estimated_mw={round(properties.mw, 3)}")
            if properties.hbd is not None:
                support.append(f"hbd={properties.hbd}")
            if properties.hba is not None:
                support.append(f"hba={properties.hba}")

        risk = []
        if "needs_rdkit_validation" in labels:
            risk.append("RDKit-level standardization and validation are still pending.")
        if properties is None:
            risk.append("No descriptor record is available yet.")
        else:
            metadata = properties.tool_metadata or {}
            if metadata.get("validator") == "rdkit":
                risk.append("RDKit descriptors do not include docking or ADMET evidence yet.")
            if properties.logp is None:
                risk.append("LogP is not available yet.")
            if properties.tpsa is None:
                risk.append("TPSA is not available yet.")

        return DecisionBlueprint(
            title="Advance to rule filtering",
            decision="advance_to_rule_filter",
            summary=(
                "The molecule passed the lightweight structure check and has preliminary "
                "properties, so it can move to the next rule-filtering stage."
            ),
            claim="This molecule can proceed to basic medicinal-chemistry filtering.",
            support=support,
            risk=risk,
            next_steps=[
                "Run RDKit or Datamol standardization.",
                "Apply Lipinski, Veber, PAINS, Brenk, and reactive-group filters.",
            ],
            uncertainty=(
                "Descriptor values are lightweight estimates and should be replaced by "
                "RDKit calculations before scientific use."
            ),
            confidence=0.58,
            evidence_ids=evidence_ids,
            provenance=provenance,
        )

    return DecisionBlueprint(
        title="Run structure validation",
        decision="needs_structure_validation",
        summary=(
            "The molecule is present in the project candidate pool, but no validation "
            "decision has been recorded yet."
        ),
        claim="This molecule needs structure validation before it can be judged.",
        support=[f"status={molecule.status}", *label_factors],
        risk=["No structure validation or property record is available yet."],
        next_steps=[f"Run POST /projects/{project.project_id}/molecules/validate."],
        uncertainty="No chemistry decision should be made before validation.",
        confidence=0.4,
        evidence_ids=evidence_ids,
        provenance=provenance,
    )


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
