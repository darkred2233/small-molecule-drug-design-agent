"""CReM generation agent."""

from medagent.agents.generation_base import GenerationAgent
from medagent.domain.schemas import AgentName


class CremAgent(GenerationAgent):
    agent_name: AgentName = "crem"
