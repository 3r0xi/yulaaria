param(
    [switch]$IncludeUserTokens
)

$ErrorActionPreference = 'Stop'
$factory = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:\Users\ercan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = Join-Path $factory 'src'

function Save-Secret([string]$Name, [string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        $env:YULA_PENDING_SECRET = $value
        & $python -c "import os; from yula_factory.secrets import save_config_value; save_config_value('$Name', os.environ.pop('YULA_PENDING_SECRET'), True)"
        if ($LASTEXITCODE -ne 0) { throw "Unable to store $Name" }
    }
    finally {
        Remove-Item Env:YULA_PENDING_SECRET -ErrorAction SilentlyContinue
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

Save-Secret 'TIKTOK_CLIENT_KEY' 'TikTok client key'
Save-Secret 'TIKTOK_CLIENT_SECRET' 'TikTok client secret'
if ($IncludeUserTokens) {
    Save-Secret 'TIKTOK_ACCESS_TOKEN' 'TikTok user access token'
    Save-Secret 'TIKTOK_REFRESH_TOKEN' 'TikTok user refresh token'
}
Write-Host 'TikTok credentials stored in the encrypted local vault. No value was printed.'
