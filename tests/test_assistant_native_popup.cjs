const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function main() {
  const nodes = Object.fromEntries(["result", "start", "stop", "duration"].map((name) => [name, {
    textContent: "", value: name === "duration" ? "300" : "", disabled: false,
    addEventListener(type, fn) { this[type] = fn; }
  }]));
  let observation = { status: "idle" };
  let portPresent = false;
  let onChanged;
  const browser = {
    storage: { onChanged: { addListener(fn) { onChanged = fn; } } },
    runtime: { async sendMessage(message) {
      if (message.type === "getObservation") return { observation: { ...observation }, portPresent };
      if (message.type === "startObservation") {
        observation = { status: "connecting", durationSeconds: message.durationSeconds };
        portPresent = true;
        return { ok: true };
      }
      return { ok: true };
    } }
  };
  const document = { querySelector(selector) { return nodes[selector.slice(1)]; } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../assistant-ui/native-port-probe/popup.js"), "utf8"), { browser, document, Number });
  await new Promise(setImmediate);
  await nodes.start.click();
  assert.equal(nodes.result.textContent, "接続中");
  observation = { status: "waiting", durationSeconds: 300, pid: 123 };
  onChanged({ nativePortObservation: { newValue: observation } }, "local");
  await new Promise(setImmediate);
  assert.match(nodes.result.textContent, /接続中・遅延イベント待ち \/ Host PID: 123/);
  assert.equal(nodes.stop.disabled, false);
  process.stdout.write("assistant native popup: OK\n");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
