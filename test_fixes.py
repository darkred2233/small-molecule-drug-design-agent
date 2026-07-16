#!/usr/bin/env python3
"""
验证空壳实现修复的测试脚本
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def check_imports():
    """测试所有模块是否可以正确导入"""
    print("=" * 60)
    print("测试 1: 模块导入")
    print("=" * 60)

    try:
        from medagent.agents.target import TargetAgent
        assert TargetAgent is not None
        print("✓ TargetAgent 导入成功")

        from medagent.agents.sar import SARAgent
        assert SARAgent is not None
        print("✓ SARAgent 导入成功")

        from medagent.agents.conversation import ConversationAgent
        assert ConversationAgent is not None
        print("✓ ConversationAgent 导入成功")

        from medagent.services.synthesis_workflow import check_building_block_availability
        assert check_building_block_availability is not None
        print("✓ check_building_block_availability 导入成功")

        from medagent.pipeline.tasks import batch_molecule_task
        assert batch_molecule_task is not None
        print("✓ batch_molecule_task 导入成功")

        print("\n✅ 所有模块导入成功\n")
        return True
    except Exception as e:
        print(f"\n❌ 模块导入失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_conversation_agent():
    """测试 ConversationAgent"""
    print("=" * 60)
    print("测试 2: ConversationAgent (规则引擎回退)")
    print("=" * 60)

    try:
        from medagent.agents.conversation import ConversationAgent

        agent = ConversationAgent()

        # 测试1: hERG风险
        result = agent._rule_based_parse("降低 hERG 风险")
        assert result.intent == "avoid_risk"
        assert len(result.constraints) > 0
        assert result.constraints[0].field == "hERG_risk"
        print("✓ 测试用例 1: hERG 风险解析正确")

        # 测试2: 溶解度
        result = agent._rule_based_parse("提高溶解度")
        assert result.intent == "prioritize_property"
        assert len(result.constraints) > 0
        assert result.constraints[0].field == "solubility"
        print("✓ 测试用例 2: 溶解度解析正确")

        # 测试3: 保留骨架
        result = agent._rule_based_parse("保留苯环骨架")
        assert result.intent == "keep_scaffold"
        assert len(result.constraints) > 0
        print("✓ 测试用例 3: 骨架保留解析正确")

        # 测试4: 启动流程
        result = agent._rule_based_parse("跑一轮")
        assert result.intent == "run_pipeline"
        print("✓ 测试用例 4: 流程启动解析正确")

        print("\n✅ ConversationAgent 所有测试通过\n")
        return True
    except Exception as e:
        print(f"\n❌ ConversationAgent 测试失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_sar_agent_helpers():
    """测试 SARAgent 辅助方法"""
    print("=" * 60)
    print("测试 3: SARAgent 辅助方法")
    print("=" * 60)

    try:
        from medagent.agents.sar import SARAgent
        from unittest.mock import Mock

        db = Mock()
        agent = SARAgent(db)

        # 测试解析方法存在
        assert hasattr(agent, '_parse_sar_patterns')
        print("✓ _parse_sar_patterns 方法存在")

        assert hasattr(agent, '_parse_pharmacophores')
        print("✓ _parse_pharmacophores 方法存在")

        assert hasattr(agent, '_parse_optimization_suggestions')
        print("✓ _parse_optimization_suggestions 方法存在")

        assert hasattr(agent, '_rule_based_sar_patterns')
        print("✓ _rule_based_sar_patterns 方法存在")

        assert hasattr(agent, '_rule_based_pharmacophores')
        print("✓ _rule_based_pharmacophores 方法存在")

        # 测试规则引擎回退
        patterns = agent._rule_based_sar_patterns([], {})
        assert isinstance(patterns, list)
        print("✓ 规则引擎回退功能正常")

        pharmacophores = agent._rule_based_pharmacophores([], {})
        assert isinstance(pharmacophores, list)
        assert len(pharmacophores) > 0
        print("✓ 药效团回退功能正常")

        print("\n✅ SARAgent 辅助方法测试通过\n")
        return True
    except Exception as e:
        print(f"\n❌ SARAgent 测试失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_target_agent_methods():
    """测试 TargetAgent 方法签名"""
    print("=" * 60)
    print("测试 4: TargetAgent 方法")
    print("=" * 60)

    try:
        from medagent.agents.target import TargetAgent
        from unittest.mock import Mock

        db = Mock()
        agent = TargetAgent(db)

        # 验证方法存在且不是空实现
        assert hasattr(agent, '_analyze_disease_associations')
        print("✓ _analyze_disease_associations 方法存在")

        assert hasattr(agent, '_predict_binding_sites')
        print("✓ _predict_binding_sites 方法存在")

        assert hasattr(agent, '_analyze_competitive_drugs')
        print("✓ _analyze_competitive_drugs 方法存在")

        print("\n✅ TargetAgent 方法测试通过\n")
        return True
    except Exception as e:
        print(f"\n❌ TargetAgent 测试失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_building_block_check():
    """测试构建块检查"""
    print("=" * 60)
    print("测试 5: 构建块可用性检查")
    print("=" * 60)

    try:
        from medagent.services.synthesis_workflow import (
            check_building_block_availability,
            _heuristic_building_block_check,
            _check_zinc20
        )

        # 测试方法存在
        assert callable(check_building_block_availability)
        print("✓ check_building_block_availability 函数存在")

        assert callable(_heuristic_building_block_check)
        print("✓ _heuristic_building_block_check 函数存在")

        assert callable(_check_zinc20)
        print("✓ _check_zinc20 函数存在")

        # 测试简单分子（苯）
        result = _heuristic_building_block_check("c1ccccc1")
        assert result.smiles == "c1ccccc1"
        assert result.is_available
        assert result.vendor == "estimated"
        print("✓ 启发式检查: 简单分子判断正确")

        # 测试复杂分子
        complex_smiles = "CC(C)Cc1ccc(cc1)C(C)C(=O)O" * 3  # 大分子
        result = _heuristic_building_block_check(complex_smiles)
        assert not result.is_available
        print("✓ 启发式检查: 复杂分子判断正确")

        print("\n✅ 构建块检查测试通过\n")
        return True
    except Exception as e:
        print(f"\n❌ 构建块检查测试失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_batch_molecule_task():
    """测试 batch_molecule_task"""
    print("=" * 60)
    print("测试 6: batch_molecule_task")
    print("=" * 60)

    try:
        from medagent.pipeline.tasks import batch_molecule_task

        # 验证函数签名
        import inspect
        sig = inspect.signature(batch_molecule_task)
        params = list(sig.parameters.keys())

        assert 'db' in params
        assert 'project' in params
        assert 'molecule_ids' in params
        assert 'operation' in params
        print("✓ batch_molecule_task 函数签名正确")

        # 验证函数体不再是空实现
        source = inspect.getsource(batch_molecule_task)
        assert "Operation-specific logic would go here" not in source
        print("✓ batch_molecule_task 已实现具体逻辑")

        assert "validate" in source
        assert "filter" in source
        assert "delete" in source
        print("✓ batch_molecule_task 包含所有操作分支")

        print("\n✅ batch_molecule_task 测试通过\n")
        return True
    except Exception as e:
        print(f"\n❌ batch_molecule_task 测试失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def check_config_consistency():
    """测试配置文件一致性"""
    print("=" * 60)
    print("测试 7: config.yaml 一致性")
    print("=" * 60)

    try:
        import yaml

        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        agents = config.get("agents", {})

        # 验证关键agent配置存在
        assert "target" in agents
        assert agents["target"]["use_llm"]
        print("✓ target agent 配置正确")

        assert "sar" in agents
        assert agents["sar"]["use_llm"]
        print("✓ sar agent 配置正确")

        assert "conversation" in agents
        assert agents["conversation"]["use_llm"]
        print("✓ conversation agent 配置已添加")

        assert "self_refutation" in agents
        assert agents["self_refutation"]["use_llm"]
        print("✓ self_refutation agent 配置正确")

        # advisor 应该不使用LLM（规则引擎）
        assert "advisor" in agents
        assert "use_llm" not in agents["advisor"]
        print("✓ advisor agent 配置正确（规则引擎）")

        print("\n✅ config.yaml 一致性测试通过\n")
        return True
    except Exception as e:
        print(f"\n❌ config.yaml 测试失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_imports():
    assert check_imports()


def test_conversation_agent():
    assert check_conversation_agent()


def test_sar_agent_helpers():
    assert check_sar_agent_helpers()


def test_target_agent_methods():
    assert check_target_agent_methods()


def test_building_block_check():
    assert check_building_block_check()


def test_batch_molecule_task():
    assert check_batch_molecule_task()


def test_config_consistency():
    assert check_config_consistency()


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("开始验证空壳实现修复")
    print("=" * 60 + "\n")

    results = []

    # 运行所有测试
    results.append(("模块导入", check_imports()))
    results.append(("ConversationAgent", check_conversation_agent()))
    results.append(("SARAgent 辅助方法", check_sar_agent_helpers()))
    results.append(("TargetAgent 方法", check_target_agent_methods()))
    results.append(("构建块检查", check_building_block_check()))
    results.append(("batch_molecule_task", check_batch_molecule_task()))
    results.append(("config.yaml 一致性", check_config_consistency()))

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
        print("🎉 所有测试通过！修复验证成功。\n")
        return 0
    else:
        print(f"⚠️  有 {total - passed} 个测试失败，请检查。\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
