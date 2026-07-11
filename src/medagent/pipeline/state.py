from typing import Literal


PipelineStatus = Literal[
    "pipeline_queued",
    "pipeline_running",
    "pipeline_completed",
    "pipeline_failed",
]

PIPELINE_QUEUED: PipelineStatus = "pipeline_queued"
PIPELINE_RUNNING: PipelineStatus = "pipeline_running"
PIPELINE_COMPLETED: PipelineStatus = "pipeline_completed"
PIPELINE_FAILED: PipelineStatus = "pipeline_failed"

