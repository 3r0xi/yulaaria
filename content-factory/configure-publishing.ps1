$Values = @{
    META_FACEBOOK_API_VERSION = Read-Host 'Facebook Graph API version (example: vXX.X)'
    META_INSTAGRAM_API_VERSION = Read-Host 'Instagram Graph API version (example: vXX.X)'
    META_THREADS_API_VERSION = Read-Host 'Threads Graph API version (example: vXX.X)'
    META_PAGE_ID = Read-Host 'Facebook Page ID'
    META_IG_USER_ID = Read-Host 'Instagram professional account ID'
    META_THREADS_USER_ID = Read-Host 'Threads user ID'
}
foreach ($Pair in $Values.GetEnumerator()) {
    & (Join-Path $PSScriptRoot 'save-credential.ps1') -Name $Pair.Key -Value $Pair.Value
}
[Environment]::SetEnvironmentVariable('YULA_SCHEDULER_LIVE', '0', 'User')
Remove-Variable Values -ErrorAction SilentlyContinue

Write-Host 'Publishing configuration was stored in the encrypted local JSON vault. Live publishing remains disabled.'
