"""Unified entry point for molecule generation agents."""

from medagent.agents.autogrow4_agent import AutoGrow4Agent
from medagent.agents.crem_agent import CremAgent
from medagent.agents.generation_base import GenerationAgent
from medagent.agents.reinvent4_agent import Reinvent4Agent
from medagent.domain.schemas import AgentName, AgentResult, AgentTask


GENERATION_AGENTS: dict[AgentName, GenerationAgent] = {
    "reinvent4": Reinvent4Agent(),
    "crem": CremAgent(),
    "autogrow4": AutoGrow4Agent(),
}


def run_generation_agent(task: AgentTask) -> AgentResult:
    return GENERATION_AGENTS[task.agent].run(task)


__all__ = [
    "AutoGrow4Agent",
    "CremAgent",
    "GENERATION_AGENTS",
    "GenerationAgent",
    "Reinvent4Agent",
    "run_generation_agent",
]
