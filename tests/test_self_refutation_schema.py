from types import SimpleNamespace

from medagent.db.models import Molecule, Project
from medagent.services import self_refutation


class _Response:
    content = (
        '{"hidden_risks": [], "evidence_concerns": [], '
        '"analogy_failures": [], "verdict": {"risk_adjustment": "maintain"}}'
    )


class _Client:
    def __init__(self) -> None:
        self.prompt = ""

    def complete(self, *, messages, **_kwargs):
        self.prompt = messages[0].content
        return _Response()


def test_llm_refutation_uses_current_project_schema(monkeypatch):
    client = _Client()
    monkeypatch.setattr(self_refutation, "get_llm_client", lambda: client)
    project = Project(
        project_id="PROJ-TEST",
        name="BRAF project",
        target_id="BRAF",
        target_name="BRAF V600E",
        objective="Prioritize selective inhibitors",
    )
    molecule = Molecule(
        molecule_id="mol-test",
        project_id=project.project_id,
        smiles="CCO",
    )
    settings = SimpleNamespace(
        self_refutation_provider="deepseek",
        self_refutation_model="deepseek-chat",
    )

    result = self_refutation._llm_critique(
        settings,
        project,
        molecule,
        None,
        None,
        None,
        [],
        [],
        [],
    )

    assert result is not None
    assert "BRAF V600E" in client.prompt
    assert "Prioritize selective inhibitors" in client.prompt
