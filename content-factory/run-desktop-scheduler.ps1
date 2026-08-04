param(
    [int]$Limit = 20,
    [ValidateRange(0, 1440)]
    [int]$CatchUpMinutes = 120
)

$FactoryRoot = $PSScriptRoot
$LogDirectory = Join-Path $FactoryRoot 'logs'
$LogPath = Join-Path $LogDirectory 'desktop-scheduler.log'
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

$env:YULA_SCHEDULER_LIVE = '1'
$env:YULA_SCHEDULER_CATCH_UP_MINUTES = [string]$CatchUpMinutes
$Timestamp = Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK'
$Output = & (Join-Path $FactoryRoot 'run.ps1') schedule-dispatch --limit $Limit --live 2>&1 | Out-String
"[$Timestamp] $Output" | Add-Content -LiteralPath $LogPath -Encoding utf8
exit $LASTEXITCODE
