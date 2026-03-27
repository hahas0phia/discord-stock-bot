# Discord EMA Bot - Production Ready

> **⚠️ Updated for Oracle Cloud Deployment with PostgreSQL Support**

A Discord bot for EMA-based stock scanning, portfolio tracking, price alerts, and trade management with full Oracle Cloud support.

## 🎯 Features

- ✅ **40+ Themed Stock Watchlists** (AI, Quantum, Nuclear, Space, Solar, etc.)
- ✅ **EMA Tier System** (Leading/Mediocre/Lagging based on 9/21/50 EMAs)
- ✅ **Live Market Scans** (/scan, /premarket, /potent, /leaders)
- ✅ **Price Alerts** (DM when stocks hit targets or enter tiers)
- ✅ **Trade Logging** (Entry/exit with P&L tracking)
- ✅ **Portfolio Tracker** (Real-time position monitoring)
- ✅ **IBKR Integration** (Sync positions, auto-calculate stops/targets)
- ✅ **Backtesting** (EMA 9/21 crossover strategy)
- ✅ **Personal Watchlists** (Import/export, morning briefings)
- ✅ **Command Logging** (Full audit trail)
- ✅ **Health Checks** (Ready for production monitoring)

## 🚀 Quick Start (Local Development)

### 1. Install Python 3.9+

```bash
python --version  # Should be 3.9 or higher
```

### 2. Clone & Setup

```bash
cd discord-bot-export
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

pip install -r requirements.txt
```

### 3. Create .env File

```bash
cp .env.example .env
```

Edit `.env`:
```env
DISCORD_TOKEN=your_discord_bot_token_here
DATABASE_URL=sqlite:////tmp/alerts.db
PORT=8080
```

### 4. Run Locally

```bash
python main.py
```

Bot should now be online in your Discord server!

---

## 🌩️ Deployment to Oracle Cloud

### Prerequisites

- Oracle Cloud Account (free tier available)
- Discord Bot Token
- PostgreSQL Database (Oracle Autonomous DB or OCI PostgreSQL)

### Quick Deployment (5 steps)

1. **Create Database**
   ```bash
   # In Oracle Cloud Console → OCI PostgreSQL Database Service
   # Note your connection string
   ```

2. **Update .env**
   ```bash
   DISCORD_TOKEN=your_token
   DATABASE_URL=postgresql://user:password@host:5432/discord_bot
   PORT=8080
   ```

3. **Build Docker Image**
   ```bash
   docker build -t discord-bot:latest .
   docker tag discord-bot:latest ocir.region.oraclecloud.com/namespace/discord-bot:latest
   docker push ocir.region.oraclecloud.com/namespace/discord-bot:latest
   ```

4. **Deploy to Container Runtime**
   ```bash
   # In Oracle Cloud Console → Container Instances → Create Instance
   # Select your image, set environment variables, deploy
   ```

5. **Verify**
   ```bash
   curl http://your-instance-ip:8080/health
   # Should return: {"status": "healthy", ...}
   ```

**📖 Full guide:** See `DEPLOYMENT_GUIDE.md`

---

## 🔧 Configuration

### Environment Variables

| Variable | Required | Default | Example |
|----------|----------|---------|---------|
| `DISCORD_TOKEN` | ✅ Yes | - | your_bot_token |
| `DATABASE_URL` | ❌ No | `sqlite:////tmp/alerts.db` | `postgresql://user:pass@host:5432/db` |
| `PORT` | ❌ No | `8080` | `8080` |

### Database Selection

- **Local/Development:** Uses SQLite (`/tmp/alerts.db`)
- **Production/Oracle Cloud:** Uses PostgreSQL (recommended)

Auto-detection: If `DATABASE_URL` contains `postgresql` or `postgres`, uses PostgreSQL with connection pooling.

---

## 📊 Key Commands

### Scanning
- `/scan` - Full 3-tier EMA scan (200+ stocks)
- `/premarket` - Gap-up/gap-down scanner
- `/potent` - Strong movers (>5% in 1D)
- `/leaders` - Top performers (1-month gains)
- `/stock TICKER` - Single ticker lookup

### Watchlists (40+ themes)
- `/watchlists AI` - AI stocks
- `/watchlists Nuclear` - Nuclear energy
- `/watchlists Space` - Space/aerospace
- `/watchlist add AAPL` - Add to personal list
- `/watchlist scan` - Scan your watchlist

### Portfolio & Trading
- `/portfolio add NVDA 10 150.50` - Add position
- `/portfolio view` - Show positions with live P&L
- `/recommend` - Top buy setups (Martin Luk criteria)
- `/history` - View closed trades
- `/equity +2.3` - Log P&L (sets risk mode)

### Alerts
- `/alert ticker NVDA Leading` - DM when NVDA enters Leading tier
- `/alert premarket 3.0` - DM on gaps > 3%
- `/alert hotsector Technology` - DM if sector becomes top leader
- `/alert target NVDA 200.00` - DM when price hits $200
- `/alerts` - Show all active alerts

### IBKR Integration
- `/ibkr setup` - Connect IBKR account
- `/ibkr sync` - Fetch positions, set alerts
- `/ibkr positions` - View holdings with EMA tier

---

## 🏗️ Architecture

```
main.py
├── Flask App (port 8080)
│   ├── /health → Health check endpoint
│   ├── / → "EMA Bot 24/7 ✅"
│   └── Health monitoring
├── Discord Bot
│   ├── 40+ Slash Commands
│   ├── 4 Background Monitors
│   │   ├── _check_alerts() - Check price/tier alerts every 10 min
│   │   ├── _monitor_trades() - Monitor active trades every 2 min
│   │   ├── _monitor_watchlists() - Check personal lists every 30 min
│   │   └── _morning_watchlist_brief() - Daily 9:30 AM ET summary
│   └── Market Data (yfinance)
└── PostgreSQL Database (or SQLite)
    ├── alerts
    ├── trades
    ├── portfolio
    ├── command_log
    ├── user_watchlists
    └── ibkr_config
```

---

## 🔄 Migration from SQLite to PostgreSQL

If you have existing data in SQLite:

```bash
# 1. Create PostgreSQL database on Oracle Cloud
# 2. Run migration script
python migrate_to_postgres.py /tmp/alerts.db postgresql://user:pass@host:5432/discord_bot

# 3. Update DATABASE_URL in .env
# 4. Restart bot
```

---

## 📈 Performance & Limits

| Metric | Value | Notes |
|--------|-------|-------|
| Rate Limit | 10 scans/min per user | Prevents API spam |
| Tickers Scanned | 200+ | S&P 500 + ETFs + growth stocks |
| Data Retention | Unlimited | PostgreSQL persists data |
| Alert Checks | Every 10 min | During trading hours 4 AM - 6 PM ET |
| Trade Monitoring | Every 2 min | Auto-close on target/stop hit |

---

## 🛡️ Security

✅ **Best Practices**
- Environment variables for secrets
- Database connection pooling
- SQL injection prevention (parameterized queries)
- Health check monitoring
- SSL/TLS for database connections (recommended)
- No hardcoded credentials

⚠️ **Recommendations**
- Use Oracle Secrets Manager for DISCORD_TOKEN in production
- Enable VPC for database (private access only)
- Monitor logs for unusual activity
- Regular database backups
- Rate limiting on scanning endpoints

---

## 🐛 Troubleshooting

### Bot offline on startup

```bash
# Check DISCORD_TOKEN is valid
# Verify bot has required Discord permissions:
# - applications.commands
# - bot
# - guilds
# - guilds.join
```

### Health check failing

```bash
# Test endpoint: curl http://localhost:8080/health
# If fails, check:
# - Port 8080 is not blocked
# - Database connection is valid
# - PostgreSQL is reachable (if using)
```

### Scans timing out

```bash
# yfinance can be slow with 200+ tickers
# Solutions:
# - Reduce watchlist size
# - Increase timeout in yfinance calls
# - Cache results more aggressively
```

### Data lost after restart

```bash
# Ensure using PostgreSQL (not SQLite)
# Verify DATABASE_URL points to persistent database
# Check backups are enabled in Oracle Cloud
```

---

## 📚 Documentation

- **Commands:** Type `/help` in Discord
- **Deployment:** See `DEPLOYMENT_GUIDE.md`
- **Architecture:** See inline code comments in `main.py`
- **Oracle Cloud:** https://docs.oracle.com/
- **Discord.py:** https://discordpy.readthedocs.io/

---

## 📦 Files Overview

| File | Purpose |
|------|---------|
| `main.py` | Main bot code (4000+ lines) |
| `requirements.txt` | Python dependencies |
| `wsgi.py` | WSGI wrapper for Gunicorn |
| `health.py` | Standalone health check service |
| `Dockerfile` | Docker image for Oracle Cloud |
| `app.yaml` | Oracle Container Runtime config |
| `migrate_to_postgres.py` | SQLite → PostgreSQL migration |
| `.env.example` | Environment template |
| `DEPLOYMENT_GUIDE.md` | Detailed deployment instructions |
| `README.md` | This file |

---

## 🤝 Contributing

Found a bug? Have a feature request?
- Check the code comments (well-documented)
- Review existing commands for patterns
- Test thoroughly before deploying to production

---

## 📄 License

Built for Discord trading community. Use responsibly.

---

## 🆘 Support

- **Discord:** Check bot DM logs for error messages
- **Oracle Cloud Issues:** Cloud Console → Compute → Instance Logs
- **Bot Crashes:** Check `wsgi.py` or `main.py` imports are correct

---

**Version:** 1.0.0  
**Last Updated:** March 27, 2026  
**Status:** ✅ Production Ready for Oracle Cloud
