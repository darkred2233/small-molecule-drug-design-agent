#!/bin/bash
# 架构修复结构验证脚本 - 无需 Python 依赖

echo "============================================================"
echo "SelfRefutation 架构修复 - 结构验证"
echo "============================================================"
echo ""

PASS=0
TOTAL=0

# 测试 1: RankerAgent 不再依赖 SelfRefutationAgent
echo "测试 1: RankerAgent 独立性"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 3))

if ! grep -q "from medagent.agents.self_refutation import" src/medagent/agents/ranker.py; then
    echo "✓ RankerAgent 不再导入 SelfRefutationAgent"
    PASS=$((PASS + 1))
else
    echo "✗ RankerAgent 仍然导入 SelfRefutationAgent"
fi

if grep -q "from medagent.db.models import.*Critique" src/medagent/agents/ranker.py; then
    echo "✓ RankerAgent 导入 Critique 模型"
    PASS=$((PASS + 1))
else
    echo "✗ RankerAgent 未导入 Critique 模型"
fi

if grep -q "db.query(Critique)" src/medagent/agents/ranker.py; then
    echo "✓ RankerAgent 直接查询 Critique 表"
    PASS=$((PASS + 1))
else
    echo "✗ RankerAgent 未查询 Critique 表"
fi

echo ""

# 测试 2: RankerAgent 使用 Critique 数据
echo "测试 2: RankerAgent 使用 Critique 数据"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 4))

if grep -q "critique.con_score\|critique_con_score" src/medagent/agents/ranker.py; then
    echo "✓ RankerAgent 使用 con_score"
    PASS=$((PASS + 1))
else
    echo "✗ RankerAgent 未使用 con_score"
fi

if grep -q "critique.refutation_decision\|refutation_decision" src/medagent/agents/ranker.py; then
    echo "✓ RankerAgent 使用 refutation_decision"
    PASS=$((PASS + 1))
else
    echo "✗ RankerAgent 未使用 refutation_decision"
fi

if grep -q "llm_critique_json\|llm_provider" src/medagent/agents/ranker.py; then
    echo "✓ RankerAgent 访问 LLM 质询结果"
    PASS=$((PASS + 1))
else
    echo "✗ RankerAgent 未访问 LLM 质询结果"
fi

if grep -q '"reject"\|"reserve"\|"pass"' src/medagent/agents/ranker.py; then
    echo "✓ RankerAgent 根据 decision 调整分数"
    PASS=$((PASS + 1))
else
    echo "✗ RankerAgent 未根据 decision 调整分数"
fi

echo ""

# 测试 3: agents/self_refutation.py 标记为废弃
echo "测试 3: agents/self_refutation.py 废弃标记"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 3))

if grep -q "DEPRECATED" src/medagent/agents/self_refutation.py; then
    echo "✓ self_refutation.py 标记为 DEPRECATED"
    PASS=$((PASS + 1))
else
    echo "✗ self_refutation.py 未标记为 DEPRECATED"
fi

if grep -q "DeprecationWarning" src/medagent/agents/self_refutation.py; then
    echo "✓ 包含 DeprecationWarning"
    PASS=$((PASS + 1))
else
    echo "✗ 未包含 DeprecationWarning"
fi

if grep -q "generate_project_critiques" src/medagent/agents/self_refutation.py; then
    echo "✓ 包含迁移指南"
    PASS=$((PASS + 1))
else
    echo "✗ 缺少迁移指南"
fi

echo ""

# 测试 4: Critique 模型包含 LLM 字段
echo "测试 4: Critique 模型 LLM 字段"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 2))

if grep -q "llm_critique_json.*Mapped" src/medagent/db/models.py; then
    echo "✓ Critique 模型包含 llm_critique_json 字段"
    PASS=$((PASS + 1))
else
    echo "✗ Critique 模型缺少 llm_critique_json 字段"
fi

if grep -q "llm_provider.*Mapped" src/medagent/db/models.py; then
    echo "✓ Critique 模型包含 llm_provider 字段"
    PASS=$((PASS + 1))
else
    echo "✗ Critique 模型缺少 llm_provider 字段"
fi

echo ""

# 测试 5: services/self_refutation.py LLM 质询
echo "测试 5: services/self_refutation.py LLM 质询"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 3))

if grep -q "def _llm_critique" src/medagent/services/self_refutation.py; then
    echo "✓ 包含 _llm_critique 方法"
    PASS=$((PASS + 1))
else
    echo "✗ 缺少 _llm_critique 方法"
fi

if grep -q "hidden_risks.*evidence_concerns.*analogy_failures" src/medagent/services/self_refutation.py; then
    echo "✓ LLM 质询包含 4 个维度"
    PASS=$((PASS + 1))
else
    echo "✗ LLM 质询缺少维度"
fi

if grep -A 5 "_build_critique_blueprint" src/medagent/services/self_refutation.py | grep -q "_llm_critique"; then
    echo "✓ _build_critique_blueprint 调用 _llm_critique"
    PASS=$((PASS + 1))
else
    echo "✗ _build_critique_blueprint 未调用 _llm_critique"
fi

echo ""

# 测试 6: ReportAgent 更新
echo "测试 6: ReportAgent 更新"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 2))

if grep -q "from medagent.db.models import.*Critique" src/medagent/agents/report.py || \
   grep -q "Critique," src/medagent/agents/report.py; then
    echo "✓ ReportAgent 导入 Critique"
    PASS=$((PASS + 1))
else
    echo "✗ ReportAgent 未导入 Critique"
fi

if grep -q "# DEPRECATED.*RefutationResult\|DEPRECATED.*self_refutation" src/medagent/agents/report.py; then
    echo "✓ ReportAgent 标记了废弃导入"
    PASS=$((PASS + 1))
else
    echo "✗ ReportAgent 未标记废弃导入"
fi

echo ""

# 测试 7: 配置文件
echo "测试 7: 配置文件"
echo "------------------------------------------------------------"
TOTAL=$((TOTAL + 2))

if grep -A 5 "self_refutation:" config.yaml | grep -q "use_llm: true"; then
    echo "✓ self_refutation.use_llm 配置正确"
    PASS=$((PASS + 1))
else
    echo "✗ self_refutation.use_llm 配置错误"
fi

if grep -A 5 "self_refutation:" config.yaml | grep -q 'provider: "deepseek"'; then
    echo "✓ self_refutation.provider 配置正确"
    PASS=$((PASS + 1))
else
    echo "✗ self_refutation.provider 配置错误"
fi

echo ""

# 汇总
echo "============================================================"
echo "测试结果汇总"
echo "============================================================"
echo "通过: $PASS / $TOTAL"
echo ""

if [ $PASS -eq $TOTAL ]; then
    echo "🎉 所有测试通过！架构修复验证成功。"
    echo ""
    exit 0
else
    FAILED=$((TOTAL - PASS))
    echo "⚠️  有 $FAILED 个测试失败。"
    echo ""
    exit 1
fi
