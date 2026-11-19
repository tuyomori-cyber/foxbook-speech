/* global browser */
(() => {
  const HOST_ID = "foxbook-assistant-preview-indicator";
  if (document.getElementById(HOST_ID)) return;

  const labels = {
    disconnected: "未接続",
    waiting: "呼びかけを待機中",
    recognizing: "認識中",
    choosing: "候補を選択中",
    error: "サービスエラー"
  };
  const host = document.createElement("div");
  host.id = HOST_ID;
  for (const [property, value] of Object.entries({
    all: "initial", position: "fixed", left: "12px", top: "12px",
    "z-index": "2147483647", display: "block", margin: "0", padding: "0"
  })) host.style.setProperty(property, value, "important");
  const shadow = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = `
    .indicator { box-sizing: border-box; max-width: min(300px, 90vw); min-height: 44px;
      padding: 11px 14px; border: 1px solid #87929b; border-radius: 8px;
      background: #fffdf8; color: #202b35; box-shadow: 0 3px 12px #0004;
      font: 14px/1.4 system-ui, sans-serif; cursor: grab; touch-action: none;
      user-select: none; overflow-wrap: anywhere; }
    .indicator:active { cursor: grabbing; }
  `;
  const panel = document.createElement("div");
  panel.className = "indicator";
  panel.setAttribute("role", "status");
  panel.setAttribute("aria-live", "polite");
  panel.setAttribute("title", "ドラッグして移動できます（表示試作）");
  shadow.append(style, panel);
  document.documentElement.append(host);

  let position = { left: 12, top: 12 };
  let positionTouched = false;
  let drag;
  function place(left, top) {
    position = {
      left: Math.min(Math.max(0, left), Math.max(0, window.innerWidth - host.offsetWidth)),
      top: Math.min(Math.max(0, top), Math.max(0, window.innerHeight - host.offsetHeight))
    };
    host.style.setProperty("left", `${position.left}px`, "important");
    host.style.setProperty("top", `${position.top}px`, "important");
  }
  function render(value) {
    panel.textContent = `試作：${labels[value] || labels.disconnected}`;
    place(position.left, position.top);
  }

  panel.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || event.button !== 0) return;
    positionTouched = true;
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY, left: position.left, top: position.top };
    panel.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  panel.addEventListener("pointermove", (event) => {
    if (drag?.id !== event.pointerId) return;
    place(drag.left + event.clientX - drag.x, drag.top + event.clientY - drag.y);
  });
  function finishDrag(event) {
    if (drag?.id !== event.pointerId) return;
    drag = undefined;
    browser.storage.local.set({ indicatorPosition: position }).catch(console.error);
  }
  panel.addEventListener("pointerup", finishDrag);
  panel.addEventListener("pointercancel", finishDrag);
  panel.addEventListener("lostpointercapture", finishDrag);
  window.addEventListener("resize", () => place(position.left, position.top));
  browser.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.previewState) render(changes.previewState.newValue);
    const saved = changes.indicatorPosition?.newValue;
    if (!drag && Number.isFinite(saved?.left) && Number.isFinite(saved?.top)) place(saved.left, saved.top);
  });
  render("disconnected");
  browser.runtime.sendMessage({ type: "getPreviewState" }).then((response) => {
    if (response) render(response.state);
  }).catch(() => render("error"));
  browser.storage.local.get("indicatorPosition").then(({ indicatorPosition: saved }) => {
    if (!positionTouched && Number.isFinite(saved?.left) && Number.isFinite(saved?.top)) place(saved.left, saved.top);
  }).catch(console.error);
})();
