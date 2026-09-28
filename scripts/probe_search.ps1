$queries = @(
  'unity claude code plugin',
  'godot mcp',
  'phaser mcp',
  'game engine mcp server',
  'roblox mcp'
)
foreach ($q in $queries) {
  "=== QUERY: $q ==="
  try {
    $enc = [uri]::EscapeDataString($q)
    $res = Invoke-RestMethod -Uri "https://api.github.com/search/repositories?q=$enc&sort=stars&order=desc&per_page=6" -Headers $headers -TimeoutSec 25
    foreach ($it in $res.items) {
      $lic = if ($it.license) { $it.license.spdx_id } else { 'NONE' }
      $age = [int]((Get-Date) - [datetime]$it.pushed_at).TotalDays
      "{0}`t{1}`t{2}`t{3}`t{4}" -f $it.full_name, $it.stargazers_count, $lic, $it.language, $age
    }
  } catch {
    "SEARCH_ERR: $($_.Exception.Message)"
  }
  Start-Sleep -Seconds 2
}
