<script setup lang="ts">
withDefaults(defineProps<{ showRight?: boolean }>(), {
  showRight: true,
});
</script>

<template>
  <div class="app-shell">
    <slot name="sidebar" />
    <main class="main-col">
      <slot />
    </main>
    <aside v-if="showRight" class="right-panel">
      <slot name="right" />
    </aside>
  </div>
</template>
