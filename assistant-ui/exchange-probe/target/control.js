/* global browser */
const mode = document.querySelector("#mode");
const status = document.querySelector("#status");
const count = document.querySelector("#count");
const operations = document.querySelector("#operations");
function render(state) {
  mode.value = state.mode;
  count.textContent = `実行回数：${state.operations.length}`;
  operations.replaceChildren(...state.operations.map((time) => {
    const item = document.createElement("li");
    item.textContent = new Date(time).toLocaleString();
    return item;
  }));
}
async function send(message) {
  try { render(await browser.runtime.sendMessage(message)); status.textContent = ""; }
  catch (_) { status.textContent = "試験設定の読み書きに失敗しました。"; }
}
mode.addEventListener("change", () => send({ type: "setMode", mode: mode.value }));
document.querySelector("#reset").addEventListener("click", () => send({ type: "reset" }));
browser.storage.onChanged.addListener((changes, area) => { if (area === "local") send({ type: "getState" }); });
send({ type: "getState" });
