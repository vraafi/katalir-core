// Probe repo via GitHub API. Prints one compact line per repo so a table can
// be built without hand-copying. Token comes from env GITHUB_TOKEN if set
// (read from .env, never echoed) to avoid the 60/hr anonymous rate limit.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$token = $env:GITHUB_TOKEN
if (-not $token) {
  $line = Get-Content .env -ErrorAction SilentlyContinue | Where-Object { $_ -match '^GITHUB_TOKEN=' } | Select-Object -First 1
  if ($line) { $token = ($line -split '=', 2)[1].Trim() }
}
$headers = @{ 'User-Agent' = 'katalir-gamedev-research'; 'Accept' = 'application/vnd.github+json' }
if ($token) { $headers['Authorization'] = "Bearer $token" }

$repos = @(
  'raskell-io/kage',
  'faisalishfaq2005/loopflow',
  'Flesymeb/HarnessOfHarness',
  'cline/cline',
  'anthropics/claude-code',
  'leigest519/OpenGame',
  'htdt/godogen',
  'Donchitos/Claude-Code-Game-Studios',
  'NintendaDev/unikit-ai',
  'Roblox/studio-rust-mcp-server',
  'krazyjakee/MoGen',
  'dada-x/pixelda',
  'aliboIly/Tripwire'
)

foreach ($r in $repos) {
  try {
    $resp = Invoke-RestMethod -Uri "https://api.github.com/repos/$r" -Headers $headers -TimeoutSec 25
    $lic = if ($resp.license) { $resp.license.spdx_id } else { 'NONE' }
    $pushed = $resp.pushed_at
    $age = [int]((Get-Date) - [datetime]$pushed).TotalDays
    "{0}`tFOUND`t{1}`t{2}`t{3}`t{4}`t{5}" -f $r, $resp.stargazers_count, $lic, $resp.language, $pushed, $age
  } catch {
    $code = $_.Exception.Response.StatusCode.value__
    "{0}`tMISSING/ERR({1})" -f $r, $code
  }
}
