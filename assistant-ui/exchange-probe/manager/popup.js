/* global browser */
const targets = {
  dummy: { id: "foxbook-exchange-target@foxbook.example", appId: "dummy_metronome", commandId: "preview_tempo_increase" },
  session: { id: "the-session-tools@example.invalid", appId: "the_session_tools", commandId: "tempo.increase.small" }
};
const targetSelect = document.querySelector("#target");
const get = document.querySelector("#get");
const execute = document.querySelector("#execute");
const result = document.querySelector("#result");
let commandId;
let selectedTarget;

targetSelect.addEventListener("change", () => {
  commandId = undefined;
  selectedTarget = undefined;
  execute.disabled = true;
  execute.textContent = targetSelect.value === "session" ? "テンポを5上げる（実操作）" : "模擬操作を送信";
  result.textContent = "定義を取得してください。";
});

get.addEventListener("click", async () => {
  execute.disabled = true;
  commandId = undefined;
  const target = targets[targetSelect.value];
  if (!target) return;
  try {
    const response = await browser.runtime.sendMessage(target.id, { version: 1, type: "getCommands" });
    if (targets[targetSelect.value] !== target) return;
    const definition = response?.definition;
    const command = definition?.commands?.[0];
    if (!response?.ok || definition?.version !== 1 || definition.appId !== target.appId ||
        command?.id !== target.commandId || typeof definition.name !== "string" || typeof command.label !== "string") {
      result.textContent = `定義を取得できません：${response?.error || "形式不正"}`;
      return;
    }
    commandId = command.id;
    selectedTarget = target;
    result.textContent = `定義を取得：${definition.name} / ${command.label}`;
    execute.disabled = false;
  } catch (_) {
    result.textContent = "対象拡張に接続できません。対象の試作拡張が読み込まれているか確認してください。";
  }
});

execute.addEventListener("click", async () => {
  if (!commandId || !selectedTarget) return;
  const target = selectedTarget;
  const requestedCommand = commandId;
  try {
    const response = await browser.runtime.sendMessage(target.id, { version: 1, type: "execute", commandId: requestedCommand });
    if (selectedTarget !== target) return;
    if (response?.ok && target.appId === "the_session_tools") {
      result.textContent = response.result.changed ? `テンポを変更：${response.result.bpm} BPM` : `テンポは上限です：${response.result.bpm} BPM`;
    } else {
      result.textContent = response?.ok ? response.result : `操作失敗：${response?.error || "応答不正"}`;
    }
  } catch (_) {
    result.textContent = "対象拡張に接続できません。";
  }
});
