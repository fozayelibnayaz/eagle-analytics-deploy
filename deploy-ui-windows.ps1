Write-Host "=== Eagle Analytics UI Docker Deploy ==="
Write-Host ""

Set-Location $PSScriptRoot

if (!(Test-Path ".streamlit\secrets.toml")) {
    Write-Host "ERROR: .streamlit\secrets.toml not found."
    Write-Host "Please copy .streamlit\secrets.template.toml to .streamlit\secrets.toml and fill the real values."
    exit 1
}

Write-Host "Checking Docker..."
docker version
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker is not running."
    exit 1
}

docker compose version
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: docker compose is not available."
    exit 1
}

Write-Host ""
Write-Host "Stopping old UI stack if present..."
try {
    docker compose -f docker-compose.ui.yml down
} catch {
    Write-Host "No previous stack to stop."
}

Write-Host ""
Write-Host "Building UI image..."
docker compose -f docker-compose.ui.yml build --no-cache
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: UI build failed."
    exit 1
}

Write-Host ""
Write-Host "Starting UI container..."
docker compose -f docker-compose.ui.yml up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: UI start failed."
    exit 1
}

Write-Host ""
Write-Host "Container status:"
docker compose -f docker-compose.ui.yml ps

Write-Host ""
Write-Host "Recent UI logs:"
docker compose -f docker-compose.ui.yml logs --tail=100 ui

Write-Host ""
Write-Host "Testing local UI..."
Start-Sleep -Seconds 8

try {
    (Invoke-WebRequest -Uri "http://127.0.0.1:18501" -UseBasicParsing).StatusCode
    Write-Host ""
    Write-Host "SUCCESS: UI is running locally on port 18501"
}
catch {
    Write-Host "ERROR: UI check failed."
    Write-Host $_
    exit 1
}
