$ErrorActionPreference = "Continue"

$projectRoot = "D:\codex\nastaunik_club"
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$appFile = Join-Path $projectRoot "app.py"
$logDir = Join-Path $projectRoot "logs"
$stdoutLog = Join-Path $logDir "bot.stdout.log"
$stderrLog = Join-Path $logDir "bot.stderr.log"

if (!(Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

Set-Location $projectRoot

while ($true) {
    Add-Content -Path $stdoutLog -Value ("[{0}] Starting bot process" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    & $pythonExe $appFile 1>> $stdoutLog 2>> $stderrLog
    $exitCode = $LASTEXITCODE
    Add-Content -Path $stderrLog -Value ("[{0}] Bot process stopped with exit code {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $exitCode)
    Start-Sleep -Seconds 5
}