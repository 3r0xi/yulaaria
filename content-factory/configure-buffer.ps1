$secure = Read-Host 'Buffer API key' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    [Environment]::SetEnvironmentVariable('BUFFER_API_KEY', $value, 'User')
    $env:BUFFER_API_KEY = $value
    Write-Host 'BUFFER_API_KEY was stored in the Windows user environment. Restart terminals before using it elsewhere.'
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    Remove-Variable value -ErrorAction SilentlyContinue
}
