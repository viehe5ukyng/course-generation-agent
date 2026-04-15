import type { components } from "./generated/api";

export type MessageRole = components["schemas"]["MessageRole"];
export type MessageRecord = components["schemas"]["MessageRecord"];
export type DraftArtifact = components["schemas"]["DraftArtifact"];
export type WorkflowStepState = components["schemas"]["WorkflowStepState"];
export type SavedArtifactRecord = components["schemas"]["SavedArtifactRecord"];
export type VersionRecord = components["schemas"]["VersionRecord"];
export type TimelineEvent = components["schemas"]["TimelineEvent"];
export type ThreadHistoryEntry = components["schemas"]["ThreadHistoryEntry"];
export type ReviewCriterionResult = components["schemas"]["ReviewCriterionResult"];
export type ReviewSuggestion = components["schemas"]["ReviewSuggestion"];
export type ReviewBatch = components["schemas"]["ReviewBatch"];
export type ThreadState = components["schemas"]["ThreadState"];
export type ThreadSummary = components["schemas"]["ThreadSummary"];
export type ConversationConstraint = components["schemas"]["ConversationConstraint"];
export type SourceDocument = components["schemas"]["SourceDocument"];
export type ArtifactVersionDetail = components["schemas"]["ArtifactVersionDetail"];
export type HumanReviewAction = components["schemas"]["HumanReviewAction"];

export type ThreadStatus = ThreadState["status"];
export type CourseMode = ThreadState["course_mode"];
