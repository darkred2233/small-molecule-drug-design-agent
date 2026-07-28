"""Generation-batch Vina-GPU backend for the local AutoGrow4 runtime.

The backend intentionally has no per-ligand CPU path. A failed GPU batch
raises so the caller can mark the campaign failed instead of misreporting a
QuickVina result as GPU docking.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from autogrow.docking.docking_class.docking_class_children.vina_docking import VinaDocking


class VinaGpuBatchDocking(VinaDocking):
    """Dock each AutoGrow generation through one or more Vina-GPU batches."""

    adapter_mode = "vina_gpu_2_1_batch"

    def __init__(self, vars=None, receptor_file=None, file_conversion_class_object=None, test_boot=True):
        self.opencl_binary_path = os.environ.get(
            "MEDAGENT_VINA_GPU_OPENCL_BINARY_PATH", ""
        ).strip()
        super().__init__(vars, receptor_file, file_conversion_class_object, test_boot=test_boot)
        if not test_boot:
            self.gpu_id = _env_int("MEDAGENT_VINA_GPU_ID", 0, minimum=0)
            if self.gpu_id != 0:
                raise RuntimeError("AutoGrow Vina-GPU is restricted to physical GPU 0")
            self.thread_count = _env_int("MEDAGENT_VINA_GPU_THREAD", 1000, minimum=1000)
            self.max_batch_size = _env_int(
                "MEDAGENT_VINA_GPU_MAX_BATCH_SIZE", 128, minimum=1
            )
            self.batch_timeout = _env_int(
                "MEDAGENT_VINA_GPU_BATCH_TIMEOUT_SECONDS", 1800, minimum=1
            )
            self.wait_timeout = _env_int(
                "MEDAGENT_VINA_GPU_WAIT_TIMEOUT_SECONDS", 300, minimum=0
            )
            self.max_utilization = _env_int(
                "MEDAGENT_VINA_GPU_MAX_UTILIZATION_PERCENT", 80, minimum=0
            )
            self.retry_count = _env_int("MEDAGENT_VINA_GPU_RETRY_COUNT", 1, minimum=0)
            self.lock_file = Path(
                os.environ.get("MEDAGENT_VINA_GPU_LOCK_FILE", "/tmp/medagent-vina-gpu0.lock")
            )

    def get_docking_executable_file(self, vars):
        executable = str(vars.get("docking_executable") or "").strip()
        if not executable or not Path(executable).is_file():
            raise RuntimeError("configured_vina_gpu_executable_unavailable")
        if not self.opencl_binary_path or not Path(self.opencl_binary_path).is_dir():
            raise RuntimeError("configured_vina_gpu_opencl_path_unavailable")
        return executable

    def run_dock(self, _pdbqt_filename):
        raise RuntimeError("VinaGpuBatchDocking does not support CPU-style per-ligand docking")

    def run_batch_dock(self, pdbqt_filenames):
        ligands = [Path(value).resolve() for value in pdbqt_filenames]
        if not ligands:
            return []
        missing = [
            str(path) for path in ligands if not path.is_file() or path.stat().st_size == 0
        ]
        if missing:
            raise RuntimeError("vina_gpu_input_ligands_missing:" + ",".join(missing))
        receptor = Path(self.receptor_pdbqt_file).resolve()
        if not receptor.is_file() or receptor.stat().st_size == 0:
            raise RuntimeError("vina_gpu_receptor_pdbqt_missing")

        started = time.monotonic()
        records = []
        failed = []
        try:
            with self._exclusive_gpu():
                for offset in range(0, len(ligands), self.max_batch_size):
                    pending = ligands[offset : offset + self.max_batch_size]
                    for attempt in range(self.retry_count + 1):
                        record, resolved = self._run_gpu_chunk(receptor, pending, attempt)
                        records.append(record)
                        pending = [path for path in pending if path not in set(resolved)]
                        if not pending:
                            break
                    failed.extend(pending)
        except Exception as exc:
            self._write_provenance(
                ligands, records, started, [], f"{type(exc).__name__}:{exc}"
            )
            raise

        failed_names = []
        for ligand in [*failed, *[path for path in ligands if path not in failed]]:
            did_dock, name = self.check_docked(str(ligand).replace("qt", ""))
            if not did_dock and name:
                failed_names.append(name)
        self._write_provenance(ligands, records, started, failed_names)
        return failed_names

    @contextmanager
    def _exclusive_gpu(self):
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait_timeout
        with self.lock_file.open("a+", encoding="utf-8") as handle:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("vina_gpu0_lock_wait_timeout")
                    time.sleep(2)
            try:
                self._wait_until_gpu_available(deadline)
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _wait_until_gpu_available(self, deadline):
        while True:
            snapshot = _gpu_snapshot(self.gpu_id)
            if snapshot["utilization_percent"] <= self.max_utilization:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "gpu0_busy_external_job:" + json.dumps(snapshot, sort_keys=True)
                )
            time.sleep(5)

    def _run_gpu_chunk(self, receptor, ligands, attempt):
        # The class runs in WSL while Vina-GPU is a native Windows process.
        # Keep the batch workspace on the Windows-mounted output filesystem.
        with tempfile.TemporaryDirectory(
            prefix="autogrow_vina_gpu_", dir=str(ligands[0].parent)
        ) as temporary:
            root = Path(temporary)
            input_dir, output_dir = root / "ligands", root / "output"
            input_dir.mkdir()
            output_dir.mkdir()
            copied_inputs = {}
            for index, ligand in enumerate(ligands):
                copied = input_dir / f"{index:05d}_{ligand.name}"
                shutil.copy2(ligand, copied)
                copied_inputs[copied.stem] = ligand
            config_file = root / "vina-gpu.config"
            config_file.write_text(
                self._config_text(receptor, input_dir, output_dir), encoding="utf-8"
            )
            command = [
                self.vars["docking_executable"],
                "--config",
                _windows_path(config_file),
                "--opencl_binary_path",
                _windows_path(self.opencl_binary_path),
            ]
            started = time.monotonic()
            try:
                process = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.batch_timeout,
                    check=False,
                    cwd=str(Path(self.opencl_binary_path).resolve()),
                )
            except subprocess.TimeoutExpired as exc:
                return {
                    "attempt": attempt,
                    "adapter_mode": self.adapter_mode,
                    "gpu_id": self.gpu_id,
                    "thread": self.thread_count,
                    "input_count": len(ligands),
                    "success_count": 0,
                    "runtime_seconds": round(time.monotonic() - started, 6),
                    "exit_code": None,
                    "stdout": str(exc.stdout or "")[-4000:],
                    "stderr": f"vina_gpu_batch_timeout:{exc}"[-4000:],
                }, []
            except OSError as exc:
                return {
                    "attempt": attempt,
                    "adapter_mode": self.adapter_mode,
                    "gpu_id": self.gpu_id,
                    "thread": self.thread_count,
                    "input_count": len(ligands),
                    "success_count": 0,
                    "runtime_seconds": round(time.monotonic() - started, 6),
                    "exit_code": None,
                    "stdout": "",
                    "stderr": f"vina_gpu_batch_os_error:{type(exc).__name__}:{exc}"[-4000:],
                }, []
            if process.returncode != 0:
                return {
                    "attempt": attempt,
                    "adapter_mode": self.adapter_mode,
                    "gpu_id": self.gpu_id,
                    "thread": self.thread_count,
                    "input_count": len(ligands),
                    "success_count": 0,
                    "runtime_seconds": round(time.monotonic() - started, 6),
                    "exit_code": process.returncode,
                    "stdout": (process.stdout or "")[-4000:],
                    "stderr": (process.stderr or "")[-4000:],
                }, []
            outputs = _index_gpu_outputs(output_dir)
            resolved = []
            for copied_stem, original in copied_inputs.items():
                output = outputs.get(copied_stem)
                if output and _valid_vina_output(output):
                    shutil.copy2(output, f"{original}.vina")
                    resolved.append(original)
            return {
                "attempt": attempt,
                "adapter_mode": self.adapter_mode,
                "gpu_id": self.gpu_id,
                "thread": self.thread_count,
                "input_count": len(ligands),
                "success_count": len(resolved),
                "runtime_seconds": round(time.monotonic() - started, 6),
                "exit_code": process.returncode,
                "stdout": (process.stdout or "")[-4000:],
                "stderr": (process.stderr or "")[-4000:],
            }, resolved

    def _config_text(self, receptor, input_dir, output_dir):
        values = {
            "receptor": _windows_path(receptor),
            "ligand_directory": _windows_path(input_dir),
            "output_directory": _windows_path(output_dir),
            "center_x": self.vars["center_x"],
            "center_y": self.vars["center_y"],
            "center_z": self.vars["center_z"],
            "size_x": self.vars["size_x"],
            "size_y": self.vars["size_y"],
            "size_z": self.vars["size_z"],
            "thread": self.thread_count,
        }
        return "".join(f"{key} = {value}\n" for key, value in values.items())

    def _write_provenance(self, ligands, records, started, failed_names, failure=None):
        path = ligands[0].parent.parent / "vina_gpu_batches.jsonl"
        payload = {
            "adapter_mode": self.adapter_mode,
            "cpu_fallback_enabled": False,
            "gpu_id": self.gpu_id,
            "thread": self.thread_count,
            "requested_count": len(ligands),
            "failed_smiles_names": failed_names,
            "runtime_seconds": round(time.monotonic() - started, 6),
            "batches": records,
            "failure": failure,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _index_gpu_outputs(output_dir):
    outputs = {}
    for path in output_dir.rglob("*.pdbqt"):
        stem = path.stem[:-4] if path.stem.endswith("_out") else path.stem
        outputs[stem] = path
    return outputs


def _valid_vina_output(path):
    return (
        path.is_file()
        and path.stat().st_size > 0
        and b"REMARK VINA RESULT" in path.read_bytes()
    )


def _gpu_snapshot(gpu_id):
    result = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            str(gpu_id),
            "--query-gpu=utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("vina_gpu_nvidia_smi_query_failed")
    try:
        utilization = int(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("vina_gpu_nvidia_smi_output_invalid") from exc
    return {"gpu_id": gpu_id, "utilization_percent": utilization}


def _env_int(name, default, minimum=0):
    try:
        return max(int(os.environ.get(name, default)), minimum)
    except (TypeError, ValueError):
        return default


def _windows_path(path):
    """Translate WSL-mounted paths for the native Windows GPU process."""
    completed = subprocess.run(
        ["wslpath", "-w", str(path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("vina_gpu_windows_path_conversion_failed:" + str(path))
    return completed.stdout.strip()
