param([string]$TaskName = 'Yula Aria Local Publisher')

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $Existing) {
    Write-Output "Scheduled task is not installed: $TaskName"
    exit 0
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "Removed scheduled task: $TaskName"
