<script setup lang="ts">
import type { ReviewBatch } from "../../types";

defineProps<{
  latestReview: ReviewBatch | null;
  reviewDraft: Record<string, { action: "approve" | "edit" | "reject"; edited: string }>;
}>();

const emit = defineEmits<{
  (e: "set-action", suggestionId: string, action: "approve" | "edit" | "reject"): void;
  (e: "update-edited", suggestionId: string, value: string): void;
  (e: "submit"): void;
}>();
</script>

<template>
  <section v-if="latestReview" class="rp-block review-block">
    <div class="rp-block-head">
      <h3 class="rp-title">评审建议</h3>
      <span class="review-score-badge">{{ latestReview.total_score }} 分</span>
    </div>
    <div class="review-list">
      <div
        v-for="s in latestReview.suggestions"
        :key="s.suggestion_id"
        class="review-item"
        :class="s.severity"
      >
        <p class="review-problem">{{ s.problem }}</p>
        <p class="review-suggestion">{{ s.suggestion }}</p>
        <div class="review-actions">
          <button :class="{ active: reviewDraft[s.suggestion_id ?? '']?.action === 'approve' }" @click="emit('set-action', s.suggestion_id ?? '', 'approve')">通过</button>
          <button :class="{ active: reviewDraft[s.suggestion_id ?? '']?.action === 'edit' }" @click="emit('set-action', s.suggestion_id ?? '', 'edit')">修改</button>
          <button :class="['danger-btn', { active: reviewDraft[s.suggestion_id ?? '']?.action === 'reject' }]" @click="emit('set-action', s.suggestion_id ?? '', 'reject')">驳回</button>
        </div>
        <textarea
          v-if="reviewDraft[s.suggestion_id ?? '']?.action === 'edit'"
          :value="reviewDraft[s.suggestion_id ?? ''].edited"
          class="review-textarea"
          rows="2"
          placeholder="输入修改意见"
          @input="emit('update-edited', s.suggestion_id ?? '', ($event.target as HTMLTextAreaElement).value)"
        />
      </div>
    </div>
    <button class="review-submit-btn" @click="emit('submit')">提交审核结果</button>
  </section>
</template>
