import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.db.models import (
    Base,
    BindingSite,
    ExecutionManifest,
    Project,
    ProjectStructure,
    ScientificArtifact,
    Target,
    TargetResourceLink,
    UploadedFile,
)
from medagent.db.session import build_engine, build_session_factory
from medagent.services.p2rank_adapter import run_project_p2rank
from medagent.services.scientific_workflow import prepare_round_preflight


def _pdb_line(serial: int, atom: str, residue: str, chain: str, number: int, x: float) -> str:
    return (
        f"ATOM  {serial:5d}  {atom:<3s} {residue:>3s} {chain}{number:4d}"
        f"    {x:8.3f}{x + 1:8.3f}{x + 2:8.3f}  1.00 10.00           C\n"
    )


def _setup_project(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'p2rank.db'}",
        storage_local_root=str(tmp_path / "uploads"),
    )
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)
    receptor = tmp_path / "egfr.pdb"
    receptor.write_text(
        "".join(
            [
                _pdb_line(1, "CA", "MET", "A", 10, 1.0),
                _pdb_line(2, "CB", "MET", "A", 10, 2.0),
                _pdb_line(3, "CA", "LYS", "A", 20, 20.0),
                _pdb_line(4, "CB", "LYS", "A", 20, 21.0),
                "END\n",
            ]
        ),
        encoding="utf-8",
    )
    with session_factory() as db:
        target = Target(target_id="TGT-P2RANK", name="P2Rank", aliases=[], pdb_ids=[])
        project = Project(project_id="PROJ-P2RANK", name="P2Rank", target_id=target.target_id)
        source = UploadedFile(
            file_id="FILE-P2RANK",
            project_id=project.project_id,
            filename="egfr.pdb",
            file_type="pdb",
            storage_path=f"local://{receptor}",
            parse_status="parsed",
        )
        db.add_all([target, project, source])
        db.commit()
    return settings, session_factory


def test_p2rank_prediction_persists_all_predicted_pockets_and_audit_artifacts(tmp_path, monkeypatch):
    settings, session_factory = _setup_project(tmp_path)

    def fake_status():
        return {
            "available": True,
            "runtime_available": True,
            "java_executable": "java.exe",
            "launcher": "prank.bat",
            "working_directory": str(tmp_path),
            "version": "2.5.1",
        }

    def fake_run(command, **kwargs):
        output = Path(command[command.index("-o") + 1])
        output.mkdir(parents=True)
        (output / "input.pdb_predictions.csv").write_text(
            "name,rank,score,probability,sas_points,surf_atoms,center_x,center_y,center_z,residue_ids,surf_atom_ids\n"
            "pocket1,1,9.77,0.525,70,40,1.5,2.5,3.5,A_10,1 2\n"
            "pocket2,2,3.04,0.101,37,18,20.5,21.5,22.5,A_20,3 4\n",
            encoding="utf-8",
        )
        (output / "input.pdb_residues.csv").write_text("chain,residue_label,pocket\nA,10,1\n", encoding="utf-8")
        (output / "run.log").write_text("P2Rank completed", encoding="utf-8")

        class Completed:
            returncode = 0
            stdout = "P2Rank completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr("medagent.services.p2rank_adapter.p2rank_tool_status", fake_status)
    monkeypatch.setattr("medagent.services.p2rank_adapter.subprocess.run", fake_run)

    with session_factory() as db:
        project = db.query(Project).filter_by(project_id="PROJ-P2RANK").one()
        result = run_project_p2rank(db, settings, project, "FILE-P2RANK")
        db.commit()

        sites = db.query(BindingSite).filter_by(project_id=project.project_id).all()
        assert result.status == "succeeded", result.warnings
        assert len(sites) == 2
        assert all(site.preparation_status == "pocket_predicted" for site in sites)
        assert all(site.validation_status == "predicted_not_experimentally_validated" for site in sites)
        assert all(Path(site.grid_box["pocket_file"].removeprefix("local://")).is_file() for site in sites)
        assert all(site.grid_box["derivation"] == "p2rank_residue_bounds_v1" for site in sites)
        assert db.query(ScientificArtifact).count() >= 5
        assert db.query(TargetResourceLink).filter_by(target_id="TGT-P2RANK").count() >= 5
        manifest = db.query(ExecutionManifest).filter_by(project_id=project.project_id).one()
        assert manifest.status == "succeeded"
        assert manifest.output_artifacts["predictions_csv"]["sha256"]
        audited_site = manifest.result_json["payload"]["binding_sites"][0]
        assert audited_site["center"] == sites[0].grid_box["center"]
        assert audited_site["size"] == sites[0].grid_box["size"]
        assert audited_site["pocket_artifact"]["sha256"]


def test_p2rank_uses_absolute_command_paths_with_relative_storage_root(tmp_path, monkeypatch):
    settings, session_factory = _setup_project(tmp_path)
    application_directory = tmp_path / "application"
    working_directory = tmp_path / "p2rank-tool"
    application_directory.mkdir()
    working_directory.mkdir()
    monkeypatch.chdir(application_directory)
    settings.storage_local_root = "relative-storage"

    monkeypatch.setattr(
        "medagent.services.p2rank_adapter.p2rank_tool_status",
        lambda: {
            "available": True,
            "runtime_available": True,
            "java_executable": "java.exe",
            "launcher": "prank.bat",
            "working_directory": str(working_directory),
            "version": "2.5.1",
        },
    )

    def fake_run(command, **kwargs):
        input_path = Path(command[command.index("-f") + 1])
        output_path = Path(command[command.index("-o") + 1])
        assert input_path.is_absolute()
        assert output_path.is_absolute()
        assert kwargs["cwd"] == working_directory
        output_path.mkdir(parents=True)
        (output_path / "input.pdb_predictions.csv").write_text(
            "name,rank,score,probability,sas_points,surf_atoms,center_x,center_y,center_z,residue_ids,surf_atom_ids\n"
            "pocket1,1,9.77,0.525,70,40,1.5,2.5,3.5,A_10,1 2\n",
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stdout = "P2Rank completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr("medagent.services.p2rank_adapter.subprocess.run", fake_run)

    with session_factory() as db:
        project = db.query(Project).filter_by(project_id="PROJ-P2RANK").one()
        result = run_project_p2rank(db, settings, project, "FILE-P2RANK")

    assert result.status == "succeeded"


def test_p2rank_reports_runtime_blocked_without_creating_sites(tmp_path, monkeypatch):
    settings, session_factory = _setup_project(tmp_path)
    monkeypatch.setattr(
        "medagent.services.p2rank_adapter.p2rank_tool_status",
        lambda: {"available": False, "warning": "p2rank_required_files_missing"},
    )

    with session_factory() as db:
        project = db.query(Project).filter_by(project_id="PROJ-P2RANK").one()
        result = run_project_p2rank(db, settings, project, "FILE-P2RANK")

        assert result.status == "runtime_blocked"
        assert result.warnings == ["p2rank_required_files_missing"]
        assert db.query(BindingSite).count() == 0


def test_p2rank_rejects_an_entire_run_when_any_predicted_pocket_is_unusable(tmp_path, monkeypatch):
    settings, session_factory = _setup_project(tmp_path)

    monkeypatch.setattr(
        "medagent.services.p2rank_adapter.p2rank_tool_status",
        lambda: {
            "available": True,
            "runtime_available": True,
            "java_executable": "java.exe",
            "launcher": "prank.bat",
            "working_directory": str(tmp_path),
            "version": "2.5.1",
        },
    )

    def fake_run(command, **kwargs):
        output = Path(command[command.index("-o") + 1])
        output.mkdir(parents=True)
        (output / "input.pdb_predictions.csv").write_text(
            "name,rank,score,probability,sas_points,surf_atoms,center_x,center_y,center_z,residue_ids,surf_atom_ids\n"
            "pocket1,1,9.77,0.525,70,40,1.5,2.5,3.5,A_10,1 2\n"
            "pocket2,2,3.04,0.101,37,18,20.5,21.5,22.5,A_999,3 4\n",
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stdout = "P2Rank completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr("medagent.services.p2rank_adapter.subprocess.run", fake_run)

    with session_factory() as db:
        project = db.query(Project).filter_by(project_id="PROJ-P2RANK").one()
        result = run_project_p2rank(db, settings, project, "FILE-P2RANK")

        assert result.status == "failed"
        assert result.warnings == ["p2rank_output_parse_failed"]
        assert db.query(BindingSite).count() == 0


def test_p2rank_pocket_makes_targetdiff_eligible_in_the_project_preflight(tmp_path, monkeypatch):
    settings, session_factory = _setup_project(tmp_path)

    monkeypatch.setattr(
        "medagent.services.p2rank_adapter.p2rank_tool_status",
        lambda: {
            "available": True,
            "runtime_available": True,
            "java_executable": "java.exe",
            "launcher": "prank.bat",
            "working_directory": str(tmp_path),
            "version": "2.5.1",
        },
    )

    def fake_run(command, **kwargs):
        output = Path(command[command.index("-o") + 1])
        output.mkdir(parents=True)
        (output / "input.pdb_predictions.csv").write_text(
            "name,rank,score,probability,sas_points,surf_atoms,center_x,center_y,center_z,residue_ids,surf_atom_ids\n"
            "pocket1,1,9.77,0.525,70,40,1.5,2.5,3.5,A_10,1 2\n",
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stdout = "P2Rank completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr("medagent.services.p2rank_adapter.subprocess.run", fake_run)

    with session_factory() as db:
        project = db.query(Project).filter_by(project_id="PROJ-P2RANK").one()
        source = db.query(UploadedFile).filter_by(file_id="FILE-P2RANK").one()
        source_path = Path(source.storage_path.removeprefix("local://"))
        source.metadata_json = {
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "size_bytes": source_path.stat().st_size,
        }
        prepared_path = tmp_path / "receptor.pdbqt"
        prepared_path.write_text("ATOM prepared receptor\n", encoding="utf-8")
        structure = ProjectStructure(
            structure_id="STR-P2RANK",
            project_id=project.project_id,
            target_id=project.target_id,
            source="upload",
            source_identifier=source.file_id,
            source_file_id=source.file_id,
            status="prepared",
            prepared_receptor_file=f"local://{prepared_path}",
            prepared_receptor_sha256=hashlib.sha256(prepared_path.read_bytes()).hexdigest(),
        )
        project.active_structure_id = structure.structure_id
        db.add(structure)
        db.flush()

        result = run_project_p2rank(
            db, settings, project, structure_id=structure.structure_id
        )
        assert result.status == "succeeded"
        selected_site = result.binding_sites[0]
        project.active_binding_site_id = selected_site.binding_site_id
        db.commit()

        preflight = prepare_round_preflight(
            db,
            project,
            tool_capabilities={
                "crem": {"available": False},
                "targetdiff": {"available": True},
                "autogrow4": {"available": False},
                "vina": {"available": False},
                "gnina": {"available": False},
                "admet_ai": {"available": False},
                "aizynthfinder": {"available": False},
                "rdkit": {"available": True},
            },
        )

    resource = preflight["snapshot"]["target_resource"]
    stages = {stage["stage"]: stage for stage in preflight["plan"]["stages"]}
    assert resource["package_status"] == "pocket_predicted"
    assert resource["structure_id"] == "STR-P2RANK"
    assert resource["binding_site_id"] == selected_site.binding_site_id
    assert resource["pocket_predicted"] is True
    assert resource["targetdiff_pocket"] is True
    assert resource["prepared_receptor"] is True
    assert resource["source_receptor"]["sha256"] == source.metadata_json["sha256"]
    assert resource["pocket_pdb"]["sha256"]
    assert resource["prepared_receptor_pdbqt"]["sha256"] == structure.prepared_receptor_sha256
    assert resource["grid"]["center"] == selected_site.grid_box["center"]
    assert resource["grid"]["size"] == selected_site.grid_box["size"]
    assert resource["artifact_hashes_complete"] is True
    assert stages["generate_candidates"]["allowed"] is True
    assert "predicted_not_experimentally_validated" in stages["generate_candidates"]["warnings"]


def test_p2rank_api_predicts_only_from_a_project_owned_uploaded_receptor(tmp_path, monkeypatch):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        storage_local_root=str(tmp_path / "uploads"),
    )

    def fake_status():
        return {
            "available": True,
            "runtime_available": True,
            "java_executable": "java.exe",
            "launcher": "prank.bat",
            "working_directory": str(tmp_path),
            "version": "2.5.1",
        }

    def fake_run(command, **kwargs):
        output = Path(command[command.index("-o") + 1])
        output.mkdir(parents=True)
        (output / "input.pdb_predictions.csv").write_text(
            "name,rank,score,probability,sas_points,surf_atoms,center_x,center_y,center_z,residue_ids,surf_atom_ids\n"
            "pocket1,1,9.77,0.525,70,40,1.5,2.5,3.5,A_10,1 2\n",
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stdout = "P2Rank completed"
            stderr = ""

        return Completed()

    monkeypatch.setattr("medagent.services.p2rank_adapter.p2rank_tool_status", fake_status)
    monkeypatch.setattr("medagent.services.p2rank_adapter.subprocess.run", fake_run)

    with TestClient(create_app(settings)) as client:
        project = client.post(
            "/projects", json={"name": "P2Rank API", "target_id": "TGT-EGFR", "objective": "test"}
        ).json()
        receptor = "".join(
            [
                _pdb_line(1, "CA", "MET", "A", 10, 1.0),
                _pdb_line(2, "CB", "MET", "A", 10, 2.0),
            ]
        ).encode("utf-8")
        upload = client.post(
            f"/projects/{project['project_id']}/files",
            files={"file": ("receptor.pdb", receptor, "chemical/x-pdb")},
        )
        assert upload.status_code == 202

        response = client.post(
            f"/projects/{project['project_id']}/p2rank/predict",
            json={"source_file_id": upload.json()["file_id"]},
        )

        assert response.status_code == 200, response.text
        site = response.json()["binding_sites"][0]
        assert site["structure_id"]
        project_state = client.get(f"/projects/{project['project_id']}").json()
        assert project_state["active_structure_id"] == site["structure_id"]

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["input_status"] == "predicted_not_experimentally_validated"
    assert len(body["binding_sites"]) == 1
    assert body["binding_sites"][0]["preparation_status"] == "pocket_predicted"
