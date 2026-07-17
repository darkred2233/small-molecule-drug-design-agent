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


# Round statuses
ROUND_DRAFT = "draft"
ROUND_READY = "ready"
ROUND_RUNNING = "running"
ROUND_COMPLETED = "completed"
ROUND_FAILED = "failed"
ROUND_CANCELLED = "cancelled"

# Campaign statuses
CAMPAIGN_PENDING = "pending"
CAMPAIGN_RUNNING = "running"
CAMPAIGN_COMPLETED = "completed"
CAMPAIGN_FAILED = "failed"
CAMPAIGN_SKIPPED = "skipped"

