# deploy.ps1 — PowerShell wrapper for deploy.sh (requires Git Bash).
$ErrorActionPreference = "Stop"

$bash = (Get-Command bash -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path)
if (-not $bash -or -not (Test-Path $bash) -or $bash -match 'wsl\.exe' -or $bash -match 'WindowsApps' -or $bash -match 'System32') {
    $candidates = @(
        "$env:ProgramFiles\Git\bin\bash.exe",
        "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
        "$env:LocalAppData\Programs\Git\bin\bash.exe",
        "C:\Program Files\Git\bin\bash.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $bash = $c
            break
        }
    }
}

if (-not $bash -or -not (Test-Path $bash)) {
    Write-Error "Git Bash (bash.exe) was not found on PATH or standard Git installation paths."
    exit 1
}

& $bash "$PSScriptRoot\deploy.sh" @args
exit $LASTEXITCODE
