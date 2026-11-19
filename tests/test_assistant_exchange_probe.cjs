const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function main() {
  const root = path.join(__dirname, "../assistant-ui/exchange-probe/target");
  const definition = JSON.parse(fs.readFileSync(path.join(root, "commands.json"), "utf8"));
  let receive;
  let internal;
  const store = {};
  let timers = [];
  const setTimeout = (fn) => { timers.push(fn); };
  const browser = { action: { onClicked: { addListener() {} } }, tabs: {}, storage: { local: { async get() { return { ...store }; }, async set(value) { Object.assign(store, value); } } }, runtime: {
    id: "foxbook-exchange-target@foxbook.example",
    onMessage: { addListener(fn) { internal = fn; } },
    getURL(name) { return `moz-extension://dummy/${name}`; },
    onMessageExternal: { addListener(fn) { receive = fn; } }
  } };
  const fetch = async (url) => ({ ok: url === "moz-extension://dummy/commands.json", async json() { return definition; } });
  vm.runInNewContext(fs.readFileSync(path.join(root, "background.js"), "utf8"), { browser, fetch, Promise, Object, Array, Date, setTimeout });
  const trusted = { id: "foxbook-exchange-manager@foxbook.example" };
  const other = { id: "untrusted@example.invalid" };
  assert.equal((await receive({ version: 1, type: "getCommands" }, other)).error, "UNAUTHORIZED");
  const reply = await receive({ version: 1, type: "getCommands" }, trusted);
  assert.equal(reply.ok, true);
  assert.equal(reply.definition.appId, "dummy_metronome");
  assert.equal((await receive({ version: 1, type: "execute", commandId: "preview_tempo_increase" }, trusted)).ok, true);
  const own = { id: browser.runtime.id, url: "moz-extension://dummy/control.html" };
  await internal({ type: "reset" }, own);
  await internal({ type: "setMode", mode: "delay_response" }, own);
  const delayed = receive({ version: 1, type: "execute", commandId: "preview_tempo_increase" }, trusted);
  while (!timers.length) await new Promise((resolve) => setImmediate(resolve));
  assert.equal(store.operations.length, 1);
  timers.shift()();
  assert.equal((await delayed).ok, true);
  await internal({ type: "reset" }, own);
  await internal({ type: "setMode", mode: "delay_execute" }, own);
  const late = receive({ version: 1, type: "execute", commandId: "preview_tempo_increase" }, trusted);
  while (!timers.length) await new Promise((resolve) => setImmediate(resolve));
  assert.equal(store.operations.length, 0);
  timers.shift()();
  assert.equal((await late).ok, true);
  assert.equal(store.operations.length, 1);
  await internal({ type: "setMode", mode: "no_response" }, own);
  receive({ version: 1, type: "execute", commandId: "preview_tempo_increase" }, trusted);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(store.operations.length, 1);
  await internal({ type: "setMode", mode: "normal" }, own);
  for (const request of [
    { version: 1, type: "execute", commandId: "unknown" },
    { version: 1, type: "execute", commandId: "preview_tempo_increase", extra: 1 },
    { version: 2, type: "getCommands" }, null
  ]) assert.equal((await receive(request, trusted)).error, "INVALID_REQUEST");
  process.stdout.write("assistant exchange probe: OK\n");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
