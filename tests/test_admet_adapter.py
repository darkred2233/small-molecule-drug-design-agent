"""Tests for the Chemprop ADMET adapter."""

import csv
import tempfile
from pathlib import Path
from types import SimpleNamespace

from medagent.services import admet_adapter
from medagent.services.admet_adapter import (
    ChempropADMETRequest,
    SingleADMETResult,
    _parse_admet_ai_predictions,
    check_chemprop_available,
    _parse_chemprop_output,
    run_chemprop_admet,
    _risk_label,
    _solubility_class,
    _permeability_class,
    _write_input_csv,
)


class TestRiskLabel:
    def test_high_risk(self):
        assert _risk_label(0.8, "hERG") == "high_risk"

    def test_medium_risk(self):
        assert _risk_label(0.5, "hERG") == "medium_risk"

    def test_low_risk(self):
        assert _risk_label(0.2, "hERG") == "low_risk"

    def test_none_returns_unknown(self):
        assert _risk_label(None, "hERG") == "unknown_risk"

    def test_different_properties(self):
        assert _risk_label(0.8, "Ames") == "high_risk"
        assert _risk_label(0.5, "CYP3A4") == "medium_risk"


class TestSolubilityClass:
    def test_high(self):
        assert _solubility_class(0.8) == "high"

    def test_medium(self):
        assert _solubility_class(0.5) == "medium"

    def test_low(self):
        assert _solubility_class(0.2) == "low"

    def test_none(self):
        assert _solubility_class(None) == "unknown"


class TestPermeabilityClass:
    def test_high(self):
        assert _permeability_class(0.8) == "high"

    def test_medium(self):
        assert _permeability_class(0.5) == "medium"

    def test_low(self):
        assert _permeability_class(0.2) == "low"

    def test_none(self):
        assert _permeability_class(None) == "unknown"


class TestWriteInputCSV:
    def test_writes_smiles_to_csv(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "test.csv"
            _write_input_csv(path, ["CCO", "CCCO", "CCCC"])

            with open(path) as f:
                reader = csv.reader(f)
                rows = list(reader)

            assert rows[0] == ["smiles"]
            assert rows[1] == ["CCO"]
            assert rows[2] == ["CCCO"]
            assert rows[3] == ["CCCC"]

    def test_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "test.csv"
            _write_input_csv(path, [])

            with open(path) as f:
                reader = csv.reader(f)
                rows = list(reader)

            assert rows[0] == ["smiles"]
            assert len(rows) == 1


class TestChempropAvailability:
    def test_detects_admet_ai_models_first(self, monkeypatch):
        monkeypatch.setattr(
            "medagent.services.admet_adapter._check_admet_ai_available",
            lambda: {
                "version": "2.0.1",
                "models_dir": "models",
                "model_count": 10,
                "gpu_available": True,
                "device": "cuda",
            },
        )
        monkeypatch.setattr(
            "medagent.services.admet_adapter.shutil.which",
            lambda command: None,
        )

        status = check_chemprop_available()

        assert status["available"] is True
        assert status["mode"] == "admet_ai"
        assert status["version"] == "2.0.1"
        assert status["models_dir"] == "models"
        assert status["model_count"] == 10
        assert status["gpu_available"] is True
        assert status["device"] == "cuda"

    def test_cli_without_checkpoint_is_not_available_for_prediction(self, monkeypatch):
        monkeypatch.delenv("CHEMPROP_CHECKPOINT_DIR", raising=False)
        monkeypatch.setattr(
            "medagent.services.admet_adapter._check_admet_ai_available",
            lambda: None,
        )
        monkeypatch.setattr(
            "medagent.services.admet_adapter.shutil.which",
            lambda command: "chemprop" if command == "chemprop" else None,
        )

        def fake_run(args, **kwargs):
            if args == ["chemprop", "--version"]:
                return SimpleNamespace(returncode=2, stdout="", stderr="mode required")
            raise AssertionError(f"unexpected command: {args}")

        monkeypatch.setattr(
            "medagent.services.admet_adapter.subprocess.run",
            fake_run,
        )

        status = check_chemprop_available()

        assert status["available"] is False
        assert status["runtime_available"] is True
        assert status["model_configured"] is False
        assert status["mode"] == "local_cli"
        assert status["path"] == "chemprop"
        assert status["warning"] == "chemprop_checkpoint_not_configured"

    def test_cli_with_checkpoint_is_available_for_prediction(self, tmp_path, monkeypatch):
        checkpoint_dir = tmp_path / "models"
        checkpoint_dir.mkdir()
        monkeypatch.setenv("CHEMPROP_CHECKPOINT_DIR", str(checkpoint_dir))
        monkeypatch.setattr(
            "medagent.services.admet_adapter._check_admet_ai_available",
            lambda: None,
        )
        monkeypatch.setattr(
            "medagent.services.admet_adapter._check_chemprop_cli",
            lambda: {"version": "2.2.4", "path": "chemprop"},
        )

        status = check_chemprop_available()

        assert status["available"] is True
        assert status["runtime_available"] is True
        assert status["model_configured"] is True
        assert status["models_dir"] == str(checkpoint_dir.resolve())


class TestRunChempropADMET:
    def test_missing_checkpoint_returns_without_running_cli(self, monkeypatch):
        monkeypatch.delenv("CHEMPROP_CHECKPOINT_DIR", raising=False)

        def fail_run(*args, **kwargs):
            raise AssertionError("Chemprop CLI should not run without a checkpoint")

        monkeypatch.setattr(
            "medagent.services.admet_adapter.subprocess.run",
            fail_run,
        )

        request = ChempropADMETRequest(
            smiles_list=["CCO"],
            molecule_ids=["MOL-001"],
            timeout_seconds=1,
        )
        result = run_chemprop_admet(
            request,
            {"available": True, "mode": "local_cli"},
        )

        assert result.success is False
        assert result.adapter_mode == "chemprop_model_not_configured"
        assert "chemprop_checkpoint_not_configured" in result.warnings

    def test_docker_command_uses_image_entrypoint_and_mounts_checkpoint(self, tmp_path):
        data_dir = tmp_path / "data"
        checkpoint_dir = tmp_path / "models"
        data_dir.mkdir()
        checkpoint_dir.mkdir()

        command = admet_adapter._build_chemprop_docker_command(
            docker_image="chemprop:latest",
            container_name="chemprop_test",
            data_dir=data_dir,
            checkpoint_dir=checkpoint_dir,
            use_gpu=True,
        )

        image_index = command.index("chemprop:latest")
        assert command[image_index + 1] == "predict"
        assert command.count("chemprop") == 0
        assert f"{checkpoint_dir.resolve()}:/models:ro" in command
        assert command[command.index("--checkpoint-dir") + 1] == "/models"
        assert command[command.index("--gpus") + 1] == "all"


class TestParseChempropOutput:
    def test_parses_basic_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "output.csv"
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["smiles", "hERG", "Ames", "Solubility"])
                writer.writerow(["CCO", "0.3", "0.2", "0.7"])
                writer.writerow(["CCCO", "0.8", "0.6", "0.4"])

            results = _parse_chemprop_output(
                path,
                molecule_ids=["MOL-1", "MOL-2"],
                smiles_list=["CCO", "CCCO"],
            )

            assert len(results) == 2
            assert results[0].molecule_id == "MOL-1"
            assert results[0].hERG_probability == 0.3
            assert results[0].hERG_risk == "low_risk"
            assert results[0].solubility == "high"
            assert results[1].molecule_id == "MOL-2"
            assert results[1].hERG_probability == 0.8
            assert results[1].hERG_risk == "high_risk"

    def test_handles_missing_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "output.csv"
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["smiles", "hERG", "Ames"])
                writer.writerow(["CCO", "", "0.2"])

            results = _parse_chemprop_output(
                path,
                molecule_ids=["MOL-1"],
                smiles_list=["CCO"],
            )

            assert len(results) == 1
            assert results[0].hERG_probability is None
            assert results[0].hERG_risk == "unknown_risk"

    def test_handles_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "output.csv"
            with open(path, "w") as f:
                f.write("")

            results = _parse_chemprop_output(path, ["MOL-1"], ["CCO"])
            assert results == []


class TestParseAdmetAiPredictions:
    def test_maps_admet_ai_columns(self):
        rows = [{
            "hERG": 0.2,
            "AMES": 0.72,
            "CYP3A4_Veith": 0.4,
            "CYP2D6_Veith": 0.5,
            "Solubility_AqSolDB": -1.5,
            "PAMPA_NCATS": 0.8,
            "DILI": 0.4,
            "Pgp_Broccatelli": 0.6,
            "BBB_Martins": 0.1,
        }]
        predictions = SimpleNamespace(to_dict=lambda orient: rows)

        results = _parse_admet_ai_predictions(
            predictions,
            molecule_ids=["MOL-1"],
            smiles_list=["CCO"],
        )

        assert len(results) == 1
        result = results[0]
        assert result.molecule_id == "MOL-1"
        assert result.hERG_probability == 0.2
        assert result.Ames_probability == 0.72
        assert result.Ames_risk == "high_risk"
        assert result.solubility == "high"
        assert result.solubility_score == 0.75
        assert result.permeability == "high"
        assert result.admet_risk_score == 0.44
        assert "admet_ai_predicted" in result.labels
        assert "admet_blocker" in result.labels

    def test_preserves_zero_probabilities(self):
        predictions = {
            "hERG": 0.0,
            "AMES": 0.0,
            "DILI": 0.0,
            "Solubility_AqSolDB": -6.0,
            "PAMPA_NCATS": 0.0,
        }

        results = _parse_admet_ai_predictions(
            predictions,
            molecule_ids=["MOL-1"],
            smiles_list=["CCO"],
        )

        assert len(results) == 1
        assert results[0].hERG_probability == 0.0
        assert results[0].Ames_probability == 0.0
        assert results[0].DILI_probability == 0.0
        assert results[0].permeability_score == 0.0
        assert results[0].admet_risk_score == 0.0

    def test_uses_prediction_index_after_admet_ai_filters_invalid_smiles(self):
        class IndexedPredictions:
            index = ["CCO", "CCN"]

            def to_dict(self, orient):
                assert orient == "records"
                return [
                    {"hERG": 0.11, "AMES": 0.12, "DILI": 0.13},
                    {"hERG": 0.21, "AMES": 0.22, "DILI": 0.23},
                ]

        results = _parse_admet_ai_predictions(
            IndexedPredictions(),
            molecule_ids=["BAD-FIRST", "ETOH", "BAD-MIDDLE", "ETHYLAMINE"],
            smiles_list=["not-a-smiles", "CCO", "also-invalid", "CCN"],
        )

        assert [(item.molecule_id, item.smiles) for item in results] == [
            ("ETOH", "CCO"),
            ("ETHYLAMINE", "CCN"),
        ]
        assert [item.hERG_probability for item in results] == [0.11, 0.21]

    def test_maps_duplicate_smiles_to_input_occurrences_in_order(self):
        class IndexedPredictions:
            index = ["CCO", "CCO"]

            def to_dict(self, orient):
                assert orient == "records"
                return [
                    {"hERG": 0.31, "AMES": 0.32, "DILI": 0.33},
                    {"hERG": 0.41, "AMES": 0.42, "DILI": 0.43},
                ]

        results = _parse_admet_ai_predictions(
            IndexedPredictions(),
            molecule_ids=["ETOH-1", "ETOH-2"],
            smiles_list=["CCO", "CCO"],
        )

        assert [item.molecule_id for item in results] == ["ETOH-1", "ETOH-2"]
        assert [item.hERG_probability for item in results] == [0.31, 0.41]


class TestChempropADMETOutput:
    def test_as_dict(self):
        result = SingleADMETResult(
            molecule_id="MOL-1",
            smiles="CCO",
            hERG_probability=0.3,
            hERG_risk="low_risk",
            admet_risk_score=0.25,
            labels=["chemprop_predicted", "low_risk"],
        )
        assert result.molecule_id == "MOL-1"
        assert result.hERG_probability == 0.3

    def test_defaults(self):
        result = SingleADMETResult(molecule_id="MOL-1", smiles="CCO")
        assert result.hERG_probability is None
        assert result.labels == []
        assert result.warnings == []
