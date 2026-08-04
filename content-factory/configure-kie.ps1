$ErrorActionPreference = 'Stop'
$BundledPython = 'C:\Users\ercan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $BundledPython)) {
    throw "Bundled Python was not found: $BundledPython"
}

$SecureValue = Read-Host 'Paste the Kie.ai API key' -AsSecureString
$Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
try {
    $PlainValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
    if ([string]::IsNullOrWhiteSpace($PlainValue)) {
        throw 'KIE_API_KEY cannot be empty'
    }
    $env:KIE_API_KEY = $PlainValue.Trim()
    try {
        [Environment]::SetEnvironmentVariable('KIE_API_KEY', $env:KIE_API_KEY, 'User')
    }
    catch {
        Write-Warning 'The Windows user environment could not be updated; continuing with the encrypted local vault.'
    }
    $env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
    & $BundledPython -c "import os; from yula_factory.secrets import save_config_value; save_config_value('KIE_API_KEY', os.environ['KIE_API_KEY'], secret=True)"
    if ($LASTEXITCODE -ne 0) {
        throw 'The encrypted local credential vault could not be updated.'
    }
}
finally {
    Remove-Item Env:KIE_API_KEY -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
    Remove-Variable PlainValue,SecureValue,Pointer -ErrorAction SilentlyContinue
}
Write-Host 'KIE_API_KEY was stored in the DPAPI-encrypted local vault.'
Write-Host 'The plaintext key was not written to the project or printed.'
