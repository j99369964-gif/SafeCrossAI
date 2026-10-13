# Starts the SafeCross PWA on this PC and exposes it with a free Cloudflare quick tunnel.
# Run from the repository root:   powershell -ExecutionPolicy Bypass -File pwa\tunnel\start_windows.ps1
# Put your keys in pwa\tunnel\keys.ps1 first (copy keys.example.ps1).

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $root

$keys = Join-Path $PSScriptRoot "keys.ps1"
if (-not (Test-Path $keys)) { Write-Error "Missing pwa\tunnel\keys.ps1 - copy keys.example.ps1 to keys.ps1 and fill it in."; exit 1 }
. $keys

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  Write-Error "cloudflared not found. Install it with:  winget install --id Cloudflare.cloudflared   then reopen this window."; exit 1
}

$env:HOST = "127.0.0.1"      # only the tunnel can reach the server, not your local network
$env:PORT = "8000"
$env:TRUST_PROXY = "1"       # the tunnel forwards the visitor's address in X-Forwarded-For

$server = Start-Process python -ArgumentList "pwa\server\server.py" -PassThru -NoNewWindow

# Wait (up to 3 minutes) for the server to answer BEFORE starting the tunnel, and stop with a clear message if it crashed.
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
  if ($server.HasExited) { break }
  try { Invoke-WebRequest -Uri "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 2 | Out-Null; $ready = $true; break } catch { Start-Sleep -Seconds 2 }
}
if (-not $ready) {
  if ($server.HasExited) { Write-Host "`nThe server stopped before it started answering (exit code $($server.ExitCode)). Read the error printed above this message." -ForegroundColor Red }
  else { Write-Host "`nThe server did not answer on http://127.0.0.1:8000 within 3 minutes." -ForegroundColor Red; Stop-Process -Id $server.Id -Force }
  exit 1
}
Write-Host "Server is up. Starting tunnel..." -ForegroundColor Green
try {
  Write-Host "`nLook for the https://....trycloudflare.com address below. Add it to your Google browser-key referrers." -ForegroundColor Cyan
  cloudflared tunnel --url http://127.0.0.1:8000
} finally {
  if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}
