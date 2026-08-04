param(
    [string]$TaskName = 'Yula Aria Local Publisher',
    [ValidateRange(1, 60)]
    [int]$EveryMinutes = 5,
    [ValidateRange(0, 23)]
    [int]$StartHour = 6,
    [ValidateRange(1, 24)]
    [int]$ActiveHours = 18,
    [ValidateRange(0, 1440)]
    [int]$CatchUpMinutes = 120,
    [switch]$Replace
)

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing -and -not $Replace) {
    throw "Scheduled task already exists. Re-run with -Replace only after reviewing the current task."
}
if ($Existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$PowerShell = (Get-Command powershell.exe).Source
$Runner = Join-Path $PSScriptRoot 'run-desktop-scheduler.ps1'
$Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -CatchUpMinutes $CatchUpMinutes"
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments -WorkingDirectory $PSScriptRoot
$At = (Get-Date).Date.AddHours($StartHour)
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Trigger.Repetition.Interval = "PT${EveryMinutes}M"
$Trigger.Repetition.Duration = "PT${ActiveHours}H"
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description 'Runs the approval-gated SQLite publisher locally while this user is signed in.' `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal | Out-Null

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
