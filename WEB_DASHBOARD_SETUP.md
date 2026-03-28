# 🔐 Web Dashboard Setup Guide

## Overview

Your Discord bot now includes a **private, token-based web dashboard** that allows users to securely view their portfolio, trade history, watchlist, and alerts from any web browser.

---

## 🚀 Quick Start

### 1. **Generate Your Access Token in Discord**

Inside your Discord server where the bot is running, use:
```
/web token
```

The bot will DM you with a **personal access token**. This token:
- Grants access to **your data only**
- Expires in **30 days**
- Is shown **only once** — save it in a safe place
- Should be treated like a password

### 2. **Access Your Dashboard**

Replace `YOUR_ORACLE_IP` with your server's IP address, then open in your browser:
```
http://YOUR_ORACLE_IP:8080/dashboard?token=YOUR_TOKEN_HERE
```

Example:
```
http://130.123.456.789:8080/dashboard?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 3. **View Your Data**

Once logged in, you'll see:
- 📊 **Portfolio**: All your open positions with cost basis
- 📋 **Closed Trades**: Trade history with P&L
- 🔍 **Watchlist**: Your saved ticker watchlist
- 🔔 **Alerts**: Active price & tier alerts

---

## 📋 Available Commands

### `/web token`
Generates a new 30-day access token for web dashboard access.
**Output:** Personal token (shown only once in your DM)

### `/web tokens`
Lists all your active tokens with creation date and last used timestamp.
**Use:** Check which devices/sessions are accessing your dashboard

### `/web revoke`
Revokes ALL active tokens immediately.
**Use:** Emergency logout — invalidates all web sessions

---

## 🔒 Security Features

✅ **Token-Based Auth**: No passwords needed
✅ **Private Data**: Only you can access your data with your token
✅ **No Plaintext Storage**: Tokens are hashed with SHA256
✅ **Auto-Expiry**: Tokens expire after 30 days
✅ **Session Tracking**: Dashboard records API calls (in command_log)
✅ **Revoke Anytime**: Kill all sessions instantly with `/web revoke`

---

## 🛠 Backend Architecture

### Database Schema
```sql
-- New table for token management
CREATE TABLE web_tokens (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,     -- SHA256 hash
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_used_at TEXT,
    is_active BOOLEAN DEFAULT 1
);
```

### Flask API Endpoints

| Endpoint | Method | Auth | Returns |
|----------|--------|------|---------|
| `/dashboard` | GET | Token URL | HTML dashboard page |
| `/api/portfolio` | GET | Bearer token | User's open positions |
| `/api/trades` | GET | Bearer token | Last 50 closed trades |
| `/api/watchlist` | GET | Bearer token | User's saved watchlist |
| `/api/alerts` | GET | Bearer token | Active price & tier alerts |

**Example API Call:**
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://your-ip:8080/api/portfolio
```

Response:
```json
{
  "success": true,
  "portfolio": [
    {
      "ticker": "AAPL",
      "shares": 100,
      "entry_price": 150.50,
      "cost_basis": 15050.00,
      "added_at": "2026-03-20T14:30:00"
    }
  ],
  "summary": {
    "total_cost_basis": 15050.00,
    "position_count": 1
  }
}
```

---

## 📦 Deployment on Oracle Cloud

### Step 1: Upload Files to Oracle Instance

```bash
scp -r discord-bot-export ubuntu@YOUR_ORACLE_IP:/home/ubuntu/
```

### Step 2: Set Environment Variables

Add to your `.env` file:
```env
# Ensure these are set
DISCORD_TOKEN=your_token_here
DATABASE_URL=postgresql://user:password@localhost/botdb
PORT=8080

# Optional: Custom token secret
TOKEN_SECRET=your_secret_key_here
```

### Step 3: Update Oracle Security List

In Oracle Cloud Console:
- Go to **Networking → Virtual Cloud Networks**
- Find your VCN
- Edit **Security Lists**
- Add **Ingress Rule** for Port 8080:
  - **Source:** 0.0.0.0/0
  - **Protocol:** TCP
  - **Port Range:** 8080

### Step 4: Restart Bot

```bash
pkill -f main.py
python /home/ubuntu/discord-bot-export/main.py &
```

### Step 5: Test the Dashboard

1. Generate token in Discord: `/web token`
2. Open: `http://YOUR_ORACLE_IP:8080/dashboard?token=YOUR_TOKEN`
3. You should see your portfolio data

---

## 🔧 Configuration

### Token Expiry

Edit `main.py` line ~32:
```python
TOKEN_EXPIRY_DAYS = 30  # Change to 7, 60, etc.
```

### Token Length

Edit `main.py` line ~33:
```python
TOKEN_LENGTH = 32  # Longer = more secure but harder to copy
```

### API Rate Limiting (Future)

Coming soon: Add `/api/rate-limit` headers to prevent abuse

---

## ❌ Troubleshooting

### "Session Expired" Error

Your token may have expired. Generate a new one:
```
/web token
```

### Dashboard Shows "Connecting..."

Check:
1. Flask server is running (`PORT=8080` in logs)
2. Database connection is working
3. Firewall allows port 8080
4. Token is correct (no typos)

### "Invalid Token" Response

This usually means:
- Token was revoked (`/web revoke`)
- Token expired (30 days old)
- Token is malformed (copied incorrectly)

Generate a fresh token with `/web token`

### Can't Access `/api/portfolio`

Make sure you're sending the Authorization header:
```
Authorization: Bearer YOUR_TOKEN_HERE
```

(Not just the raw token)

---

## 🎯 Future Enhancements

- [ ] Real-time price updates for portfolio
- [ ] Interactive charts for trade history
- [ ] Export to PDF/CSV from dashboard
- [ ] Mobile app version
- [ ] Dark mode toggle (already built in!)
- [ ] Multi-user dashboard (for agencies)
- [ ] WebSocket for live updates
- [ ] 2FA for extra security

---

## 📞 Support

If you encounter issues:

1. Check bot is running: `/ping`
2. View command log: `/commandlog`
3. Check database: Verify `web_tokens` table exists
4. Review Flask logs in console

---

## 🎓 How It Works (Technical Deep Dive)

### Flow Diagram

```
User in Discord
      ↓
   /web token
      ↓
Bot generates: token (plaintext) + token_hash (SHA256)
      ↓
Bot stores: token_hash in database
      ↓
Bot DMs user: plaintext token (only shown once!)
      ↓
User pastes token in browser
      ↓
Browser requests: /dashboard?token=...
      ↓
Server hashes the token, looks up in database
      ↓
Server verifies: token_hash matches, not expired, still active
      ↓
Server serves dashboard.html with token embedded
      ↓
Dashboard makes API calls with Authorization: Bearer token header
      ↓
Each API endpoint verifies token again, returns user-specific data
      ↓
Dashboard displays portfolio/trades/watchlist/alerts
```

### Why This Approach?

✅ **No Passwords**: Tokens are generated, not chosen by users
✅ **No Session Storage**: Each request is independent
✅ **Stateless**: Can scale to multiple servers (database is the source of truth)
✅ **One-Time Display**: Token shown only once, prevents accidental sharing
✅ **Easy Revocation**: `/web revoke` instantly kills all sessions

---

## 📄 File Summary

| File | Purpose |
|------|---------|
| `main.py` | Bot + Flask server with new API endpoints |
| `dashboard.html` | Web UI for dashboard (served dynamically) |
| `WEB_DASHBOARD_SETUP.md` | This guide |

---

## 🚨 Security Checklist

Before deploying to production:

- [ ] `TOKEN_SECRET` is set to a strong random value
- [ ] Firewall only allows 8080 from your IP range (optional but recommended)
- [ ] HTTPS is enabled (for production, use reverse proxy like nginx)
- [ ] Database backups are enabled
- [ ] Token rotation policy is documented
- [ ] Users are advised to treat tokens like passwords
- [ ] Rate limiting is implemented on API

---

**Enjoy your secure, private trading dashboard!** 🎉
