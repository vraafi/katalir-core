import { execFileSync } from "node:child_process";

let listener = "";
try {
  listener = execFileSync("powershell.exe", ["-NoProfile", "-Command", "Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"], { encoding: "utf8" }).trim();
} catch {
  // Get-NetTCPConnection exits non-zero when no listener exists: port is free.
  listener = "";
}
if (listener) {
  console.error("BLOCKED: next dev/port 3000 masih hidup (PID " + listener + "). Hentikan dev sebelum build agar .next tidak korup.");
  process.exit(1);
}
console.log("BUILD_PRECHECK=ok: port 3000 bebas.");
