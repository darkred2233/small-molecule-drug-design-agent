from types import SimpleNamespace

from medagent.services import admet_adapter
from medagent.services.admet_adapter import ChempropADMETRequest, run_chemprop_admet


def test_status_prefers_local_admet_ai_with_bundled_models(monkeypatch):
    monkeypatch.setattr(
        admet_adapter,
        "_check_admet_ai_available",
        lambda: {
            "version": "2.0.1",
            "models_dir": "C:/models/admet-ai",
            "model_count": 2,
            "gpu_available": False,
            "device": "cpu",
        },
    )

    status = admet_adapter.check_chemprop_available()

    assert status["available"] is True
    assert status["mode"] == "admet_ai"
    assert status["model_configured"] is True


def test_unavailable_admet_runtime_returns_a_failed_result_without_surrogate():
    result = run_chemprop_admet(
        ChempropADMETRequest(smiles_list=["CCO"], molecule_ids=["MOL-1"]),
        {"available": False, "warning": "admet_ai_and_local_chemprop_unavailable"},
    )

    assert result.success is False
    assert result.adapter_mode == "chemprop_unavailable"
    assert result.results == []
    assert result.warnings == ["admet_ai_and_local_chemprop_unavailable"]


def test_admet_ai_rows_preserve_input_identity_after_invalid_smiles_are_filtered():
    class IndexedPredictions:
        index = ["CCO", "CCN"]

        def to_dict(self, orient):
            assert orient == "records"
            return [
                {"hERG": 0.11, "AMES": 0.12, "DILI": 0.13, "Solubility_AqSolDB": -3.0},
                {"hERG": 0.81, "AMES": 0.22, "DILI": 0.23, "Solubility_AqSolDB": -5.0},
            ]

    results = admet_adapter._parse_admet_ai_predictions(
        IndexedPredictions(),
        ["BAD", "ETOH", "ETHYLAMINE"],
        ["not-a-smiles", "CCO", "CCN"],
    )

    assert [(item.molecule_id, item.smiles) for item in results] == [("ETOH", "CCO"), ("ETHYLAMINE", "CCN")]
    assert results[0].solubility == "medium"
    assert results[1].hERG_risk == "high_risk"


def test_local_chemprop_cli_uses_a_checkpoint_and_parses_real_csv(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()

    def fake_run(command, **_kwargs):
        output = __import__("pathlib").Path(command[command.index("--preds-path") + 1])
        output.write_text("smiles,hERG,AMES,DILI\nCCO,0.1,0.2,0.3\n", encoding="utf-8")
        assert command[:2] == ["chemprop.exe", "predict"]
        assert "--checkpoint-dir" in command
        return SimpleNamespace(returncode=0, stdout="predicted", stderr="")

    monkeypatch.setattr(admet_adapter.subprocess, "run", fake_run)
    result = run_chemprop_admet(
        ChempropADMETRequest(smiles_list=["CCO"], molecule_ids=["MOL-1"], checkpoint_dir=str(checkpoint)),
        {"available": True, "mode": "local_cli", "path": "chemprop.exe", "models_dir": str(checkpoint)},
    )

    assert result.success is True
    assert result.adapter_mode == "chemprop_local_prediction"
    assert result.results[0].molecule_id == "MOL-1"
    assert result.results[0].hERG_probability == 0.1
