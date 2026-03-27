# 🚀 ORACLE CLOUD DEPLOYMENT - QUICK REFERENCE

**Last Updated:** March 27, 2026  
**Version:** 1.0.0 Production Ready

---

## 📋 ONE-PAGE QUICK START

### Step 1: Prerequisites (2 min)
```bash
# Check you have:
✓ Docker installed
✓ Python 3.9+
✓ Discord bot token
✓ Oracle Cloud account with PostgreSQL DB
```

### Step 2: Prepare (3 min)
```bash
cd discord-bot-export
cp .env.example .env

# Edit .env:
# DISCORD_TOKEN=your_token_here
# DATABASE_URL=postgresql://user:password@host:5432/discord_bot
# PORT=8080
```

### Step 3: Build (2 min)
```bash
docker build -t discord-bot:latest .
```

### Step 4: Test (5 min)
```bash
docker run -e DISCORD_TOKEN="$TOKEN" \
  -e DATABASE_URL="$DB_URL" \
  -p 8080:8080 discord-bot:latest &
  
sleep 5
curl http://localhost:8080/health
# Should return: {"status": "healthy", ...}
```

### Step 5: Push to Oracle (2 min)
```bash
docker tag discord-bot:latest \
  ocir.region.oraclecloud.com/namespace/discord-bot:latest

docker push ocir.region.oraclecloud.com/namespace/discord-bot:latest
```

### Step 6: Deploy (5 min)
```
In Oracle Cloud Console:
1. Container Instances → Create Instance
2. Image: ocir.region.oraclecloud.com/namespace/discord-bot:latest
3. Environment:
   - DISCORD_TOKEN = your_token
   - DATABASE_URL = postgresql://...
   - PORT = 8080
4. Network: Allow port 8080
5. Create
```

### Step 7: Verify (1 min)
```bash
curl http://your-instance-ip:8080/health
# ✅ Success: {"status": "healthy", ...}
# ❌ Failed: Check logs in Oracle Cloud Console
```

**Total time: ~20 minutes**

---

## 📁 KEY FILES AT A GLANCE

```
main.py ..................... Main bot (4,300 lines)
├─ /health endpoint ......... Health monitoring
├─ PostgreSQL support ....... Production database
└─ Connection pooling ....... 5-10 connections

wsgi.py ..................... WSGI wrapper for Gunicorn
Dockerfile .................. Container image
requirements.txt ............ All dependencies

.env.example ................ Copy to .env
.gitignore .................. Protects secrets

DEPLOYMENT_GUIDE.md ......... Full instructions (pick your path)
README_PRODUCTION.md ........ Features & commands
```

---

## 🔄 DATABASE MODES

### Production (Oracle Cloud)
```
DATABASE_URL = postgresql://user:pass@host:5432/db
├─ Connection pooling: YES (5-10 connections)
├─ Thread-safe: YES
├─ Data persistence: YES ✓
├─ Scalable: YES ✓
└─ Backups: Supported
```

### Development (Local)
```
DATABASE_URL = sqlite:////tmp/alerts.db
├─ No external dependencies
├─ Single connection
├─ Easy testing
├─ Data lost on restart ⚠️
└─ Perfect for testing
```

---

## 🏥 HEALTH CHECK

### What It Does
```
GET /health
    ↓
Check database connection
    ↓
Return: {"status": "healthy"|"unhealthy", ...}
    ↓
HTTP 200 ✅ or 503 ❌
```

### How to Monitor
```bash
# Check health
curl http://your-instance-ip:8080/health

# Monitor continuously
watch -n 5 'curl -s http://your-instance-ip:8080/health | jq'

# In Oracle Cloud Console
Compute → Instances → Your Instance → Logs
```

---

## 🔐 SECURITY

### ✅ Already Secure
- No hardcoded secrets
- Environment variables
- Connection pooling
- Thread-safe operations

### 🛡️ Recommended
- [ ] Use Oracle Secrets Manager
- [ ] Enable VPC for database
- [ ] SSL/TLS for connections
- [ ] Firewall restrictions
- [ ] Audit logging
- [ ] Regular backups

---

## ⚠️ COMMON ISSUES & FIXES

### Issue: "Docker build failed"
```bash
# Fix: Check Dockerfile exists
ls -la Dockerfile

# Fix: Build with verbose output
docker build -v -t discord-bot:latest .
```

### Issue: "Health check returns 503"
```bash
# Fix: Check DATABASE_URL
echo $DATABASE_URL

# Fix: Test database connection
psql $DATABASE_URL -c "SELECT 1"

# Fix: Check port is accessible
curl http://localhost:8080/health
```

### Issue: "Bot offline in Discord"
```bash
# Fix: Check Discord token
echo $DISCORD_TOKEN

# Fix: Verify bot is running in container
docker logs container_name | tail -20

# Fix: Check bot has Discord permissions
Discord Developer Portal → OAuth2 → Scopes
```

### Issue: "Data lost after restart"
```bash
# Problem: Using SQLite (not PostgreSQL)
# Fix: Update DATABASE_URL to PostgreSQL
DATABASE_URL=postgresql://user:pass@host:5432/db
```

---

## 📊 PERFORMANCE TUNING

### If Bot Is Slow
```bash
# Problem: Scanning 200+ stocks takes time
# Solution 1: Increase compute resources
#   - 2+ OCPUs
#   - 2+ GB RAM

# Solution 2: Optimize yfinance
#   - Use caching
#   - Reduce scan frequency

# Solution 3: Reduce watchlist size
#   - Edit ALL_TICKERS in main.py
#   - Remove inactive tickers
```

### If Memory Is High
```bash
# Problem: Bot uses 300-500MB
# Solution 1: Use instance with 2GB+ RAM

# Solution 2: Restart periodically
#   - Set systemd restart
#   - Use container orchestration
```

### If Database Is Slow
```bash
# Problem: Queries taking too long
# Solution 1: Increase connection pool
#   - Edit pool_size in main.py (currently 5)
#   - Increase max_overflow

# Solution 2: Add database indexes
#   - On user_id columns
#   - On ticker columns

# Solution 3: Scale PostgreSQL
#   - Increase database instance size
#   - Add read replicas
```

---

## 🚀 MIGRATION (SQLite → PostgreSQL)

### If You Have Existing Data

```bash
# 1. Create PostgreSQL database
# 2. Run migration
python migrate_to_postgres.py \
  /tmp/alerts.db \
  postgresql://user:password@host:5432/discord_bot

# 3. Verify
psql $DATABASE_URL -c "SELECT COUNT(*) FROM alerts"

# 4. Update environment
DATABASE_URL=postgresql://user:password@host:5432/discord_bot

# 5. Restart bot
# All data preserved ✓
```

---

## 📈 DEPLOYMENT OPTIONS

### Option 1: Container Runtime (Easiest ⭐)
```
Pros:
✅ No VM management
✅ Auto-scaling available
✅ Managed by Oracle
✅ Cheaper for low usage

Setup: 5 minutes
Cost: Free tier eligible
```

### Option 2: Compute VM (Most Control)
```
Pros:
✅ Full control
✅ Custom setup
✅ Better for monitoring
✅ Can run multiple services

Setup: 15 minutes
Cost: Starts at ~$0.01/hour
```

### Option 3: Docker Compose (Hybrid)
```
Pros:
✅ Multi-container support
✅ Local dev-prod parity
✅ Easy updates
✅ Good for small teams

Setup: 10 minutes
Cost: Compute VM cost
```

---

## ✅ DEPLOYMENT MATRIX

| Aspect | Container Runtime | Compute VM | Docker Compose |
|--------|-------------------|------------|---|
| Setup time | 5 min | 20 min | 10 min |
| Difficulty | Easy | Medium | Easy |
| Scaling | Automatic | Manual | Manual |
| Cost | Low | Medium | Medium |
| Best for | Getting started | Production | Development |
| Oracle native | ✅ Yes | ⚠️ Compute | ⚠️ Manual |

---

## 🎯 QUICK COMMAND REFERENCE

### Docker
```bash
docker build -t discord-bot:latest .
docker run -e DISCORD_TOKEN="x" -p 8080:8080 discord-bot:latest
docker push ocir.region.oraclecloud.com/namespace/discord-bot:latest
docker logs container_name
docker stop container_name
```

### Database
```bash
# Test connection
psql $DATABASE_URL -c "SELECT 1"

# Migration
python migrate_to_postgres.py /tmp/alerts.db $DATABASE_URL

# Check data
psql $DATABASE_URL -c "SELECT COUNT(*) FROM trades"
```

### Monitoring
```bash
# Health check
curl http://localhost:8080/health

# Real-time logs (Docker)
docker logs -f container_name

# Real-time logs (VM)
sudo journalctl -u discord-bot -f
```

---

## 📞 DOCUMENTATION MAP

| Need | File |
|------|------|
| Quick start | This file |
| Features & commands | README_PRODUCTION.md |
| Detailed deployment | DEPLOYMENT_GUIDE.md |
| Architecture | main.py (inline comments) |
| Changes made | PRODUCTION_UPDATE_SUMMARY.md |
| File index | COMPLETE_FILE_INDEX.md |

---

## ⏱️ TIME ESTIMATES

| Task | Time |
|------|------|
| Read this guide | 5 min |
| Prepare .env | 5 min |
| Build Docker image | 5 min |
| Test locally | 10 min |
| Push to OCR | 2 min |
| Deploy to Oracle | 5 min |
| Verify health | 2 min |
| **TOTAL** | **~35 min** |

---

## 💰 COST ESTIMATE (Oracle Cloud Free Tier)

| Component | Free | Paid |
|-----------|------|------|
| Compute (1 OCPU, 1GB RAM) | ✅ Always free | $0.0116/hr |
| PostgreSQL (20GB) | ✅ Always free | $0.318/GB/mo |
| Data transfer (10TB) | ✅ Always free | $0.0085/GB |
| **Total for free tier** | **$0** | — |

---

## 🆘 EMERGENCY CONTACTS

### If Something Breaks
1. Check logs: `docker logs container_name` or Oracle console
2. Check health: `curl http://ip:8080/health`
3. Check database: `psql $DATABASE_URL -c "SELECT 1"`
4. Check network: `ping host` and firewall rules
5. Restart: `docker restart container_name` or systemctl
6. Read: `DEPLOYMENT_GUIDE.md` troubleshooting section

### If Still Stuck
- Review main.py comments
- Check Oracle Cloud documentation
- Review Discord.py documentation
- Check PostgreSQL logs

---

## 🎉 SUCCESS INDICATORS

✅ Health check returns: `{"status": "healthy", ...}`  
✅ Discord bot shows online  
✅ Commands work in Discord  
✅ Data persists after restart  
✅ No errors in logs  

**You're done! 🚀**

---

## 📝 FINAL CHECKLIST

Before going live:
- [ ] .env created and filled
- [ ] Docker builds successfully
- [ ] Health endpoint works
- [ ] Database backups enabled
- [ ] Security group configured
- [ ] Discord token verified
- [ ] Logs monitored
- [ ] Troubleshooting doc reviewed

---

**Ready? Start deploying! 🚀**

Questions? See DEPLOYMENT_GUIDE.md
Features? See README_PRODUCTION.md

---

*Generated March 27, 2026*
*Version 1.0.0 - Production Ready*
