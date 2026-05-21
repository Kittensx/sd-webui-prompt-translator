// Prompt Translator selection helper for A1111/Gradio.
// This file exposes functions used by button .click(_js=...) callbacks.

(function () {
  function app() {
    if (typeof gradioApp === "function") return gradioApp();
    return document;
  }

  function findTextareaByElemId(elemId) {
    const root = app();
    const box = root.querySelector(`#${elemId} textarea`);
    if (box) return box;
    return root.querySelector(`textarea#${elemId}`);
  }

  function activePromptTextarea() {
    const active = document.activeElement;
    if (active && active.tagName === "TEXTAREA") return active;
    return findTextareaByElemId("txt2img_prompt") || findTextareaByElemId("img2img_prompt");
  }

  function textareaPayload(textarea, promptKind) {
    textarea = textarea || activePromptTextarea();
    if (!textarea) {
      return JSON.stringify({ value: "", selection_start: 0, selection_end: 0, selected_text: "", prompt_kind: promptKind || "unknown", error: "No prompt textarea found" });
    }
    const start = typeof textarea.selectionStart === "number" ? textarea.selectionStart : 0;
    const end = typeof textarea.selectionEnd === "number" ? textarea.selectionEnd : start;
    return JSON.stringify({
      value: textarea.value || "",
      selection_start: start,
      selection_end: end,
      selected_text: (textarea.value || "").slice(start, end),
      prompt_kind: promptKind || "active"
    });
  }

  window.promptTranslatorCaptureActiveSelection = function () {
    return textareaPayload(activePromptTextarea(), "active");
  };

  window.promptTranslatorCaptureTxt2ImgSelection = function () {
    return textareaPayload(findTextareaByElemId("txt2img_prompt"), "txt2img");
  };

  window.promptTranslatorCaptureImg2ImgSelection = function () {
    return textareaPayload(findTextareaByElemId("img2img_prompt"), "img2img");
  };
})();
