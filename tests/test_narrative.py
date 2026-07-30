import pytest

from medagent.services.narrative import build_molecule_narratives_from_report


def _report_with_admet_risks(herg_risk: str, ames_risk: str) -> dict:
    return {
        "top_candidates": [
            {
                "molecule_id": "MOL-1",
                "docking": {"pose_artifact_available": True},
                "admet": {
                    "hERG": {"risk": herg_risk},
                    "Ames": {"risk": ames_risk},
                    "admet_risk_score": 0.15,
                },
                "refutation_chain": {"risk_level": "low"},
            }
        ]
    }


def test_low_risk_labels_do_not_trigger_herg_or_ames_recommendations():
    narrative = build_molecule_narratives_from_report(
        _report_with_admet_risks("low_risk", "low_risk")
    )[0]

    assert not any("hERG" in risk or "Ames" in risk for risk in narrative["risks"])
    assert not any("ADMET" in risk for risk in narrative["risks"])
    assert not any(
        "hERG" in suggestion or "Ames" in suggestion
        for suggestion in narrative["next_round_suggestions"]
    )
    assert any("SAR" in suggestion for suggestion in narrative["next_round_suggestions"])


@pytest.mark.parametrize("risk", ["medium_risk", "high_risk"])
def test_actionable_risk_labels_trigger_matching_recommendations(risk: str):
    narrative = build_molecule_narratives_from_report(_report_with_admet_risks(risk, risk))[0]

    assert any("hERG" in risk_line for risk_line in narrative["risks"])
    assert any("Ames" in risk_line for risk_line in narrative["risks"])
    assert any("hERG" in suggestion for suggestion in narrative["next_round_suggestions"])
    assert any("诱变" in suggestion for suggestion in narrative["next_round_suggestions"])
