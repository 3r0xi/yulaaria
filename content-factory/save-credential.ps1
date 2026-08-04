param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Z0-9_]+$')]
    [string]$Name,

    [string]$Value,

    [switch]$Secret,

    [switch]$FromClipboard,

    [string]$TransferFile
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security

$VaultDirectory = Join-Path $PSScriptRoot 'secrets'
$VaultPath = Join-Path $VaultDirectory 'providers.local.json'
New-Item -ItemType Directory -Force -Path $VaultDirectory | Out-Null

$Values = [ordered]@{}
if (Test-Path -LiteralPath $VaultPath) {
    $Existing = Get-Content -Raw -LiteralPath $VaultPath | ConvertFrom-Json
    if ($Existing.values) {
        foreach ($Property in $Existing.values.PSObject.Properties) {
            $Values[$Property.Name] = $Property.Value
        }
    }
}

if ($Secret) {
    if ($FromClipboard -and $TransferFile) { throw 'Use either -FromClipboard or -TransferFile, not both' }
    if ($FromClipboard) {
        $ClipboardValue = Get-Clipboard -Raw
        if ($null -eq $ClipboardValue) { throw 'Clipboard is empty' }
        $PlainValue = $ClipboardValue.ToString().Trim()
    }
    elseif ($TransferFile) {
        $ResolvedTransfer = (Resolve-Path -LiteralPath $TransferFile).Path
        $ResolvedVaultDirectory = (Resolve-Path -LiteralPath $VaultDirectory).Path
        if ([IO.Path]::GetDirectoryName($ResolvedTransfer) -ne $ResolvedVaultDirectory -or [IO.Path]::GetExtension($ResolvedTransfer) -ne '.tmp') {
            throw 'Transfer file must be a .tmp file directly inside the local secrets directory'
        }
        try {
            $PlainValue = (Get-Content -Raw -LiteralPath $ResolvedTransfer).Trim()
        }
        finally {
            Remove-Item -LiteralPath $ResolvedTransfer -Force
        }
    }
    else {
        $SecureValue = Read-Host $Name -AsSecureString
        $Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
        try {
            $PlainValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
        }
    }
    if ([string]::IsNullOrWhiteSpace($PlainValue)) { throw "$Name cannot be empty" }
    $Bytes = [Text.Encoding]::UTF8.GetBytes($PlainValue)
    $Protected = [System.Security.Cryptography.ProtectedData]::Protect($Bytes, $null, [System.Security.Cryptography.DataProtectionScope]::LocalMachine)
    $Values[$Name] = [ordered]@{ type = 'dpapi'; value = [Convert]::ToBase64String($Protected) }
    if ($FromClipboard) { Set-Clipboard -Value ' ' }
    Remove-Variable PlainValue,ClipboardValue,Bytes,Protected,SecureValue,Pointer,ResolvedTransfer,ResolvedVaultDirectory -ErrorAction SilentlyContinue
}
else {
    if ([string]::IsNullOrWhiteSpace($Value)) { throw "$Name requires -Value" }
    $Values[$Name] = [ordered]@{ type = 'plain'; value = $Value.Trim() }
}

$Payload = [ordered]@{
    version = 1
    protection = 'Windows DPAPI LocalMachine with inherited user-folder ACLs'
    updated_at = [DateTime]::UtcNow.ToString('o')
    values = $Values
}
$Payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $VaultPath -Encoding utf8
Write-Host "$Name stored in the encrypted local provider vault."
