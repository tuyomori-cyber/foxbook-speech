/* global browser */
const ALARM_NAME = "background-observation";
const STORAGE_KEY = "backgroundObservation";

browser.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== ALARM_NAME) return;
  const saved = await browser.storage.local.get(STORAGE_KEY);
  const previous = saved[STORAGE_KEY];
  if (previous?.status !== "scheduled") return;
  await browser.storage.local.set({ [STORAGE_KEY]: {
    ...previous, status: "fired", firedAt: Date.now(), scheduledTime: alarm.scheduledTime
  } });
});

browser.runtime.onMessage.addListener(async (message, sender) => {
  if (sender.url !== browser.runtime.getURL("popup.html")) return undefined;
  if (message?.type === "getObservation") {
    const saved = await browser.storage.local.get(STORAGE_KEY);
    const alarm = await browser.alarms.get(ALARM_NAME);
    return { observation: saved[STORAGE_KEY] || null, alarmScheduled: Boolean(alarm) };
  }
  if (message?.type === "scheduleObservation") {
    const scheduledAt = Date.now();
    await browser.alarms.clear(ALARM_NAME);
    await browser.storage.local.set({ [STORAGE_KEY]: { status: "scheduled", scheduledAt } });
    try {
      await browser.alarms.create(ALARM_NAME, { delayInMinutes: 0.5 });
      return { ok: true };
    } catch (_) {
      await browser.storage.local.set({ [STORAGE_KEY]: { status: "error", scheduledAt } });
      return { ok: false };
    }
  }
  return undefined;
});
