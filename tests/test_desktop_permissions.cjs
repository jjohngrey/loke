const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

async function permissionHandlers() {
  let request;
  let check;
  const electron = {
    app: { whenReady: () => Promise.resolve(), on() {} },
    BrowserWindow: class {
      webContents = { setWindowOpenHandler() {}, on() {} };
      loadURL() {}
    },
    session: { defaultSession: {
      setPermissionRequestHandler(handler) { request = handler; },
      setPermissionCheckHandler(handler) { check = handler; },
    } },
  };
  vm.runInNewContext(readFileSync(path.join(__dirname, "../layers/input/desktop/main.cjs"), "utf8"), {
    require: () => electron, URL,
  });
  await Promise.resolve();
  return { request, check };
}

test("desktop grants clipboard writes and existing media access only to the app origin", async () => {
  const { request, check } = await permissionHandlers();
  const webContents = { getURL: () => "http://127.0.0.1:3000/" };
  const details = { requestingUrl: "http://127.0.0.1:3000/chat", isMainFrame: true };
  for (const permission of ["clipboard-sanitized-write", "media"]) {
    let granted;
    request(webContents, permission, (value) => { granted = value; }, details);
    assert.equal(granted, true, permission);
    assert.equal(check(webContents, permission, "http://127.0.0.1:3000", details), true);
  }
});

test("desktop denies clipboard reads, unrelated permissions and foreign or malformed origins", async () => {
  const { request, check } = await permissionHandlers();
  const appUrl = "http://127.0.0.1:3000/";
  const cases = [
    [appUrl, appUrl, "clipboard-read"],
    [appUrl, appUrl, "deprecated-sync-clipboard-read"],
    [appUrl, appUrl, "notifications"],
    ...["http://127.0.0.1:30001", "https://127.0.0.1:3000", "https://example.com", "invalid"].flatMap((url) => [
      [appUrl, url, "clipboard-sanitized-write"],
      [url, appUrl, "clipboard-sanitized-write"],
    ]),
  ];
  for (const [topUrl, requestingUrl, permission] of cases) {
    const webContents = { getURL: () => topUrl };
    const details = { requestingUrl, isMainFrame: topUrl === requestingUrl };
    let granted;
    request(webContents, permission, (value) => { granted = value; }, details);
    assert.equal(granted, false, `${permission}: ${topUrl}, ${requestingUrl}`);
    assert.equal(check(webContents, permission, requestingUrl, details), false);
  }
  assert.equal(check(null, "clipboard-sanitized-write", appUrl, {}), false);
  assert.equal(check({ getURL: () => appUrl }, "clipboard-sanitized-write", "https://example.com", { requestingUrl: appUrl }), false);
});
