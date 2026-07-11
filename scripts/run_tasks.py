"""
工具任务执行脚本

用于执行各种计算化学任务
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from medagent.db.models import Molecule, Project
from medagent.db.session import get_db
from medagent.services.admet_workflow import run_admet_workflow
from medagent.services.docking_workflow import run_docking_workflow
from medagent.services.rdkit_enhanced import validate_and_calculate_enhanced
from medagent.services.synthesis_workflow import run_synthesis_workflow


def task_validate_molecules(db: Session, project_id: str):
    """任务：验证分子并计算描述符"""
    print("=" * 60)
    print("任务：分子验证和描述符计算")
    print("=" * 60)

    project = db.query(Project).filter_by(project_id=project_id).first()
    if not project:
        print(f"错误：项目 {project_id} 不存在")
        return

    molecules = db.query(Molecule).filter_by(project_id=project_id).all()
    print(f"找到 {len(molecules)} 个分子")

    success_count = 0
    for i, molecule in enumerate(molecules, 1):
        print(f"\n[{i}/{len(molecules)}] 处理 {molecule.molecule_id}...")

        result = validate_and_calculate_enhanced(molecule.smiles)

        if result.valid:
            print(f"  ✓ 验证通过")
            print(f"    MW: {result.descriptors.mw:.1f}")
            print(f"    LogP: {result.descriptors.logp:.2f}")
            print(f"    QED: {result.descriptors.qed:.3f}")
            success_count += 1
        else:
            print(f"  ✗ 验证失败: {result.reason}")

    print(f"\n完成: {success_count}/{len(molecules)} 个分子验证成功")


def task_predict_admet(db: Session, project_id: str, use_chemprop: bool = True):
    """任务：ADMET预测"""
    print("=" * 60)
    print("任务：ADMET预测")
    print("=" * 60)

    project = db.query(Project).filter_by(project_id=project_id).first()
    if not project:
        print(f"错误：项目 {project_id} 不存在")
        return

    molecules = db.query(Molecule).filter_by(project_id=project_id).all()
    print(f"找到 {len(molecules)} 个分子")

    result = run_admet_workflow(
        db=db,
        project=project,
        molecules=molecules,
        use_chemprop=use_chemprop,
        batch_size=100,
    )

    print(f"\n完成:")
    print(f"  评估: {result.evaluated_count} 个")
    print(f"  存储: {result.stored_count} 个")
    print(f"  工具: {result.tool_name}")
    print(f"  高风险: {len(result.high_risk_molecules)} 个")
    print(f"  耗时: {result.runtime_seconds:.1f}秒")


def task_run_docking(
    db: Session,
    project_id: str,
    receptor_pdb: str,
    center_x: float,
    center_y: float,
    center_z: float,
    size_x: float = 20.0,
    size_y: float = 20.0,
    size_z: float = 20.0,
):
    """任务：分子对接"""
    print("=" * 60)
    print("任务：分子对接")
    print("=" * 60)

    project = db.query(Project).filter_by(project_id=project_id).first()
    if not project:
        print(f"错误：项目 {project_id} 不存在")
        return

    molecules = db.query(Molecule).filter_by(project_id=project_id).all()
    print(f"找到 {len(molecules)} 个分子")

    # 检查工具状态
    from medagent.services.docking_adapters import check_docking_tools_available
    tool_status = check_docking_tools_available()

    available_tools = [name for name, status in tool_status.items() if status.get("available")]
    print(f"可用对接工具: {', '.join(available_tools)}")

    if not available_tools:
        print("错误：没有可用的对接工具")
        return

    success_count = 0
    for i, molecule in enumerate(molecules, 1):
        print(f"\n[{i}/{len(molecules)}] 对接 {molecule.molecule_id}...")

        result = run_docking_workflow(
            db=db,
            project=project,
            molecule=molecule,
            receptor_pdb_file=receptor_pdb,
            binding_site_center=[center_x, center_y, center_z],
            binding_site_size=[size_x, size_y, size_z],
            tool_status=tool_status,
        )

        if result.success:
            print(f"  ✓ 对接成功")
            print(f"    工具: {result.docking_tool}")
            print(f"    Vina评分: {result.vina_score:.2f}")
            if result.cnn_score:
                print(f"    CNN评分: {result.cnn_score:.3f}")
            success_count += 1
        else:
            print(f"  ✗ 对接失败")

    print(f"\n完成: {success_count}/{len(molecules)} 个分子对接成功")


def task_assess_synthesis(db: Session, project_id: str):
    """任务：合成可及性评估"""
    print("=" * 60)
    print("任务：合成可及性评估")
    print("=" * 60)

    project = db.query(Project).filter_by(project_id=project_id).first()
    if not project:
        print(f"错误：项目 {project_id} 不存在")
        return

    molecules = db.query(Molecule).filter_by(project_id=project_id).all()
    print(f"找到 {len(molecules)} 个分子")

    success_count = 0
    for i, molecule in enumerate(molecules, 1):
        print(f"\n[{i}/{len(molecules)}] 评估 {molecule.molecule_id}...")

        result = run_synthesis_workflow(
            db=db,
            project=project,
            molecule=molecule,
            run_retrosynthesis=False,
        )

        if result.success:
            print(f"  ✓ 评估完成")
            if result.sa_score_result:
                print(f"    SA Score: {result.sa_score_result.sa_score:.2f}")
                print(f"    复杂度: {result.sa_score_result.complexity_level}")
            print(f"    总体: {result.overall_assessment}")
            success_count += 1
        else:
            print(f"  ✗ 评估失败")

    print(f"\n完成: {success_count}/{len(molecules)} 个分子评估成功")


def task_run_agents(db: Session, project_id: str, strict_mode: bool = False):
    """任务：运行Agent流程"""
    print("=" * 60)
    print("任务：运行Agent流程")
    print("=" * 60)

    project = db.query(Project).filter_by(project_id=project_id).first()
    if not project:
        print(f"错误：项目 {project_id} 不存在")
        return

    molecules = db.query(Molecule).filter_by(project_id=project_id).all()
    print(f"找到 {len(molecules)} 个分子")

    # 导入Agent
    from medagent.agents.advisor import AdvisorAgent
    from medagent.agents.ranker import RankerAgent
    from medagent.agents.report import ReportAgent
    from medagent.agents.self_refutation import SelfRefutationAgent

    # 1. Self-Refutation
    print("\n[1/4] Self-Refutation Agent...")
    refutation_agent = SelfRefutationAgent(db)
    refutation_results = refutation_agent.batch_refute(project, molecules, strict_mode)

    rejected = sum(1 for r in refutation_results if r.overall_assessment == "rejected")
    recommended = sum(1 for r in refutation_results if r.overall_assessment == "recommended")
    print(f"  完成: {rejected}个拒绝, {recommended}个推荐")

    # 2. Ranker
    print("\n[2/4] Ranker Agent...")
    ranker_agent = RankerAgent(db)
    ranking_result = ranker_agent.rank_molecules(project, molecules, use_refutation=True, strict_mode=strict_mode)
    print(f"  完成: {ranking_result.excellent_count}个优秀, {ranking_result.good_count}个良好")

    # 3. Advisor
    print("\n[3/4] Advisor Agent...")
    advisor_agent = AdvisorAgent(db)
    advisor_report = advisor_agent.analyze_project(project, ranking_result)
    print(f"  完成: {len(advisor_report.optimization_advice)}条建议, {len(advisor_report.action_plan)}项行动")

    # 4. Report
    print("\n[4/4] Report Agent...")
    report_agent = ReportAgent(db)
    project_report = report_agent.generate_report(
        project, ranking_result, advisor_report, refutation_results
    )
    print(f"  完成: 报告已生成")

    # 显示摘要
    print("\n" + "=" * 60)
    print("执行摘要")
    print("=" * 60)
    exec_summary = project_report.executive_summary
    print(f"优秀候选物: {exec_summary.excellent_candidates}个")
    print(f"成功概率: {exec_summary.success_probability * 100:.1f}%")
    print(f"下一步: {exec_summary.next_milestone}")


def main():
    parser = argparse.ArgumentParser(description="执行工具任务")
    parser.add_argument("task", choices=[
        "validate", "admet", "docking", "synthesis", "agents"
    ], help="任务类型")
    parser.add_argument("--project", required=True, help="项目ID")
    parser.add_argument("--receptor", help="受体PDB文件（对接任务需要）")
    parser.add_argument("--center", nargs=3, type=float, metavar=("X", "Y", "Z"),
                       help="结合位点中心坐标（对接任务需要）")
    parser.add_argument("--size", nargs=3, type=float, metavar=("X", "Y", "Z"),
                       default=[20.0, 20.0, 20.0], help="结合位点大小")
    parser.add_argument("--no-chemprop", action="store_true", help="不使用Chemprop")
    parser.add_argument("--strict", action="store_true", help="严格模式")

    args = parser.parse_args()

    # 获取数据库会话
    db = next(get_db())

    try:
        if args.task == "validate":
            task_validate_molecules(db, args.project)

        elif args.task == "admet":
            task_predict_admet(db, args.project, use_chemprop=not args.no_chemprop)

        elif args.task == "docking":
            if not args.receptor or not args.center:
                print("错误：对接任务需要 --receptor 和 --center 参数")
                sys.exit(1)
            task_run_docking(
                db, args.project, args.receptor,
                args.center[0], args.center[1], args.center[2],
                args.size[0], args.size[1], args.size[2]
            )

        elif args.task == "synthesis":
            task_assess_synthesis(db, args.project)

        elif args.task == "agents":
            task_run_agents(db, args.project, strict_mode=args.strict)

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
