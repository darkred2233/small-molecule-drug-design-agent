#!/bin/bash
echo "检查各 Agent 的 LLM 集成情况"
echo "=================================="
echo ""

for agent in target.py sar.py conversation.py generator.py advisor.py ranker.py report.py; do
    echo "--- $agent ---"
    if [ -f "src/medagent/agents/$agent" ]; then
        echo "LLM 导入:"
        grep -n "from.*llm import\|import.*llm" src/medagent/agents/$agent | head -3
        echo "LLM 调用:"
        grep -n "llm_client\|self.llm" src/medagent/agents/$agent | head -5
        echo ""
    fi
done
