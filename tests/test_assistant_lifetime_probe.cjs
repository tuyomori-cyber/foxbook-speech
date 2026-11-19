const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

async function main() {
  const values = {};
  let alarmListener;
  let messageListener;
  let scheduled;
  const browser = {
    runtime: { getURL: (name) => `moz-extension://probe/${name}`, onMessage: { addListener(fn) { messageListener = fn; } } },
    storage: { local: {
      async get(key) { return { [key]: values[key] }; },
      async set(update) { Object.assign(values, update); }
    } },
    alarms: {
      onAlarm: { addListener(fn) { alarmListener = fn; } },
      async get(name) { return scheduled?.name === name ? scheduled : undefined; },
      async clear() { scheduled = undefined; },
      async create(name, options) { scheduled = { name, ...options }; }
    }
  };
  const code = fs.readFileSync(path.join(__dirname, "../assistant-ui/lifetime-probe/background.js"), "utf8");
  function load() { vm.runInNewContext(code, { browser, Date }); }
  const send = (type, url = "moz-extension://probe/popup.html") => messageListener({ type }, { url });
  load();
  assert.equal(await send("scheduleObservation", "https://example.com/"), undefined);
  assert.equal((await send("scheduleObservation")).ok, true);
  assert.equal((await send("getObservation")).observation.status, "scheduled");
  assert.equal((await send("getObservation")).alarmScheduled, true);
  // Simulate an event page restarting while there is no popup or content script.
  load();
  await alarmListener({ name: "unrelated" });
  assert.equal(values.backgroundObservation.status, "scheduled");
  await alarmListener({ name: "background-observation", scheduledTime: Date.now() });
  scheduled = undefined;
  assert.equal((await send("getObservation")).observation.status, "fired");
  assert.equal((await send("getObservation")).alarmScheduled, false);
  process.stdout.write("assistant lifetime probe: OK\n");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
