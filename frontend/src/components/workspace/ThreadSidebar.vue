<script setup lang="ts">
import { computed } from "vue";

import type { ThreadSummary, CourseMode } from "../../types";

const props = defineProps<{
  sidebarCollapsed: boolean;
  threadList: ThreadSummary[];
  currentThreadId: string;
  currentCourseMode: CourseMode;
  workspaceModeOptions: ReadonlyArray<{ id: "series" | "single"; label: string }>;
  openMenuThreadId: string | null;
}>();

const emit = defineEmits<{
  (e: "toggle-sidebar"): void;
  (e: "new-conversation"): void;
  (e: "select-mode", mode: "series" | "single"): void;
  (e: "select-thread", threadId: string): void;
  (e: "toggle-thread-menu", threadId: string, event: MouseEvent): void;
  (e: "delete-thread", threadId: string): void;
}>();

const starredThreads = computed(() => props.threadList.filter((t) => t.thread_id === props.currentThreadId));
const recentThreads = computed(() => props.threadList.filter((t) => t.thread_id !== props.currentThreadId));
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
    <div class="sidebar-top">
      <div class="sidebar-brand">
        <img src="/icon.png" alt="制课 Agent" class="sidebar-logo" />
        <span v-if="!sidebarCollapsed" class="sidebar-brand-name">制课 Agent</span>
      </div>
      <button class="sidebar-toggle-btn" aria-label="折叠侧栏" @click="emit('toggle-sidebar')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <rect x="5" y="5" width="14" height="14" rx="2.5"/>
          <path d="M9 5v14"/>
        </svg>
      </button>
    </div>

    <div class="sidebar-nav">
      <button class="nav-item new-chat-btn" @click="emit('new-conversation')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
        <span v-if="!sidebarCollapsed">新对话</span>
      </button>
      <button class="nav-item" type="button">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <span v-if="!sidebarCollapsed">搜索</span>
      </button>
    </div>

    <div v-if="!sidebarCollapsed" class="mode-section">
      <div class="mode-label">制课模式</div>
      <div class="mode-segment">
        <button
          v-for="opt in workspaceModeOptions"
          :key="opt.id"
          class="mode-btn"
          :class="{ active: currentCourseMode === opt.id }"
          @click="emit('select-mode', opt.id)"
        >{{ opt.label }}</button>
      </div>
    </div>

    <div class="nav-divider" />

    <div class="sidebar-list" :class="{ hidden: sidebarCollapsed }">
      <div v-if="!threadList.length" class="sidebar-empty">暂无历史对话</div>

      <template v-if="starredThreads.length">
        <div class="list-section-label">固定</div>
        <div
          v-for="thread in starredThreads"
          :key="thread.thread_id"
          class="thread-entry active"
          @click="emit('select-thread', thread.thread_id)"
        >
          <div class="thread-main">
            <span class="thread-title">{{ thread.title || "当前对话" }}</span>
            <span class="thread-meta">{{ thread.subtitle }}</span>
          </div>
          <div class="thread-menu-wrap" @click.stop>
            <button class="thread-menu-btn" :class="{ open: openMenuThreadId === thread.thread_id }" aria-label="更多操作" @click="emit('toggle-thread-menu', thread.thread_id, $event)">
              <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><circle cx="3" cy="8" r="1.2"/><circle cx="8" cy="8" r="1.2"/><circle cx="13" cy="8" r="1.2"/></svg>
            </button>
            <div v-if="openMenuThreadId === thread.thread_id" class="thread-dropdown" @click.stop>
              <button class="dropdown-item dropdown-danger" @click="emit('delete-thread', thread.thread_id)">
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M4 4h8"/><path d="M6 4V3h4v1"/><path d="M5 4l.5 8h5L11 4"/></svg>
                删除
              </button>
            </div>
          </div>
        </div>
      </template>

      <template v-if="recentThreads.length">
        <div class="list-section-label">最近</div>
        <div
          v-for="thread in recentThreads"
          :key="thread.thread_id"
          class="thread-entry"
          @click="emit('select-thread', thread.thread_id)"
        >
          <div class="thread-main">
            <span class="thread-title">{{ thread.title || "未命名对话" }}</span>
            <span class="thread-meta">{{ thread.subtitle }}</span>
          </div>
          <div class="thread-menu-wrap" @click.stop>
            <button class="thread-menu-btn" :class="{ open: openMenuThreadId === thread.thread_id }" aria-label="更多操作" @click="emit('toggle-thread-menu', thread.thread_id, $event)">
              <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><circle cx="3" cy="8" r="1.2"/><circle cx="8" cy="8" r="1.2"/><circle cx="13" cy="8" r="1.2"/></svg>
            </button>
            <div v-if="openMenuThreadId === thread.thread_id" class="thread-dropdown" @click.stop>
              <button class="dropdown-item dropdown-danger" @click="emit('delete-thread', thread.thread_id)">
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M4 4h8"/><path d="M6 4V3h4v1"/><path d="M5 4l.5 8h5L11 4"/></svg>
                删除
              </button>
            </div>
          </div>
        </div>
      </template>
    </div>
  </aside>
</template>
