import medagent.pipeline.orchestrator as orchestrator_module
from medagent.core.config import Settings
from medagent.db.models import Base, BindingSite, Project, Target
from medagent.db.session import build_engine, build_session_factory
from medagent.pipeline.orchestrator import PipelineOrchestrator, _normalize_pipeline_config


def test_orchestrator_passes_default_drug_likeness_constraints_to_generator(tmp_path, monkeypatch):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)
    captured_constraints = {}

    def fake_generate_project_molecules(_db, _project, *, constraints, **_kwargs):
        captured_constraints.update(constraints)
        return {"molecule_count": 0, "constraints": constraints}

    monkeypatch.setattr(orchestrator_module, "generate_project_molecules", fake_generate_project_molecules)

    with session_factory() as db:
        project = Project(project_id="PROJ-CONSTRAINTS", name="Generation constraints")
        db.add(project)
        db.commit()

        output = PipelineOrchestrator(settings)._run_generation_if_needed(
            db,
            project,
            {
                "strategy_counts": {"reinvent4": 1},
                "generation_size": 1,
                "generate_when_seeds_exist": True,
            },
        )

    assert output["constraints"] == captured_constraints
    assert captured_constraints["max_mw"] == 500
    assert captured_constraints["max_logp"] == 5
    assert captured_constraints["max_tpsa"] == 140
    assert captured_constraints["max_hbd"] == 5
    assert captured_constraints["max_hba"] == 10


def test_orchestrator_passes_receptor_and_grid_to_autogrow4(tmp_path, monkeypatch):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)
    receptor_file = tmp_path / "receptor.pdb"
    receptor_file.write_text("HEADER    TEST RECEPTOR\n", encoding="utf-8")
    captured_constraints = {}

    def fake_generate_project_molecules(_db, _project, *, constraints, **_kwargs):
        captured_constraints.update(constraints)
        return {"molecule_count": 0, "constraints": constraints}

    monkeypatch.setattr(orchestrator_module, "generate_project_molecules", fake_generate_project_molecules)

    with session_factory() as db:
        target = Target(target_id="TGT-AUTOGROW", name="AutoGrow target")
        project = Project(
            project_id="PROJ-AUTOGROW",
            name="AutoGrow project",
            target_id=target.target_id,
        )
        db.add_all([target, project])
        db.flush()
        db.add(
            BindingSite(
                binding_site_id="SITE-AUTOGROW",
                project_id=project.project_id,
                target_id=target.target_id,
                receptor_file=f"local://{receptor_file}",
                grid_box={"center": [1.0, 2.0, 3.0], "size": [20.0, 20.0, 20.0]},
                key_residues=["LYS42"],
            )
        )
        db.commit()

        PipelineOrchestrator(settings)._run_generation_if_needed(
            db,
            project,
            {
                "strategy_counts": {"autogrow4": 1},
                "generation_size": 1,
                "generate_when_seeds_exist": True,
            },
        )

    assert captured_constraints["receptor_file"] == str(receptor_file)
    assert captured_constraints["grid_center"] == [1.0, 2.0, 3.0]
    assert captured_constraints["grid_size"] == [20.0, 20.0, 20.0]
    assert captured_constraints["key_residues"] == ["LYS42"]


def test_pipeline_config_preserves_candidate_assessment_mode():
    project = Project(
        project_id="PROJ-ASSESSMENT-MODE",
        name="Assessment mode",
        constraints_json={
            "pipeline_config": {
                "strategy_counts": {"reinvent4": 2, "crem": 1, "autogrow4": 0},
                "top_n": 3,
                "max_assessment_molecules": 12,
                "assessment_mode": "fast",
                "external_top_n": 2,
            }
        },
    )

    config = _normalize_pipeline_config(project)

    assert config["assessment_mode"] == "fast"
    assert config["external_top_n"] == 2
    assert config["top_n"] == 3
    assert config["max_assessment_molecules"] == 12


def test_pipeline_config_defaults_to_external_assessment_mode():
    project = Project(project_id="PROJ-ASSESSMENT-DEFAULT", name="Assessment default")

    config = _normalize_pipeline_config(project)

    assert config["assessment_mode"] == "external"
    assert config["external_top_n"] == 10
    assert config["top_n"] == 20
