<script setup lang="ts">
import { reactive } from "vue";
import type { ComponentPublicInstance } from "vue";

import WorkspaceShell from "./components/workspace/WorkspaceShell.vue";
import ThreadSidebar from "./components/workspace/ThreadSidebar.vue";
import MessageList from "./components/workspace/MessageList.vue";
import ArtifactPanel from "./components/workspace/ArtifactPanel.vue";
import ReviewPanel from "./components/workspace/ReviewPanel.vue";
import { useThreadWorkspace } from "./composables/useThreadWorkspace";

const starterChips = [
  "制作面向中学生的数学思维训练课",
  "帮我设计一门 AI 海报制作入门课",
  "做一门给运营同学的提示词入门课",
];

const rawWorkspace = useThreadWorkspace();
const workspace = reactive(rawWorkspace);
const inputEl = rawWorkspace.inputEl;

function bindInputEl(el: Element | ComponentPublicInstance | null) {
  inputEl.value = (el as HTMLTextAreaElement | null) ?? null;
}
</script>

<template>
  <WorkspaceShell :show-right="!workspace.landingMode">
    <template #sidebar>
      <ThreadSidebar
        :sidebar-collapsed="workspace.sidebarCollapsed"
        :thread-list="workspace.threadList"
        :current-thread-id="workspace.threadId"
        :current-course-mode="workspace.currentCourseMode"
        :workspace-mode-options="workspace.workspaceModeOptions"
        :open-menu-thread-id="workspace.openMenuThreadId"
        @toggle-sidebar="workspace.sidebarCollapsed = !workspace.sidebarCollapsed"
        @new-conversation="workspace.newConversation"
        @select-mode="workspace.selectWorkspaceMode"
        @select-thread="workspace.selectThread"
        @toggle-thread-menu="workspace.toggleThreadMenu"
        @delete-thread="workspace.handleDeleteThread"
      />
    </template>

    <template v-if="workspace.landingMode">
      <div class="landing-wrap">
        <div class="landing-center">
          <div class="brand-cluster">
            <div class="landing-heading-row">
              <img src="/icon.png" class="landing-icon" alt="" aria-hidden="true" />
              <h1 class="landing-greeting">你好，今天想做什么课？</h1>
            </div>
            <p class="landing-sub">告诉我课程主题，我帮你把选题、框架、案例和逐字稿全部搞定。</p>
          </div>

          <div class="composer-card landing-composer-card" :class="{ focused: workspace.content.length > 0 }">
            <textarea
              :ref="bindInputEl"
              v-model="workspace.content"
              class="composer-textarea"
              rows="1"
              placeholder="描述你想做的课程，或直接发送需求…"
              @keydown="workspace.handleKeydown"
              @input="workspace.autoResize"
            />
            <input id="landing-context-upload" class="hidden-input" type="file" multiple @change="workspace.handleUpload('context', ($event.target as HTMLInputElement).files)" />
            <div class="composer-bar">
              <label class="attach-btn" for="landing-context-upload" aria-label="添加文件">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
              </label>
              <div class="composer-right">
                <button
                  class="send-btn"
                  :disabled="!workspace.content.trim() || workspace.sending || workspace.booting"
                  aria-label="发送"
                  @click="workspace.handleSend"
                >
                  <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M.5 1.163A1 1 0 011.97.28l12.868 6.837a1 1 0 010 1.766L1.969 15.72A1 1 0 01.5 14.836V10.33a1 1 0 01.816-.983L8.5 8 1.316 6.653A1 1 0 01.5 5.67V1.163z"/></svg>
                </button>
              </div>
            </div>
          </div>

          <div class="starter-grid">
            <button v-for="chip in starterChips" :key="chip" class="starter-card" @click="workspace.fillChip(chip)">
              <span>{{ chip }}</span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M7 17L17 7M17 7H7M17 7v10"/></svg>
            </button>
          </div>

          <p v-if="workspace.bootError" class="boot-error">{{ workspace.bootError }}</p>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="main-topbar">
        <div class="main-topbar-path">
          <span class="main-topbar-root">制课写作</span>
          <span class="main-topbar-sep">/</span>
          <span class="main-topbar-current">{{ workspace.currentThreadTitle }}</span>
        </div>
        <div v-if="workspace.statusLabel" class="topbar-status">
          <span class="status-dot" :class="{ active: workspace.processing }" />
          {{ workspace.statusLabel }}
        </div>
      </div>

      <MessageList
        :active-constraints="workspace.activeConstraints"
        :visible-messages="workspace.visibleMessages"
        :editable-user-message-id="workspace.editableUserMessageId"
        :copied-message-id="workspace.copiedMessageId"
        :streaming-assistant-active="workspace.streamingAssistantActive"
        :streaming-assistant="workspace.streamingAssistant"
        :processing="workspace.processing"
        :reconnect-notice="workspace.reconnectNotice"
        :boot-error="workspace.bootError"
        :viewing-file="workspace.artifactViewer.viewingFile"
        :viewing-file-content="workspace.artifactViewer.viewingFileContent"
        :right-tab="workspace.artifactViewer.rightTab"
        :editable-markdown="workspace.artifactViewer.editableMarkdown"
        :copied-viewed-file="workspace.artifactViewer.copiedViewedFile"
        @copy-message="workspace.copyMessage"
        @edit-message="workspace.editMessage"
        @update:right-tab="workspace.artifactViewer.rightTab = $event"
        @update:editable-markdown="workspace.artifactViewer.editableMarkdown = $event"
        @save-artifact="workspace.saveEditedArtifact"
        @close-file-viewer="workspace.artifactViewer.closeFileViewer"
        @copy-viewed-file="workspace.artifactViewer.copyViewedFile"
      />

      <div class="composer-wrap">
        <div class="chat-composer">
          <textarea
            :ref="bindInputEl"
            v-model="workspace.content"
            class="composer-textarea"
            rows="1"
            :disabled="workspace.booting || (workspace.processing && !workspace.isPaused)"
            placeholder="继续补充需求，或说你想修改什么…"
            @keydown="workspace.handleKeydown"
            @input="workspace.autoResize"
          />
          <input id="chat-context-upload" class="hidden-input" type="file" multiple @change="workspace.handleUpload('context', ($event.target as HTMLInputElement).files)" />
          <div class="composer-bar">
            <label class="attach-btn" for="chat-context-upload" aria-label="添加文件">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
            </label>
            <div class="composer-actions">
              <button v-if="workspace.canRetract" class="ghost-btn" @click="workspace.retractMessage">撤回</button>
              <button
                class="send-btn"
                :class="{ paused: workspace.processing || workspace.isPaused }"
                :disabled="(!workspace.content.trim() && !workspace.processing && !workspace.isPaused) || workspace.sending || workspace.booting"
                :aria-label="workspace.processing || workspace.isPaused ? (workspace.isPaused ? '继续' : '暂停') : '发送'"
                @click="workspace.processing || workspace.isPaused ? workspace.handlePauseResume() : workspace.handleSend()"
              >
                <svg v-if="!(workspace.processing || workspace.isPaused)" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M.5 1.163A1 1 0 011.97.28l12.868 6.837a1 1 0 010 1.766L1.969 15.72A1 1 0 01.5 14.836V10.33a1 1 0 01.816-.983L8.5 8 1.316 6.653A1 1 0 01.5 5.67V1.163z"/></svg>
                <svg v-else-if="workspace.processing && !workspace.isPaused" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><rect x="3" y="3" width="4" height="10" rx="1"/><rect x="9" y="3" width="4" height="10" rx="1"/></svg>
                <svg v-else viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M4 3.5v9l8-4.5-8-4.5z"/></svg>
              </button>
            </div>
          </div>
        </div>
        <p class="disclaimer">制课 Agent 可能会犯错，请核实重要内容。</p>
      </div>
    </template>

    <template #right>
      <template v-if="!workspace.landingMode">
        <ArtifactPanel
          :visible-workflow-steps="workspace.visibleWorkflowSteps"
          :content-creation-steps="workspace.contentCreationSteps"
          :generated-artifacts="workspace.generatedArtifacts"
          :package-files="workspace.packageFiles"
          @click-step="workspace.clickStep"
          @open-artifact="workspace.artifactViewer.openFileViewer"
          @upload="workspace.handleUpload"
        />
        <div class="rp-divider" />
        <ReviewPanel
          :latest-review="workspace.latestReview"
          :review-draft="workspace.reviewDraft"
          @set-action="workspace.setAction"
          @update-edited="workspace.updateEditedSuggestion"
          @submit="workspace.handleReviewSubmit"
        />
      </template>
    </template>
  </WorkspaceShell>
</template>


<style>
/* ─── DESIGN TOKENS ─── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, #app {
  height: 100%;

  --parchment:    #f5f4ed;
  --ivory:        #faf9f5;
  --white:        #ffffff;
  --warm-sand:    #e8e6dc;
  --dark-surface: #30302e;
  --near-black:   #141413;

  --text-1:  #141413;
  --text-2:  #5e5d59;
  --text-3:  #87867f;
  --text-4:  #b0aea5;
  --text-btn: #4d4c48;

  --terracotta: #c96442;
  --coral:      #d97757;
  --focus-blue: #3898ec;
  --success:    #2e9c5a;

  --border-cream: #f0eee6;
  --border-warm:  #e8e6dc;
  --border-dark:  #30302e;

  --ring-1: #d1cfc5;
  --ring-2: #c8c5bb;
  --ring-3: #c2c0b6;

  --danger:            #b53333;
  --danger-bg:         #fef5f5;
  --danger-border:     #fad7d7;
  --warning-border:    #fde9bb;
  --warning-bg:        #fffcf5;

  --terracotta-hover:  #b85a3a;
  --terracotta-bg:     #fef5f0;
  --terracotta-border: #fad5c5;

  --font-serif: Georgia, 'Times New Roman', serif;
  --font-sans:  "Inter", "PingFang SC", "Noto Sans SC", system-ui, sans-serif;
  --font-mono:  'SF Mono', 'Fira Code', 'Cascadia Code', 'Menlo', monospace;

  --r-sm:  6px;
  --r-md:  8px;
  --r-lg:  12px;
  --r-xl:  16px;
  --r-2xl: 24px;

  font-family: var(--font-sans);
  font-size: 15px;
  line-height: 1.6;
  color: var(--text-1);
  background: var(--parchment);
  -webkit-font-smoothing: antialiased;
}

::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-warm); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--ring-1); }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
</style>

<style>
/* ═══════════════════════════════════════
   APP SHELL
═══════════════════════════════════════ */
.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--parchment);
}

.hidden-input { display: none; }

/* ═══════════════════════════════════════
   LEFT SIDEBAR
═══════════════════════════════════════ */
.sidebar {
  width: 240px;
  flex-shrink: 0;
  background: var(--ivory);
  border-right: 1px solid var(--border-cream);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  transition: width .2s cubic-bezier(.16,1,.3,1);
  z-index: 20;
}
.sidebar.collapsed { width: 52px; }

.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px 8px;
  flex-shrink: 0;
  transition: padding .2s;
}
.sidebar.collapsed .sidebar-top { justify-content: center; padding: 12px 0 8px; }

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 9px;
  overflow: hidden;
  min-width: 0;
}
.sidebar.collapsed .sidebar-brand { display: none; }

.sidebar-logo { width: 22px; height: 22px; display: block; flex-shrink: 0; }
.sidebar-brand-name {
  font-family: var(--font-serif);
  font-size: 14.5px;
  font-weight: 500;
  color: var(--text-1);
  white-space: nowrap;
}

.sidebar-toggle-btn {
  width: 28px; height: 28px;
  border: none; border-radius: var(--r-md);
  background: transparent; color: var(--text-3);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; flex-shrink: 0;
  transition: background .12s, color .12s;
}
.sidebar-toggle-btn svg { width: 16px; height: 16px; }
.sidebar-toggle-btn:hover { background: var(--parchment); color: var(--text-1); }

/* Nav */
.sidebar-nav {
  padding: 2px 10px 6px;
  display: flex; flex-direction: column; gap: 1px;
  flex-shrink: 0;
  transition: padding .2s;
}
.sidebar.collapsed .sidebar-nav { padding: 2px 6px 6px; align-items: center; }

.nav-item {
  display: flex; align-items: center; justify-content: flex-start;
  gap: 9px; padding: 7px 10px;
  border: none; border-radius: var(--r-md);
  background: transparent; color: var(--text-2);
  cursor: pointer; min-height: 34px;
  font-size: 13.5px; font-family: var(--font-sans);
  white-space: nowrap; overflow: hidden;
  transition: background .12s, color .12s; width: 100%;
}
.sidebar.collapsed .nav-item {
  width: 34px; height: 34px; min-height: 34px; padding: 0;
  justify-content: center; gap: 0; border-radius: var(--r-md);
}
.nav-item svg { width: 15px; height: 15px; flex-shrink: 0; }
.nav-item:hover { background: var(--parchment); color: var(--text-1); }
.new-chat-btn { color: var(--text-1); font-weight: 500; }

/* Mode segment */
.mode-section {
  padding: 0 10px 10px;
  flex-shrink: 0;
}
.mode-label {
  font-size: 10.5px; font-weight: 600;
  color: var(--text-3); text-transform: uppercase;
  letter-spacing: .5px; padding: 0 4px 5px;
}
.mode-segment {
  display: flex;
  background: var(--parchment);
  border-radius: var(--r-md);
  padding: 3px; gap: 2px;
}
.mode-btn {
  flex: 1; height: 28px;
  border: none; border-radius: calc(var(--r-md) - 2px);
  background: transparent;
  font-size: 13px; font-family: var(--font-sans); font-weight: 500;
  color: var(--text-3); cursor: pointer;
  transition: background .15s, color .15s, box-shadow .15s;
}
.mode-btn.active {
  background: var(--ivory); color: var(--text-1);
  box-shadow: var(--ivory) 0 0 0 0, var(--ring-1) 0 0 0 1px, rgba(0,0,0,.06) 0 1px 3px;
}
.mode-btn:hover:not(.active) { color: var(--text-2); }

.nav-divider {
  height: 1px; background: var(--border-cream);
  margin: 2px 10px 4px; flex-shrink: 0;
}
.sidebar.collapsed .nav-divider { margin: 2px 10px 4px; width: auto; }

/* Thread list */
.sidebar-list {
  flex: 1; overflow-y: auto;
  padding: 0 8px 12px;
}
.sidebar-list.hidden { display: none; }
.sidebar-empty { padding: 10px 8px; font-size: 12px; color: var(--text-3); }

.list-section-label {
  font-size: 10.5px; font-weight: 600; color: var(--text-3);
  padding: 12px 8px 4px; user-select: none;
  text-transform: uppercase; letter-spacing: .5px;
}

.thread-entry {
  display: flex; align-items: center; justify-content: space-between;
  gap: 4px; padding: 7px 8px;
  border-radius: var(--r-md); cursor: pointer;
  margin-bottom: 1px;
  transition: background .12s;
}
.thread-entry:hover { background: var(--parchment); }
.thread-entry.active { background: var(--parchment); }

.thread-main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.thread-title { font-size: 12.5px; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.thread-meta  { font-size: 11px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.thread-menu-wrap { position: relative; flex-shrink: 0; }
.thread-menu-btn {
  width: 20px; height: 20px; border: none; border-radius: var(--r-sm);
  background: transparent; color: var(--text-3); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  opacity: 0; transition: opacity .12s, background .12s, color .12s;
}
.thread-menu-btn svg { width: 13px; height: 13px; }
.thread-entry:hover .thread-menu-btn,
.thread-entry.active .thread-menu-btn,
.thread-menu-btn.open { opacity: 1; }
.thread-menu-btn:hover, .thread-menu-btn.open { background: var(--border-cream); color: var(--text-1); }

.thread-dropdown {
  position: absolute; right: 0; top: calc(100% + 4px);
  min-width: 140px; background: var(--ivory);
  border: 1px solid var(--border-cream); border-radius: var(--r-lg);
  box-shadow: var(--ivory) 0 0 0 0, var(--ring-2) 0 0 0 1px, rgba(0,0,0,.1) 0 8px 24px;
  padding: 4px; z-index: 100;
  animation: dropIn .12s cubic-bezier(.16,1,.3,1) both;
}
@keyframes dropIn {
  from { opacity: 0; transform: scale(.96) translateY(-4px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}
.dropdown-item {
  display: flex; align-items: center; gap: 8px;
  width: 100%; padding: 7px 10px; border: none; border-radius: var(--r-md);
  background: transparent; font-size: 13px; font-family: var(--font-sans);
  color: var(--text-1); cursor: pointer; text-align: left;
  transition: background .1s, color .1s;
}
.dropdown-item svg { width: 13px; height: 13px; flex-shrink: 0; }
.dropdown-item:hover { background: var(--parchment); }
.dropdown-danger { color: var(--danger); }
.dropdown-danger:hover { background: var(--danger-bg); }

/* ═══════════════════════════════════════
   MAIN COLUMN
═══════════════════════════════════════ */
.main-col {
  flex: 1; display: flex; flex-direction: column;
  min-width: 0; height: 100vh; background: var(--parchment);
  border-right: 1px solid var(--border-cream);
}

/* ─── Landing ─── */
.landing-wrap {
  flex: 1; display: flex; align-items: center; justify-content: center;
  padding: 60px 24px;
}
.landing-center {
  width: 100%; max-width: 640px;
  display: flex; flex-direction: column; align-items: center; gap: 28px;
  animation: fadeUp .45s cubic-bezier(.16,1,.3,1) both;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}
.brand-cluster { display: flex; flex-direction: column; align-items: center; gap: 12px; text-align: center; }
.landing-heading-row { display: flex; align-items: center; gap: 14px; }
.landing-icon { width: 36px; height: 36px; flex-shrink: 0; display: block; }
.landing-greeting {
  font-family: var(--font-serif); font-size: 34px; font-weight: 500;
  letter-spacing: -.3px; line-height: 1.2; color: var(--text-1);
}
.landing-sub { font-size: 15.5px; color: var(--text-3); max-width: 400px; line-height: 1.65; }

/* ─── Composer card (landing) ─── */
.composer-card {
  width: 100%;
  background: var(--ivory); border: 1px solid var(--border-cream); border-radius: var(--r-xl);
  padding: 14px 16px 11px;
  box-shadow: var(--ivory) 0 0 0 0, var(--ring-1) 0 0 0 1px, rgba(0,0,0,.04) 0 4px 24px;
  transition: box-shadow .18s;
}
.composer-card:focus-within {
  box-shadow: var(--ivory) 0 0 0 0, var(--focus-blue) 0 0 0 1.5px, rgba(0,0,0,.06) 0 4px 24px;
}
.composer-textarea {
  width: 100%; min-height: 28px; max-height: 200px;
  border: none; outline: none; resize: none; background: transparent;
  font-family: var(--font-sans); font-size: 15px; line-height: 1.6;
  color: var(--text-1); caret-color: var(--terracotta);
}
.composer-textarea::placeholder { color: var(--text-3); }
.composer-textarea:disabled { opacity: .45; cursor: not-allowed; }

.composer-bar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px; margin-top: 10px;
}
.composer-right { display: flex; align-items: center; gap: 6px; }
.composer-actions { display: flex; align-items: center; gap: 6px; }

/* Attach button */
.attach-menu-wrap { position: relative; }
.attach-btn {
  width: 28px; height: 28px;
  border: 1px solid var(--border-warm); border-radius: var(--r-md);
  background: var(--ivory); color: var(--text-3);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: background .12s, color .12s, box-shadow .12s;
}
.attach-btn svg { width: 13px; height: 13px; }
.attach-btn:hover { background: var(--warm-sand); color: var(--text-1); }

.attach-dropdown {
  position: absolute; left: 0; top: calc(100% + 6px);
  min-width: 200px; background: var(--ivory);
  border: 1px solid var(--border-cream); border-radius: var(--r-lg);
  box-shadow: var(--ivory) 0 0 0 0, var(--ring-2) 0 0 0 1px, rgba(0,0,0,.1) 0 8px 24px;
  padding: 4px; z-index: 200;
  animation: dropIn .12s cubic-bezier(.16,1,.3,1) both;
}
.attach-dropdown--up { bottom: calc(100% + 6px); top: auto; }

.attach-option {
  display: flex; align-items: center; gap: 9px;
  width: 100%; padding: 8px 10px; border: none; border-radius: var(--r-md);
  background: transparent; font-family: var(--font-sans); font-size: 13.5px;
  color: var(--text-1); cursor: pointer; text-align: left;
  transition: background .1s;
}
.attach-option svg { width: 15px; height: 15px; color: var(--text-3); flex-shrink: 0; }
.attach-option:hover { background: var(--parchment); }

/* Send button */
.send-btn {
  flex-shrink: 0; width: 32px; height: 32px;
  border-radius: var(--r-md); border: none;
  background: var(--terracotta); color: var(--ivory);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  box-shadow: var(--terracotta) 0 0 0 0, var(--terracotta) 0 0 0 1px;
  transition: background .12s, transform .1s, box-shadow .12s;
}
.send-btn svg { width: 14px; height: 14px; }
.send-btn:hover:not(:disabled) {
  background: var(--terracotta-hover);
  box-shadow: var(--terracotta) 0 0 0 0, var(--terracotta-hover) 0 0 0 1px;
}
.send-btn.paused { background: var(--dark-surface); box-shadow: var(--dark-surface) 0 0 0 0, var(--border-dark) 0 0 0 1px; }
.send-btn.paused:hover:not(:disabled) { background: var(--near-black); }
.send-btn:active:not(:disabled) { transform: scale(.93); }
.send-btn:disabled { background: var(--warm-sand); box-shadow: none; color: var(--text-3); cursor: not-allowed; }

/* Starter chips */
.starter-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; width: 100%;
}
.starter-card {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 8px; background: var(--ivory); border: 1px solid var(--border-cream);
  border-radius: var(--r-lg); padding: 13px 13px; text-align: left;
  cursor: pointer; font-family: var(--font-sans); font-size: 12.5px;
  line-height: 1.5; color: var(--text-2);
  box-shadow: var(--ivory) 0 0 0 0, var(--border-cream) 0 0 0 1px;
  transition: background .12s, color .12s, box-shadow .12s, transform .12s;
}
.starter-card:hover {
  background: var(--warm-sand); color: var(--text-1);
  box-shadow: var(--warm-sand) 0 0 0 0, var(--ring-1) 0 0 0 1px;
  transform: translateY(-1px);
}
.starter-card:active { transform: none; }
.starter-card svg { width: 13px; height: 13px; flex-shrink: 0; color: var(--text-3); margin-top: 2px; }
.starter-card:hover svg { color: var(--text-2); }

.boot-error {
  font-size: 13px; color: var(--danger);
  background: var(--danger-bg); border: 1px solid var(--danger-border);
  border-radius: var(--r-md); padding: 8px 14px;
}

/* ─── Chat topbar ─── */
.main-topbar {
  flex-shrink: 0; height: 42px;
  border-bottom: 1px solid var(--border-cream);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 18px;
  background: rgba(250,249,245,.88); backdrop-filter: blur(10px);
}
.main-topbar-path { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
.main-topbar-root { color: var(--text-3); }
.main-topbar-sep  { color: var(--text-4); }
.main-topbar-current { color: var(--text-1); font-weight: 500; }

.topbar-status {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-3);
}
.status-dot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--text-4); flex-shrink: 0;
}
.status-dot.active {
  background: var(--focus-blue);
  animation: dotPulse 1.5s ease-in-out infinite;
}
@keyframes dotPulse { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }

/* ─── Chat body + messages ─── */
.chat-body {
  flex: 1; min-height: 0; position: relative;
  display: flex; flex-direction: column; overflow: hidden;
}
.messages-scroll { flex: 1; overflow-y: auto; scroll-behavior: smooth; }
.messages-inner {
  max-width: 820px; margin: 0 auto;
  padding: 28px 24px 12px;
  display: flex; flex-direction: column;
}

/* Messages */
.msg-row { display: flex; animation: msgIn .2s cubic-bezier(.16,1,.3,1) both; }
.msg-row.user      { justify-content: flex-end; margin-bottom: 8px; }
.msg-row.assistant { justify-content: flex-start; margin-bottom: 18px; }
@keyframes msgIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

.user-message-group { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; max-width: 72%; }
.user-bubble {
  background: var(--warm-sand); border: 1px solid var(--border-warm);
  border-radius: 18px 18px 4px 18px; padding: 10px 16px;
  font-size: 14.5px; line-height: 1.65; color: var(--text-1);
  white-space: pre-wrap; word-break: break-word;
}

.assistant-row { display: flex; gap: 11px; max-width: 92%; align-items: flex-start; }
.asst-avatar {
  width: 26px; height: 26px; border-radius: var(--r-md);
  background: var(--ivory); display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-top: 2px; overflow: hidden;
  box-shadow: var(--ivory) 0 0 0 0, var(--border-warm) 0 0 0 1px;
}
.asst-avatar img { width: 18px; height: 18px; display: block; }
.asst-avatar--pulse { animation: avatarPulse 1.5s ease-in-out infinite; }
@keyframes avatarPulse { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }
.asst-body { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
.asst-label { font-size: 10.5px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); }
.asst-text { font-size: 15px; line-height: 1.7; color: var(--text-1); word-break: break-word; overflow-wrap: break-word; }
.asst-text :deep(p)            { margin: 0 0 .65em; }
.asst-text :deep(p:last-child) { margin-bottom: 0; }
.asst-text :deep(h1)           { font-family: var(--font-serif); font-size: 19px; font-weight: 500; margin: .9em 0 .4em; }
.asst-text :deep(h2)           { font-family: var(--font-serif); font-size: 16px; font-weight: 500; margin: .85em 0 .35em; }
.asst-text :deep(h3)           { font-size: 14.5px; font-weight: 600; margin: .75em 0 .3em; }
.asst-text :deep(ul)           { list-style: disc; }
.asst-text :deep(ol)           { list-style: decimal; }
.asst-text :deep(ul), .asst-text :deep(ol) { padding-left: 1.4em; margin: .3em 0 .65em; }
.asst-text :deep(li)           { margin-bottom: .25em; line-height: 1.65; }
.asst-text :deep(code)         { font-family: var(--font-mono); background: var(--warm-sand); border-radius: 4px; padding: 1px 5px; font-size: 12.5px; color: var(--text-2); }
.asst-text :deep(pre)          { font-family: var(--font-mono); background: var(--near-black); color: var(--text-4); border-radius: var(--r-lg); padding: 14px 16px; overflow-x: auto; margin: .5em 0 .7em; font-size: 12.5px; line-height: 1.6; }
.asst-text :deep(pre code)     { background: none; padding: 0; color: inherit; font-size: inherit; }
.asst-text :deep(blockquote)   { border-left: 2px solid var(--border-warm); padding-left: 12px; color: var(--text-2); margin: .5em 0; font-style: italic; }
.asst-text :deep(strong)       { font-weight: 600; }
.asst-text :deep(table)        { width: 100%; border-collapse: collapse; margin: .5em 0; font-size: 13.5px; }
.asst-text :deep(th)           { padding: 7px 11px; font-weight: 600; font-size: 11.5px; letter-spacing: .03em; text-align: left; border-bottom: 1px solid var(--border-warm); color: var(--text-2); }
.asst-text :deep(td)           { padding: 7px 11px; border-bottom: 1px solid var(--border-cream); vertical-align: top; }
.asst-text :deep(tr:last-child td) { border-bottom: none; }
.asst-text :deep(a)            { color: var(--terracotta); text-decoration: underline; text-underline-offset: 2px; }

.message-tools {
  display: inline-flex; align-items: center; gap: 5px;
  opacity: 0; transition: opacity .12s; color: var(--text-3);
}
.user-message-group:hover .message-tools,
.assistant-row:hover .message-tools { opacity: 1; }
.assistant-tools { margin-top: 2px; }
.message-time { font-size: 11.5px; line-height: 1; }
.message-tool-btn {
  width: 18px; height: 18px; border: none; border-radius: 999px;
  background: transparent; color: inherit;
  display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
}
.message-tool-btn svg { width: 13px; height: 13px; }
.message-tool-btn:hover { background: var(--parchment); color: var(--text-1); }

/* Streaming caret */
.stream-caret {
  display: inline-block; width: 2px; height: 1em; background: var(--text-2);
  border-radius: 1px; vertical-align: text-bottom;
  animation: caretBlink .9s steps(1) infinite; margin-left: 2px;
}
@keyframes caretBlink { 0%, 44% { opacity: 1; } 55%, 100% { opacity: 0; } }

/* Thinking dots */
.thinking-dots { display: flex; gap: 5px; align-items: center; padding: 6px 0 4px; }
.thinking-dots span {
  width: 6px; height: 6px; border-radius: 50%; background: var(--text-3);
  animation: dotBounce 1.2s ease-in-out infinite both;
}
.thinking-dots span:nth-child(2) { animation-delay: .16s; }
.thinking-dots span:nth-child(3) { animation-delay: .32s; }
@keyframes dotBounce { 0%, 100% { opacity: .3; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-5px); } }

/* Banners */
.banner { border-radius: var(--r-md); padding: 9px 13px; font-size: 13px; margin: 4px 0; }
.banner.info    { background: #f0f6ff; color: #1d4ed8; border: 1px solid #dbeafe; }
.banner.error   { background: var(--danger-bg); color: var(--danger); border: 1px solid var(--danger-border); }
.banner.warning { background: var(--warning-bg); color: var(--text-2); border: 1px solid var(--warning-border); }

/* ─── File Viewer Overlay ─── */
.file-viewer-overlay {
  position: absolute; inset: 0; z-index: 50;
  background: var(--ivory);
  border: 1px solid var(--border-cream);
  border-radius: var(--r-lg);
  margin: 6px;
  display: flex; flex-direction: column; overflow: hidden;
  box-shadow: var(--ivory) 0 0 0 0, var(--ring-2) 0 0 0 1px, rgba(0,0,0,.10) 0 12px 40px;
}
.file-viewer-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; border-bottom: 1px solid var(--border-cream);
  background: var(--parchment); flex-shrink: 0;
}
.file-viewer-title { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; }
.file-ext-chip {
  background: var(--terracotta-bg); border: 1px solid var(--terracotta-border);
  color: var(--terracotta); border-radius: var(--r-sm);
  padding: 2px 6px; font-size: 10px; font-weight: 700;
  font-family: var(--font-mono); flex-shrink: 0;
}
.file-viewer-name {
  font-size: 13.5px; font-weight: 500; color: var(--text-1);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.fv-actions { display: flex; align-items: center; gap: 5px; flex-shrink: 0; margin-left: 10px; }
.fv-btn {
  display: flex; align-items: center; gap: 5px;
  height: 27px; padding: 0 10px;
  border: 1px solid var(--border-warm); border-radius: var(--r-md);
  background: var(--ivory); font-size: 12.5px; font-family: var(--font-sans);
  color: var(--text-2); cursor: pointer;
  transition: background .12s, color .12s;
}
.fv-btn svg { width: 12px; height: 12px; }
.fv-btn:hover { background: var(--warm-sand); color: var(--text-1); }
.fv-btn--save { background: var(--terracotta); color: var(--ivory); border-color: var(--terracotta); }
.fv-btn--save:hover { background: var(--terracotta-hover); color: var(--ivory); }
.fv-close-btn {
  width: 27px; height: 27px; border: none; border-radius: var(--r-md);
  background: transparent; color: var(--text-3); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background .12s, color .12s;
}
.fv-close-btn svg { width: 13px; height: 13px; }
.fv-close-btn:hover { background: var(--danger-bg); color: var(--danger); }
.file-viewer-body { flex: 1; overflow-y: auto; padding: 24px 28px; }
.file-edit-textarea {
  width: 100%; height: 100%; min-height: 400px;
  border: 1px solid var(--border-cream); border-radius: var(--r-md);
  padding: 16px 18px; font-family: var(--font-mono); font-size: 13px;
  line-height: 1.7; resize: none; outline: none;
  background: var(--parchment); color: var(--text-1);
  transition: border-color .15s;
}
.file-edit-textarea:focus { border-color: var(--focus-blue); }
.file-raw-content {
  font-family: var(--font-mono); font-size: 12.5px; line-height: 1.65;
  color: var(--text-1); white-space: pre-wrap; word-break: break-word;
}
/* File viewer transition */
.fv-enter-active { animation: fvIn .18s cubic-bezier(.16,1,.3,1) both; }
.fv-leave-active { animation: fvOut .14s cubic-bezier(.16,1,.3,1) both; }
@keyframes fvIn  { from { opacity: 0; transform: scale(.97) translateY(6px); } to { opacity: 1; transform: scale(1) translateY(0); } }
@keyframes fvOut { from { opacity: 1; transform: scale(1) translateY(0); }    to { opacity: 0; transform: scale(.97) translateY(4px); } }

/* ─── Chat composer ─── */
.composer-wrap { flex-shrink: 0; padding: 8px 18px 14px; }
.chat-composer {
  max-width: 820px; margin: 0 auto;
  background: var(--ivory); border: 1px solid var(--border-cream); border-radius: var(--r-xl);
  padding: 12px 14px 10px;
  box-shadow: var(--ivory) 0 0 0 0, var(--ring-1) 0 0 0 1px, rgba(0,0,0,.04) 0 4px 20px;
  transition: box-shadow .18s;
}
.chat-composer:focus-within {
  box-shadow: var(--ivory) 0 0 0 0, var(--focus-blue) 0 0 0 1.5px, rgba(0,0,0,.06) 0 8px 28px;
}
.ghost-btn {
  height: 28px; border: 1px solid var(--border-warm); border-radius: var(--r-sm);
  background: transparent; padding: 0 11px;
  font-size: 12.5px; font-family: var(--font-sans); color: var(--text-2); cursor: pointer;
  transition: background .12s, color .12s;
}
.ghost-btn:hover { background: var(--warm-sand); color: var(--text-1); }
.disclaimer {
  max-width: 820px; margin: 6px auto 0;
  text-align: center; font-size: 11px; color: var(--text-3);
}

/* ═══════════════════════════════════════
   RIGHT PANEL
═══════════════════════════════════════ */
.right-panel {
  width: 288px; flex-shrink: 0;
  background: var(--ivory); border-left: 1px solid var(--border-cream);
  display: flex; flex-direction: column;
  height: 100vh; overflow: hidden;
}

.rp-block { display: flex; flex-direction: column; min-height: 0; }
.rp-block-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px;
}
.rp-title {
  font-size: 10.5px; font-weight: 600; color: var(--text-3);
  text-transform: uppercase; letter-spacing: .5px;
}
.rp-divider { height: 1px; background: var(--border-cream); flex-shrink: 0; }
.rp-empty { font-size: 12px; color: var(--text-3); text-align: center; padding: 12px 0; line-height: 1.5; }

/* ─── Steps block ─── */
.steps-block {
  flex-shrink: 0; max-height: 38vh;
  overflow-y: auto; padding: 14px 14px 10px;
}
.step-list { display: flex; flex-direction: column; }
.step-phase-label {
  font-size: 10px; font-weight: 600; color: var(--text-3);
  text-transform: uppercase; letter-spacing: .5px;
  padding: 2px 8px 4px; margin-top: 2px;
}
.step-phase-divider { height: 1px; background: var(--border-cream); margin: 8px 0 6px; }
.step-row {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 8px; border-radius: var(--r-md); margin-bottom: 1px;
  transition: background .12s;
}
.step-row.clickable { cursor: pointer; }
.step-row.clickable:hover { background: var(--parchment); }
.step-row.active { background: rgba(56,152,236,.07); }
.step-icon { width: 16px; height: 16px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
.step-icon svg { width: 16px; height: 16px; }
.step-row.pending  .step-icon { color: var(--text-4); }
.step-row.active   .step-icon { color: var(--focus-blue); }
.step-row.completed .step-icon { color: var(--success); }
.step-label { font-size: 12.5px; color: var(--text-2); line-height: 1.4; }
.step-row.pending  .step-label { color: var(--text-4); }
.step-row.active   .step-label { color: var(--text-1); font-weight: 500; }
.step-label.step-done { text-decoration: line-through; color: var(--text-3); }
/* ─── Artifacts block ─── */
.artifacts-block {
  flex: 1; min-height: 0;
  overflow-y: auto; padding: 12px 14px 10px;
}

/* File cards */
.file-cards { display: flex; flex-direction: column; gap: 5px; margin-bottom: 12px; }
.file-card {
  display: flex; align-items: center; gap: 9px;
  padding: 8px 10px;
  background: var(--parchment); border: 1px solid var(--border-cream); border-radius: var(--r-md);
  cursor: pointer; transition: background .12s, box-shadow .12s;
}
.file-card:hover {
  background: var(--warm-sand);
  box-shadow: var(--warm-sand) 0 0 0 0, var(--ring-1) 0 0 0 1px;
}
.file-card.small { padding: 5px 8px; }
.file-card-icon {
  width: 30px; height: 30px;
  background: var(--ivory); border: 1px solid var(--border-warm); border-radius: var(--r-sm);
  display: flex; align-items: center; justify-content: center;
  font-size: 9.5px; font-weight: 700; color: var(--terracotta);
  font-family: var(--font-mono); flex-shrink: 0;
}
.file-card-icon.small { width: 22px; height: 22px; font-size: 8px; }
.file-card-info { min-width: 0; flex: 1; }
.file-card-name { font-size: 12.5px; font-weight: 500; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.file-card-meta { font-size: 10.5px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* Context files */
.context-section { border-top: 1px solid var(--border-cream); padding-top: 10px; margin-top: 2px; }
.context-head {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;
}
.context-label { font-size: 10px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .5px; }
.small-file-cards { display: flex; flex-direction: column; gap: 4px; }

/* Upload zone */
.upload-zone {
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  padding: 14px 10px; border: 1.5px dashed var(--border-warm);
  border-radius: var(--r-md); cursor: pointer; text-align: center;
  transition: background .12s, border-color .12s;
}
.upload-zone:hover { background: var(--parchment); border-color: var(--ring-1); }
.upload-zone svg { width: 18px; height: 18px; color: var(--text-3); }
.upload-zone span { font-size: 11px; color: var(--text-3); line-height: 1.4; }

/* Mini button */
.mini-btn {
  width: 20px; height: 20px; border: none; border-radius: var(--r-sm);
  background: transparent; color: var(--text-3);
  display: flex; align-items: center; justify-content: center; cursor: pointer;
  transition: background .12s, color .12s;
}
.mini-btn svg { width: 12px; height: 12px; }
.mini-btn:hover { background: var(--parchment); color: var(--text-1); }


/* ─── Package block ─── */
.package-block { flex-shrink: 0; padding: 12px 14px 14px; max-height: 200px; overflow-y: auto; }

/* ─── Review block ─── */
.review-block { padding: 12px 14px 14px; max-height: 320px; overflow-y: auto; }
.review-score-badge {
  background: var(--terracotta-bg); border: 1px solid var(--terracotta-border);
  color: var(--terracotta); border-radius: 999px;
  padding: 2px 8px; font-size: 11.5px; font-weight: 600;
}
.review-list { display: flex; flex-direction: column; gap: 7px; margin-bottom: 10px; }
.review-item {
  border: 1px solid var(--border-cream); border-radius: var(--r-md);
  padding: 10px 11px; background: var(--parchment);
  display: flex; flex-direction: column; gap: 5px;
}
.review-item.high   { border-color: var(--danger-border); background: var(--danger-bg); }
.review-item.medium { border-color: var(--warning-border); background: var(--warning-bg); }
.review-problem    { font-size: 12.5px; font-weight: 500; color: var(--text-1); line-height: 1.4; }
.review-suggestion { font-size: 12px; color: var(--text-2); line-height: 1.5; }
.review-actions { display: flex; gap: 5px; }
.review-actions button {
  height: 24px; padding: 0 9px;
  border: 1px solid var(--border-warm); border-radius: var(--r-sm);
  background: var(--ivory); font-size: 12px; font-family: var(--font-sans);
  color: var(--text-2); cursor: pointer;
  transition: background .1s, color .1s;
}
.review-actions button:hover,
.review-actions button.active { background: var(--warm-sand); color: var(--text-1); }
.review-actions .danger-btn { color: var(--danger); }
.review-actions .danger-btn.active { background: var(--danger-bg); color: var(--danger); border-color: var(--danger-border); }
.review-textarea {
  width: 100%; margin-top: 4px; padding: 5px 8px;
  border: 1px solid var(--border-warm); border-radius: var(--r-sm);
  font-size: 12px; font-family: var(--font-sans); color: var(--text-1);
  background: var(--ivory); resize: none; outline: none;
}
.review-submit-btn {
  width: 100%; height: 30px; border: none; border-radius: var(--r-md);
  background: var(--terracotta); color: var(--ivory);
  font-size: 13px; font-family: var(--font-sans); font-weight: 500;
  cursor: pointer; transition: background .12s;
}
.review-submit-btn:hover { background: var(--terracotta-hover); }

/* ─── Timeline block ─── */
.timeline-block { padding: 12px 14px 14px; flex: 1; min-height: 0; overflow-y: auto; }
.timeline-list { display: flex; flex-direction: column; gap: 10px; }
.timeline-item { padding: 8px 10px; border: 1px solid var(--border-cream); border-radius: var(--r-md); background: var(--parchment); }
.timeline-time { font-size: 10.5px; color: var(--text-3); margin-bottom: 4px; }
.timeline-title { font-size: 12.5px; color: var(--text-1); font-weight: 500; }
.timeline-detail { font-size: 12px; color: var(--text-2); margin-top: 3px; line-height: 1.5; }

/* ═══════════════════════════════════════
   PROSE (file viewer markdown)
═══════════════════════════════════════ */
.prose {
  max-width: 100%; font-size: 15px; line-height: 1.75; color: var(--text-1);
}
.prose :deep(h1) {
  font-family: var(--font-serif); font-size: 24px; font-weight: 500;
  margin: 0 0 14px; letter-spacing: -.2px; line-height: 1.2; color: var(--text-1);
  border-bottom: 1px solid var(--border-cream); padding-bottom: 12px;
}
.prose :deep(h2) {
  font-family: var(--font-serif); font-size: 18px; font-weight: 500;
  margin: 26px 0 9px; color: var(--text-1); line-height: 1.3;
}
.prose :deep(h3) { font-size: 15px; font-weight: 600; margin: 18px 0 7px; color: var(--text-1); }
.prose :deep(h4) {
  font-size: 10.5px; font-weight: 600; margin: 14px 0 5px;
  color: var(--text-3); text-transform: uppercase; letter-spacing: .08em;
}
.prose :deep(p)  { margin: 0 0 .85em; }
.prose :deep(p:last-child) { margin-bottom: 0; }
.prose :deep(ul) { list-style: disc; }
.prose :deep(ol) { list-style: decimal; }
.prose :deep(ul), .prose :deep(ol) { padding-left: 1.4em; margin: .3em 0 .85em; }
.prose :deep(li) { margin-bottom: .35em; line-height: 1.7; }
.prose :deep(li > p) { margin: 0; }
.prose :deep(hr) { border: none; border-top: 1px solid var(--border-cream); margin: 20px 0; }
.prose :deep(blockquote) {
  border-left: 3px solid var(--border-warm); padding: 3px 0 3px 16px;
  color: var(--text-2); margin: .8em 0; font-style: italic;
}
.prose :deep(code) {
  font-family: var(--font-mono); background: var(--parchment);
  border: 1px solid var(--border-cream); border-radius: 4px;
  padding: 1px 6px; font-size: 12.5px; color: var(--text-2);
}
.prose :deep(pre) {
  font-family: var(--font-mono); background: var(--near-black);
  color: var(--text-4); border-radius: var(--r-lg);
  padding: 16px 20px; overflow-x: auto; margin: .7em 0 .85em;
  font-size: 12.5px; line-height: 1.65;
}
.prose :deep(pre code) { background: none; border: none; padding: 0; color: inherit; font-size: inherit; }
.prose :deep(table) { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 13.5px; }
.prose :deep(thead) { background: var(--parchment); }
.prose :deep(th) { padding: 9px 14px; text-align: left; font-size: 11px; font-weight: 600; letter-spacing: .04em; color: var(--text-2); border-bottom: 1px solid var(--border-warm); }
.prose :deep(td) { padding: 9px 14px; border-bottom: 1px solid var(--border-cream); vertical-align: top; }
.prose :deep(tr:last-child td) { border-bottom: none; }
.prose :deep(strong) { font-weight: 600; }
.prose :deep(em) { font-style: italic; color: var(--text-2); }
.prose :deep(a) { color: var(--terracotta); text-decoration: underline; text-underline-offset: 2px; }
</style>
