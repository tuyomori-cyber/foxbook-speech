const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function main() {
  const root = path.join(__dirname, "../assistant-ui/exchange-probe/target");
  const definition = JSON.parse(fs.readFileSync(path.join(root, "commands.json"), "utf8"));
  let receive;
  const browser = { runtime: {
    getURL(name) { assert.equal(name, "commands.json"); return "moz-extension://dummy/commands.json"; },
    onMessageExternal: { addListener(fn) { receive = fn; } }
  } };
  const fetch = async (url) => ({ ok: url === "moz-extension://dummy/commands.json", async json() { return definition; } });
  vm.runInNewContext(fs.readFileSync(path.join(root, "background.js"), "utf8"), { browser, fetch, Promise, Object, Array });
  const trusted = { id: "foxbook-exchange-manager@foxbook.example" };
  const other = { id: "untrusted@example.invalid" };
  assert.equal((await receive({ version: 1, type: "getCommands" }, other)).error, "UNAUTHORIZED");
  const reply = await receive({ version: 1, type: "getCommands" }, trusted);
  assert.equal(reply.ok, true);
  assert.equal(reply.definition.appId, "dummy_metronome");
  assert.equal((await receive({ version: 1, type: "execute", commandId: "preview_tempo_increase" }, trusted)).ok, true);
  for (const request of [
    { version: 1, type: "execute", commandId: "unknown" },
    { version: 1, type: "execute", commandId: "preview_tempo_increase", extra: 1 },
    { version: 2, type: "getCommands" }, null
  ]) assert.equal((await receive(request, trusted)).error, "INVALID_REQUEST");
  process.stdout.write("assistant exchange probe: OK\n");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
