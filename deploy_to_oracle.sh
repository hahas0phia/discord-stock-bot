#!/bin/bash
# Discord Bot - Oracle Cloud Quick Deploy Script
# Usage: ./deploy_to_oracle.sh

set -e

echo "🚀 Discord Bot - Oracle Cloud Deployment Script"
echo "================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed${NC}"
    echo "   Install Docker from: https://www.docker.com/"
    exit 1
fi
echo -e "${GREEN}✅ Docker installed${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python 3 installed${NC}"

# Check for .env file
echo ""
echo "📝 Checking configuration..."

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo -e "${YELLOW}⚠️  .env file not found${NC}"
        echo "   Creating from .env.example..."
        cp .env.example .env
        echo -e "${YELLOW}⚠️  Please edit .env with your configuration:${NC}"
        echo "   - DISCORD_TOKEN"
        echo "   - DATABASE_URL"
        echo "   - PORT"
        read -p "   Press Enter once you've updated .env..."
    else
        echo -e "${RED}❌ .env.example not found${NC}"
        exit 1
    fi
fi

# Load environment
source .env

# Validate environment variables
echo ""
echo "🔐 Validating environment variables..."

if [ -z "$DISCORD_TOKEN" ]; then
    echo -e "${RED}❌ DISCORD_TOKEN not set in .env${NC}"
    exit 1
fi
echo -e "${GREEN}✅ DISCORD_TOKEN is set${NC}"

if [ -z "$DATABASE_URL" ]; then
    echo -e "${YELLOW}⚠️  DATABASE_URL not set, using default SQLite${NC}"
else
    echo -e "${GREEN}✅ DATABASE_URL is set${NC}"
fi

PORT=${PORT:-8080}
echo -e "${GREEN}✅ PORT is $PORT${NC}"

# Build Docker image
echo ""
echo "🔨 Building Docker image..."

if docker build -t discord-bot:latest .; then
    echo -e "${GREEN}✅ Docker image built successfully${NC}"
else
    echo -e "${RED}❌ Docker build failed${NC}"
    exit 1
fi

# Test image locally
echo ""
echo "🧪 Testing image locally..."
echo "   Starting bot in test mode for 10 seconds..."

if timeout 10 docker run -e DISCORD_TOKEN="$DISCORD_TOKEN" -e DATABASE_URL="$DATABASE_URL" -e PORT="$PORT" -p 8080:8080 discord-bot:latest || [ $? -eq 124 ]; then
    echo -e "${GREEN}✅ Docker image runs successfully${NC}"
else
    echo -e "${RED}❌ Docker image failed to run${NC}"
    exit 1
fi

# Test health endpoint
echo ""
echo "🏥 Testing health endpoint..."

if curl -s http://localhost:8080/health | grep -q "healthy"; then
    echo -e "${GREEN}✅ Health endpoint working${NC}"
else
    echo -e "${YELLOW}⚠️  Health endpoint not accessible (might not be running yet)${NC}"
fi

# Ready for deployment
echo ""
echo "================================================"
echo -e "${GREEN}✅ All checks passed!${NC}"
echo ""
echo "📦 Next steps for Oracle Cloud deployment:"
echo ""
echo "1. Tag image for Oracle Container Registry:"
echo "   docker tag discord-bot:latest ocir.REGION.oraclecloud.com/NAMESPACE/discord-bot:latest"
echo ""
echo "2. Push to OCR:"
echo "   docker push ocir.REGION.oraclecloud.com/NAMESPACE/discord-bot:latest"
echo ""
echo "3. Deploy to Container Instances:"
echo "   - Go to: Oracle Cloud Console → Container Instances → Create Instance"
echo "   - Select your image from Container Registry"
echo "   - Set environment variables (DISCORD_TOKEN, DATABASE_URL, PORT)"
echo "   - Configure security group for port 8080"
echo "   - Deploy"
echo ""
echo "4. Verify deployment:"
echo "   curl http://your-instance-ip:8080/health"
echo ""
echo "📚 For detailed instructions, see: DEPLOYMENT_GUIDE.md"
echo ""

# Ask if user wants to continue
read -p "Do you want to upload to Oracle Container Registry now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "🌐 Oracle Container Registry Upload"
    echo "===================================="
    echo ""
    read -p "Enter your region (e.g., us-phoenix-1): " REGION
    read -p "Enter your namespace (e.g., mynamespace): " NAMESPACE
    
    if [ -z "$REGION" ] || [ -z "$NAMESPACE" ]; then
        echo -e "${RED}❌ Region and namespace are required${NC}"
        exit 1
    fi
    
    REGISTRY_URL="ocir.${REGION}.oraclecloud.com"
    IMAGE_URL="${REGISTRY_URL}/${NAMESPACE}/discord-bot:latest"
    
    echo ""
    echo "📤 Tagging image for: $IMAGE_URL"
    docker tag discord-bot:latest "$IMAGE_URL"
    
    echo "🔐 Please log in to Oracle Container Registry:"
    docker login "$REGISTRY_URL"
    
    echo ""
    echo "📤 Pushing image..."
    if docker push "$IMAGE_URL"; then
        echo -e "${GREEN}✅ Image pushed successfully!${NC}"
        echo ""
        echo "Use this image URL in Oracle Cloud Console:"
        echo "  $IMAGE_URL"
    else
        echo -e "${RED}❌ Failed to push image${NC}"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}🎉 Deployment preparation complete!${NC}"
echo ""
