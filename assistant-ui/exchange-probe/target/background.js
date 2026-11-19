/* global browser */
const ALLOWED_MANAGER = "foxbook-exchange-manager@foxbook.example";
const validKeys = (value, keys) => Object.keys(value).sort().join(",") === [...keys].sort().join(",");

browser.runtime.onMessageExternal.addListener((message, sender) => {
  if (sender.id !== ALLOWED_MANAGER) return Promise.resolve({ ok: false, error: "UNAUTHORIZED" });
  if (!message || typeof message !== "object" || Array.isArray(message) || message.version !== 1) {
    return Promise.resolve({ ok: false, error: "INVALID_REQUEST" });
  }
  if (message.type === "getCommands" && validKeys(message, ["version", "type"])) {
    return fetch(browser.runtime.getURL("commands.json"))
      .then((response) => { if (!response.ok) throw new Error("definition unavailable"); return response.json(); })
      .then((definition) => ({ ok: true, definition }))
      .catch(() => ({ ok: false, error: "DEFINITION_UNAVAILABLE" }));
  }
  if (message.type === "execute" && validKeys(message, ["version", "type", "commandId"]) &&
      message.commandId === "preview_tempo_increase") {
    return Promise.resolve({ ok: true, result: "模擬操作を受け付けました。実際のテンポは変更していません。" });
  }
  return Promise.resolve({ ok: false, error: "INVALID_REQUEST" });
});
