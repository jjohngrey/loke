const { app, BrowserWindow, shell, session } = require("electron");
const allowedResources = new Set(["nba.uth.tmc.edu"]);
app.whenReady().then(() => {
  session.defaultSession.setPermissionRequestHandler(
    (webContents, permission, callback) => {
      callback(
        webContents.getURL().startsWith("http://127.0.0.1:3000") &&
          permission === "media",
      );
    },
  );
  const window = new BrowserWindow({
    width: 1320,
    height: 900,
    minWidth: 900,
    minHeight: 700,
    title: "Loke",
    backgroundColor: "#F5F5F7",
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
