"""REINVENT4 generation agent."""

from medagent.agents.generation_base import GenerationAgent
from medagent.domain.schemas import AgentName


class Reinvent4Agent(GenerationAgent):
    agent_name: AgentName = "reinvent4"
