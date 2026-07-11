from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineStep:
    agent_name: str
    default_model: str


PIPELINE_STEPS = (
    PipelineStep("conversation_agent", "qwen3.7-plus"),
    PipelineStep("knowledge_ingestion_agent", "qwen3.7-plus"),
    PipelineStep("rag_builder_agent", "text-embedding-v4"),
    PipelineStep("target_agent", "qwen3.7-plus"),
    PipelineStep("sar_agent", "qwen3.7-plus"),
    PipelineStep("generator_agent", "qwen3.7-max"),
    PipelineStep("filter_agent", "tool-adapter"),
    PipelineStep("docking_agent", "tool-adapter"),
    PipelineStep("admet_agent", "tool-adapter"),
    PipelineStep("synthesis_agent", "tool-adapter"),
    PipelineStep("self_refutation_agent", "deepseek-v4-pro"),
    PipelineStep("ranker_agent", "qwen3.7-max"),
    PipelineStep("advisor_agent", "qwen3.7-plus"),
    PipelineStep("report_agent", "qwen3.7-plus"),
)

PIPELINE_AGENTS = [(step.agent_name, step.default_model) for step in PIPELINE_STEPS]

