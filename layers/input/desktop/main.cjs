const { app, BrowserWindow, shell, session } = require("electron");
function localOrigin(url) {
  try {
    return new URL(url).origin === "http://127.0.0.1:3000";
  } catch {
    return false;
  }
}
const allowedResources = new Set(["nba.uth.tmc.edu"]);
app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler(
    (webContents, permission, callback) => {
      callback(localOrigin(webContents.getURL()) && permission === "media");
    },
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
    if (!localOrigin(url)) event.preventDefault();
  });
  window.loadURL("http://127.0.0.1:3000");
});
app.on("window-all-closed", () => app.quit());
