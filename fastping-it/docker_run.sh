# docker-run.sh
#!/bin/bash

# FastPing Docker Deployment Script
# Run this to get everything up and running

set -e

echo "🚀 FastPing Docker Deployment Starting..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  Creating .env from template..."
    cp .env.example .env
    echo "📝 Please edit .env with your PayPal credentials and other settings"
    echo "💡 Run 'nano .env' to edit, then run this script again"
    exit 1
fi

# Create required directories
echo "📁 Creating directories..."
mkdir -p data logs ssl

# Generate secret key if not set
if ! grep -q "SECRET_KEY=.*[a-zA-Z0-9]" .env; then
    echo "🔑 Generating secret key..."
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i "s/SECRET_KEY=.*/SECRET_KEY=$SECRET_KEY/" .env
fi

# Build and start services
echo "🏗️  Building Docker images..."
docker-compose build

echo "🚀 Starting services..."
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Test the deployment
echo "🧪 Testing deployment..."
if curl -f http://localhost:9876/health > /dev/null 2>&1; then
    echo "✅ FastPing is running!"
    echo "🌐 Access your service at: http://localhost:9876"
    echo "📊 Admin dashboard: http://localhost:9876/admin/stats"
    echo "🔍 Health check: http://localhost:9876/health"
else
    echo "❌ Service not responding, checking logs..."
    docker-compose logs fastping
    exit 1
fi

# Show useful commands
echo ""
echo "🛠️  Useful commands:"
echo "docker-compose logs -f fastping    # View logs"
echo "docker-compose restart fastping    # Restart service"
echo "docker-compose down               # Stop everything"
echo "docker-compose up -d              # Start everything"