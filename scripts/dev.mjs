import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const env = { ...process.env };
if (existsSync(path.join(root, ".env")))
  for (const line of readFileSync(path.join(root, ".env"), "utf8").split(
    "\n",
  )) {
    const match = line.match(/^([A-Z_]+)=(.*)$/);
    if (match) env[match[1]] ??= match[2].trim();
  }
env.SESSION_TOKEN ||= "local-demo-change-me";
env.BACKEND_URL ||= "http://127.0.0.1:8000";
const children = [];
let closing = false;
function stop(code = 0) {
  if (closing) return;
  closing = true;
  for (const child of children) {
    try {
      if (process.platform !== "win32") process.kill(-child.pid, "SIGTERM");
      else child.kill("SIGTERM");
    } catch {}
  }
  setTimeout(() => process.exit(code), 300);
}
function start(command, args) {
  const child = spawn(command, args, {
    cwd: root,
    env,
    stdio: "inherit",
    detached: process.platform !== "win32",
  });
  children.push(child);
  child.on("error", (error) => {
    console.error(error.message);
    stop(1);
  });
  child.on("exit", () => {
    if (!closing) stop();
  });
  return child;
}
async function waitFor(url) {
  for (let i = 0; i < 90; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Readiness timeout: ${url}`);
}
process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());
try {
  if (!existsSync(path.join(root, ".venv/bin/python")))
    throw new Error("Run uv sync before starting Loke.");
  start(path.join(root, ".venv/bin/python"), [
    "-m",
    "uvicorn",
    "loke_intelligence.app:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
  ]);
  start("npm", ["run", "dev", "--workspace", "@loke/input-web"]);
  await waitFor("http://127.0.0.1:8000/healthz");
  await waitFor("http://127.0.0.1:3000");
  console.log(
    "Loke is ready at http://127.0.0.1:3000. Ctrl+C stops both services.",
  );
  if (process.argv.includes("--desktop"))
    start("npm", ["run", "start", "--workspace", "@loke/input-desktop"]);
} catch (error) {
  console.error(error.message);
  stop(1);
}
