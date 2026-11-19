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
  let pendingExecute;
  let failExecute = false;
  let holdDefinition = false;
  let timers = [];
  const setTimeout = (fn) => { const timer = { fn }; timers.push(timer); return timer; };
  const clearTimeout = (timer) => { timers = timers.filter((item) => item !== timer); };
  const browser = { runtime: { async sendMessage(id, message) {
    sent.push({ id, message });
    if (message.type === "getCommands" && holdDefinition) return new Promise(() => {});
    if (message.type === "getCommands") return { ok: true, definition: { version: 1, appId: "the_session_tools", name: "THE SESSION TOOLS", commands: [{ id: "tempo.increase.small", label: "テンポを5上げる" }] } };
    if (failExecute) throw new Error("disconnected");
    return new Promise((resolve) => { pendingExecute = resolve; });
  } } };
  const document = { querySelector(selector) { return nodes[selector.slice(1)]; } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../assistant-ui/exchange-probe/manager/popup.js"), "utf8"), { browser, document, setTimeout, clearTimeout });
  nodes.target.value = "session";
  nodes.target.change();
  await nodes.get.click();
  assert.equal(nodes.execute.disabled, false);
  assert.match(nodes.result.textContent, /THE SESSION TOOLS/);
  const first = nodes.execute.click();
  assert.equal(nodes.execute.disabled, true);
  await nodes.execute.click();
  assert.equal(sent.filter((item) => item.message.type === "execute").length, 1);
  pendingExecute({ ok: true, result: { bpm: 115, changed: true } });
  await first;
  assert.equal(sent.at(-1).id, "the-session-tools@example.invalid");
  assert.equal(sent.at(-1).message.commandId, "tempo.increase.small");
  assert.equal(nodes.result.textContent, "テンポを変更：115 BPM");
  failExecute = true;
  await nodes.execute.click();
  assert.match(nodes.result.textContent, /実行されたか確認/);
  assert.equal(sent.filter((item) => item.message.type === "execute").length, 2);
  assert.equal(nodes.execute.disabled, true);
  failExecute = false;
  await nodes.get.click();
  const timed = nodes.execute.click();
  const lateResponse = pendingExecute;
  timers[0].fn();
  await timed;
  assert.match(nodes.result.textContent, /時間切れ/);
  assert.equal(nodes.execute.disabled, true);
  lateResponse({ ok: true, result: { bpm: 120, changed: true } });
  await Promise.resolve();
  assert.match(nodes.result.textContent, /時間切れ/);
  assert.equal(sent.filter((item) => item.message.type === "execute").length, 3);
  holdDefinition = true;
  const timedGet = nodes.get.click();
  timers[0].fn();
  await timedGet;
  assert.match(nodes.result.textContent, /接続できません/);
  assert.equal(nodes.execute.disabled, true);
  nodes.target.value = "dummy";
  nodes.target.change();
  assert.equal(nodes.execute.disabled, true);
  process.stdout.write("assistant exchange manager: OK\n");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
