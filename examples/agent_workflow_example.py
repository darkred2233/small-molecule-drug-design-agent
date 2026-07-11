"""
完整Agent流程使用示例

展示如何使用所有4个Agent进行端到端的候选分子评估
"""

from sqlalchemy.orm import Session

from medagent.agents.advisor import AdvisorAgent
from medagent.agents.ranker import RankerAgent, RankingWeights
from medagent.agents.report import ReportAgent
from medagent.agents.self_refutation import SelfRefutationAgent
from medagent.db.models import Molecule, Project


def run_complete_agent_workflow(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    strict_mode: bool = False,
) -> dict:
    """
    运行完整的Agent工作流

    流程：
    1. Self-Refutation Agent: 批判性审查每个分子
    2. Ranker Agent: 综合排序和分层
    3. Advisor Agent: 分析并提供建议
    4. Report Agent: 生成完整报告

    Args:
        db: 数据库会话
        project: 项目对象
        molecules: 候选分子列表
        strict_mode: 严格模式

    Returns:
        包含所有Agent结果的字典
    """

    print(f"开始完整Agent工作流，共{len(molecules)}个候选分子...")
    print()

    # ========================================
    # 第1步：Self-Refutation Agent
    # ========================================
    print("=" * 60)
    print("步骤1: Self-Refutation Agent - 批判性审查")
    print("=" * 60)

    refutation_agent = SelfRefutationAgent(db)
    refutation_results = refutation_agent.batch_refute(
        project=project,
        molecules=molecules,
        strict_mode=strict_mode,
    )

    # 统计反驳结果
    rejected = sum(1 for r in refutation_results if r.overall_assessment == "rejected")
    questionable = sum(1 for r in refutation_results if r.overall_assessment == "questionable")
    acceptable = sum(1 for r in refutation_results if r.overall_assessment == "acceptable")
    recommended = sum(1 for r in refutation_results if r.overall_assessment == "recommended")

    print(f"反驳评估完成：")
    print(f"  - 拒绝: {rejected}个")
    print(f"  - 存疑: {questionable}个")
    print(f"  - 可接受: {acceptable}个")
    print(f"  - 推荐: {recommended}个")
    print()

    # ========================================
    # 第2步：Ranker Agent
    # ========================================
    print("=" * 60)
    print("步骤2: Ranker Agent - 综合排序")
    print("=" * 60)

    ranker_agent = RankerAgent(db)

    # 配置权重（可选）
    weights = RankingWeights(
        structure_weight=0.2,
        admet_weight=0.3,
        docking_weight=0.35,
        synthesis_weight=0.15,
    )

    ranking_result = ranker_agent.rank_molecules(
        project=project,
        molecules=molecules,
        weights=weights,
        use_refutation=True,
        strict_mode=strict_mode,
    )

    print(f"排序完成：")
    print(f"  - 优秀（≥80分）: {ranking_result.excellent_count}个")
    print(f"  - 良好（65-79分）: {ranking_result.good_count}个")
    print(f"  - 可接受（50-64分）: {ranking_result.acceptable_count}个")
    print(f"  - 较差（<50分）: {ranking_result.poor_count}个")
    print()

    # 显示Top 5
    print("Top 5 候选分子:")
    for i, mol_score in enumerate(ranking_result.ranked_molecules[:5], 1):
        print(f"  {i}. {mol_score.details.get('mol_name', mol_score.molecule_id[:8])}")
        print(f"     最终评分: {mol_score.final_score:.1f} | 层级: {mol_score.tier}")
        print(f"     结构:{mol_score.structure_score:.0f} ADMET:{mol_score.admet_score:.0f} "
              f"对接:{mol_score.docking_score:.0f} 合成:{mol_score.synthesis_score:.0f}")
    print()

    # ========================================
    # 第3步：Advisor Agent
    # ========================================
    print("=" * 60)
    print("步骤3: Advisor Agent - 专业建议")
    print("=" * 60)

    advisor_agent = AdvisorAgent(db)
    advisor_report = advisor_agent.analyze_project(
        project=project,
        ranking_result=ranking_result,
    )

    print("项目分析：")
    print(advisor_report.project_status_summary)
    print()

    print("关键发现：")
    for finding in advisor_report.key_findings[:3]:
        print(f"  • {finding}")
    print()

    print("优化建议（前3项）：")
    for advice in advisor_report.optimization_advice[:3]:
        print(f"  [{advice.priority.upper()}] {advice.title}")
        print(f"     问题: {advice.problem}")
        print(f"     建议: {advice.suggestion}")
    print()

    print("行动计划：")
    for action in advisor_report.action_plan:
        print(f"  {action.priority}. {action.title}")
        print(f"     {action.description}")
    print()

    print(f"成功概率: {advisor_report.success_probability * 100:.1f}%")
    print(f"下一个里程碑: {advisor_report.next_milestone}")
    print()

    # ========================================
    # 第4步：Report Agent
    # ========================================
    print("=" * 60)
    print("步骤4: Report Agent - 生成报告")
    print("=" * 60)

    report_agent = ReportAgent(db)
    project_report = report_agent.generate_report(
        project=project,
        ranking_result=ranking_result,
        advisor_report=advisor_report,
        refutation_results=refutation_results,
        include_details=True,
    )

    print("报告生成完成：")
    print()

    # 执行摘要
    exec_summary = project_report.executive_summary
    print(f"项目: {exec_summary.project_name}")
    print(f"报告日期: {exec_summary.report_date}")
    print(f"候选分子: {exec_summary.total_candidates}个")
    print(f"优秀候选物: {exec_summary.excellent_candidates}个")
    print()

    print("推荐候选物:")
    for mol_id in exec_summary.recommended_candidates[:3]:
        print(f"  • {mol_id}")
    print()

    print("关键成就:")
    for achievement in exec_summary.key_achievements:
        print(f"  ✓ {achievement}")
    print()

    if exec_summary.main_challenges:
        print("主要挑战:")
        for challenge in exec_summary.main_challenges:
            print(f"  ⚠ {challenge}")
        print()

    print(f"成功概率: {exec_summary.success_probability * 100:.1f}%")
    print()

    print("下一步行动:")
    for step in exec_summary.next_steps:
        print(f"  → {step}")
    print()

    # ========================================
    # 返回结果
    # ========================================
    return {
        "refutation_results": refutation_results,
        "ranking_result": ranking_result,
        "advisor_report": advisor_report,
        "project_report": project_report,
    }


def quick_evaluate_top_molecules(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    n: int = 10,
) -> list:
    """
    快速评估Top N分子

    简化流程，只进行排序和反驳
    """
    print(f"快速评估Top {n}分子...")

    # 反驳
    refutation_agent = SelfRefutationAgent(db)
    refutation_results = refutation_agent.batch_refute(project, molecules)

    # 排序
    ranker_agent = RankerAgent(db)
    ranking_result = ranker_agent.rank_molecules(
        project, molecules, use_refutation=True
    )

    # 获取Top N
    top_molecules = ranker_agent.get_top_molecules(
        ranking_result, n=n, min_tier="acceptable"
    )

    print(f"Top {len(top_molecules)} 分子:")
    for mol_score in top_molecules:
        print(f"  Rank {mol_score.rank}: {mol_score.final_score:.1f}分 ({mol_score.tier})")

    return top_molecules


def compare_two_molecules(
    db: Session,
    molecule_id1: str,
    molecule_id2: str,
) -> dict:
    """
    比较两个分子

    使用Ranker Agent的比较功能
    """
    # 这里需要先获取分子的评分
    # 实际使用中需要先运行排序
    pass


# ========================================
# 使用示例
# ========================================

if __name__ == "__main__":
    # 示例：运行完整工作流
    # from medagent.db.session import get_db
    #
    # db = next(get_db())
    # project = db.query(Project).filter_by(project_id="PROJ-001").first()
    # molecules = db.query(Molecule).filter_by(project_id=project.project_id).all()
    #
    # results = run_complete_agent_workflow(
    #     db=db,
    #     project=project,
    #     molecules=molecules,
    #     strict_mode=False,
    # )
    #
    # # 访问结果
    # ranking = results["ranking_result"]
    # advisor = results["advisor_report"]
    # report = results["project_report"]

    print("Agent工作流示例脚本")
    print("请在实际环境中调用上述函数")
