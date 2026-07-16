from medagent.core.config import Settings
from medagent.db.models import Base, BindingSite, Project, Target
from medagent.db.session import build_engine, build_session_factory
from medagent.pipeline.orchestrator import _generation_constraints_for_round
from medagent.services.run_plan import _normalize_pipeline_config, build_default_run_plan


def test_run_plan_round_constraints_include_default_drug_likeness_limits(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)

    with session_factory() as db:
        project = Project(project_id="PROJ-CONSTRAINTS", name="Generation constraints")
        db.add(project)
        db.commit()

        run_plan = build_default_run_plan(
            project,
            {"strategy_counts": {"reinvent4": 1, "crem": 0, "autogrow4": 0}},
        )
        constraints = _generation_constraints_for_round(db, project, run_plan, round_number=1)

    assert constraints["max_mw"] == 500
    assert constraints["max_logp"] == 5
    assert constraints["max_tpsa"] == 140
    assert constraints["max_hbd"] == 5
    assert constraints["max_hba"] == 10
    assert constraints["optimization_round"] == 1


def test_run_plan_round_constraints_include_receptor_and_grid(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)
    receptor_file = tmp_path / "receptor.pdb"
    receptor_file.write_text("HEADER    TEST RECEPTOR\n", encoding="utf-8")

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

        run_plan = build_default_run_plan(
            project,
            {"strategy_counts": {"reinvent4": 0, "crem": 0, "autogrow4": 1}},
        )
        constraints = _generation_constraints_for_round(db, project, run_plan, round_number=2)

    assert constraints["receptor_file"] == str(receptor_file)
    assert constraints["grid_center"] == [1.0, 2.0, 3.0]
    assert constraints["grid_size"] == [20.0, 20.0, 20.0]
    assert constraints["key_residues"] == ["LYS42"]
    assert constraints["optimization_round"] == 2


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


def test_default_run_plan_is_derived_from_pipeline_config():
    project = Project(
        project_id="PROJ-RUN-PLAN",
        name="RunPlan derivation",
        objective="优先降低 hERG，同时保持可合成性",
        constraints_json={
            "pipeline_config": {
                "strategy_counts": {"reinvent4": 50, "crem": 10, "autogrow4": 0},
                "assessment_mode": "fast",
                "top_n": 8,
                "generation_constraints": {"max_logp": 4.0},
                "max_rounds": 2,
                "max_total_molecules": 120,
            }
        },
    )

    run_plan = build_default_run_plan(project)

    assert run_plan.status == "draft"
    assert run_plan.objective == "优先降低 hERG，同时保持可合成性"
    assert run_plan.max_rounds == 2
    assert run_plan.exploration_level == "medium"
    assert run_plan.agents["reinvent4"].enabled is True
    assert run_plan.agents["reinvent4"].budget == "high"
    assert run_plan.agents["reinvent4"].requested_count == 50
    assert run_plan.agents["crem"].budget == "low"
    assert run_plan.agents["crem"].requested_count == 10
    assert run_plan.agents["autogrow4"].enabled is False
    assert run_plan.agents["autogrow4"].requested_count == 0
    assert run_plan.evaluation.mode == "fast"
    assert run_plan.evaluation.top_n == 8
    assert run_plan.evaluation.use_docking is False
    assert run_plan.evaluation.use_synthesis is True
    assert run_plan.evaluation.synthesis_route_scope == "final_round_top_n"
    assert run_plan.constraints["max_logp"] == 4.0
    assert run_plan.stopping.max_total_molecules == 120
