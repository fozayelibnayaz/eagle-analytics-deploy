Write-Host "=== Eagle Analytics Backend Check ==="
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "Container status:"
docker compose -f docker-compose.backend.yml ps

Write-Host ""
Write-Host "Recent logs:"
docker compose -f docker-compose.backend.yml logs --tail=50 api

Write-Host ""
Write-Host "Health check:"
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method Get
    $resp | ConvertTo-Json -Depth 5
}
catch {
    Write-Host "Health failed:"
    Write-Host $_
}
