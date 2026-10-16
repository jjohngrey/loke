const { app, BrowserWindow, shell, session } = require("electron");
const allowedResources = new Set(["nba.uth.tmc.edu"]);

function isAppUrl(value) {
  try {
    return new URL(value).origin === "http://127.0.0.1:3000";
  } catch {
    return false;
  }
}

function canUsePermission(webContents, permission, requestingUrl) {
  return ["media", "clipboard-sanitized-write"].includes(permission) &&
    isAppUrl(webContents?.getURL()) && isAppUrl(requestingUrl);
}

app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler(
    (webContents, permission, callback, details) => {
      callback(canUsePermission(webContents, permission, details.requestingUrl));
    },
  );
  session.defaultSession.setPermissionCheckHandler(
    (webContents, permission, requestingOrigin, details) =>
      isAppUrl(requestingOrigin) &&
      canUsePermission(webContents, permission, details.requestingUrl || requestingOrigin),
  );
  const window = new BrowserWindow({
    width: 1320,
    height: 900,
    minWidth: 900,
    minHeight: 700,
    title: "Loke",
    titleBarStyle: "hiddenInset",
    backgroundColor: "#f2f5f2",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const parsed = new URL(url);
      if (parsed.protocol === "https:" && allowedResources.has(parsed.hostname))
        shell.openExternal(url);
    } catch {}
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith("http://127.0.0.1:3000/")) event.preventDefault();
  });
  window.loadURL("http://127.0.0.1:3000");
});
app.on("window-all-closed", () => app.quit());
