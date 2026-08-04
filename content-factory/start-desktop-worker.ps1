param(
    [string]$HostAddress = '127.0.0.1',
    [int]$Port = 8765
)

$BundledPython = 'C:\Users\ercan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $BundledPython)) {
    throw "Bundled Python was not found: $BundledPython"
}

$WorkerToken = [Environment]::GetEnvironmentVariable('YULA_FACTORY_TOKEN', 'User')
if (-not $WorkerToken) {
    throw 'YULA_FACTORY_TOKEN is not configured. Run configure-secrets.ps1 first.'
}

$env:YULA_FACTORY_TOKEN = $WorkerToken
$env:YULA_SCHEDULER_LIVE = '1'
$SourcePath = Join-Path $PSScriptRoot 'src'
$PublishingDependencies = Join-Path $PSScriptRoot '.deps\publishing'
$env:PYTHONPATH = if (Test-Path -LiteralPath $PublishingDependencies) {
    "$PublishingDependencies;$SourcePath"
} else {
    $SourcePath
}
& $BundledPython -m yula_factory.cli serve --host $HostAddress --port $Port
exit $LASTEXITCODE
