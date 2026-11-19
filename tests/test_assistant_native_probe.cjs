const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function event() {
  let listener;
  return { addListener(fn) { listener = fn; }, emit(value) { listener(value); } };
}

async function main() {
  const values = {};
  let listener;
  const port = { onMessage: event(), onDisconnect: event(), postMessage() {}, disconnect() {} };
  const browser = {
    runtime: { getURL: (p) => `moz-extension://test/${p}`, onMessage: { addListener(fn) { listener = fn; } },
      connectNative(name) { assert.equal(name, "foxbook_native_port_probe"); return port; } },
    storage: { local: { async get(key) { return { [key]: values[key] }; }, async set(update) { Object.assign(values, update); } } }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../assistant-ui/native-port-probe/background.js"), "utf8"), { browser, Date, console });
  const send = (type, url = "moz-extension://test/popup.html", durationSeconds = 300) => listener({ type, durationSeconds }, { url });
  assert.equal(await send("startObservation", "https://example.com/"), undefined);
  assert.equal((await send("startObservation")).ok, true);
  port.onMessage.emit({ version: 1, event: "ready", pid: 123 });
  await new Promise(setImmediate);
  assert.equal((await send("getObservation")).observation.status, "waiting");
  port.onMessage.emit({ version: 1, event: "delayed", pid: 456, durationSeconds: 300 });
  assert.equal((await send("getObservation")).observation.status, "waiting");
  port.onMessage.emit({ version: 1, event: "delayed", pid: 123, durationSeconds: 90 });
  assert.equal((await send("getObservation")).observation.status, "waiting");
  port.onMessage.emit({ version: 1, event: "delayed", pid: 123, durationSeconds: 300 });
  await new Promise(setImmediate);
  assert.equal((await send("getObservation")).observation.status, "received");
  port.onDisconnect.emit();
  await new Promise(setImmediate);
  assert.equal((await send("getObservation")).observation.status, "received_disconnected");
  process.stdout.write("assistant native port probe: OK\n");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
