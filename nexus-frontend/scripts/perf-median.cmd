@echo off
REM FASE 6 final -- ukur SATU rute beberapa kali lalu cetak skor tiap run.
REM Kenapa bukan sekali: mesin ini memberi derau besar (mainthread 4.0s vs 22s
REM antar run), jadi satu angka tidak bisa dipakai untuk klaim. Median dihitung
REM dari output yang dikumpulkan di sini.
REM Pakai: scripts\perf-median.cmd <route> <preset> <runs>
setlocal
cd /d C:\Users\user\Proyek_AI\nexus-frontend
set BASE_URL=http://localhost:3100
set "ONLY_ROUTE=%1"
set "ONLY_PRESET=%2"
set RUNS=%3
if "%RUNS%"=="" set RUNS=3
echo ==== PERF_MEDIAN route=%1 preset=%2 runs=%RUNS% (server statis :3100) ====
for /L %%i in (1,1,%RUNS%) do (
  echo ---- RUN %%i ----
  node scripts\final-lighthouse.mjs
)
