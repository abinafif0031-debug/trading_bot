# 🤖 AI Trading Bot v8 — Ultra Pro

بوت تداول احترافي مدعوم بالذكاء الاصطناعي للسوق الأمريكي

---

## ⚡ المميزات

| Feature | Details |
|---------|---------|
| 📊 Timeframes | 15m + 1h + 1d (multi-timeframe) |
| 🧠 AI Engine | Claude Haiku — final signal gatekeeper |
| 📈 Indicators | 14 indicators (RSI, MACD, BB, EMA, VWAP, ATR, Stoch, ADX, Williams%R, MFI, OBV, CCI + Candle Patterns + S/R) |
| ⏰ Sessions | Pre-market (4am) + Market + After-hours (8pm ET) |
| 🎯 Target | 2-4% per trade |
| ⏳ Hold Time | Hours to 1 week max |
| 📦 Tracking | Auto-tracks all signals, TP/SL hits |
| 💾 Storage | SQLite (no external DB needed) |

---

## 🏗️ Architecture

```
Telegram User
     ↓
  Bot.py (Controller)
     ↓
Scanner → Quick score all watchlist symbols
     ↓
Analyzer → Full 14-indicator multi-TF analysis
     ↓
AI Gatekeeper (Claude Haiku) → Final verdict
     ↓
Signal sent to Telegram + Tracked in SQLite
     ↓
Position Monitor → Auto TP/SL/Time alerts
```

---

## 📊 Signal Example

```
🟢 NVDA | 📈 OPEN
━━━━━━━━━━━━━━━━━━━
📥 Entry: $875.20
🎯 TP1: $892.70 (+2.0%)
🎯 TP2: $910.21 (+4.0%)
🛑 SL: $862.03 (-1.5%)
⚖️ R:R: 1:2.7
━━━━━━━━━━━━━━━━━━━
📊 Score: 74/100 | Conf: 7
⏳ Hold: 2-8 hours
💡 Setup: MACD Bullish Cross | Volume Surge | Above VWAP
📦 Vol: 2.3x avg

🤖 Strong momentum, clean breakout
```

---

## 🚀 Setup

### 1. Clone & Install
```bash
git clone https://github.com/YOUR_USERNAME/trading-bot.git
cd trading-bot
pip install -r requirements.txt
```

### 2. Environment Variables
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run Locally
```bash
python bot.py
```

---

## 🚂 Deploy to Railway

1. Push to GitHub
2. Create new project on [railway.app](https://railway.app)
3. Connect your GitHub repo
4. Add environment variables in Railway dashboard:
   - `TELEGRAM_TOKEN`
   - `ANTHROPIC_API_KEY`
   - `TWELVE_DATA_KEY`
   - `FINNHUB_KEY`
5. Deploy — Railway auto-detects `Procfile`

---

## 📱 Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Start receiving alerts |
| `/stop` | Stop alerts |
| `/scan` | Force scan now |
| `/status` | Bot status + market session |
| `/stats` | All-time performance stats |
| `/open` | View open tracked positions |
| `/watchlist` | Show all symbols |
| `/add AAPL TSLA` | Add symbols to watchlist |
| `/remove AAPL` | Remove symbol |
| `NVDA` (just send ticker) | Instant analysis |

---

## ⚙️ Key Settings (.env)

```
MIN_SCORE=62           # Lower = more signals, higher = fewer but better
MIN_CONFIRMATIONS=4    # Minimum indicator agreement
TP1_PCT=2.0            # Take profit 1
TP2_PCT=4.0            # Take profit 2
SL_PCT=1.5             # Stop loss (tight for speculation)
SCAN_INTERVAL=180      # How often to scan (seconds)
COOLDOWN_SEC=3600      # Min time between alerts for same stock
```

---

## 🔌 APIs Used

| API | Purpose | Cost |
|-----|---------|------|
| Twelve Data | OHLCV candles (15m/1h/1d) | Paid |
| Finnhub | News sentiment, earnings, short interest | Free |
| Anthropic (Claude Haiku) | AI signal gatekeeper | Paid |
| Built-in | SQLite trade tracking | Free |

---

## ⚠️ Disclaimer

هذا البوت للأغراض التعليمية والتجريبية.
التداول ينطوي على مخاطر عالية. لا تستثمر أكثر مما تستطيع تحمل خسارته.
ابدأ دائماً بـ Paper Trading قبل المال الحقيقي.

*This bot is for educational purposes. Trading involves significant risk.*
