const { contextBridge, ipcRenderer } = require("electron");

const allowedCommands = new Set([
  "bootstrap",
  "save_settings",
  "check_backend",
  "check_ftp",
  "pack",
  "inspect_archive",
  "publish",
  "retry_sync",
]);

contextBridge.exposeInMainWorld("aov", {
  request(command, payload = {}) {
    if (!allowedCommands.has(command)) {
      return Promise.reject(new Error(`Unsupported command: ${command}`));
    }
    return ipcRenderer.invoke("bridge:request", command, payload);
  },
  selectDirectory: () => ipcRenderer.invoke("dialog:select-directory"),
  openPath: (target) => ipcRenderer.invoke("shell:open-path", target),
  onBridgeEvent(callback) {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("bridge-event", listener);
    return () => ipcRenderer.removeListener("bridge-event", listener);
  },
  onBridgeError(callback) {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("bridge-error", listener);
    return () => ipcRenderer.removeListener("bridge-error", listener);
  },
});
