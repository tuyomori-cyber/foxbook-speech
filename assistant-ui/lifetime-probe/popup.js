/* global browser */
const result = document.querySelector("#result");
const button = document.querySelector("#start");

async function refresh() {
  try {
    const { observation, alarmScheduled } = await browser.runtime.sendMessage({ type: "getObservation" });
    if (!observation) result.textContent = "まだ予約していません。";
    else if (observation.status === "fired") result.textContent = `処理を実行しました：${new Date(observation.firedAt).toLocaleTimeString()}`;
    else if (observation.status === "scheduled" && alarmScheduled) result.textContent = "処理を予約しました。";
    else result.textContent = "予約が失われたか失敗しました。もう一度予約してください。";
  } catch (_) {
    result.textContent = "検証状態を取得できません。";
  }
}

button.addEventListener("click", async () => {
  button.disabled = true;
  try {
    const response = await browser.runtime.sendMessage({ type: "scheduleObservation" });
    if (!response?.ok) result.textContent = "予約できませんでした。";
    else await refresh();
  } catch (_) {
    result.textContent = "予約できませんでした。";
  } finally {
    button.disabled = false;
  }
});
refresh();
