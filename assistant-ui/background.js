/* global browser */

// Stage 1 only: preview state is independent of page availability. This does
// not connect to the speech host or start microphone capture.
const PREVIEW_STATES = ["disconnected", "waiting", "recognizing", "choosing", "error"];
const DEFAULT_STATE = "disconnected";

browser.runtime.onMessage.addListener(async (message, sender) => {
  if (message?.type === "getPreviewState") {
    const { previewState } = await browser.storage.local.get({ previewState: DEFAULT_STATE });
    return { state: PREVIEW_STATES.includes(previewState) ? previewState : DEFAULT_STATE };
  }
  if (message?.type === "setPreviewState" && sender.url === browser.runtime.getURL("preview.html")) {
    if (!PREVIEW_STATES.includes(message.state)) return { ok: false };
    await browser.storage.local.set({ previewState: message.state });
    return { ok: true };
  }
  return undefined;
});
