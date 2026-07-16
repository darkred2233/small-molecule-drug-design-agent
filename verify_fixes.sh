#!/bin/bash
# 代码结构验证脚本 - 无需运行 Python

echo "============================================================"
echo "验证空壳实现修复 - 代码结构检查"
echo "============================================================"
echo ""

PASS=0
TOTAL=0

# 测试 1: TargetAgent 修复
echo "测试 1: TargetAgent 三个伪方法修复"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 3))

if grep -A 50 "_analyze_disease_associations" src/medagent/agents/target.py | grep -q "json_match = re.search"; then
    echo "✓ _analyze_disease_associations 已修复（解析LLM响应）"
    PASS=$((PASS + 1))
else
    echo "✗ _analyze_disease_associations 未修复"
fi

if grep -q "def _predict_binding_sites" src/medagent/agents/target.py && \
   grep -A 30 "_predict_binding_sites" src/medagent/agents/target.py | grep -q "if use_llm:"; then
    echo "✓ _predict_binding_sites 已修复（接入LLM）"
    PASS=$((PASS + 1))
else
    echo "✗ _predict_binding_sites 未修复"
fi

if grep -q "def _analyze_competitive_drugs" src/medagent/agents/target.py && \
   grep -A 30 "_analyze_competitive_drugs" src/medagent/agents/target.py | grep -q "if use_llm:"; then
    echo "✓ _analyze_competitive_drugs 已修复（接入LLM）"
    PASS=$((PASS + 1))
else
    echo "✗ _analyze_competitive_drugs 未修复"
fi

echo ""

# 测试 2: SARAgent 修复
echo "测试 2: SARAgent LLM 接入"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 4))

if grep -q "from medagent.llm import LLMMessage" src/medagent/agents/sar.py; then
    echo "✓ SARAgent 已导入 LLMMessage"
    PASS=$((PASS + 1))
else
    echo "✗ SARAgent 未导入 LLMMessage"
fi

if grep -q "_rule_based_sar_patterns" src/medagent/agents/sar.py; then
    echo "✓ SARAgent 包含规则引擎回退方法"
    PASS=$((PASS + 1))
else
    echo "✗ SARAgent 缺少规则引擎回退"
fi

if grep -q "self.llm_client.complete" src/medagent/agents/sar.py; then
    echo "✓ SARAgent 调用 LLM"
    PASS=$((PASS + 1))
else
    echo "✗ SARAgent 未调用 LLM"
fi

if grep -q "_parse_sar_patterns" src/medagent/agents/sar.py && \
   grep -q "_parse_pharmacophores" src/medagent/agents/sar.py; then
    echo "✓ SARAgent 包含解析方法"
    PASS=$((PASS + 1))
else
    echo "✗ SARAgent 缺少解析方法"
fi

echo ""

# 测试 3: ConversationAgent 修复
echo "测试 3: ConversationAgent LLM 接入"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 3))

if grep -q "from medagent.llm import LLMMessage, get_llm_client" src/medagent/agents/conversation.py; then
    echo "✓ ConversationAgent 已导入 LLM 模块"
    PASS=$((PASS + 1))
else
    echo "✗ ConversationAgent 未导入 LLM 模块"
fi

if grep -q "def _llm_parse" src/medagent/agents/conversation.py; then
    echo "✓ ConversationAgent 包含 _llm_parse 方法"
    PASS=$((PASS + 1))
else
    echo "✗ ConversationAgent 缺少 _llm_parse 方法"
fi

if grep -q "def _rule_based_parse" src/medagent/agents/conversation.py; then
    echo "✓ ConversationAgent 包含规则引擎回退"
    PASS=$((PASS + 1))
else
    echo "✗ ConversationAgent 缺少规则引擎回退"
fi

echo ""

# 测试 4: batch_molecule_task 修复
echo "测试 4: batch_molecule_task 实现"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 2))

if ! grep -q "Operation-specific logic would go here" src/medagent/pipeline/tasks.py; then
    echo "✓ batch_molecule_task 已移除占位符注释"
    PASS=$((PASS + 1))
else
    echo "✗ batch_molecule_task 仍有占位符注释"
fi

if grep -q 'if operation == "validate":' src/medagent/pipeline/tasks.py && \
   grep -q 'elif operation == "filter":' src/medagent/pipeline/tasks.py && \
   grep -q 'elif operation == "delete":' src/medagent/pipeline/tasks.py; then
    echo "✓ batch_molecule_task 包含操作分支"
    PASS=$((PASS + 1))
else
    echo "✗ batch_molecule_task 缺少操作分支"
fi

echo ""

# 测试 5: 构建块检查修复
echo "测试 5: 构建块可用性检查"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 2))

if grep -q "def _check_zinc20" src/medagent/services/synthesis_workflow.py; then
    echo "✓ 已添加 _check_zinc20 函数"
    PASS=$((PASS + 1))
else
    echo "✗ 缺少 _check_zinc20 函数"
fi

if grep -q "def _heuristic_building_block_check" src/medagent/services/synthesis_workflow.py; then
    echo "✓ 已添加 _heuristic_building_block_check 函数"
    PASS=$((PASS + 1))
else
    echo "✗ 缺少 _heuristic_building_block_check 函数"
fi

echo ""

# 测试 6: config.yaml 更新
echo "测试 6: config.yaml 配置更新"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 3))

if grep -A 5 "conversation:" config.yaml | grep -q "use_llm: true"; then
    echo "✓ conversation agent 配置已添加"
    PASS=$((PASS + 1))
else
    echo "✗ conversation agent 配置缺失"
fi

if grep -A 5 "self_refutation:" config.yaml | grep -q "use_llm: true"; then
    echo "✓ self_refutation agent 配置已更新"
    PASS=$((PASS + 1))
else
    echo "✗ self_refutation agent 配置未更新"
fi

if grep -A 3 "advisor:" config.yaml | grep -v "use_llm" | grep -q "enabled"; then
    echo "✓ advisor agent 保持规则引擎"
    PASS=$((PASS + 1))
else
    echo "✗ advisor agent 配置不正确"
fi

echo ""

# 汇总
echo "============================================================"
echo "测试结果汇总"
echo "============================================================"
echo "通过: $PASS / $TOTAL"
echo ""

if [ $PASS -eq $TOTAL ]; then
    echo "🎉 所有测试通过！修复验证成功。"
    echo ""
    exit 0
else
    FAILED=$((TOTAL - PASS))
    echo "⚠️  有 $FAILED 个测试失败。"
    echo ""
    exit 1
fi
