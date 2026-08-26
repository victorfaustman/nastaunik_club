$ErrorActionPreference = "SilentlyContinue"

$projectRoot = "D:\codex\nastaunik_club"
$pidFile = Join-Path $projectRoot "bot_runner.pid"

if (Test-Path $pidFile) {
    $runnerPid = Get-Content $pidFile
    if ($runnerPid) {
        Stop-Process -Id $runnerPid -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$botProcess = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*D:\codex\nastaunik_club\app.py*"
}

foreach ($process in $botProcess) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Output "Bot processes stopped."
