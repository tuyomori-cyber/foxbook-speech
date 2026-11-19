const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function main() {
  const nodes = Object.fromEntries(["target", "get", "execute", "result"].map((name) => [name, {
    value: name === "target" ? "dummy" : "", textContent: "", disabled: false,
    addEventListener(type, fn) { this[type] = fn; }
  }]));
  const sent = [];
  const browser = { runtime: { async sendMessage(id, message) {
    sent.push({ id, message });
    if (message.type === "getCommands") return { ok: true, definition: { version: 1, appId: "the_session_tools", name: "THE SESSION TOOLS", commands: [{ id: "tempo.increase.small", label: "テンポを5上げる" }] } };
    return { ok: true, result: { bpm: 115, changed: true } };
  } } };
  const document = { querySelector(selector) { return nodes[selector.slice(1)]; } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../assistant-ui/exchange-probe/manager/popup.js"), "utf8"), { browser, document });
  nodes.target.value = "session";
  nodes.target.change();
  await nodes.get.click();
  assert.equal(nodes.execute.disabled, false);
  assert.match(nodes.result.textContent, /THE SESSION TOOLS/);
  await nodes.execute.click();
  assert.equal(sent.at(-1).id, "the-session-tools@example.invalid");
  assert.equal(sent.at(-1).message.commandId, "tempo.increase.small");
  assert.equal(nodes.result.textContent, "テンポを変更：115 BPM");
  nodes.target.value = "dummy";
  nodes.target.change();
  assert.equal(nodes.execute.disabled, true);
  process.stdout.write("assistant exchange manager: OK\n");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
