$AccountId = Read-Host 'Cloudflare account ID'
$BucketName = Read-Host 'R2 bucket name'

& (Join-Path $PSScriptRoot 'save-credential.ps1') -Name R2_ACCOUNT_ID -Value $AccountId
& (Join-Path $PSScriptRoot 'save-credential.ps1') -Name R2_BUCKET_NAME -Value $BucketName
& (Join-Path $PSScriptRoot 'save-credential.ps1') -Name R2_ACCESS_KEY_ID -Secret
& (Join-Path $PSScriptRoot 'save-credential.ps1') -Name R2_SECRET_ACCESS_KEY -Secret

Remove-Variable AccountId,BucketName -ErrorAction SilentlyContinue
Write-Host 'Cloudflare R2 configuration stored. Use r2-stage only after a controlled upload test.'
