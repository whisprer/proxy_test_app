# docker-deploy.ps1 (PowerShell version for Windows)
# Ultimate FastPing Docker Deployment Script for Windows

Write-Host "🚀 Ultimate FastPing Docker Deployment Starting..." -ForegroundColor Green

# Check if .env exists
if (-not (Test-Path .env)) {
    Write-Host "⚠️  Creating .env from template..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "📝 Please edit .env with your PayPal credentials and other settings" -ForegroundColor Cyan
    Write-Host "💡 Edit .env file, then run this script again" -ForegroundColor Cyan
    exit 1
}

# Create required directories
Write-Host "📁 Creating directories..." -ForegroundColor Blue
New-Item -ItemType Directory -Force -Path "data", "logs", "ssl" | Out-Null

# Generate secret key if not set
$envContent = Get-Content .env -Raw
if ($envContent -notmatch "SECRET_KEY=.+") {
    Write-Host "🔑 Generating secret key..." -ForegroundColor Blue
    $secretKey = [System.Web.Security.Membership]::GeneratePassword(32, 0)
    $envContent = $envContent -replace "SECRET_KEY=.*", "SECRET_KEY=$secretKey"
    $envContent | Set-Content .env
}

# Build and start services
Write-Host "🏗️  Building Docker images..." -ForegroundColor Blue
docker-compose build

Write-Host "🚀 Starting services..." -ForegroundColor Green
docker-compose up -d

# Wait for services to be ready
Write-Host "⏳ Waiting for services to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 15

# Test the deployment
Write-Host "🧪 Testing deployment..." -ForegroundColor Blue
try {
    $response = Invoke-WebRequest -Uri "http://localhost:9876/health" -UseBasicParsing
    if ($response.StatusCode -eq 200) {
        Write-Host "✅ FastPing is running!" -ForegroundColor Green
        Write-Host "🌐 Access your service at: http://localhost:9876" -ForegroundColor Cyan
        Write-Host "📊 Admin dashboard: http://localhost:9876/admin/stats" -ForegroundColor Cyan
        Write-Host "🔍 Health check: http://localhost:9876/health" -ForegroundColor Cyan
        Write-Host "⚡ Redis caching: Available" -ForegroundColor Cyan
    }
} catch {
    Write-Host "❌ Service not responding, checking logs..." -ForegroundColor Red
    docker-compose logs fastping
    exit 1
}

# Show useful commands
Write-Host ""
Write-Host "🛠️  Useful commands:" -ForegroundColor Yellow
Write-Host "docker-compose logs -f fastping    # View logs"
Write-Host "docker-compose restart fastping    # Restart service"
Write-Host "docker-compose down               # Stop everything"
Write-Host "docker-compose up -d              # Start everything"
Write-Host "docker-compose exec fastping bash # Shell into container"