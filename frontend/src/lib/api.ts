import type { components } from "../generated/api";
import { API_BASE, client } from "./openapi-client";

type EnvelopeLike<T> = { data: T };
type ThreadStateResponse = components["schemas"]["ThreadStateResponse"];
type ThreadListResponse = components["schemas"]["ThreadListResponse"];
type ThreadDetailResponse = components["schemas"]["ThreadDetailResponse"];
type ThreadHistoryResponse = components["schemas"]["ThreadHistoryResponse"];
type ThreadTimelineResponse = components["schemas"]["ThreadTimelineResponse"];
type ThreadVersionsResponse = components["schemas"]["ThreadVersionsResponse"];
type ArtifactResponse = components["schemas"]["ArtifactResponse"];
type ArtifactDiffResponse = components["schemas"]["ArtifactDiffResponse"];
type ReviewSubmitRequest = components["schemas"]["ReviewSubmitRequest"];
type BooleanResultResponse = components["schemas"]["BooleanResultResponse"];
type UploadFileResponse = components["schemas"]["UploadFileResponse"];

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(`Request failed: ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(operation: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await operation;
  if (error || !data) {
    throw new ApiError(response.status, error ?? null);
  }
  return data;
}

function unwrap<T>(payload: EnvelopeLike<T>): T {
  return payload.data;
}

export async function createThread() {
  return unwrap(
    await request(
      client.POST("/api/v1/threads"),
    ),
  );
}

export async function fetchThreads() {
  return unwrap(
    await request(
      client.GET("/api/v1/threads"),
    ),
  ) as ThreadListResponse;
}

export async function updateThreadMode(threadId: string, mode: "single" | "series") {
  return unwrap(
    await request(
      client.PATCH("/api/v1/threads/{thread_id}/mode", {
        params: { path: { thread_id: threadId } },
        body: { mode, user_id: "default-user" },
      }),
    ),
  ) as ThreadStateResponse;
}

export async function confirmThreadStep(threadId: string, stepId: string, note?: string) {
  return unwrap(
    await request(
      client.POST("/api/v1/threads/{thread_id}/confirm-step", {
        params: { path: { thread_id: threadId } },
        body: { step_id: stepId, note, user_id: "default-user" },
      }),
    ),
  ) as ThreadStateResponse;
}

export async function deleteThread(threadId: string) {
  return unwrap(
    await request(
      client.DELETE("/api/v1/threads/{thread_id}", {
        params: { path: { thread_id: threadId } },
      }),
    ),
  ) as BooleanResultResponse;
}

export async function fetchThread(threadId: string) {
  return unwrap(
    await request(
      client.GET("/api/v1/threads/{thread_id}", {
        params: { path: { thread_id: threadId } },
      }),
    ),
  ) as ThreadDetailResponse;
}

export async function fetchThreadHistory(threadId: string) {
  return unwrap(
    await request(
      client.GET("/api/v1/threads/{thread_id}/history", {
        params: { path: { thread_id: threadId } },
      }),
    ),
  ) as ThreadHistoryResponse;
}

export async function fetchThreadTimeline(threadId: string) {
  return unwrap(
    await request(
      client.GET("/api/v1/threads/{thread_id}/timeline", {
        params: { path: { thread_id: threadId } },
      }),
    ),
  ) as ThreadTimelineResponse;
}

export async function fetchThreadVersions(threadId: string) {
  return unwrap(
    await request(
      client.GET("/api/v1/threads/{thread_id}/versions", {
        params: { path: { thread_id: threadId } },
      }),
    ),
  ) as ThreadVersionsResponse;
}

export async function sendMessage(threadId: string, content: string) {
  return unwrap(
    await request(
      client.POST("/api/v1/threads/{thread_id}/messages", {
        params: { path: { thread_id: threadId } },
        body: { content, user_id: "default-user" },
      }),
    ),
  ) as BooleanResultResponse;
}

export async function pauseThread(threadId: string) {
  return unwrap(
    await request(
      client.POST("/api/v1/threads/{thread_id}/pause", {
        params: { path: { thread_id: threadId } },
      }),
    ),
  ) as BooleanResultResponse;
}

export async function resumeThread(threadId: string) {
  return unwrap(
    await request(
      client.POST("/api/v1/threads/{thread_id}/resume", {
        params: { path: { thread_id: threadId } },
      }),
    ),
  ) as BooleanResultResponse;
}

export async function fetchLatestArtifact(threadId: string) {
  return unwrap(
    await request(
      client.GET("/api/v1/threads/{thread_id}/artifacts/latest", {
        params: { path: { thread_id: threadId } },
      }),
    ),
  ) as ArtifactResponse;
}

export async function fetchArtifactVersion(threadId: string, version: number) {
  return unwrap(
    await request(
      client.GET("/api/v1/threads/{thread_id}/artifacts/{version}", {
        params: { path: { thread_id: threadId, version } },
      }),
    ),
  ) as ArtifactResponse;
}

export async function updateLatestArtifact(threadId: string, markdown: string) {
  return unwrap(
    await request(
      client.PATCH("/api/v1/threads/{thread_id}/artifacts/latest", {
        params: { path: { thread_id: threadId } },
        body: { markdown },
      }),
    ),
  ) as ArtifactResponse;
}

export async function fetchDiff(threadId: string, version: number, prevVersion: number) {
  return unwrap(
    await request(
      client.GET("/api/v1/threads/{thread_id}/artifacts/{version}/diff/{prev_version}", {
        params: { path: { thread_id: threadId, version, prev_version: prevVersion } },
      }),
    ),
  ) as ArtifactDiffResponse;
}

export async function regenerateArtifact(threadId: string, instruction: string, baseVersion?: number) {
  return unwrap(
    await request(
      client.POST("/api/v1/threads/{thread_id}/regenerate", {
        params: { path: { thread_id: threadId } },
        body: { instruction, base_version: baseVersion ?? null },
      }),
    ),
  ) as ArtifactResponse;
}

export async function submitReview(threadId: string, batchId: string, reviewActions: ReviewSubmitRequest["review_actions"]) {
  return unwrap(
    await request(
      client.POST("/api/v1/threads/{thread_id}/review-batches/{batch_id}/submit", {
        params: { path: { thread_id: threadId, batch_id: batchId } },
        body: {
          submitter_id: "default-user",
          review_actions: reviewActions,
        },
      }),
    ),
  );
}

export async function retractLastMessage(threadId: string) {
  return unwrap(
    await request(
      client.DELETE("/api/v1/threads/{thread_id}/messages/last", {
        params: { path: { thread_id: threadId } },
      }),
    ),
  ) as BooleanResultResponse;
}

export async function replaceLastMessage(threadId: string, content: string) {
  return unwrap(
    await request(
      client.PUT("/api/v1/threads/{thread_id}/messages/last", {
        params: { path: { thread_id: threadId } },
        body: { content, user_id: "default-user" },
      }),
    ),
  ) as BooleanResultResponse;
}

export async function uploadThreadFile(threadId: string, file: File, category: "context" | "package") {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/v1/threads/${threadId}/files?category=${category}`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = null;
    }
    throw new ApiError(response.status, detail);
  }
  const json = await response.json() as EnvelopeLike<UploadFileResponse>;
  return json.data;
}

export function streamThread(threadId: string, onEvent: (event: MessageEvent, type: string) => void) {
  const source = new EventSource(`${API_BASE}/api/v1/threads/${threadId}/stream`);
  [
    "assistant_message", "assistant_token", "assistant_stream_end", "token_stream", "node_update",
    "review_batch", "artifact_updated", "audit_event",
    "file_uploaded", "message_retracted",
    "clarification_started", "clarification_completed",
    "generation_started", "generation_chunk", "generation_completed",
    "review_ready", "revision_started", "revision_completed", "thread_failed",
    "thread_paused", "thread_resumed",
  ].forEach((type) => {
    source.addEventListener(type, (event) => onEvent(event as MessageEvent, type));
  });
  return source;
}
