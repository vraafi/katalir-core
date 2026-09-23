@echo off
REM FASE 5: Lighthouse a11y MOBILE (ulang setelah perbaikan label tema kanvas).
setlocal
cd /d C:\Users\user\Proyek_AI\nexus-frontend
set COMMON=--only-categories=accessibility --chrome-flags="--headless=new --no-sandbox" --output=json --quiet

call npx --yes lighthouse http://localhost:3000/builder %COMMON% --output-path="%TEMP%\lhfm2_builder.json"
call npx --yes lighthouse http://localhost:3000/settings %COMMON% --output-path="%TEMP%\lhfm2_settings.json"
call npx --yes lighthouse http://localhost:3000/         %COMMON% --output-path="%TEMP%\lhfm2_root.json"
echo BATCH_SELESAI