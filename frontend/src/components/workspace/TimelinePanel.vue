<script setup lang="ts">
import type { TimelineEvent } from "../../types";

defineProps<{
  timeline: TimelineEvent[];
}>();

function formatTime(ts: string) {
  try {
    return new Date(ts).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return ts;
  }
}
</script>

<template>
  <section class="rp-block timeline-block">
    <div class="rp-block-head">
      <h3 class="rp-title">时间线</h3>
    </div>
    <div v-if="!timeline.length" class="rp-empty">暂无时间线事件</div>
    <div v-else class="timeline-list">
      <div v-for="item in timeline" :key="item.event_id" class="timeline-item">
        <div class="timeline-time">{{ formatTime(item.created_at ?? "") }}</div>
        <div class="timeline-title">{{ item.title }}</div>
        <div v-if="item.detail" class="timeline-detail">{{ item.detail }}</div>
      </div>
    </div>
  </section>
</template>
