<script setup lang="ts">
import { computed } from "vue";
import { marked } from "marked";

import type { ConversationConstraint, MessageRecord, SavedArtifactRecord } from "../../types";

const props = defineProps<{
  activeConstraints: ConversationConstraint[];
  visibleMessages: MessageRecord[];
  editableUserMessageId: string | null;
  copiedMessageId: string | null;
  streamingAssistantActive: boolean;
  streamingAssistant: string;
  processing: boolean;
  reconnectNotice: string;
  bootError: string;
  viewingFile: SavedArtifactRecord | null;
  viewingFileContent: string;
  rightTab: "preview" | "edit";
  editableMarkdown: string;
  copiedViewedFile: boolean;
}>();

const emit = defineEmits<{
  (e: "copy-message", messageId: string, content: string): void;
  (e: "edit-message", messageId: string, content: string): void;
  (e: "update:rightTab", value: "preview" | "edit"): void;
  (e: "update:editableMarkdown", value: string): void;
  (e: "save-artifact"): void;
  (e: "close-file-viewer"): void;
  (e: "copy-viewed-file"): void;
}>();

const viewingMarkdownRendered = computed(() => {
  if (!props.viewingFileContent) return "";
  return marked.parse(props.viewingFileContent.trim()) as string;
});

function renderAssistantMessage(content: string) {
  const normalized = content.replace(/\n{3,}/g, "\n\n").replace(/[ \t]+\n/g, "\n").trim();
  return marked.parse(normalized || "") as string;
}

function renderUserMessage(content: string) {
  return content.replace(/\n{3,}/g, "\n\n").trim();
}

function formatMessageTime(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function getFileExt(filename: string) {
  return filename.split(".").pop()?.toUpperCase() ?? "FILE";
}
</script>

<template>
  <div class="chat-body">
    <div class="messages-scroll">
      <div class="messages-inner">
        <div v-if="activeConstraints.length" class="banner warning">
          当前约束：{{ activeConstraints.map((c) => c.instruction).join("；") }}
        </div>

        <div v-for="msg in visibleMessages" :key="msg.message_id" class="msg-row" :class="msg.role">
          <template v-if="msg.role === 'user'">
            <div class="user-message-group">
              <div class="message-tools">
                <span class="message-time">{{ formatMessageTime(msg.timestamp ?? "") }}</span>
                <button class="message-tool-btn" :title="copiedMessageId === (msg.message_id ?? msg.content) ? '已复制' : '复制'" @click="emit('copy-message', msg.message_id ?? msg.content, msg.content)">
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="5" y="3" width="8" height="10" rx="2"/><path d="M3 11V5a2 2 0 012-2"/></svg>
                </button>
                <button v-if="msg.message_id === editableUserMessageId" class="message-tool-btn" title="编辑" @click="emit('edit-message', msg.message_id ?? msg.content, msg.content)">
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M3 11.5V13h1.5L11.8 5.7 10.3 4.2 3 11.5z"/><path d="M9.6 4.9l1.5 1.5"/></svg>
                </button>
              </div>
              <div class="user-bubble">{{ renderUserMessage(msg.content) }}</div>
            </div>
          </template>
          <template v-else>
            <div class="assistant-row">
              <span class="asst-avatar" aria-hidden="true"><img src="/icon.png" alt="" /></span>
              <div class="asst-body">
                <p class="asst-label">制课 Agent</p>
                <div class="asst-text" v-html="renderAssistantMessage(msg.content)" />
                <div class="message-tools assistant-tools">
                  <span class="message-time">{{ formatMessageTime(msg.timestamp ?? "") }}</span>
                  <button class="message-tool-btn" :title="copiedMessageId === (msg.message_id ?? msg.content) ? '已复制' : '复制'" @click="emit('copy-message', msg.message_id ?? msg.content, msg.content)">
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="5" y="3" width="8" height="10" rx="2"/><path d="M3 11V5a2 2 0 012-2"/></svg>
                  </button>
                </div>
              </div>
            </div>
          </template>
        </div>

        <div v-if="streamingAssistantActive" class="msg-row assistant">
          <div class="assistant-row">
            <span class="asst-avatar" aria-hidden="true"><img src="/icon.png" alt="" /></span>
            <div class="asst-body">
              <p class="asst-label">制课 Agent</p>
              <div class="asst-text" v-html="renderAssistantMessage(streamingAssistant)" />
              <span class="stream-caret" aria-hidden="true">▋</span>
            </div>
          </div>
        </div>

        <div v-if="processing && !streamingAssistantActive" class="msg-row assistant">
          <div class="assistant-row">
            <span class="asst-avatar asst-avatar--pulse" aria-hidden="true"><img src="/icon.png" alt="" /></span>
            <div class="thinking-dots" aria-label="正在思考"><span /><span /><span /></div>
          </div>
        </div>

        <div v-if="reconnectNotice" class="banner info">{{ reconnectNotice }}</div>
        <div v-if="bootError" class="banner error">{{ bootError }}</div>
      </div>
    </div>

    <transition name="fv">
      <div v-if="viewingFile" class="file-viewer-overlay">
        <div class="file-viewer-header">
          <div class="file-viewer-title">
            <span class="file-ext-chip">{{ getFileExt(viewingFile.filename) }}</span>
            <span class="file-viewer-name">{{ viewingFile.label || viewingFile.filename }}</span>
          </div>
          <div class="fv-actions">
            <button class="fv-btn" @click="emit('copy-viewed-file')">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="5" y="3" width="8" height="10" rx="2"/><path d="M3 11V5a2 2 0 012-2"/></svg>
              {{ copiedViewedFile ? "已复制" : "复制" }}
            </button>
            <button
              v-if="viewingFile.kind === 'generated' && rightTab === 'preview'"
              class="fv-btn"
              @click="emit('update:rightTab', 'edit')"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M3 11.5V13h1.5L11.8 5.7 10.3 4.2 3 11.5z"/><path d="M9.6 4.9l1.5 1.5"/></svg>
              编辑
            </button>
            <button v-if="viewingFile.kind === 'generated' && rightTab === 'edit'" class="fv-btn fv-btn--save" @click="emit('save-artifact')">保存</button>
            <button v-if="rightTab === 'edit'" class="fv-btn" @click="emit('update:rightTab', 'preview')">取消</button>
            <button class="fv-close-btn" aria-label="关闭" @click="emit('close-file-viewer')">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>
            </button>
          </div>
        </div>
        <div class="file-viewer-body">
          <template v-if="rightTab === 'preview'">
            <div v-if="viewingFile.kind === 'generated'" class="prose" v-html="viewingMarkdownRendered" />
            <pre v-else class="file-raw-content">{{ viewingFileContent || "（无法预览此文件）" }}</pre>
          </template>
          <template v-else>
            <textarea :value="editableMarkdown" class="file-edit-textarea" spellcheck="false" @input="emit('update:editableMarkdown', ($event.target as HTMLTextAreaElement).value)" />
          </template>
        </div>
      </div>
    </transition>
  </div>
</template>
