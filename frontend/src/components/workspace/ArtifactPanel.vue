<script setup lang="ts">
import { ref } from "vue";

import type { SavedArtifactRecord, WorkflowStepState } from "../../types";

defineProps<{
  visibleWorkflowSteps: WorkflowStepState[];
  contentCreationSteps: WorkflowStepState[];
  generatedArtifacts: SavedArtifactRecord[];
  packageFiles: SavedArtifactRecord[];
}>();

const emit = defineEmits<{
  (e: "click-step", step: WorkflowStepState): void;
  (e: "open-artifact", artifact: SavedArtifactRecord): void;
  (e: "upload", category: "context" | "package", files: FileList | null): void;
}>();

const packageUploadRef = ref<HTMLInputElement | null>(null);

function triggerPackageUpload() {
  packageUploadRef.value?.click();
}

function getFileExt(filename: string) {
  return filename.split(".").pop()?.toUpperCase() ?? "FILE";
}
</script>

<template>
  <section class="rp-block steps-block">
    <div class="rp-block-head">
      <h3 class="rp-title">制课进度</h3>
    </div>

    <div v-if="!visibleWorkflowSteps.length" class="rp-empty">开始对话后将显示制课步骤</div>

    <div v-else class="step-list">
      <template v-if="contentCreationSteps.length">
        <div class="step-phase-label">内容创作</div>
        <div
          v-for="step in contentCreationSteps"
          :key="step.step_id"
          class="step-row"
          :class="[step.status, { clickable: step.status === 'completed' }]"
          @click="emit('click-step', step)"
        >
          <span class="step-icon">
            <svg v-if="step.status === 'completed'" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><polyline points="3 8 6.5 12 13 5"/></svg>
            <svg v-else-if="step.status === 'active'" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><circle cx="8" cy="8" r="4"/></svg>
            <svg v-else viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><circle cx="8" cy="8" r="2.5"/></svg>
          </span>
          <span class="step-label" :class="{ 'step-done': step.status === 'completed' }">{{ step.label }}</span>
        </div>
      </template>
    </div>
  </section>

  <div class="rp-divider" />

  <section class="rp-block artifacts-block">
    <div class="rp-block-head">
      <h3 class="rp-title">成果文件</h3>
    </div>

    <div class="file-cards">
      <div
        v-for="artifact in generatedArtifacts"
        :key="artifact.artifact_id"
        class="file-card"
        role="button"
        tabindex="0"
        @click="emit('open-artifact', artifact)"
        @keydown.enter="emit('open-artifact', artifact)"
      >
        <div class="file-card-icon">.md</div>
        <div class="file-card-info">
          <div class="file-card-name">{{ artifact.label }}</div>
          <div class="file-card-meta">{{ artifact.filename }}</div>
        </div>
      </div>
      <div v-if="!generatedArtifacts.length" class="rp-empty">生成完成后的成果文件会显示在这里</div>
    </div>

    <input class="hidden-input" type="file" multiple @change="emit('upload', 'context', ($event.target as HTMLInputElement).files)" />
  </section>

  <div class="rp-divider" />

  <section class="rp-block package-block">
    <div class="rp-block-head">
      <h3 class="rp-title">素材包</h3>
      <button class="mini-btn" title="上传素材" @click="triggerPackageUpload">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M8 2v8M5 7l3 3 3-3"/><path d="M3 13h10"/></svg>
      </button>
    </div>
    <div class="small-file-cards">
      <div v-for="file in packageFiles" :key="file.artifact_id" class="file-card small">
        <div class="file-card-icon small">{{ getFileExt(file.filename) }}</div>
        <div class="file-card-info">
          <div class="file-card-name">{{ file.filename }}</div>
        </div>
      </div>
      <div v-if="!packageFiles.length" class="upload-zone" @click="triggerPackageUpload">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        <span>点击上传素材文件</span>
      </div>
    </div>
    <input ref="packageUploadRef" class="hidden-input" type="file" multiple @change="emit('upload', 'package', ($event.target as HTMLInputElement).files)" />
  </section>
</template>
