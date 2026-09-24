@echo off
REM FASE 6 lanjutan -- ukur PERF satu rute pada server statis (port 3100) supaya
REM dev server di :3000 tidak perlu dimatikan dan tiap iterasi bisa diukur ~40s.
REM Pakai: scripts\perf-iterate.cmd <route> [preset]
REM   contoh: scripts\perf-iterate.cmd / mobile
setlocal
cd /d C:\Users\user\Proyek_AI\nexus-frontend
set BASE_URL=http://localhost:3100
set "ONLY_ROUTE=%1"
if not "%2"=="" set "ONLY_PRESET=%2"
node scripts\final-lighthouse.mjs
