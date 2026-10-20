const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const { existsSync } = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

const PROJECT_ROOT = path.resolve(__dirname, "..");

function resolveDevPython() {
  if (process.env.AOV_PYTHON) return process.env.AOV_PYTHON;
  const venvPython = path.join(PROJECT_ROOT, ".venv", "bin", "python");
  if (existsSync(venvPython)) return venvPython;
  for (const candidate of ["python3", "python"]) {
    const probe = spawnSync(candidate, ["--version"], { stdio: "ignore" });
    if (!probe.error && probe.status === 0) return candidate;
  }
  return "python3";
}

function resolveBridgeLaunch() {
  if (app.isPackaged) {
    const home = app.getPath("userData");
    const exeName = process.platform === "win32" ? "aov-bridge.exe" : "aov-bridge";
    return {
      command: path.join(process.resourcesPath, "bridge", exeName),
      args: [],
      cwd: home,
      env: {
        ...process.env,
        PYTHONUTF8: "1",
        AOV_PACKER_HOME: home,
        AOV_AUTOPACKER_SETTINGS: path.join(home, "settings.json"),
        AOV_VALIDATION_RULE_CACHE: path.join(home, "rules", "cached_rule_set.json"),
      },
    };
  }
  return {
    command: resolveDevPython(),
    args: [path.join(PROJECT_ROOT, "electron_bridge.py")],
    cwd: PROJECT_ROOT,
    env: { ...process.env, PYTHONUTF8: "1" },
  };
}

class PythonBridge {
  constructor() {
    this.sequence = 0;
    this.pending = new Map();
    this.process = null;
  }

  start() {
    if (this.process) return;
    const launch = resolveBridgeLaunch();
    this.process = spawn(launch.command, launch.args, {
      cwd: launch.cwd,
      env: launch.env,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });

    const lines = readline.createInterface({ input: this.process.stdout });
    lines.on("line", (line) => this.onLine(line));
    this.process.stderr.on("data", (chunk) => {
      const message = chunk.toString("utf8").trim();
      if (message) this.broadcast("bridge-error", { message });
    });
    this.process.on("error", (error) => {
      this.process = null;
      this.failAll(error);
    });
    this.process.on("exit", (code) => {
      this.process = null;
      this.failAll(new Error(`Python bridge stopped with code ${code ?? "unknown"}`));
    });
  }

  onLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      this.broadcast("bridge-error", { message: line });
      return;
    }
    const item = this.pending.get(message.id);
    if (message.type === "event") {
      this.broadcast("bridge-event", message);
      return;
    }
    if (!item || message.type !== "response") return;
    this.pending.delete(message.id);
    if (message.ok) item.resolve(message.result);
    else item.reject(new Error(message.error || "Python operation failed"));
  }

  request(command, payload = {}) {
    this.start();
    const id = `${Date.now()}-${++this.sequence}`;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      try {
        this.process.stdin.write(`${JSON.stringify({ id, command, payload })}\n`, "utf8");
      } catch (error) {
        this.pending.delete(id);
        reject(error);
      }
    });
  }

  broadcast(channel, payload) {
    for (const window of BrowserWindow.getAllWindows()) {
      if (!window.isDestroyed()) window.webContents.send(channel, payload);
    }
  }

  failAll(error) {
    for (const item of this.pending.values()) item.reject(error);
    this.pending.clear();
  }

  stop() {
    if (!this.process) return;
    this.process.stdin.end();
    this.process.kill();
    this.process = null;
  }
}

const bridge = new PythonBridge();

function createWindow() {
  const window = new BrowserWindow({
    width: 1240,
    height: 820,
    minWidth: 980,
    minHeight: 680,
    show: false,
    backgroundColor: "#f4f5f3",
    icon: path.join(PROJECT_ROOT, "icon.ico"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.removeMenu();
  window.loadFile(path.join(__dirname, "index.html"));
  window.once("ready-to-show", () => window.show());
}

app.whenReady().then(() => {
  ipcMain.handle("bridge:request", (_event, command, payload) => bridge.request(command, payload));
  ipcMain.handle("dialog:select-directory", async () => {
    const result = await dialog.showOpenDialog({ properties: ["openDirectory"] });
    return result.canceled ? "" : result.filePaths[0] || "";
  });
  ipcMain.handle("shell:open-path", async (_event, target) => {
    if (typeof target !== "string" || !path.isAbsolute(target)) {
      throw new Error("A local absolute path is required");
    }
    const error = await shell.openPath(target);
    if (error) throw new Error(error);
    return true;
  });
  bridge.start();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => bridge.stop());
