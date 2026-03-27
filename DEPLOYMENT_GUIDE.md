# Discord Bot - Oracle Cloud Deployment Guide

## 📋 Prerequisites

- Oracle Cloud Account (Free Tier eligible)
- Python 3.9+ (local development)
- Discord Bot Token (from Discord Developer Portal)
- PostgreSQL database (Oracle Autonomous DB or OCI PostgreSQL)

---

## 🚀 Deployment Options

### Option 1: Oracle App Container Runtime (Recommended - Serverless)

#### Step 1: Create PostgreSQL Database

```bash
# In Oracle Cloud Console:
# 1. Navigate to "OCI PostgreSQL Database Service"
# 2. Create a new database instance
# 3. Note the connection string: postgresql://user:password@host:5432/discord_bot
```

#### Step 2: Prepare Application

```bash
# Clone or download your application
cd discord-bot-export

# Create .env file with production values
cp .env.example .env
# Edit .env with your:
# - DISCORD_TOKEN=your_token
# - DATABASE_URL=postgresql://user:password@host:5432/discord_bot
# - PORT=8080
```

#### Step 3: Deploy to App Container Runtime

```bash
# Using Oracle Cloud CLI
oci artifacts container images upload \
  --repository-name discord-bot \
  --image-tag latest \
  --dockerfile Dockerfile .

# Or push to Oracle Container Registry manually
docker build -t discord-bot:latest .
docker tag discord-bot:latest ocir.us-phoenix-1.oraclecloud.com/your-namespace/discord-bot:latest
docker push ocir.us-phoenix-1.oraclecloud.com/your-namespace/discord-bot:latest
```

#### Step 4: Deploy via Container Runtime

```bash
# In Oracle Cloud Console:
# 1. Go to "Container Instances"
# 2. Create new container instance
# 3. Select your image from Container Registry
# 4. Set environment variables:
#    - DISCORD_TOKEN
#    - DATABASE_URL
#    - PORT (8080)
# 5. Configure network security group to allow port 8080
# 6. Deploy
```

---

### Option 2: Oracle Compute VM (More Control)

#### Step 1: Launch Compute Instance

```bash
# In Oracle Cloud Console:
# 1. Create compute instance (Ubuntu 22.04 LTS recommended)
# 2. Create/use public SSH key
# 3. Configure security group to allow port 8080
# 4. Create instance
```

#### Step 2: SSH and Setup

```bash
ssh ubuntu@your-instance-ip

# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install Python and dependencies
sudo apt-get install -y python3.11 python3-pip postgresql-client git

# Clone repository
git clone <your-repo> discord-bot
cd discord-bot

# Install requirements
pip3 install -r requirements.txt

# Create .env file
nano .env
# Add your DISCORD_TOKEN and DATABASE_URL
```

#### Step 3: Run with Systemd

```bash
# Create systemd service file
sudo nano /etc/systemd/system/discord-bot.service
```

```ini
[Unit]
Description=Discord EMA Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/discord-bot
Environment="PATH=/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin"
Environment="DATABASE_URL=postgresql://user:password@host:5432/discord_bot"
Environment="DISCORD_TOKEN=your_token"
Environment="PORT=8080"
ExecStart=/usr/bin/python3 -m gunicorn -w 1 -b 0.0.0.0:8080 --timeout 300 wsgi:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable discord-bot
sudo systemctl start discord-bot

# Check status
sudo systemctl status discord-bot

# View logs
sudo journalctl -u discord-bot -f
```

---

### Option 3: Docker Container (Most Portable)

#### Step 1: Build and Run Locally

```bash
# Build image
docker build -t discord-bot:latest .

# Run locally (for testing)
docker run -it \
  -e DISCORD_TOKEN=your_token \
  -e DATABASE_URL=postgresql://user:password@host:5432/discord_bot \
  -e PORT=8080 \
  -p 8080:8080 \
  discord-bot:latest
```

#### Step 2: Push to Oracle Container Registry

```bash
# Login to OCR
docker login ocir.us-phoenix-1.oraclecloud.com

# Tag image
docker tag discord-bot:latest ocir.us-phoenix-1.oraclecloud.com/your-namespace/discord-bot:latest

# Push
docker push ocir.us-phoenix-1.oraclecloud.com/your-namespace/discord-bot:latest
```

#### Step 3: Deploy with Docker Compose (on VM)

```bash
# Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
version: '3.8'
services:
  bot:
    image: ocir.us-phoenix-1.oraclecloud.com/your-namespace/discord-bot:latest
    environment:
      DISCORD_TOKEN: ${DISCORD_TOKEN}
      DATABASE_URL: ${DATABASE_URL}
      PORT: 8080
    ports:
      - "8080:8080"
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 5s
EOF

# Run
docker-compose up -d
```

---

## 🔄 Database Migration (SQLite → PostgreSQL)

### If you have existing SQLite data:

```bash
# 1. Create PostgreSQL database on Oracle Cloud
# 2. Run migration script
python3 migrate_to_postgres.py /tmp/alerts.db postgresql://user:password@host:5432/discord_bot

# 3. Verify migration success
# 4. Update DATABASE_URL in environment
# 5. Restart bot
```

---

## 🔒 Security Best Practices

### 1. Use Oracle Cloud Secrets Manager

```bash
# Store DISCORD_TOKEN in OCI Secrets Manager
# In Container/Compute instance environment, reference the secret:
# DISCORD_TOKEN=${OCI_SECRET_DISCORD_TOKEN}
```

### 2. Network Security

```bash
# Configure Security Group in Oracle Cloud:
# - Allow inbound on port 8080 from: 0.0.0.0/0 (or specific IP)
# - Restrict database access to bot instance only
# - Use private subnet for database if possible
```

### 3. Database Connection

```bash
# Use SSL/TLS for PostgreSQL:
# DATABASE_URL=postgresql+psycopg2://user:password@host:5432/discord_bot?sslmode=require
```

---

## 📊 Monitoring & Logs

### Check Bot Status

```bash
# Health check endpoint
curl http://your-instance-ip:8080/health

# Expected response:
# {"status": "healthy", "timestamp": "2026-03-27T..."}
```

### View Logs

```bash
# Container instances (Cloud Console):
# - Go to Container Instances → Your Instance → Logs

# Compute VM with systemd:
sudo journalctl -u discord-bot -f

# Docker container:
docker logs -f container-name
```

### Performance Monitoring

```bash
# In Oracle Cloud Console:
# - Monitoring → Metrics
# - Search for your compute instance
# - Monitor CPU, memory, network usage
```

---

## 🛠️ Troubleshooting

### Issue: Bot crashes on startup

```bash
# Check logs for database connection error
# Verify DATABASE_URL is correct
# Ensure PostgreSQL database exists and is accessible
# Test connection manually:
psql postgresql://user:password@host:5432/discord_bot -c "SELECT 1"
```

### Issue: Health check failing

```bash
# Endpoint should be: http://your-ip:8080/health
# Verify database connection works
# Check firewall rules allow port 8080
```

### Issue: High CPU/Memory usage

```bash
# Bot downloads market data every scan
# Discord.py + yfinance are resource-intensive
# Recommendations:
# - Use at least 2GB RAM for compute
# - Consider caching strategies
# - Rate-limit scans more aggressively
```

### Issue: Data loss on restart

```bash
# Ensure DATABASE_URL points to PostgreSQL (not /tmp)
# Never use ephemeral storage in /tmp for production
# Verify database backups are enabled in Oracle Cloud
```

---

## 📈 Scaling & Optimization

### For High Load (100+ concurrent users):

```bash
# 1. Scale up database
#    - Increase PostgreSQL instance size
#    - Enable read replicas if needed

# 2. Scale up compute
#    - Use larger compute instance
#    - Consider multi-instance with load balancing

# 3. Optimize bot
#    - Implement caching for market data (Redis)
#    - Batch database writes
#    - Use async operations more efficiently

# 4. Add CDN for static files
#    - Use Oracle Cloud CDN for data exports
```

---

## 💰 Cost Estimation (Oracle Cloud Free Tier)

| Component | Free Tier | Monthly Cost (if exceeded) |
|-----------|-----------|---------------------------|
| Compute (1 instance, 1 OCPU, 1GB RAM) | ✅ Always Free | $0.0116/hour |
| PostgreSQL Database | ✅ Always Free (20GB) | $0.318/GB/month |
| Object Storage | ✅ Always Free (20GB) | $0.0255/GB/month |
| Data Transfer (outbound) | ✅ Free (10TB/month) | $0.0085/GB |
| Load Balancer | ❌ Not free | $16/month + data |

**Estimated cost for Free Tier:** $0 (within free limits)

---

## 🆘 Getting Help

- **Oracle Cloud Documentation:** https://docs.oracle.com/
- **Discord.py Documentation:** https://discordpy.readthedocs.io/
- **PostgreSQL Documentation:** https://www.postgresql.org/docs/
- **Oracle Cloud Community:** https://www.oracle.com/cloud/free/

---

## ✅ Deployment Checklist

- [ ] Database created (PostgreSQL on Oracle Cloud)
- [ ] `.env` file created with all required variables
- [ ] `requirements.txt` updated with production dependencies
- [ ] `wsgi.py` created for WSGI server
- [ ] `Dockerfile` created and tested locally
- [ ] Health endpoint `/health` tested and working
- [ ] Security group configured for port 8080
- [ ] Database backups enabled
- [ ] Secrets stored in Oracle Secrets Manager
- [ ] Logs configured for monitoring
- [ ] Bot tested with health endpoint
- [ ] Database migration completed (if migrating from SQLite)

---

**Good luck with your deployment! 🚀**
