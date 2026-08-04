$WorkerToken = [Environment]::GetEnvironmentVariable('YULA_FACTORY_TOKEN', 'User')
if ([string]::IsNullOrWhiteSpace($WorkerToken)) {
    throw 'YULA_FACTORY_TOKEN is not configured. Run configure-secrets.ps1 first.'
}
Set-Clipboard -Value "Bearer $WorkerToken"
Remove-Variable WorkerToken
Write-Host 'The Authorization header value is now on the clipboard. Paste it into the n8n HTTP Header Auth credential.'
