import { ref } from "vue";

import { streamThread } from "../lib/api";

export function useThreadStream() {
  const eventSrc = ref<EventSource | null>(null);

  function disconnect() {
    eventSrc.value?.close();
    eventSrc.value = null;
  }

  function connect(threadId: string, onEvent: (event: MessageEvent, type: string) => void) {
    disconnect();
    eventSrc.value = streamThread(threadId, onEvent);
  }

  return {
    connect,
    disconnect,
    eventSrc,
  };
}
