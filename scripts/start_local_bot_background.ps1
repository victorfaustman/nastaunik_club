$ErrorActionPreference = "Stop"

$projectRoot = "D:\codex\nastaunik_club"
$runnerScript = Join-Path $projectRoot "scripts\run_bot_forever.ps1"
$pidFile = Join-Path $projectRoot "bot_runner.pid"

if (Test-Path $pidFile) {
    $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existingPid) {
        $process = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($process) {
            Write-Output "Bot runner is already active with PID $existingPid."
            exit 0
        }
    }
}

$process = Start-Process `
    -FilePath "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -ArgumentList @(
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $runnerScript
    ) `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path $pidFile -Value $process.Id
Write-Output "Bot runner started with PID $($process.Id)."