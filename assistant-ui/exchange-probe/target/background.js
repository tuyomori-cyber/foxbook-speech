/* global browser */
const ALLOWED_MANAGER = "foxbook-exchange-manager@foxbook.example";
const validKeys = (value, keys) => Object.keys(value).sort().join(",") === [...keys].sort().join(",");
const MODES = ["normal", "delay_response", "delay_execute", "no_response", "no_definition"];
const DELAY_MS = 8000;
let updateQueue = Promise.resolve();

async function readState() {
  const stored = await browser.storage.local.get(["mode", "operations"]);
  return { mode: MODES.includes(stored.mode) ? stored.mode : "normal", operations: Array.isArray(stored.operations) ? stored.operations : [] };
}
function updateState(update) {
  const task = updateQueue.then(async () => {
    const state = await readState();
    await browser.storage.local.set(update(state));
  });
  updateQueue = task.catch(() => {});
  return task;
}
function recordOperation() {
  return updateState((state) => ({ operations: [...state.operations, new Date().toISOString()] }));
}
const delay = () => new Promise((resolve) => setTimeout(resolve, DELAY_MS));
const noResponse = () => new Promise(() => {});
const success = () => ({ ok: true, result: "模擬操作を受け付けました。実際のテンポは変更していません。" });

browser.action.onClicked.addListener(() => browser.tabs.create({ url: browser.runtime.getURL("control.html") }));
browser.runtime.onMessage.addListener((message, sender) => {
  if (sender.id !== browser.runtime.id || !sender.url?.startsWith(browser.runtime.getURL("control.html"))) return;
  if (message?.type === "getState") return readState();
  if (message?.type === "setMode" && MODES.includes(message.mode)) return updateState(() => ({ mode: message.mode })).then(readState);
  if (message?.type === "reset") return updateState(() => ({ operations: [] })).then(readState);
});

browser.runtime.onMessageExternal.addListener(async (message, sender) => {
  if (sender.id !== ALLOWED_MANAGER) return { ok: false, error: "UNAUTHORIZED" };
  if (!message || typeof message !== "object" || Array.isArray(message) || message.version !== 1) return { ok: false, error: "INVALID_REQUEST" };
  if (message.type === "getCommands" && validKeys(message, ["version", "type"])) {
    if ((await readState()).mode === "no_definition") return noResponse();
    try {
      const response = await fetch(browser.runtime.getURL("commands.json"));
      if (!response.ok) throw new Error("definition unavailable");
      return { ok: true, definition: await response.json() };
    } catch (_) { return { ok: false, error: "DEFINITION_UNAVAILABLE" }; }
  }
  if (message.type === "execute" && validKeys(message, ["version", "type", "commandId"]) && message.commandId === "preview_tempo_increase") {
    const { mode } = await readState();
    if (mode === "no_response") return noResponse();
    if (mode === "delay_execute") await delay();
    await recordOperation();
    if (mode === "delay_response") await delay();
    return success();
  }
  return { ok: false, error: "INVALID_REQUEST" };
});
