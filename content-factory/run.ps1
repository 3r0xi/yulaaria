param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$FactoryArgs
)

$BundledPython = 'C:\Users\ercan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $BundledPython)) {
    throw "Bundled Python was not found: $BundledPython"
}
$SourcePath = Join-Path $PSScriptRoot 'src'
$PublishingDependencies = Join-Path $PSScriptRoot '.deps\publishing'
$env:PYTHONPATH = if (Test-Path -LiteralPath $PublishingDependencies) {
    "$PublishingDependencies;$SourcePath"
} else {
    $SourcePath
}
if ($FactoryArgs.Count -eq 1 -and $FactoryArgs[0] -eq 'test') {
    & $BundledPython -m unittest discover -s (Join-Path $PSScriptRoot 'tests') -v
    exit $LASTEXITCODE
}
& $BundledPython -m yula_factory.cli @FactoryArgs
exit $LASTEXITCODE
