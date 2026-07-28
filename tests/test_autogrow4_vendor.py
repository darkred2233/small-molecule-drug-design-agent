from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace


def _load_vendor_backend(monkeypatch):
    fake_fcntl = types.ModuleType("fcntl")
    fake_fcntl.LOCK_EX = 1
    fake_fcntl.LOCK_NB = 2
    fake_fcntl.LOCK_UN = 4
    fake_fcntl.flock = lambda *_args: None
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)

    module_names = [
        "autogrow",
        "autogrow.docking",
        "autogrow.docking.docking_class",
        "autogrow.docking.docking_class.docking_class_children",
        "autogrow.docking.docking_class.docking_class_children.vina_docking",
    ]
    for name in module_names:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    vina_module = sys.modules[
        "autogrow.docking.docking_class.docking_class_children.vina_docking"
    ]
    vina_module.VinaDocking = type("VinaDocking", (), {})

    path = (
        Path(__file__).parents[1]
        / "scripts"
        / "autogrow4_vendor"
        / "vina_gpu_batch_docking.py"
    )
    spec = importlib.util.spec_from_file_location("medagent_test_vina_gpu_backend", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vina_gpu_nonzero_exit_is_recorded_for_retry(tmp_path, monkeypatch):
    module = _load_vendor_backend(monkeypatch)
    backend = module.VinaGpuBatchDocking.__new__(module.VinaGpuBatchDocking)
    backend.vars = {"docking_executable": "vina_gpu.exe"}
    backend.opencl_binary_path = str(tmp_path)
    backend.adapter_mode = "vina_gpu_2_1_batch"
    backend.gpu_id = 0
    backend.thread_count = 1000
    backend.batch_timeout = 30
    backend._config_text = lambda *_args: ""
    monkeypatch.setattr(module, "_windows_path", lambda value: str(value))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=2, stdout="", stderr="temporary OpenCL failure"
        ),
    )
    receptor = tmp_path / "receptor.pdbqt"
    ligand = tmp_path / "ligand.pdbqt"
    receptor.write_text("ATOM\n", encoding="utf-8")
    ligand.write_text("ATOM\n", encoding="utf-8")

    record, resolved = backend._run_gpu_chunk(receptor, [ligand], 0)

    assert resolved == []
    assert record["exit_code"] == 2
    assert record["success_count"] == 0
    assert "OpenCL" in record["stderr"]


def test_vina_gpu_batch_retries_and_recovers(tmp_path, monkeypatch):
    module = _load_vendor_backend(monkeypatch)
    backend = module.VinaGpuBatchDocking.__new__(module.VinaGpuBatchDocking)
    backend.max_batch_size = 128
    backend.retry_count = 1
    backend._exclusive_gpu = lambda: nullcontext()
    backend.check_docked = lambda _path: (True, None)
    attempts = []
    provenance = {}

    def fake_chunk(_receptor, pending, attempt):
        attempts.append(attempt)
        if attempt == 0:
            return {
                "exit_code": 2,
                "input_count": len(pending),
                "success_count": 0,
            }, []
        return {
            "exit_code": 0,
            "input_count": len(pending),
            "success_count": len(pending),
        }, list(pending)

    def capture(_ligands, records, _started, failed_names, failure=None):
        provenance.update(records=records, failed_names=failed_names, failure=failure)

    backend._run_gpu_chunk = fake_chunk
    backend._write_provenance = capture
    receptor = tmp_path / "receptor.pdbqt"
    ligand = tmp_path / "generation_1" / "PDBs" / "ligand.pdbqt"
    ligand.parent.mkdir(parents=True)
    receptor.write_text("ATOM\n", encoding="utf-8")
    ligand.write_text("ATOM\n", encoding="utf-8")
    backend.receptor_pdbqt_file = str(receptor)

    failed = backend.run_batch_dock([str(ligand)])

    assert failed == []
    assert attempts == [0, 1]
    assert [record["exit_code"] for record in provenance["records"]] == [2, 0]
    assert provenance["failure"] is None
