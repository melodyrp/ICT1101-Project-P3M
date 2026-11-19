param(
    [ValidateSet("menu","word","spell")]
    [string]$Mode = "menu"
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$TeamRoot = Split-Path -Parent $Here
$ProjectRoot = Split-Path -Parent $TeamRoot
$WordRepo = Join-Path $ProjectRoot "sign_lang_trans"

function Run-WordMode {
    $script = Join-Path $WordRepo "src\live_demo_team.py"
    if (-not (Test-Path $script)) {
        throw "250-word team demo not found: $script. Run install_into_translator.ps1 first."
    }
    Push-Location $WordRepo
    try { python .\src\live_demo_team.py }
    finally { Pop-Location }
}

function Run-SpellMode {
    Push-Location $TeamRoot
    try { python .\SignAI\fingerspell_team.py }
    finally { Pop-Location }
}

if ($Mode -eq "word") { Run-WordMode; exit }
if ($Mode -eq "spell") { Run-SpellMode; exit }

Write-Host ""
Write-Host "Person 1 Sign AI" -ForegroundColor Cyan
Write-Host "1 - 250-word ASL mode"
Write-Host "2 - Fingerspelling A-Z mode"
Write-Host ""
$choice = Read-Host "Choose mode"

switch ($choice) {
    "1" { Run-WordMode }
    "2" { Run-SpellMode }
    default { Write-Host "Cancelled." }
}
