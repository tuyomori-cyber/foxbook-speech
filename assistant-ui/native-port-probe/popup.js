/* global browser */
const result = document.querySelector("#result");
const start = document.querySelector("#start");
const stop = document.querySelector("#stop");
const duration = document.querySelector("#duration");

async function refresh() {
  try {
    const { observation: o, portPresent } = await browser.runtime.sendMessage({ type: "getObservation" });
    const names = { idle: "未開始", connecting: "接続中", waiting: "接続中・遅延イベント待ち", received: `${o.durationSeconds}秒後のイベントを受信`, received_disconnected: "イベント受信後に切断", disconnected: "イベント前に切断", stopped: "接続を終了", error: "接続エラー" };
    const stale = !portPresent && ["connecting", "waiting", "received"].includes(o.status);
    result.textContent = `${names[o.status] || "状態不明"}${stale ? "（背景処理の再起動等によりPort不在）" : ""}${o.pid ? ` / Host PID: ${o.pid}` : ""}${o.error ? ` / ${o.error}` : ""}`;
    start.disabled = portPresent;
    stop.disabled = !portPresent;
  } catch (_) {
    result.textContent = "状態を取得できません。";
  }
}

start.addEventListener("click", async () => {
  start.disabled = true;
  try { await browser.runtime.sendMessage({ type: "startObservation", durationSeconds: Number(duration.value) }); } finally { await refresh(); }
});
stop.addEventListener("click", async () => {
  try { await browser.runtime.sendMessage({ type: "stopObservation" }); } finally { await refresh(); }
});
browser.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.nativePortObservation) refresh();
});
refresh();
