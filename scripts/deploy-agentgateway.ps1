# Placeholder-free deployment checklist for agentgateway.
# Requires a separately created Railway service and a verified image/config.
param([string]$ServiceUrl)
if (-not $ServiceUrl) { throw 'Pass the verified agentgateway Railway service URL.' }
Write-Host "TARGET=$ServiceUrl"
Write-Host 'Verify /health, authenticated /servers, /servers/{id}/tools, and one /call before enabling production.'
