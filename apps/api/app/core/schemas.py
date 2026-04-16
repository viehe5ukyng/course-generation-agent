from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ThreadStatus(str, Enum):
    COLLECTING = "collecting_requirements"
    GENERATING = "generating"
    PAUSED = "paused"
    REVIEW_PENDING = "review_pending"
    REVISING = "revising"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewSuggestionStatus(str, Enum):
    OPEN = "open"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class HumanReviewActionType(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class ConstraintKind(str, Enum):
    REQUIRE = "require"
    BAN = "ban"
    PREFER = "prefer"


class CourseMode(str, Enum):
    SINGLE = "single"
    SERIES = "series"


class WorkflowStage(str, Enum):
    CONTENT = "content_creation"
    DELIVERY = "delivery"


class StepStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"


class UploadCategory(str, Enum):
    CONTEXT = "context"
    PACKAGE = "package"
    FRAMEWORK = "framework"


class GenerationRunKind(str, Enum):
    GENERATION = "generation"
    REVISION = "revision"
    REVIEW = "review"
    CLARIFICATION = "clarification"


class GenerationRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RequirementSlot(BaseModel):
    slot_id: str
    label: str
    prompt_hint: str
    value: str | None = None
    confidence: float = 0.0
    source: str = "conversation"
    confirmed: bool = False


class DecisionItem(BaseModel):
    decision_id: str = Field(default_factory=lambda: uuid4().hex)
    topic: str
    value: str
    reason: str
    confirmed_by: str = "user"
    timestamp: datetime = Field(default_factory=utc_now)


class MessageRecord(BaseModel):
    message_id: str = Field(default_factory=lambda: uuid4().hex)
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=utc_now)
    meta: dict[str, Any] = Field(default_factory=dict)


class ConversationConstraint(BaseModel):
    constraint_id: str = Field(default_factory=lambda: uuid4().hex)
    kind: ConstraintKind
    instruction: str
    normalized_instruction: str
    source_message_id: str | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class SourceChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: uuid4().hex)
    text: str
    index: int


class SourceDocument(BaseModel):
    doc_id: str = Field(default_factory=lambda: uuid4().hex)
    filename: str
    mime_type: str
    extract_status: Literal["pending", "parsed", "failed"] = "pending"
    text_chunks: list[SourceChunk] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepState(BaseModel):
    step_id: str
    label: str
    stage: WorkflowStage
    status: StepStatus = StepStatus.PENDING
    required_slots: list[str] = Field(default_factory=list)
    optional_slots: list[str] = Field(default_factory=list)
    forbidden_topics: list[str] = Field(default_factory=list)
    needs_review: bool = True
    confirmed_at: datetime | None = None
    artifact_id: str | None = None


class SavedArtifactRecord(BaseModel):
    artifact_id: str = Field(default_factory=lambda: uuid4().hex)
    step_id: str
    label: str
    filename: str
    path: str
    kind: Literal["generated", "uploaded", "reference"] = "generated"
    version: int = 1
    updated_at: datetime = Field(default_factory=utc_now)


class DraftArtifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: uuid4().hex)
    version: int = 1
    markdown: str
    summary: str
    derived_from_feedback_ids: list[str] = Field(default_factory=list)
    source_version: int | None = None
    revision_goal: str | None = None
    generation_run_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ArtifactVersionDetail(BaseModel):
    artifact_id: str
    version: int
    markdown: str
    summary: str
    derived_from_feedback_ids: list[str] = Field(default_factory=list)
    source_version: int | None = None
    revision_goal: str | None = None
    generation_run_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ReviewCriterionResult(BaseModel):
    criterion_id: str
    name: str
    weight: float
    score: float
    max_score: float
    reason: str


class ReviewSuggestion(BaseModel):
    suggestion_id: str = Field(default_factory=lambda: uuid4().hex)
    criterion_id: str
    problem: str
    suggestion: str
    evidence_span: str
    severity: Literal["low", "medium", "high"] = "medium"
    status: ReviewSuggestionStatus = ReviewSuggestionStatus.OPEN


class ReviewBatch(BaseModel):
    review_batch_id: str = Field(default_factory=lambda: uuid4().hex)
    step_id: str
    draft_version: int
    total_score: float
    criteria: list[ReviewCriterionResult]
    suggestions: list[ReviewSuggestion]
    threshold: float = 8.0
    created_at: datetime = Field(default_factory=utc_now)


class HumanReviewAction(BaseModel):
    suggestion_id: str
    action: HumanReviewActionType
    edited_suggestion: str | None = None
    reviewer_id: str = "default-user"
    comment: str | None = None


class InterruptPayload(BaseModel):
    review_batch_id: str
    draft_version: int
    total_score: float
    criteria: list[ReviewCriterionResult]
    suggestions: list[ReviewSuggestion]
    next_expected_action: str = "submit_human_review_actions"


class ResumePayload(BaseModel):
    review_batch_id: str
    review_actions: list[HumanReviewAction]
    submitter_id: str


class ClarificationRuntimeState(BaseModel):
    missing_requirements: list[dict[str, str]] = Field(default_factory=list)
    next_requirement_to_clarify: str | None = None
    slot_summary: str = "暂无"
    latest_user_message: str = ""
    is_confirmation_reply: bool = False


class SeriesGuidedAnswer(BaseModel):
    step_id: str
    question_title: str
    selected_key: str
    selected_label: str
    final_answer: str
    custom_input: str | None = None


class SeriesGuidedRuntimeState(BaseModel):
    entry_mode: str | None = None
    awaiting_entry_mode: bool = False
    awaiting_initial_idea: bool = False
    awaiting_framework_input: bool = False
    using_existing_framework: bool = False
    imported_framework_markdown: str | None = None
    initial_user_input: str = ""
    next_question_index: int = 0
    current_question_id: str | None = None
    current_question_prompt: str | None = None
    awaiting_confirmation: bool = False
    completed: bool = False
    answers: dict[str, SeriesGuidedAnswer] = Field(default_factory=dict)


class GenerationSessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    step_id: str | None = None
    kind: GenerationRunKind = GenerationRunKind.GENERATION
    source_version: int | None = None
    revision_goal: str | None = None
    active_generation_run_id: str | None = None
    generated_markdown: str = ""
    source_summary: str = "无上传资料"
    outline: str = ""
    cases: list[dict[str, Any]] = Field(default_factory=list)
    auto_optimization_loops: int = 0
    review_batch_id: str | None = None
    started_at: datetime = Field(default_factory=utc_now)


class HumanReviewRuntimeState(BaseModel):
    interrupt_payload: InterruptPayload | None = None
    resume_payload: ResumePayload | None = None


class PauseRuntimeState(BaseModel):
    requested: bool = False
    status_before_pause: ThreadStatus | None = None


class ThreadRuntimeState(BaseModel):
    clarification: ClarificationRuntimeState = Field(default_factory=ClarificationRuntimeState)
    series_guided: SeriesGuidedRuntimeState = Field(default_factory=SeriesGuidedRuntimeState)
    generation_session: GenerationSessionState | None = None
    pending_manual_revision_request: str | None = None
    pause: PauseRuntimeState = Field(default_factory=PauseRuntimeState)
    human_review: HumanReviewRuntimeState = Field(default_factory=HumanReviewRuntimeState)


class VersionRecord(BaseModel):
    version: int
    artifact_id: str
    source_version: int | None = None
    revision_goal: str | None = None
    generation_run_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class GenerationRun(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    kind: GenerationRunKind
    status: GenerationRunStatus = GenerationRunStatus.RUNNING
    source_version: int | None = None
    target_version: int | None = None
    instruction: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    output_preview: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class TimelineEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    thread_id: str
    event_type: str
    title: str
    detail: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ArtifactUpdateRequest(BaseModel):
    markdown: str


class ThreadSummary(BaseModel):
    thread_id: str
    user_id: str
    status: ThreadStatus
    title: str = "当前对话"
    subtitle: str = ""
    course_mode: CourseMode = CourseMode.SINGLE
    current_step_id: str = "step_1"
    latest_artifact_version: int | None = None
    review_pending: bool = False
    latest_score: float | None = None
    active_constraints: list[str] = Field(default_factory=list)
    pending_review_count: int = 0
    last_generation_target: str | None = None
    current_generation_run_id: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = Field(default_factory=utc_now)
    level: str = "INFO"
    service: str = "course-agent-backend"
    env: str = "development"
    request_id: str | None = None
    thread_id: str
    run_id: str | None = None
    node_name: str | None = None
    event_type: str
    user_id: str = "default-user"
    artifact_version: int | None = None
    model_provider: str | None = None
    model_name: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    status: str = "ok"
    error_code: str | None = None
    payload_summary: dict[str, Any] = Field(default_factory=dict)


class ThreadState(BaseModel):
    thread_id: str
    user_id: str = "default-user"
    status: ThreadStatus = ThreadStatus.COLLECTING
    course_mode: CourseMode = CourseMode.SINGLE
    current_step_id: str = "step_1"
    requirements_confirmed: bool = False
    messages: list[MessageRecord] = Field(default_factory=list)
    requirement_slots: dict[str, RequirementSlot] = Field(default_factory=dict)
    conversation_constraints: list[ConversationConstraint] = Field(default_factory=list)
    decision_ledger: list[DecisionItem] = Field(default_factory=list)
    decision_summary: str = ""
    workflow_steps: list[WorkflowStepState] = Field(default_factory=list)
    saved_artifacts: list[SavedArtifactRecord] = Field(default_factory=list)
    source_manifest: list[SourceDocument] = Field(default_factory=list)
    draft_artifact: DraftArtifact | None = None
    review_batches: list[ReviewBatch] = Field(default_factory=list)
    approved_feedback: list[HumanReviewAction] = Field(default_factory=list)
    version_chain: list[VersionRecord] = Field(default_factory=list)
    generation_runs: list[GenerationRun] = Field(default_factory=list)
    runtime: ThreadRuntimeState = Field(default_factory=ThreadRuntimeState)
    run_metadata: dict[str, Any] = Field(default_factory=dict, description="Deprecated compatibility bag. Avoid new business state here.")


class ThreadHistoryEntry(BaseModel):
    checkpoint_id: str | None = None
    next_nodes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)


class DecisionRecord(BaseModel):
    record_id: str = Field(default_factory=lambda: uuid4().hex)
    thread_id: str
    suggestion_id: str
    criterion_id: str | None = None
    user_message_context: str
    decision_summary: str
    draft_excerpt: str
    model_problem: str
    model_suggestion: str
    human_action: str
    edited_suggestion: str | None = None
    reviewer_id: str = "default-user"
    created_at: datetime = Field(default_factory=utc_now)


class DecisionTrainingRecord(DecisionRecord):
    """Deprecated alias retained for compatibility with older code paths."""


T = TypeVar("T")


class ApiEnvelope(BaseModel, Generic[T]):
    success: bool = True
    request_id: str
    thread_id: str | None = None
    data: T
    error: dict[str, Any] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SendMessageRequest(BaseModel):
    content: str
    user_id: str = "default-user"


class ModeUpdateRequest(BaseModel):
    mode: CourseMode
    user_id: str = "default-user"


class ConfirmStepRequest(BaseModel):
    step_id: str
    user_id: str = "default-user"
    note: str | None = None


class ReviewSubmitRequest(BaseModel):
    submitter_id: str = "default-user"
    review_actions: list[HumanReviewAction]


class RegenerateRequest(BaseModel):
    instruction: str
    base_version: int | None = None


class LLMProviderConfig(BaseModel):
    provider: str
    model: str
    temperature: float = 0.2
    api_base_env: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None


class DeepAgentsPlanRequest(BaseModel):
    thread_id: str | None = None
    prompt: str
    include_thread_context: bool = True


class DeepAgentsReviewRequest(BaseModel):
    thread_id: str
    artifact_version: int | None = None
    prompt: str | None = None


class DeepAgentsResearchRequest(BaseModel):
    thread_id: str | None = None
    prompt: str


class DeepAgentsPlanBundle(BaseModel):
    engine: str = "llm_fallback"
    summary: str
    steps: list[str] = Field(default_factory=list)
    case_strategy: list[str] = Field(default_factory=list)
    revision_focus: list[str] = Field(default_factory=list)


class DeepAgentsReviewBundle(BaseModel):
    engine: str = "llm_fallback"
    summary: str
    findings: list[str] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)


class DeepAgentsResearchBundle(BaseModel):
    engine: str = "llm_fallback"
    summary: str
    candidate_cases: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class CreateThreadResponse(BaseModel):
    thread: ThreadSummary


class ThreadListResponse(BaseModel):
    threads: list[ThreadSummary]


class ThreadStateResponse(BaseModel):
    state: ThreadState


class ThreadDetailResponse(BaseModel):
    thread: ThreadSummary
    state: ThreadState


class ThreadTimelineResponse(BaseModel):
    timeline: list[TimelineEvent]


class ThreadHistoryResponse(BaseModel):
    history: list[ThreadHistoryEntry]


class ThreadVersionsResponse(BaseModel):
    versions: list[ArtifactVersionDetail]


class ThreadFilesResponse(BaseModel):
    files: list[SourceDocument]


class ArtifactResponse(BaseModel):
    artifact: DraftArtifact | ArtifactVersionDetail | None


class ArtifactDiffResponse(BaseModel):
    diff: str
    version: int
    prev_version: int


class UploadFileResponse(BaseModel):
    uploaded: bool = True
    filename: str
    category: UploadCategory


class BooleanResultResponse(BaseModel):
    deleted: bool | None = None
    accepted: bool | None = None
    submitted: bool | None = None
    resumed: bool | None = None
    paused: bool | None = None
    retracted: bool | None = None
    replaced: bool | None = None


class ReviewBatchResponse(BaseModel):
    review_batch: ReviewBatch


class ReviewSubmitResponse(BaseModel):
    submitted: bool = True
    review_batch_id: str


class DecisionRecordsResponse(BaseModel):
    records: list[DecisionRecord]


class DecisionModelStatusResponse(BaseModel):
    status: dict[str, Any]


class AuditEventsResponse(BaseModel):
    events: list[AuditEvent]


class DeepAgentsPlanEnvelope(BaseModel):
    bundle: DeepAgentsPlanBundle


class DeepAgentsReviewEnvelope(BaseModel):
    bundle: DeepAgentsReviewBundle


class DeepAgentsResearchEnvelope(BaseModel):
    bundle: DeepAgentsResearchBundle
