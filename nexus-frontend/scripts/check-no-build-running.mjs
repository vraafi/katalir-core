import { execFileSync } from "node:child_process";

const procs = execFileSync("powershell.exe", ["-NoProfile", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -match 'next(\\.js)? build|next build' } | Select-Object -ExpandProperty CommandLine"], { encoding: "utf8" }).trim();
if (procs) {
  console.error("BLOCKED: build terdeteksi masih berjalan. Tunggu build selesai sebelum menjalankan dev; .next tidak boleh ditulis bersamaan.");
  process.exit(1);
}
console.log("DEV_PRECHECK=ok: tidak ada proses build aktif.");
