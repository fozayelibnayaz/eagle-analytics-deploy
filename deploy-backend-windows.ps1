Write-Host "=== Eagle Analytics Backend Docker Deploy ==="
Write-Host ""

Set-Location $PSScriptRoot

if (!(Test-Path ".env.backend")) {
    Write-Host "ERROR: .env.backend not found in this folder."
    Write-Host "Please copy .env.backend.template to .env.backend and fill the real values."
    exit 1
}

Write-Host "Checking Docker..."
docker version
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker is not running or not installed."
    exit 1
}

docker compose version
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: docker compose is not available."
    exit 1
}

Write-Host ""
Write-Host "Building backend image..."
docker compose -f docker-compose.backend.yml --env-file .env.backend build --no-cache
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker build failed."
    exit 1
}

Write-Host ""
Write-Host "Starting backend container..."
docker compose -f docker-compose.backend.yml --env-file .env.backend up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker compose up failed."
    exit 1
}

Write-Host ""
Write-Host "Container status:"
docker compose -f docker-compose.backend.yml ps

Write-Host ""
Write-Host "Recent backend logs:"
docker compose -f docker-compose.backend.yml logs --tail=80 api

Write-Host ""
Write-Host "Testing local health..."
Start-Sleep -Seconds 5

try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method Get
    $resp | ConvertTo-Json -Depth 5
    Write-Host ""
    Write-Host "SUCCESS: Backend is running locally on port 8000"
}
catch {
    Write-Host "ERROR: Local health check failed."
    Write-Host $_
    exit 1
}
