"""AutoGrow4 generation agent."""

from pathlib import Path

from medagent.agents.generation_base import GenerationAgent, grid_values
from medagent.domain.schemas import AgentName, AgentTask


class AutoGrow4Agent(GenerationAgent):
    agent_name: AgentName = "autogrow4"

    def _skip_reason(self, task: AgentTask) -> str | None:
        receptor_file = task.constraints.get("receptor_file")
        if not receptor_file:
            return "autogrow4_requires_receptor_file"
        try:
            receptor_path = Path(str(receptor_file)).expanduser()
        except OSError:
            return "autogrow4_receptor_file_invalid"
        if not receptor_path.is_file():
            return "autogrow4_receptor_file_not_found"
        if grid_values(task.constraints) is None:
            return "autogrow4_requires_grid_center_and_size"
        return None
