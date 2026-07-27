Write-Host "=== Eagle Analytics UI Auto Update ==="

Set-Location $PSScriptRoot
git pull
docker compose -f docker-compose.ui.yml build
docker compose -f docker-compose.ui.yml up -d
docker compose -f docker-compose.ui.yml ps
