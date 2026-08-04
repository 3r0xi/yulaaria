$PexelsSecure = Read-Host 'Paste the Pexels API key' -AsSecureString
$PexelsPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($PexelsSecure)
try {
    $PexelsPlain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($PexelsPointer)
    [Environment]::SetEnvironmentVariable('PEXELS_API_KEY', $PexelsPlain, 'User')
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($PexelsPointer)
    Remove-Variable PexelsPlain -ErrorAction SilentlyContinue
}

$TokenBytes = New-Object byte[] 32
$TokenGenerator = New-Object Security.Cryptography.RNGCryptoServiceProvider
try {
    $TokenGenerator.GetBytes($TokenBytes)
}
finally {
    $TokenGenerator.Dispose()
}
$WorkerToken = -join ($TokenBytes | ForEach-Object { $_.ToString('x2') })
[Environment]::SetEnvironmentVariable('YULA_FACTORY_TOKEN', $WorkerToken, 'User')
Remove-Variable WorkerToken,TokenBytes,TokenGenerator,PexelsSecure,PexelsPointer -ErrorAction SilentlyContinue

Write-Host 'Secrets were saved to your Windows user environment. Open a new terminal before running the factory.'
