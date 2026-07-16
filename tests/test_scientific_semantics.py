from dataclasses import asdict
from types import SimpleNamespace

from medagent.agents.advisor import AdvisorReport
from medagent.agents.sar import SARAgent
from medagent.agents.target import TargetAnalysisReport, TargetValidationResult


def test_target_report_exposes_support_score_not_success_probability():
    report = TargetAnalysisReport(
        target_protein="ALK",
        validation_result=TargetValidationResult(
            target_name="ALK",
            is_druggable=True,
            druggability_score=0.7,
        ),
        target_support_score=0.61,
    )

    payload = asdict(report)
    assert payload["target_support_score"] == 0.61
    assert payload["score_semantics"] == "heuristic_not_probability"
    assert "success_probability" not in payload
    assert (
        payload["validation_result"]["druggability_score_semantics"]
        == "heuristic_not_probability"
    )


def test_advisor_report_exposes_readiness_score_not_success_probability():
    report = AdvisorReport(
        project_id="PROJ-1",
        project_status_summary="candidate review",
        candidate_readiness_score=0.42,
    )

    payload = asdict(report)
    assert payload["candidate_readiness_score"] == 0.42
    assert payload["score_semantics"] == "heuristic_not_probability"
    assert "success_probability" not in payload


def test_sar_parser_never_turns_vina_score_into_activity_cliff():
    agent = SARAgent(db=None)  # Parsing does not access the database.
    patterns = agent._parse_sar_patterns(
        """
        [{
          "pattern_type": "activity_cliff",
          "description": "large score change",
          "molecules": ["MOL-1", "MOL-2"],
          "structural_change": "methyl to chloro",
          "activity_range": [-9.1, -6.5]
        }]
        """
    )

    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.pattern_type == "docking_score_shift"
    assert pattern.activity_range is None
    assert pattern.score_range == (-9.1, -6.5)
    assert pattern.score_type == "vina_docking_score"
    assert pattern.evidence_kind == "computational_docking"
    assert "not_experimental_activity" in pattern.caveats


def test_sar_prompt_handles_docking_results_without_vina_score():
    agent = SARAgent(db=None)
    captured = {}

    class FakeLLMClient:
        def complete(self, messages, **_kwargs):
            captured["prompt"] = messages[0].content
            return SimpleNamespace(content="[]")

    agent._llm_client = FakeLLMClient()
    molecules = [
        SimpleNamespace(molecule_id="MOL-DIFFDOCK", smiles="CCO"),
    ]
    docking_data = {
        "MOL-DIFFDOCK": SimpleNamespace(vina_score=None),
    }

    patterns = agent._identify_sar_patterns(molecules, docking_data, use_llm=True)

    assert patterns == []
    assert "MOL-DIFFDOCK | CCO | N/A" in captured["prompt"]
