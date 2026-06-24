"""
🤖 AI Trading Bot v8 - Ultra Professional
Telegram Trading Bot with Multi-Layer AI Analysis
Speculative/Swing Trading: 1 hour to 1 week max
Target: 2-4% daily with minimal risk
"""

import os
import asyncio
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional
import pytz

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from scanner import StockScanner
from analyzer import TechnicalAnalyzer
from ai_gatekeeper import AIGatekeeper
from tracker import TradeTracker
from config import Config

# ─── Logging Setup ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ─── Bot Application ──────────────────────────────────────────────────────────
class TradingBot:
    def __init__(self):
        self.config = Config()
        self.scanner = StockScanner(self.config)
        self.analyzer = TechnicalAnalyzer(self.config)
        self.ai_gate = AIGatekeeper(self.config)
        self.tracker = TradeTracker()
        self.app = None
        self.scan_task = None

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        chat_id = update.effective_chat.id
        self.config.add_chat(chat_id)
        
        msg = (
            "🤖 *AI Trading Bot v8 - Active*\n\n"
            "📊 *Coverage:* Pre-market | Market | After-hours\n"
            "🎯 *Target:* 2-4% per trade | Max 1 week hold\n"
            "⚡ *Mode:* Speculative / Momentum\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋 *Commands:*\n"
            "`/scan` — Force scan now\n"
            "`/status` — Bot status\n"
            "`/stats` — Trade performance\n"
            "`/open` — Open positions\n"
            "`/watchlist` — Current watchlist\n"
            "`/add AAPL TSLA` — Add symbols\n"
            "`/remove AAPL` — Remove symbol\n"
            "`/stop` — Stop alerts\n\n"
            "📩 Send any ticker (e.g. `AAPL`) for instant analysis"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        self.config.remove_chat(chat_id)
        await update.message.reply_text("🔕 Alerts stopped. Use /start to resume.")

    async def scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 Scanning market... Please wait.")
        await self.run_scan(force=True)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats = self.tracker.get_stats()
        eastern = pytz.timezone('US/Eastern')
        now = datetime.now(eastern)
        market_status = self._get_market_status(now)
        
        msg = (
            f"🟢 *Bot Status: Running*\n\n"
            f"🕐 ET Time: `{now.strftime('%H:%M:%S')}`\n"
            f"📈 Market: *{market_status}*\n"
            f"⏱ Scan every: `{self.config.SCAN_INTERVAL}s`\n\n"
            f"📊 *Today's Performance:*\n"
            f"• Signals Sent: `{stats['today_signals']}`\n"
            f"• Wins: `{stats['today_wins']}` | Losses: `{stats['today_losses']}`\n"
            f"• Win Rate: `{stats['win_rate']:.1f}%`\n"
            f"• Avg Profit: `{stats['avg_profit']:.2f}%`"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats = self.tracker.get_full_stats()
        msg = (
            f"📊 *Trade Statistics*\n\n"
            f"🗓 *All Time:*\n"
            f"• Total Signals: `{stats['total']}`\n"
            f"• Wins: `{stats['wins']}` ✅\n"
            f"• Losses: `{stats['losses']}` ❌\n"
            f"• Win Rate: `{stats['win_rate']:.1f}%`\n"
            f"• Avg Win: `+{stats['avg_win']:.2f}%`\n"
            f"• Avg Loss: `-{stats['avg_loss']:.2f}%`\n"
            f"• Best Trade: `+{stats['best']:.2f}%`\n"
            f"• Profit Factor: `{stats['profit_factor']:.2f}`\n\n"
            f"📅 *Last 7 Days:*\n"
            f"• Signals: `{stats['week_signals']}`\n"
            f"• Win Rate: `{stats['week_win_rate']:.1f}%`\n"
            f"• Total Return: `{stats['week_return']:+.2f}%`"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def open_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        positions = self.tracker.get_open_positions()
        if not positions:
            await update.message.reply_text("📭 No open positions tracked.")
            return
        
        msg = "📂 *Open Positions:*\n━━━━━━━━━━━━━━\n"
        for p in positions:
            elapsed = (datetime.utcnow() - datetime.fromisoformat(p['entry_time'])).total_seconds() / 3600
            msg += (
                f"\n`{p['symbol']}` | Entry: `${p['entry']:.2f}`\n"
                f"  🎯 TP1: `${p['tp1']:.2f}` | TP2: `${p['tp2']:.2f}`\n"
                f"  🛑 SL: `${p['sl']:.2f}` | ⏱ `{elapsed:.1f}h ago`\n"
            )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def watchlist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        symbols = self.config.get_watchlist()
        msg = f"👁 *Watchlist ({len(symbols)} symbols):*\n`{' | '.join(symbols[:50])}`"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def add_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: `/add AAPL TSLA NVDA`", parse_mode=ParseMode.MARKDOWN)
            return
        added = []
        for sym in context.args:
            sym = sym.upper().strip()
            if self.config.add_to_watchlist(sym):
                added.append(sym)
        if added:
            await update.message.reply_text(f"✅ Added: `{', '.join(added)}`", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("⚠️ Symbols already in watchlist.")

    async def remove_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: `/remove AAPL`", parse_mode=ParseMode.MARKDOWN)
            return
        sym = context.args[0].upper()
        if self.config.remove_from_watchlist(sym):
            await update.message.reply_text(f"🗑 Removed: `{sym}`", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"⚠️ `{sym}` not in watchlist.", parse_mode=ParseMode.MARKDOWN)

    async def handle_ticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle direct ticker message for instant analysis"""
        text = update.message.text.strip().upper()
        # Quick check if it looks like a ticker (1-5 letters)
        if not (1 <= len(text) <= 5 and text.isalpha()):
            return
        
        msg = await update.message.reply_text(f"⚡ Analyzing `{text}`...", parse_mode=ParseMode.MARKDOWN)
        
        try:
            signal = await self.analyzer.analyze_single(text)
            # Only track & show full signal if score is high enough
            if signal and not signal.get('no_signal') and signal['score'] >= self.config.MIN_SCORE:
                response = self._format_signal(signal, on_demand=True)
                self.tracker.add_signal(signal)  # Track only valid signals
            elif signal:
                score = signal.get('score', 0)
                direction = '🟢 Leaning Long' if score > 50 else '🔴 Leaning Short'
                response = (
                    f"📊 *{text}* — No clear entry\n"
                    f"Score: `{score}/100` | {direction}\n"
                    f"Conditions not strong enough for entry."
                )
            else:
                response = f"❌ Could not fetch data for `{text}`"
            await msg.edit_text(response, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Analysis error for {text}: {e}")
            await msg.edit_text(f"❌ Error analyzing `{text}`. Try again.", parse_mode=ParseMode.MARKDOWN)

    def _format_signal(self, signal: dict, on_demand: bool = False) -> str:
        """Format a trading signal message"""
        direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
        session_emoji = {"pre": "🌅", "open": "📈", "after": "🌙"}.get(signal.get('session', 'open'), "📈")
        
        # Risk/Reward
        entry = signal['entry']
        tp1 = signal['tp1']
        tp2 = signal['tp2']
        sl = signal['stop_loss']
        rr1 = abs(tp1 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
        
        msg = (
            f"{direction_emoji} *{signal['symbol']}* | {session_emoji} {signal.get('session','').upper()}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📥 *Entry:* `${entry:.2f}`\n"
            f"🎯 *TP1:* `${tp1:.2f}` `(+{((tp1-entry)/entry*100):.1f}%)`\n"
            f"🎯 *TP2:* `${tp2:.2f}` `(+{((tp2-entry)/entry*100):.1f}%)`\n"
            f"🛑 *SL:* `${sl:.2f}` `(-{((entry-sl)/entry*100):.1f}%)`\n"
            f"⚖️ *R:R:* `1:{rr1:.1f}`\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Score:* `{signal['score']}/100` | *Conf:* `{signal['confirmations']}`\n"
            f"⏳ *Hold:* `{signal.get('hold_time', '1-3 days')}`\n"
        )
        
        # Add key reasons (max 3)
        reasons = signal.get('reasons', [])[:3]
        if reasons:
            msg += f"💡 *Setup:* {' | '.join(reasons)}\n"
        
        # Volume info
        if signal.get('volume_surge'):
            msg += f"📦 *Vol:* `{signal['volume_surge']:.1f}x avg`\n"
        
        # AI comment
        if signal.get('ai_comment'):
            msg += f"\n🤖 _{signal['ai_comment']}_"
        
        if not on_demand:
            msg += "\n\n⚡ _Auto-detected signal_"
        
        return msg

    def _get_market_status(self, now: datetime) -> str:
        eastern = pytz.timezone('US/Eastern')
        if isinstance(now, datetime) and now.tzinfo is None:
            now = eastern.localize(now)
        
        weekday = now.weekday()
        if weekday >= 5:
            return "Weekend Closed"
        
        t = now.time()
        from datetime import time
        if time(4, 0) <= t < time(9, 30):
            return "Pre-Market 🌅"
        elif time(9, 30) <= t < time(16, 0):
            return "Open 🟢"
        elif time(16, 0) <= t < time(20, 0):
            return "After-Hours 🌙"
        else:
            return "Closed ⛔"

    async def run_scan(self, force: bool = False):
        """Run the main scanning loop"""
        try:
            eastern = pytz.timezone('US/Eastern')
            now = datetime.now(eastern)
            market_status = self._get_market_status(now)
            
            # Skip if market fully closed and not forced
            if "Closed" in market_status and not force:
                logger.info("Market closed — skipping scan")
                return
            
            logger.info(f"🔍 Scanning | {market_status}")
            
            # Get candidates from scanner
            candidates = await self.scanner.get_candidates()
            logger.info(f"📋 Candidates: {len(candidates)}")
            
            signals = []
            for symbol in candidates:
                try:
                    signal = await self.analyzer.analyze(symbol, market_status)
                    if signal and signal['score'] >= self.config.MIN_SCORE:
                        # AI gatekeeper final check
                        approved, comment = await self.ai_gate.approve(signal)
                        if approved:
                            signal['ai_comment'] = comment
                            signals.append(signal)
                except Exception as e:
                    logger.error(f"Error analyzing {symbol}: {e}")
                    continue
            
            # Send signals to all chats
            for signal in signals:
                trade_id = self.tracker.add_signal(signal)
                if trade_id == -1:
                    logger.info(f"Already tracking — skipping broadcast")
                    continue
                msg = self._format_signal(signal)
                await self._broadcast(msg)
                await asyncio.sleep(1)  # Rate limit
            
            # Check existing positions for TP/SL hits
            await self._check_position_updates()
            
        except Exception as e:
            logger.error(f"Scan error: {e}")

    async def _check_position_updates(self):
        """Check open positions for TP/SL hits"""
        positions = self.tracker.get_open_positions()
        for pos in positions:
            try:
                current_price = await self.scanner.get_price(pos['symbol'])
                if current_price is None:
                    continue
                
                symbol = pos['symbol']
                entry = pos['entry']
                tp1 = pos['tp1']
                tp2 = pos['tp2']
                sl = pos['sl']
                
                pnl = ((current_price - entry) / entry) * 100
                
                if current_price >= tp2:
                    self.tracker.close_position(pos['id'], current_price, 'TP2')
                    msg = (
                        f"🏆 *{symbol}* — TP2 HIT!\n"
                        f"Entry: `${entry:.2f}` → `${current_price:.2f}`\n"
                        f"💰 *Profit: `+{pnl:.2f}%`* 🎉"
                    )
                    await self._broadcast(msg)
                    
                elif current_price >= tp1:
                    if not pos.get('tp1_hit'):
                        self.tracker.mark_tp1(pos['id'])
                        msg = (
                            f"✅ *{symbol}* — TP1 Hit\n"
                            f"`${entry:.2f}` → `${current_price:.2f}` `(+{pnl:.2f}%)`\n"
                            f"🔒 Move SL to entry | Hold for TP2"
                        )
                        await self._broadcast(msg)
                        
                elif current_price <= sl:
                    self.tracker.close_position(pos['id'], current_price, 'SL')
                    # 4h cooldown after SL — no re-entry on same symbol
                    orig = self.config.COOLDOWN_SEC
                    self.config.COOLDOWN_SEC = 14400
                    self.config.set_cooldown(symbol)
                    self.config.COOLDOWN_SEC = orig
                    msg = (
                        f"🛑 *{symbol}* — Stop Loss Hit\n"
                        f"Entry: `${entry:.2f}` → `${current_price:.2f}`\n"
                        f"📉 Loss: `{pnl:.2f}%` | No re-entry for 4h ⏳"
                    )
                    await self._broadcast(msg)
                    
                # Time-based exit (max 7 days)
                entry_time = datetime.fromisoformat(pos['entry_time'])
                if (datetime.utcnow() - entry_time).days >= 7:
                    self.tracker.close_position(pos['id'], current_price, 'TIME')
                    msg = (
                        f"⏰ *{symbol}* — Max Hold Reached (7d)\n"
                        f"Closing at `${current_price:.2f}` | P&L: `{pnl:+.2f}%`"
                    )
                    await self._broadcast(msg)
                    
            except Exception as e:
                logger.error(f"Position update error {pos.get('symbol')}: {e}")

    async def _broadcast(self, message: str):
        """Send message to all registered chats"""
        chats = self.config.get_chats()
        for chat_id in chats:
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Broadcast error to {chat_id}: {e}")

    async def scheduled_scan(self, context: ContextTypes.DEFAULT_TYPE):
        """Called by job queue periodically"""
        await self.run_scan()

    def run(self):
        """Start the bot"""
        token = self.config.TELEGRAM_TOKEN
        if not token:
            raise ValueError("TELEGRAM_TOKEN not set!")
        
        self.app = Application.builder().token(token).build()
        
        # Register handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("stop", self.stop_command))
        self.app.add_handler(CommandHandler("scan", self.scan_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("open", self.open_command))
        self.app.add_handler(CommandHandler("watchlist", self.watchlist_command))
        self.app.add_handler(CommandHandler("add", self.add_command))
        self.app.add_handler(CommandHandler("remove", self.remove_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_ticker))
        
        # Schedule scanning
        job_queue = self.app.job_queue
        job_queue.run_repeating(self.scheduled_scan, interval=self.config.SCAN_INTERVAL, first=10)
        
        logger.info("🤖 Trading Bot v8 started!")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
