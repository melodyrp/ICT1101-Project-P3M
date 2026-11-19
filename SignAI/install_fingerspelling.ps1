param(
    [string]$ModelPath = ""
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $Here)

if (-not $ModelPath) {
    $ModelPath = Join-Path $ProjectRoot "asl_fingerspell_model"
}

Write-Host "Person 1 Fingerspelling Setup" -ForegroundColor Cyan
Write-Host "External pretrained model folder: $ModelPath"

if (-not (Test-Path $ModelPath)) {
    Write-Host ""
    Write-Host "Cloning pretrained ASL alphabet model..." -ForegroundColor Yellow
    git clone https://github.com/ronronrivera/real-time-asl-detection.git $ModelPath
}

if (-not (Test-Path (Join-Path $ModelPath "models\asl_landmark_mlp.pth"))) {
    throw "Missing pretrained model: $ModelPath\models\asl_landmark_mlp.pth"
}
if (-not (Test-Path (Join-Path $ModelPath "landmark_label_encoder.pkl"))) {
    throw "Missing label encoder: $ModelPath\landmark_label_encoder.pkl"
}

Write-Host ""
Write-Host "Installing alphabet-model Python dependencies into the active Python environment..." -ForegroundColor Yellow
python -m pip install -r (Join-Path $ModelPath "requirements.txt")
python -m pip install joblib opencv-python mediapipe scikit-learn torch numpy

$configPath = Join-Path $Here "fingerspelling_config.json"
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$config.external_repo_relative = (Resolve-Path $ModelPath).Path
$config | ConvertTo-Json -Depth 10 | Set-Content $configPath -Encoding UTF8

Write-Host ""
Write-Host "Fingerspelling setup complete." -ForegroundColor Green
Write-Host "Run from the team repo root:"
Write-Host "  python .\SignAI\fingerspell_team.py"
Write-Host ""
Write-Host "Keep the 250-word model separately at PROJECT\sign_lang_trans."
