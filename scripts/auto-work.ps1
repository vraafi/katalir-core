param([int]$MaxTasks = 10)
Write-Host '=== Auto-Work Katalir ===' -ForegroundColor Cyan
Write-Host 'Baca AGENT_PLAYBOOK.md, lalu kerjakan TODO.md teratas.' -ForegroundColor Yellow
Write-Host "Auto-lanjut sampai blocked atau maksimal $MaxTasks task." -ForegroundColor Yellow
Write-Host 'Update TODO.md, commit per task, lalu push.' -ForegroundColor Green
Write-Host 'BLOCKED perlu user action? Lapor: BLOCKED: <alasan>'
