import { computed, ref } from "vue";
import { marked } from "marked";

import { fetchArtifactVersion, updateLatestArtifact } from "../lib/api";
import type { SavedArtifactRecord } from "../types";

export function useArtifactViewer(threadId: { value: string }) {
  const rightTab = ref<"preview" | "edit">("preview");
  const editableMarkdown = ref("");
  const viewingFile = ref<SavedArtifactRecord | null>(null);
  const viewingFileContent = ref("");
  const copiedViewedFile = ref(false);

  const viewingMarkdownRendered = computed(() => {
    if (!viewingFileContent.value) return "";
    return marked.parse(viewingFileContent.value.trim()) as string;
  });

  async function openFileViewer(file: SavedArtifactRecord) {
    viewingFile.value = file;
    viewingFileContent.value = "";
    copiedViewedFile.value = false;
    rightTab.value = "preview";
    if (file.kind === "generated") {
      try {
        const { artifact } = await fetchArtifactVersion(threadId.value, file.version);
        viewingFileContent.value = artifact?.markdown ?? "";
        editableMarkdown.value = artifact?.markdown ?? "";
      } catch {
        viewingFileContent.value = "无法加载文件内容";
      }
    }
  }

  function closeFileViewer() {
    viewingFile.value = null;
    viewingFileContent.value = "";
    copiedViewedFile.value = false;
    rightTab.value = "preview";
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

  async function copyViewedFile() {
    if (!viewingFileContent.value) return;
    await safeCopy(viewingFileContent.value);
    copiedViewedFile.value = true;
    setTimeout(() => {
      copiedViewedFile.value = false;
    }, 1500);
  }

  async function saveEditedArtifact() {
    if (!threadId.value) return;
    await updateLatestArtifact(threadId.value, editableMarkdown.value);
    rightTab.value = "preview";
    viewingFileContent.value = editableMarkdown.value;
  }

  return {
    rightTab,
    editableMarkdown,
    viewingFile,
    viewingFileContent,
    viewingMarkdownRendered,
    copiedViewedFile,
    openFileViewer,
    closeFileViewer,
    copyViewedFile,
    saveEditedArtifact,
  };
}
