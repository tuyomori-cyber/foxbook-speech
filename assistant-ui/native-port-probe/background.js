/* global browser */
const HOST_NAME = "foxbook_native_port_probe";
const STORAGE_KEY = "nativePortObservation";
let probePort;
let generation = 0;

async function save(observation) {
  await browser.storage.local.set({ [STORAGE_KEY]: observation });
}

browser.runtime.onMessage.addListener(async (message, sender) => {
  if (sender.url !== browser.runtime.getURL("popup.html")) return undefined;
  if (message?.type === "getObservation") {
    const saved = await browser.storage.local.get(STORAGE_KEY);
    const observation = saved[STORAGE_KEY] || { status: "idle" };
    return { observation, portPresent: Boolean(probePort) };
  }
  if (message?.type === "startObservation") {
    if (![90, 300].includes(message.durationSeconds)) return { ok: false, reason: "invalid_duration" };
    if (probePort) return { ok: false, reason: "already_running" };
    const current = ++generation;
    const observation = { status: "connecting", startedAt: Date.now(), durationSeconds: message.durationSeconds };
    await save(observation);
    try {
      const port = browser.runtime.connectNative(HOST_NAME);
      probePort = port;
      port.onMessage.addListener((event) => {
        if (current !== generation || !event || event.version !== 1) return;
        if (event.event === "ready" && Number.isInteger(event.pid)) {
          observation.status = "waiting";
          observation.pid = event.pid;
          observation.readyAt = Date.now();
          save({ ...observation }).catch(console.error);
        } else if (event.event === "delayed" && event.pid === observation.pid && event.durationSeconds === observation.durationSeconds) {
          observation.status = "received";
          observation.receivedAt = Date.now();
          save({ ...observation }).catch(console.error);
        }
      });
      port.onDisconnect.addListener(() => {
        if (current !== generation) return;
        probePort = undefined;
        observation.disconnectedAt = Date.now();
        observation.status = observation.receivedAt ? "received_disconnected" : "disconnected";
        observation.error = browser.runtime.lastError?.message || "";
        save({ ...observation }).catch(console.error);
      });
      port.postMessage({ version: 1, action: "start", durationSeconds: observation.durationSeconds });
      return { ok: true };
    } catch (error) {
      probePort = undefined;
      observation.status = "error";
      observation.error = String(error);
      await save(observation);
      return { ok: false };
    }
  }
  if (message?.type === "stopObservation") {
    const port = probePort;
    if (!port) return { ok: false };
    ++generation;
    probePort = undefined;
    port.disconnect();
    const saved = await browser.storage.local.get(STORAGE_KEY);
    await save({ ...(saved[STORAGE_KEY] || {}), status: "stopped", stoppedAt: Date.now() });
    return { ok: true };
  }
  return undefined;
});
