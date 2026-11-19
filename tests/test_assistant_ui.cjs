const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

async function main() {
  let listener;
  const values = {};
  const browser = {
    runtime: {
      getURL: (name) => `moz-extension://test/${name}`,
      onMessage: { addListener(fn) { listener = fn; } }
    },
    storage: { local: {
      async get(defaults) { return { ...defaults, ...values }; },
      async set(update) { Object.assign(values, update); }
    } }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../assistant-ui/background.js"), "utf8"), { browser });
  const send = (message, url) => listener(message, { url });
  const preview = "moz-extension://test/preview.html";
  assert.equal((await send({ type: "getPreviewState" }, "https://example.com/")).state, "disconnected");
  assert.equal((await send({ type: "setPreviewState", state: "waiting" }, "https://example.com/")), undefined);
  assert.equal((await send({ type: "setPreviewState", state: "waiting" }, preview)).ok, true);
  assert.equal((await send({ type: "getPreviewState" }, "https://example.org/")).state, "waiting");
  assert.equal((await send({ type: "setPreviewState", state: "invented" }, preview)).ok, false);
  assert.equal((await send({ type: "getPreviewState" }, preview)).state, "waiting");
  // State stays in extension storage even if a page or the event page goes away.
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../assistant-ui/background.js"), "utf8"), { browser });
  assert.equal((await send({ type: "getPreviewState" }, preview)).state, "waiting");

  class Element {
    constructor() {
      this.listeners = {};
      this.children = [];
      this.style = { values: {}, setProperty(key, value) { this.values[key] = value; } };
      this.offsetWidth = 150;
      this.offsetHeight = 44;
    }
    setAttribute() {}
    addEventListener(type, fn) { this.listeners[type] = fn; }
    setPointerCapture() {}
    attachShadow() { this.shadow = new Element(); return this.shadow; }
    append(...elements) { this.children.push(...elements); }
  }
  const root = new Element();
  let storageListener;
  browser.storage.onChanged = { addListener(fn) { storageListener = fn; } };
  browser.runtime.sendMessage = (message) => send(message, "https://example.com/");
  const document = { documentElement: root, getElementById() { return null; }, createElement() { return new Element(); } };
  const window = { innerWidth: 800, innerHeight: 600, addEventListener() {} };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../assistant-ui/indicator.js"), "utf8"), { browser, document, window, console });
  await new Promise(setImmediate);
  const host = root.children[0];
  const panel = host.shadow.children[1];
  assert.equal(panel.textContent, "試作：呼びかけを待機中");
  storageListener({ previewState: { newValue: "error" } }, "local");
  assert.equal(panel.textContent, "試作：サービスエラー");
  panel.listeners.pointerdown({ isPrimary: true, button: 0, pointerId: 1, clientX: 20, clientY: 20, preventDefault() {} });
  panel.listeners.pointermove({ pointerId: 1, clientX: 120, clientY: 70 });
  panel.listeners.pointerup({ pointerId: 1 });
  assert.equal(host.style.values.left, "112px");
  assert.equal(host.style.values.top, "62px");
  assert.equal(values.indicatorPosition.left, 112);
  assert.equal(values.indicatorPosition.top, 62);
  process.stdout.write("assistant UI preview state: OK\n");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
