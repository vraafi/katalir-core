@echo off
REM FASE 5: Lighthouse a11y -- 5 rute x 2 preset, satu perintah per rute.
REM Kenapa .cmd eksplisit: memanggil `npx lighthouse` lewat node child process
REM atau PowerShell bertingkat membuat tanda kutip `--chrome-flags="..."` hilang,
REM sehingga seluruh batch gagal ("bad option: --output=json"). Di file .cmd
REM tanda kutip diteruskan apa adanya.
setlocal
cd /d C:\Users\user\Proyek_AI\nexus-frontend
set COMMON=--only-categories=accessibility --chrome-flags="--headless=new --no-sandbox" --output=json --quiet

call npx --yes lighthouse http://localhost:3000/          --preset=desktop %COMMON% --output-path="%TEMP%\lhfd_root.json"
call npx --yes lighthouse http://localhost:3000/settings  --preset=desktop %COMMON% --output-path="%TEMP%\lhfd_settings.json"
call npx --yes lighthouse http://localhost:3000/billing   --preset=desktop %COMMON% --output-path="%TEMP%\lhfd_billing.json"
call npx --yes lighthouse http://localhost:3000/help      --preset=desktop %COMMON% --output-path="%TEMP%\lhfd_help.json"
call npx --yes lighthouse http://localhost:3000/builder   --preset=desktop %COMMON% --output-path="%TEMP%\lhfd_builder.json"

call npx --yes lighthouse http://localhost:3000/          %COMMON% --output-path="%TEMP%\lhfm_root.json"
call npx --yes lighthouse http://localhost:3000/settings  %COMMON% --output-path="%TEMP%\lhfm_settings.json"
call npx --yes lighthouse http://localhost:3000/billing   %COMMON% --output-path="%TEMP%\lhfm_billing.json"
call npx --yes lighthouse http://localhost:3000/help      %COMMON% --output-path="%TEMP%\lhfm_help.json"
call npx --yes lighthouse http://localhost:3000/builder   %COMMON% --output-path="%TEMP%\lhfm_builder.json"

echo BATCH_SELESAI