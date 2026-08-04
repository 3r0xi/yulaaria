$BundledPython = 'C:\Users\ercan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $BundledPython)) {
    throw "Bundled Python was not found: $BundledPython"
}

$Target = Join-Path $PSScriptRoot '.deps\publishing'
New-Item -ItemType Directory -Force -Path $Target | Out-Null

& $BundledPython -m pip install --upgrade --target $Target `
    'google-api-python-client>=2.0' `
    'google-auth>=2.0' `
    'google-auth-oauthlib>=1.0' `
    'google-auth-httplib2>=0.2'

if ($LASTEXITCODE -ne 0) {
    throw 'Publishing dependency installation failed.'
}

Write-Host "Publishing dependencies installed in $Target"
