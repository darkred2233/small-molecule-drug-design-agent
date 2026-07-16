from medagent.agents.planner import PlannerAgent
from medagent.db.models import Project
from medagent.services.run_plan import build_default_run_plan


def test_planner_generates_structured_plan_for_herg_three_round_request():
    project = Project(
        project_id="PROJ-PLAN-HERG",
        name="Planner hERG",
        objective="优化 EGFR seed",
    )
    current_plan = build_default_run_plan(project)

    result = PlannerAgent(use_llm=False).plan(
        "帮我围绕这个 seed 自动优化三轮，优先降低 hERG。",
        current_plan=current_plan,
    )

    assert result.intent == "update_run_plan"
    assert result.run_plan.max_rounds == 3
    assert result.run_plan.constraints["reduce_hERG"] is True
    assert result.run_plan.auto_run is True
    assert result.suggested_execution is True
    assert {change.path for change in result.plan_diff} >= {
        "constraints.reduce_hERG",
        "auto_run",
    }


def test_planner_generates_patch_to_disable_autogrow4():
    project = Project(project_id="PROJ-PLAN-AUTOGROW", name="Planner AutoGrow")
    current_plan = build_default_run_plan(project)

    result = PlannerAgent(use_llm=False).plan(
        "下一轮不要跑 AutoGrow4，先用 CReM 做保守修改。",
        current_plan=current_plan,
    )

    assert result.intent == "update_run_plan"
    assert result.plan_patch is not None
    assert result.run_plan.agents["autogrow4"].enabled is False
    assert result.run_plan.agents["autogrow4"].condition is None
    assert result.run_plan.agents["crem"].enabled is True
    assert result.run_plan.agents["crem"].budget == "high"
    assert result.run_plan.auto_run is False
    assert result.suggested_execution is False
    assert {
        (change.path, change.new_value)
        for change in result.plan_diff
    } >= {
        ("agents.autogrow4.enabled", False),
        ("agents.crem.budget", "high"),
    }


def test_planner_keeps_synthesis_feasibility_but_routes_only_final_top_n():
    project = Project(project_id="PROJ-PLAN-SYNTHESIS", name="Planner synthesis")
    current_plan = build_default_run_plan(project)
    current_plan.evaluation.use_synthesis = False
    current_plan.evaluation.synthesis_route_scope = "every_round_top_n"

    result = PlannerAgent(use_llm=False).plan(
        "合成可行性是每次都要跑的，合成路线预测不用每次都跑，只针对最后一轮输出的 top 20 跑。",
        current_plan=current_plan,
    )

    assert result.run_plan.evaluation.use_synthesis is True
    assert result.run_plan.evaluation.synthesis_route_scope == "final_round_top_n"
    assert result.run_plan.evaluation.top_n == 20
    assert {
        (change.path, change.new_value)
        for change in result.plan_diff
    } >= {
        ("evaluation.use_synthesis", True),
        ("evaluation.synthesis_route_scope", "final_round_top_n"),
        ("evaluation.top_n", 20),
    }


def test_planner_updates_agent_counts_and_next_round_seed_count():
    project = Project(project_id="PROJ-PLAN-COUNTS", name="Planner counts")
    current_plan = build_default_run_plan(project)

    result = PlannerAgent(use_llm=False).plan(
        "用标准优化，REINVENT4 生成 12 个，CReM 生成 8 个，下一轮用前 6 个种子。",
        current_plan=current_plan,
    )

    assert result.run_plan.max_rounds == 3
    assert result.run_plan.next_round_seed_count == 6
    assert result.run_plan.agents["reinvent4"].requested_count == 12
    assert result.run_plan.agents["crem"].requested_count == 8
    assert {
        (change.path, change.new_value)
        for change in result.plan_diff
    } >= {
        ("agents.reinvent4.requested_count", 12),
        ("agents.crem.requested_count", 8),
        ("next_round_seed_count", 6),
    }
