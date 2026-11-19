/* global browser */
const state = document.querySelector("#state");
const result = document.querySelector("#result");

async function initialize() {
  try {
    const current = await browser.runtime.sendMessage({ type: "getPreviewState" });
    state.value = current.state;
  } catch (_) {
    result.textContent = "試作の状態を取得できません。";
  }
}

state.addEventListener("change", async () => {
  try {
    const response = await browser.runtime.sendMessage({ type: "setPreviewState", state: state.value });
    result.textContent = response?.ok ? "表示を変更しました。" : "表示を変更できません。";
  } catch (_) {
    result.textContent = "表示を変更できません。";
  }
});
initialize();
