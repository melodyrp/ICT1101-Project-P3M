param(
    [string]$TranslatorPath = ""
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $TranslatorPath) {
    $candidates = @(
        (Join-Path (Split-Path -Parent $Here) "sign_lang_trans"),
        (Join-Path (Split-Path -Parent (Split-Path -Parent $Here)) "sign_lang_trans")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path (Join-Path $candidate "src\live_demo_transformer.py")) {
            $TranslatorPath = $candidate
            break
        }
    }
}

if (-not $TranslatorPath) {
    throw "Could not find sign_lang_trans automatically. Run: .\install_into_translator.ps1 -TranslatorPath 'C:\path\to\sign_lang_trans'"
}

$TranslatorPath = (Resolve-Path $TranslatorPath).Path
if (-not (Test-Path (Join-Path $TranslatorPath "src\live_demo_transformer.py"))) {
    throw "That folder does not contain src\live_demo_transformer.py: $TranslatorPath"
}

Copy-Item (Join-Path $Here "person1_bridge.py") (Join-Path $TranslatorPath "src\person1_bridge.py") -Force
Copy-Item (Join-Path $Here "person1_config.json") (Join-Path $TranslatorPath "person1_config.json") -Force
Copy-Item (Join-Path $Here "patch_demo.py") (Join-Path $TranslatorPath "patch_demo.py") -Force

Push-Location $TranslatorPath
try {
    python .\patch_demo.py
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Person 1 integration installed." -ForegroundColor Green
Write-Host "Start the team backend first, then run:"
Write-Host "  cd `"$TranslatorPath`""
Write-Host "  python .\src\live_demo_team.py"
