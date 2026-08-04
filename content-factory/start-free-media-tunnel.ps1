param(
    [int]$Port = 8765,
    [ValidateSet('127.0.0.1','0.0.0.0')]
    [string]$HostAddress = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'
$BundledPython = 'C:\Users\ercan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$BundledCloudflared = Join-Path $PSScriptRoot 'tools\cloudflared.exe'
$CloudflaredCommand = Get-Command cloudflared -ErrorAction SilentlyContinue
$Cloudflared = if ($CloudflaredCommand) { $CloudflaredCommand.Source } else { $BundledCloudflared }
if (-not (Test-Path -LiteralPath $Cloudflared)) {
    throw "cloudflared was not found. Install it or place cloudflared.exe at $BundledCloudflared"
}

$LogDirectory = Join-Path $PSScriptRoot 'logs'
$StateDirectory = Join-Path $PSScriptRoot 'state'
New-Item -ItemType Directory -Force -Path $LogDirectory,$StateDirectory | Out-Null
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2 | Out-Null
    $WorkerProcess = $null
    try {
        $WorkerPid = (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop | Select-Object -First 1).OwningProcess
    }
    catch {
        $PreviousStatePath = Join-Path $StateDirectory 'free-media-tunnel.json'
        if (-not (Test-Path -LiteralPath $PreviousStatePath)) { throw }
        $PreviousState = Get-Content -LiteralPath $PreviousStatePath -Raw | ConvertFrom-Json
        $PreviousWorker = Get-Process -Id $PreviousState.worker_pid -ErrorAction Stop
        if ($PreviousWorker.ProcessName -ne 'python') { throw 'The healthy worker PID does not identify Python' }
        $WorkerPid = $PreviousWorker.Id
    }
}
catch {
    $WorkerProcess = Start-Process -FilePath $BundledPython `
        -ArgumentList @('-m','yula_factory.cli','serve','--host',$HostAddress,'--port',"$Port") `
        -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDirectory 'worker.stdout.log') `
        -RedirectStandardError (Join-Path $LogDirectory 'worker.stderr.log')
    $Ready = $false
    foreach ($Attempt in 1..40) {
        Start-Sleep -Milliseconds 250
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1 | Out-Null
            $Ready = $true
            break
        }
        catch {}
    }
    if (-not $Ready) { throw 'The local Yula worker did not become healthy' }
    $WorkerPid = $WorkerProcess.Id
}

$RunStamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmssfff')
$TunnelStdout = Join-Path $LogDirectory "free-media-tunnel-$RunStamp.stdout.log"
$TunnelStderr = Join-Path $LogDirectory "free-media-tunnel-$RunStamp.stderr.log"
$TunnelProcess = Start-Process -FilePath $Cloudflared `
    -ArgumentList @('tunnel','--no-autoupdate','--url',"http://127.0.0.1:$Port") `
    -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $TunnelStdout -RedirectStandardError $TunnelStderr

$PublicUrl = $null
foreach ($Attempt in 1..80) {
    Start-Sleep -Milliseconds 250
    $LogText = ((Get-Content -Raw -ErrorAction SilentlyContinue -LiteralPath $TunnelStdout), (Get-Content -Raw -ErrorAction SilentlyContinue -LiteralPath $TunnelStderr)) -join "`n"
    $Match = [regex]::Match($LogText, 'https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com')
    if ($Match.Success) {
        $PublicUrl = $Match.Value
        break
    }
    if ($TunnelProcess.HasExited) { break }
}
if (-not $PublicUrl) {
    if (-not $TunnelProcess.HasExited) { Stop-Process -Id $TunnelProcess.Id -Force }
    throw "The free HTTPS tunnel did not return a public URL. Inspect $TunnelStderr"
}

$env:YULA_TUNNEL_URL_TO_STORE = $PublicUrl
try {
    & $BundledPython -c "import os; from yula_factory.secrets import save_config_value; save_config_value('YULA_PUBLIC_MEDIA_BASE_URL', os.environ['YULA_TUNNEL_URL_TO_STORE'], secret=False)"
    if ($LASTEXITCODE -ne 0) { throw 'Failed to store the public tunnel URL' }
}
finally {
    Remove-Item Env:YULA_TUNNEL_URL_TO_STORE -ErrorAction SilentlyContinue
}
$State = [ordered]@{
    public_url = $PublicUrl
    tunnel_pid = $TunnelProcess.Id
    worker_pid = $WorkerPid
    worker_host = $HostAddress
    content_root = $env:YULA_CONTENT_ROOT
    live_scheduler = $env:YULA_SCHEDULER_LIVE -eq '1'
    tunnel_stdout = $TunnelStdout
    tunnel_stderr = $TunnelStderr
    started_at = [DateTime]::UtcNow.ToString('o')
}
$State | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $StateDirectory 'free-media-tunnel.json') -Encoding utf8
$State | ConvertTo-Json
