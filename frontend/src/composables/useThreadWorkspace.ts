import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";

import {
  ApiError,
  createThread,
  deleteThread,
  fetchDiff,
  fetchThread,
  fetchThreadHistory,
  fetchThreads,
  fetchThreadVersions,
  pauseThread,
  replaceLastMessage,
  retractLastMessage,
  resumeThread,
  sendMessage,
  submitReview,
  updateThreadMode,
  uploadThreadFile,
} from "../lib/api";
import type {
  DraftArtifact,
  ReviewBatch,
  SavedArtifactRecord,
  ThreadHistoryEntry,
  ThreadState,
  ThreadSummary,
  VersionRecord,
  WorkflowStepState,
} from "../types";
import { useArtifactViewer } from "./useArtifactViewer";
import { useThreadStream } from "./useThreadStream";

export function useThreadWorkspace() {
  const threadId = ref("");
  const threadState = ref<ThreadState | null>(null);
  const threadHistory = ref<ThreadHistoryEntry[]>([]);
  const threadList = ref<ThreadSummary[]>([]);
  const content = ref("");
  const sending = ref(false);
  const processing = ref(false);
  const booting = ref(false);
  const bootError = ref("");
  const composerError = ref("");
  const reconnectNotice = ref("");
  const inputEl = ref<HTMLTextAreaElement | null>(null);
  const streamingMarkdown = ref("");
  const streamingAssistant = ref("");
  const streamingAssistantActive = ref(false);
  const reviewDraft = ref<Record<string, { action: "approve" | "edit" | "reject"; edited: string }>>({});
  const runtimeStatus = ref("");
  const sidebarCollapsed = ref(true);
  const refreshing = ref(false);
  const editingMessageId = ref<string | null>(null);
  const copiedMessageId = ref<string | null>(null);
  const openMenuThreadId = ref<string | null>(null);
  const frameworkDropActive = ref(false);
  let refreshQueued = false;

  const { connect, disconnect } = useThreadStream();
  const artifactViewer = useArtifactViewer(threadId);

  const workspaceModeOptions = [
    { id: "series", label: "系列课" },
    { id: "single", label: "单课" },
  ] as const;

  const messages = computed(() => threadState.value?.messages ?? []);
  const visibleMessages = computed(() => {
    if (!streamingAssistantActive.value) return messages.value;
    const cloned = [...messages.value];
    const last = cloned[cloned.length - 1];
    if (last?.role === "assistant") return cloned.slice(0, -1);
    return cloned;
  });
  const latestReview = computed<ReviewBatch | null>(() => {
    const batches = threadState.value?.review_batches ?? [];
    return batches.length ? batches[batches.length - 1] : null;
  });
  const hasDraft = computed(() => !!(threadState.value?.draft_artifact?.markdown || streamingMarkdown.value));
  const landingMode = computed(() => !threadId.value && !messages.value.length && !hasDraft.value && !booting.value);
  const versionList = computed<VersionRecord[]>(() => threadState.value?.version_chain ?? []);
  const activeConstraints = computed(() => (threadState.value?.conversation_constraints ?? []).filter((c) => c.active));
  const isPaused = computed(() => threadState.value?.status === "paused");
  const currentThreadTitle = computed(() => threadList.value.find((t) => t.thread_id === threadId.value)?.title || threadState.value?.draft_artifact?.summary || "当前对话");
  const starredThreads = computed(() => threadList.value.filter((t) => t.thread_id === threadId.value));
  const recentThreads = computed(() => threadList.value.filter((t) => t.thread_id !== threadId.value));
  const visibleWorkflowSteps = computed<WorkflowStepState[]>(() => {
    const steps = threadState.value?.workflow_steps ?? [];
    return threadState.value?.course_mode === "series" ? steps : steps.filter((s) => s.step_id !== "step_0");
  });
  const generatedArtifacts = computed<SavedArtifactRecord[]>(() => (threadState.value?.saved_artifacts ?? []).filter((a) => a.kind === "generated"));
  const packageFiles = computed<SavedArtifactRecord[]>(() => (threadState.value?.saved_artifacts ?? []).filter((a) => a.kind === "uploaded"));
  const canRetract = computed(() => {
    const last = messages.value[messages.value.length - 1];
    return !processing.value && !!last && last.role === "user" && threadState.value?.status === "collecting_requirements";
  });
  const editableUserMessageId = computed(() => {
    if (!["collecting_requirements", "paused"].includes(threadState.value?.status ?? "")) return null;
    const target = [...messages.value].reverse().find((m) => m.role === "user");
    return target?.message_id ?? null;
  });
  const currentCourseMode = computed(() => threadState.value?.course_mode ?? "single");
  const seriesGuidedRuntime = computed<Record<string, unknown> | null>(() => {
    const runtime = threadState.value?.runtime as { series_guided?: Record<string, unknown> } | undefined;
    return runtime?.series_guided ?? null;
  });
  const awaitingFrameworkUpload = computed(() => currentCourseMode.value === "series" && !!seriesGuidedRuntime.value?.awaiting_framework_input);
  const awaitingOptionalSeriesSkip = computed(
    () =>
      currentCourseMode.value === "series"
      && threadState.value?.status === "collecting_requirements"
      && seriesGuidedRuntime.value?.current_question_id === "supplementary_info",
  );
  const awaitingGenerationConfirmation = computed(
    () => currentCourseMode.value === "series" && !hasDraft.value && !!seriesGuidedRuntime.value?.awaiting_confirmation,
  );
  const canSendCurrentInput = computed(
    () => !!content.value.trim() || awaitingOptionalSeriesSkip.value,
  );
  const contentCreationSteps = computed(() => visibleWorkflowSteps.value.filter((s) => s.stage === "content_creation"));
  const statusLabel = computed(() => {
    if (runtimeStatus.value) return runtimeStatus.value;
    switch (threadState.value?.status) {
      case "collecting_requirements": return "正在收集需求";
      case "generating": return "正在生成课程稿";
      case "review_pending": return "已生成，等待处理评审建议";
      case "revising": return "正在按反馈修订";
      case "paused": return "已暂停";
      case "completed": return "已完成";
      case "failed": return "生成失败";
      default: return "";
    }
  });

  function isThreadNotFound(err: unknown) {
    return err instanceof ApiError && err.status === 404;
  }

  function autoResize() {
    const el = inputEl.value;
    if (!el) return;
    el.style.height = "28px";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  function scrollBottom() {
    nextTick(() => {
      const el = document.querySelector(".messages-scroll");
      if (el instanceof HTMLDivElement) el.scrollTop = el.scrollHeight;
    });
  }

  async function refreshThread() {
    if (refreshing.value) {
      refreshQueued = true;
      return;
    }
    refreshing.value = true;
    try {
      const { state } = await fetchThread(threadId.value);
      threadState.value = state;
      if (!awaitingFrameworkUpload.value) frameworkDropActive.value = false;
      const { history } = await fetchThreadHistory(threadId.value);
      threadHistory.value = history;
      const { threads } = await fetchThreads();
      threadList.value = threads;
      const { versions } = await fetchThreadVersions(threadId.value);
      if (versions.length) threadState.value = { ...state, version_chain: versions };
      const artifact = state.draft_artifact;
      if (artifact && artifact.version > 1) {
        const { diff } = await fetchDiff(threadId.value, artifact.version, artifact.version - 1);
        void diff;
      }
    } finally {
      refreshing.value = false;
      if (refreshQueued) {
        refreshQueued = false;
        await refreshThread();
      }
    }
  }

  function clearActiveThread() {
    disconnect();
    threadId.value = "";
    threadState.value = null;
    threadHistory.value = [];
    streamingMarkdown.value = "";
    streamingAssistant.value = "";
    streamingAssistantActive.value = false;
    composerError.value = "";
    frameworkDropActive.value = false;
    processing.value = false;
    runtimeStatus.value = "";
    reviewDraft.value = {};
    artifactViewer.closeFileViewer();
  }

  async function connectThread(newId: string) {
    threadId.value = newId;
    await refreshThread();
    connect(threadId.value, async (event, type) => {
      if (type === "assistant_token") {
        runtimeStatus.value = "正在引导你补充需求";
        const data = JSON.parse(event.data) as { content: string };
        streamingAssistantActive.value = true;
        streamingAssistant.value += data.content;
        scrollBottom();
      } else if (type === "assistant_message") {
        const data = JSON.parse(event.data) as { content?: string };
        const content = data.content ?? "";
        if (content === "已经生成好框架。") {
          processing.value = true;
          runtimeStatus.value = "已经生成好框架";
        } else if (content === "正在评分...") {
          processing.value = true;
          runtimeStatus.value = "正在评分";
        } else {
          processing.value = false;
          runtimeStatus.value = "";
        }
        streamingAssistant.value = "";
        streamingAssistantActive.value = false;
        await refreshThread();
        scrollBottom();
      } else if (type === "assistant_stream_end") {
        processing.value = false;
        streamingAssistant.value = "";
        streamingAssistantActive.value = false;
        runtimeStatus.value = "";
        await refreshThread();
        scrollBottom();
      } else if (type === "clarification_started") {
        runtimeStatus.value = "正在追问一个关键信息";
      } else if (type === "clarification_completed") {
        runtimeStatus.value = "已发出下一步引导问题";
      } else if (type === "generation_started") {
        processing.value = true;
        runtimeStatus.value = "正在生成课程主稿";
      } else if (type === "generation_chunk" || type === "token_stream") {
        runtimeStatus.value = "正在生成课程主稿";
        const data = JSON.parse(event.data) as { content: string };
        streamingMarkdown.value += data.content;
      } else if (type === "generation_completed") {
        runtimeStatus.value = "课程主稿已生成";
      } else if (type === "artifact_updated") {
        processing.value = false;
        streamingMarkdown.value = "";
        await refreshThread();
        scrollBottom();
      } else if (type === "review_ready" || type === "review_batch") {
        runtimeStatus.value = "已生成评审建议";
        await refreshThread();
      } else if (type === "revision_started") {
        processing.value = true;
        runtimeStatus.value = "正在根据反馈修订内容";
      } else if (type === "revision_completed") {
        processing.value = false;
        runtimeStatus.value = "已生成新的修订版本";
        await refreshThread();
        scrollBottom();
      } else if (type === "thread_paused") {
        processing.value = false;
        runtimeStatus.value = "已中断当前生成";
        await refreshThread();
      } else if (type === "thread_resumed") {
        runtimeStatus.value = "已继续生成";
        await refreshThread();
      } else if (type === "thread_failed") {
        processing.value = false;
        runtimeStatus.value = "生成失败，请重试";
        await refreshThread();
      } else if (type === "message_retracted" || type === "node_update") {
        await refreshThread();
        scrollBottom();
      }
    });
  }

  async function bootstrap() {
    booting.value = true;
    bootError.value = "";
    reconnectNotice.value = "";
    try {
      const { threads } = await fetchThreads();
      threadList.value = threads;
      if (threads.length) await connectThread(threads[0].thread_id);
      else clearActiveThread();
    } catch (err) {
      bootError.value = "连接失败，请刷新页面重试。";
      console.error(err);
    } finally {
      booting.value = false;
    }
  }

  async function recreateThreadAndReconnect() {
    reconnectNotice.value = "检测到后端已重启，已为你自动切换到新线程。";
    const { thread } = await createThread();
    await connectThread(thread.thread_id);
  }

  async function handleSend() {
    const rawText = content.value;
    const text = rawText.trim();
    if ((!text && !awaitingOptionalSeriesSkip.value) || sending.value || processing.value || isPaused.value) return;
    const payload = !text && awaitingOptionalSeriesSkip.value ? "" : text;
    sending.value = true;
    composerError.value = "";
    content.value = "";
    autoResize();
    try {
      if (!threadId.value) {
        const { thread } = await createThread();
        await connectThread(thread.thread_id);
      }
      if (editingMessageId.value) {
        await replaceLastMessage(threadId.value, payload);
        editingMessageId.value = null;
      } else {
        await sendMessage(threadId.value, payload);
      }
      processing.value = true;
      scrollBottom();
    } catch (err) {
      if (isThreadNotFound(err)) {
        await recreateThreadAndReconnect();
        await sendMessage(threadId.value, payload);
        processing.value = true;
        scrollBottom();
      } else {
        content.value = rawText;
        console.error(err);
      }
    } finally {
      sending.value = false;
    }
  }

  async function handlePauseResume() {
    if (!threadId.value) return;
    try {
      if (isPaused.value) {
        await resumeThread(threadId.value);
        runtimeStatus.value = "已恢复对话";
      } else {
        await pauseThread(threadId.value);
        runtimeStatus.value = "已暂停";
      }
      await refreshThread();
    } catch (err) {
      console.error(err);
    }
  }

  async function handleStartGeneration() {
    if (!threadId.value || sending.value || processing.value || isPaused.value) return;
    sending.value = true;
    composerError.value = "";
    try {
      await sendMessage(threadId.value, "开始生成");
      processing.value = true;
      scrollBottom();
    } catch (err) {
      if (isThreadNotFound(err)) {
        await recreateThreadAndReconnect();
        await sendMessage(threadId.value, "开始生成");
        processing.value = true;
        scrollBottom();
      } else {
        console.error(err);
      }
    } finally {
      sending.value = false;
    }
  }

  async function handleDeleteThread(tid: string) {
    if (!tid) return;
    try {
      await deleteThread(tid);
      if (tid === threadId.value) {
        const { threads } = await fetchThreads();
        threadList.value = threads.filter((t) => t.thread_id !== tid);
        if (threadList.value.length) await connectThread(threadList.value[0].thread_id);
        else {
          threadList.value = [];
          clearActiveThread();
        }
      } else {
        threadList.value = threadList.value.filter((t) => t.thread_id !== tid);
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function handleReviewSubmit() {
    if (!latestReview.value) return;
    processing.value = true;
    runtimeStatus.value = "正在根据审核结果修订内容";
    await submitReview(
      threadId.value,
      latestReview.value.review_batch_id ?? "",
      latestReview.value.suggestions.map((s) => {
        const suggestionId = s.suggestion_id ?? "";
        const d = reviewDraft.value[suggestionId] ?? { action: "approve", edited: "" };
        return {
          suggestion_id: suggestionId,
          action: d.action,
          edited_suggestion: d.edited || undefined,
          reviewer_id: "default-user",
          comment: "",
        };
      }),
    );
  }

  async function safeCopy(text: string) {
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(text); return; } catch { /* fall through */ }
    }
    const el = Object.assign(document.createElement("textarea"), { value: text });
    el.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(el);
    el.focus(); el.select();
    document.execCommand("copy");
    document.body.removeChild(el);
  }

  async function copyMessage(msgId: string, msgContent: string) {
    await safeCopy(msgContent);
    copiedMessageId.value = msgId;
    window.setTimeout(() => {
      if (copiedMessageId.value === msgId) copiedMessageId.value = null;
    }, 1200);
  }

  function editMessage(msgId: string, msgContent: string) {
    if (msgId !== editableUserMessageId.value) return;
    editingMessageId.value = msgId;
    content.value = msgContent;
    nextTick(() => {
      inputEl.value?.focus();
      autoResize();
    });
  }

  function setAction(id: string, action: "approve" | "edit" | "reject") {
    reviewDraft.value[id] = { ...(reviewDraft.value[id] ?? { action, edited: "" }), action };
  }

  function updateEditedSuggestion(id: string, value: string) {
    reviewDraft.value[id] = { ...(reviewDraft.value[id] ?? { action: "edit", edited: "" }), edited: value };
  }

  async function saveEditedArtifact() {
    try {
      await artifactViewer.saveEditedArtifact();
      await refreshThread();
    } catch (err) {
      if (isThreadNotFound(err)) await recreateThreadAndReconnect();
      else console.error(err);
    }
  }

  async function retractMessageAction() {
    if (!threadId.value || !canRetract.value) return;
    try {
      await retractLastMessage(threadId.value);
      await refreshThread();
    } catch (err) {
      if (isThreadNotFound(err)) await recreateThreadAndReconnect();
      else console.error(err);
    }
  }

  function newConversation() {
    clearActiveThread();
    content.value = "";
    editingMessageId.value = null;
    composerError.value = "";
    nextTick(() => inputEl.value?.focus());
  }

  function fillChip(text: string) {
    content.value = text;
    nextTick(() => {
      inputEl.value?.focus();
      autoResize();
    });
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  }

  async function clickStep(step: WorkflowStepState) {
    if (step.status !== "completed") return;
    const artifact = generatedArtifacts.value.find((a) => a.step_id === step.step_id);
    if (artifact) await artifactViewer.openFileViewer(artifact);
  }

  async function selectThread(tid: string) {
    if (!tid || tid === threadId.value) return;
    reconnectNotice.value = "";
    runtimeStatus.value = "";
    composerError.value = "";
    await connectThread(tid);
  }

  async function selectWorkspaceMode(mode: "series" | "single") {
    if (!threadId.value) {
      const { thread } = await createThread();
      await connectThread(thread.thread_id);
    }
    await updateThreadMode(threadId.value, mode);
    await refreshThread();
  }

  async function handleUpload(category: "context" | "package" | "framework", fileList: FileList | null) {
    if (!fileList?.length) return;
    composerError.value = "";
    if (!threadId.value) {
      const { thread } = await createThread();
      await connectThread(thread.thread_id);
    }
    if (category === "framework") {
      frameworkDropActive.value = false;
      processing.value = true;
      runtimeStatus.value = "正在导入现成框架";
    }
    try {
      for (const file of Array.from(fileList)) {
        await uploadThreadFile(threadId.value, file, category);
      }
      await refreshThread();
    } catch (err) {
      processing.value = false;
      runtimeStatus.value = "";
      if (isThreadNotFound(err)) {
        await recreateThreadAndReconnect();
      } else if (err instanceof ApiError) {
        const detail = err.detail as { detail?: { message?: string } } | null;
        composerError.value = detail?.detail?.message ?? "上传失败，请重试。";
      } else {
        composerError.value = "上传失败，请重试。";
        console.error(err);
      }
    }
  }

  function handleFrameworkDragOver(event: DragEvent) {
    if (!awaitingFrameworkUpload.value) return;
    event.preventDefault();
    frameworkDropActive.value = true;
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  }

  function handleFrameworkDragLeave(event: DragEvent) {
    if (!awaitingFrameworkUpload.value) return;
    const current = event.currentTarget;
    const next = event.relatedTarget;
    if (current instanceof HTMLElement && next instanceof Node && current.contains(next)) return;
    frameworkDropActive.value = false;
  }

  function handleFrameworkDrop(event: DragEvent) {
    if (!awaitingFrameworkUpload.value) return;
    event.preventDefault();
    frameworkDropActive.value = false;
    void handleUpload("framework", event.dataTransfer?.files ?? null);
  }

  function toggleThreadMenu(id: string, event: MouseEvent) {
    event.stopPropagation();
    openMenuThreadId.value = openMenuThreadId.value === id ? null : id;
  }

  function handleOutsideClick() {
    openMenuThreadId.value = null;
  }

  watch(
    () => threadState.value?.draft_artifact?.markdown,
    (md) => {
      if (artifactViewer.rightTab.value !== "edit") artifactViewer.editableMarkdown.value = md ?? "";
    },
  );

  onMounted(() => {
    void bootstrap();
    document.addEventListener("click", handleOutsideClick);
  });

  onUnmounted(() => {
    disconnect();
    document.removeEventListener("click", handleOutsideClick);
  });

  return {
    threadId,
    threadState,
    threadHistory,
    threadList,
    content,
    sending,
    processing,
    booting,
    bootError,
    composerError,
    reconnectNotice,
    inputEl,
    streamingAssistant,
    streamingAssistantActive,
    reviewDraft,
    runtimeStatus,
    sidebarCollapsed,
    editingMessageId,
    copiedMessageId,
    openMenuThreadId,
    frameworkDropActive,
    workspaceModeOptions,
    messages,
    visibleMessages,
    latestReview,
    hasDraft,
    landingMode,
    versionList,
    activeConstraints,
    isPaused,
    currentThreadTitle,
    starredThreads,
    recentThreads,
    visibleWorkflowSteps,
    generatedArtifacts,
    packageFiles,
    canRetract,
    editableUserMessageId,
    currentCourseMode,
    awaitingFrameworkUpload,
    awaitingOptionalSeriesSkip,
    awaitingGenerationConfirmation,
    canSendCurrentInput,
    contentCreationSteps,
    statusLabel,
    autoResize,
    scrollBottom,
    selectThread,
    selectWorkspaceMode,
    handleUpload,
    handleFrameworkDragOver,
    handleFrameworkDragLeave,
    handleFrameworkDrop,
    handleStartGeneration,
    handleSend,
    handlePauseResume,
    handleDeleteThread,
    handleReviewSubmit,
    copyMessage,
    editMessage,
    setAction,
    updateEditedSuggestion,
    saveEditedArtifact,
    retractMessage: retractMessageAction,
    newConversation,
    fillChip,
    handleKeydown,
    clickStep,
    toggleThreadMenu,
    refreshThread,
    artifactViewer,
  };
}
