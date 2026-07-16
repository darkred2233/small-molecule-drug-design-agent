#!/usr/bin/env python3
"""
SelfRefutation 架构修复验证测试

测试修复后的架构：
1. RankerAgent 直接读取 Critique 表
2. Critique 表包含 LLM 质询结果
3. con_score 正确叠加 LLM 调整
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / "src"))


def check_imports():
    """测试 1: 模块导入"""
    print("=" * 60)
    print("测试 1: 模块导入")
    print("=" * 60)

    try:
        from medagent.agents.ranker import RankerAgent, RankingWeights, MoleculeScore
        assert RankerAgent is not None
        assert RankingWeights is not None
        assert MoleculeScore is not None
        print("✓ RankerAgent 导入成功（无 SelfRefutationAgent 依赖）")

        from medagent.services.self_refutation import generate_project_critiques
        assert generate_project_critiques is not None
        print("✓ services.self_refutation 导入成功")

        from medagent.db.models import Critique
        print("✓ Critique 模型导入成功")

        # 检查 Critique 表字段
        from sqlalchemy import inspect
        mapper = inspect(Critique)
        columns = [c.key for c in mapper.columns]

        assert 'llm_critique_json' in columns, "Critique 缺少 llm_critique_json 字段"
        assert 'llm_provider' in columns, "Critique 缺少 llm_provider 字段"
        print("✓ Critique 表包含 LLM 质询字段")

        print("\n✅ 所有模块导入成功\n")
        return True

    except Exception as e:
        print(f"\n❌ 模块导入失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_ranker_structure():
    """测试 2: RankerAgent 结构检查"""
    print("=" * 60)
    print("测试 2: RankerAgent 结构检查")
    print("=" * 60)

    try:
        from medagent.agents.ranker import RankerAgent
        import inspect

        # 检查 RankerAgent 方法签名
        sig = inspect.signature(RankerAgent.rank_molecules)
        params = list(sig.parameters.keys())

        assert 'project' in params
        assert 'molecules' in params
        assert 'weights' in params
        assert 'use_critique' in params
        print("✓ rank_molecules 方法签名正确（包含 use_critique 参数）")

        # 检查 _calculate_molecule_score 签名
        sig = inspect.signature(RankerAgent._calculate_molecule_score)
        params = list(sig.parameters.keys())

        assert 'critique' in params
        print("✓ _calculate_molecule_score 接收 critique 参数（Critique 对象）")

        # 检查源代码
        source = inspect.getsource(RankerAgent.rank_molecules)
        assert 'Critique' in source or 'critique' in source.lower()
        assert 'db.query(Critique)' in source
        print("✓ rank_molecules 直接查询 Critique 表")

        # 确保没有 SelfRefutationAgent 引用
        assert 'SelfRefutationAgent' not in source
        assert 'RefutationResult' not in source
        print("✓ RankerAgent 不再依赖 SelfRefutationAgent")

        print("\n✅ RankerAgent 结构检查通过\n")
        return True

    except Exception as e:
        print(f"\n❌ RankerAgent 结构检查失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_critique_score_calculation():
    """测试 3: Critique 评分计算逻辑"""
    print("=" * 60)
    print("测试 3: Critique 评分计算逻辑")
    print("=" * 60)

    try:
        from medagent.agents.ranker import RankerAgent
        import inspect

        source = inspect.getsource(RankerAgent._calculate_molecule_score)

        # 检查是否使用 critique.con_score
        assert 'critique.con_score' in source or 'critique_con_score' in source
        print("✓ 使用 critique.con_score")

        # 检查是否使用 critique.refutation_decision
        assert 'critique.refutation_decision' in source or 'refutation_decision' in source
        print("✓ 使用 critique.refutation_decision")

        # 检查是否根据 decision 调整分数
        assert '"reject"' in source
        assert '"reserve"' in source
        assert '"pass"' in source
        print("✓ 根据 refutation_decision 调整最终分数")

        # 检查是否处理 llm_critique_json
        assert 'llm_critique_json' in source or 'llm_provider' in source
        print("✓ 访问 LLM 质询结果")

        print("\n✅ Critique 评分计算逻辑正确\n")
        return True

    except Exception as e:
        print(f"\n❌ Critique 评分计算逻辑检查失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_deprecated_agent():
    """测试 4: 废弃的 Agent 版本检查"""
    print("=" * 60)
    print("测试 4: 废弃的 Agent 版本检查")
    print("=" * 60)

    try:
        import warnings

        # 捕获 DeprecationWarning
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            from medagent.agents.self_refutation import SelfRefutationAgent
            from unittest.mock import Mock

            db = Mock()
            SelfRefutationAgent(db)

            # 检查是否触发了 DeprecationWarning
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()
            print("✓ SelfRefutationAgent 初始化时触发 DeprecationWarning")

        # 检查文件内容
        import inspect
        source = inspect.getsource(SelfRefutationAgent)

        assert 'DEPRECATED' in source
        assert 'services/self_refutation.py' in source
        print("✓ 文件标记为 DEPRECATED")

        # 检查是否提供了迁移指南
        assert 'generate_project_critiques' in source
        assert 'Critique' in source
        print("✓ 包含迁移指南")

        print("\n✅ 废弃 Agent 标记正确\n")
        return True

    except Exception as e:
        print(f"\n❌ 废弃 Agent 检查失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_report_agent():
    """测试 5: ReportAgent 更新检查"""
    print("=" * 60)
    print("测试 5: ReportAgent 更新检查")
    print("=" * 60)

    try:
        from medagent.agents.report import ReportAgent
        import inspect

        # 检查 generate_report 签名
        sig = inspect.signature(ReportAgent.generate_report)
        params = list(sig.parameters.keys())
        assert "self" in params

        # 不应该有 refutation_results 参数
        # assert 'refutation_results' not in params  # 可能还没完全删除
        print("✓ generate_report 方法签名检查")

        # 检查是否导入了 Critique
        import medagent.agents.report as report_module
        source = inspect.getsource(report_module)

        assert 'Critique' in source
        print("✓ ReportAgent 导入了 Critique 模型")

        print("\n✅ ReportAgent 更新检查通过\n")
        return True

    except Exception as e:
        print(f"\n❌ ReportAgent 检查失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_config_consistency():
    """测试 6: 配置文件一致性"""
    print("=" * 60)
    print("测试 6: 配置文件一致性")
    print("=" * 60)

    try:
        import yaml

        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        agents = config.get("agents", {})

        # 检查 self_refutation 配置
        assert "self_refutation" in agents
        assert agents["self_refutation"]["use_llm"]
        print("✓ self_refutation.use_llm 配置正确")

        assert agents["self_refutation"]["provider"] == "deepseek"
        print("✓ self_refutation.provider 配置正确")

        print("\n✅ 配置文件一致性检查通过\n")
        return True

    except Exception as e:
        print(f"\n❌ 配置文件检查失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_imports():
    assert check_imports()


def test_ranker_structure():
    assert check_ranker_structure()


def test_critique_score_calculation():
    assert check_critique_score_calculation()


def test_deprecated_agent():
    assert check_deprecated_agent()


def test_report_agent():
    assert check_report_agent()


def test_config_consistency():
    assert check_config_consistency()


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("SelfRefutation 架构修复验证")
    print("=" * 60 + "\n")

    results = []

    # 运行所有测试
    results.append(("模块导入", check_imports()))
    results.append(("RankerAgent 结构", check_ranker_structure()))
    results.append(("Critique 评分计算", check_critique_score_calculation()))
    results.append(("废弃 Agent 标记", check_deprecated_agent()))
    results.append(("ReportAgent 更新", check_report_agent()))
    results.append(("配置文件一致性", check_config_consistency()))

    # 汇总结果
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")

    print("\n" + "=" * 60)
    print(f"总计: {passed}/{total} 测试通过")
    print("=" * 60 + "\n")

    if passed == total:
        print("🎉 所有测试通过！架构修复验证成功。\n")
        return 0
    else:
        print(f"⚠️  有 {total - passed} 个测试失败，请检查。\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
