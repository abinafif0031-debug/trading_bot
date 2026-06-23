"""
Technical Analyzer - Multi-Timeframe Analysis Engine
Indicators: RSI, MACD, BB, EMA, VWAP, ATR, OBV, Stochastic, ADX, Williams%R, MFI, CCI
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import pytz

from data_fetcher import DataFetcher

logger = logging.getLogger(__name__)

class TechnicalAnalyzer:
    def __init__(self, config):
        self.config = config
        self.fetcher = DataFetcher(config)

    async def analyze(self, symbol: str, market_status: str = "open") -> Optional[dict]:
        """Full multi-timeframe analysis"""
        if self.config.is_on_cooldown(symbol):
            return None

        try:
            # Fetch data for all timeframes
            df_15m = await self.fetcher.get_candles(symbol, "15min", outputsize=96)    # 24h
            df_1h  = await self.fetcher.get_candles(symbol, "1h",    outputsize=72)    # 3d
            df_1d  = await self.fetcher.get_candles(symbol, "1day",  outputsize=60)    # 60d

            if df_15m is None or len(df_15m) < 30:
                return None
            if df_1h is None or len(df_1h) < 20:
                return None
            if df_1d is None or len(df_1d) < 20:
                return None

            # Basic filters
            current_price = float(df_15m['close'].iloc[-1])
            if not (self.config.MIN_PRICE <= current_price <= self.config.MAX_PRICE):
                return None

            # Volume filter
            avg_vol = df_1d['volume'].mean()
            if avg_vol < self.config.MIN_VOLUME:
                return None

            # ── Analyze each timeframe ─────────────────────────────────────
            score_15m, sigs_15m = self._score_timeframe(df_15m, "15m")
            score_1h,  sigs_1h  = self._score_timeframe(df_1h,  "1h")
            score_1d,  sigs_1d  = self._score_timeframe(df_1d,  "1d")

            # Weighted score (45% 15m, 35% 1h, 20% 1d)
            total_score = (score_15m * 0.45) + (score_1h * 0.35) + (score_1d * 0.20)
            total_score = round(total_score)

            all_signals = sigs_15m + sigs_1h + sigs_1d
            
            # Determine direction from signals
            long_sigs  = [s for s in all_signals if s.startswith('+')]
            short_sigs = [s for s in all_signals if s.startswith('-')]
            direction  = "LONG" if len(long_sigs) >= len(short_sigs) else "SHORT"

            # Re-score based on direction alignment
            if direction == "LONG":
                confirmations = len(long_sigs)
            else:
                confirmations = len(short_sigs)

            if total_score < self.config.MIN_SCORE:
                return None
            if confirmations < self.config.MIN_CONFIRMATIONS:
                return None

            # ── Calculate entry/TP/SL ─────────────────────────────────────
            atr = self._calc_atr(df_15m, period=14)
            
            entry = current_price
            if direction == "LONG":
                tp1 = round(entry * (1 + self.config.TP1_PCT / 100), 2)
                tp2 = round(entry * (1 + self.config.TP2_PCT / 100), 2)
                sl  = round(max(entry - atr * 1.5, entry * (1 - self.config.SL_PCT / 100)), 2)
            else:
                tp1 = round(entry * (1 - self.config.TP1_PCT / 100), 2)
                tp2 = round(entry * (1 - self.config.TP2_PCT / 100), 2)
                sl  = round(min(entry + atr * 1.5, entry * (1 + self.config.SL_PCT / 100)), 2)

            # Volume surge
            recent_vol  = df_15m['volume'].iloc[-1]
            avg_vol_15m = df_15m['volume'].iloc[-20:-1].mean()
            vol_surge   = recent_vol / avg_vol_15m if avg_vol_15m > 0 else 1.0

            # Session
            eastern = pytz.timezone('US/Eastern')
            now = datetime.now(eastern)
            from datetime import time as dtime
            t = now.time()
            if dtime(4, 0) <= t < dtime(9, 30):
                session = "pre"
            elif dtime(9, 30) <= t < dtime(16, 0):
                session = "open"
            else:
                session = "after"

            # Hold time estimate
            hold_time = self._estimate_hold(score_15m, score_1h, score_1d)

            # Top reasons (clean labels)
            reasons = self._get_reasons(all_signals, direction)[:3]

            self.config.set_cooldown(symbol)

            return {
                "symbol":       symbol,
                "direction":    direction,
                "score":        total_score,
                "confirmations": confirmations,
                "entry":        entry,
                "tp1":          tp1,
                "tp2":          tp2,
                "stop_loss":    sl,
                "atr":          atr,
                "volume_surge": vol_surge,
                "session":      session,
                "hold_time":    hold_time,
                "reasons":      reasons,
                "score_15m":    score_15m,
                "score_1h":     score_1h,
                "score_1d":     score_1d,
                "signals":      all_signals,
                "timestamp":    datetime.utcnow().isoformat(),
                "price":        current_price,
            }

        except Exception as e:
            logger.error(f"Analyzer error {symbol}: {e}")
            return None

    async def analyze_single(self, symbol: str) -> Optional[dict]:
        """On-demand analysis - skip cooldown"""
        original_cooldown = self.config.COOLDOWN_SEC
        self.config.COOLDOWN_SEC = 0  # Bypass cooldown for manual requests
        result = await self.analyze(symbol)
        self.config.COOLDOWN_SEC = original_cooldown
        
        # If no signal, still return partial data
        if result is None:
            try:
                df_15m = await self.fetcher.get_candles(symbol, "15min", outputsize=50)
                if df_15m is not None and len(df_15m) > 20:
                    score, sigs = self._score_timeframe(df_15m, "15m")
                    return {
                        "symbol": symbol,
                        "score": score,
                        "direction": "LONG" if score > 50 else "SHORT",
                        "entry": float(df_15m['close'].iloc[-1]),
                        "tp1": 0, "tp2": 0, "stop_loss": 0,
                        "confirmations": 0,
                        "reasons": [],
                        "no_signal": True
                    }
            except:
                pass
        return result

    def _score_timeframe(self, df: pd.DataFrame, label: str) -> tuple:
        """Score a single timeframe 0-100, return (score, signals)"""
        signals = []
        score = 50  # Neutral start

        try:
            close = df['close']
            high  = df['high']
            low   = df['low']
            vol   = df['volume']
            
            # ── 1. RSI (14) ───────────────────────────────────────────────
            rsi = self._rsi(close, 14)
            if rsi < 35:
                score += 8; signals.append("+RSI_OB")
            elif rsi < 45:
                score += 4; signals.append("+RSI_OK")
            elif rsi > 65:
                score -= 8; signals.append("-RSI_OS")
            elif rsi > 55:
                score -= 4; signals.append("-RSI_OK")
            
            # ── 2. MACD ──────────────────────────────────────────────────
            macd, signal_line, hist = self._macd(close)
            if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
                score += 12; signals.append("+MACD_X")  # Bullish crossover
            elif hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2]:
                score += 6; signals.append("+MACD_UP")
            elif hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
                score -= 12; signals.append("-MACD_X")
            elif hist.iloc[-1] < 0 and hist.iloc[-1] < hist.iloc[-2]:
                score -= 6; signals.append("-MACD_DN")

            # ── 3. Bollinger Bands ───────────────────────────────────────
            bb_up, bb_mid, bb_lo = self._bollinger(close, 20, 2)
            price = close.iloc[-1]
            bb_pos = (price - bb_lo.iloc[-1]) / (bb_up.iloc[-1] - bb_lo.iloc[-1] + 1e-8)
            
            if bb_pos < 0.1:
                score += 10; signals.append("+BB_LOW")   # Near lower band
            elif bb_pos < 0.3:
                score += 5; signals.append("+BB_OK")
            elif bb_pos > 0.9:
                score -= 10; signals.append("-BB_HIGH")
            elif bb_pos > 0.7:
                score -= 5; signals.append("-BB_OK")
            
            # Squeeze (low volatility = breakout incoming)
            bb_width = (bb_up.iloc[-1] - bb_lo.iloc[-1]) / bb_mid.iloc[-1]
            if bb_width < 0.03:
                score += 6; signals.append("+BB_SQZ")

            # ── 4. EMAs ──────────────────────────────────────────────────
            ema9  = close.ewm(span=9, adjust=False).mean()
            ema21 = close.ewm(span=21, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()
            
            if price > ema9.iloc[-1] > ema21.iloc[-1] > ema50.iloc[-1]:
                score += 10; signals.append("+EMA_BULL")   # Perfect bull alignment
            elif price > ema21.iloc[-1] > ema50.iloc[-1]:
                score += 6; signals.append("+EMA_OK")
            elif price < ema9.iloc[-1] < ema21.iloc[-1] < ema50.iloc[-1]:
                score -= 10; signals.append("-EMA_BEAR")
            elif price < ema21.iloc[-1] < ema50.iloc[-1]:
                score -= 6; signals.append("-EMA_OK")
            
            # EMA9 cross EMA21
            if ema9.iloc[-1] > ema21.iloc[-1] and ema9.iloc[-2] <= ema21.iloc[-2]:
                score += 8; signals.append("+EMA_X")

            # ── 5. VWAP ──────────────────────────────────────────────────
            if len(df) >= 20:
                vwap = self._vwap(df)
                if price > vwap * 1.002:
                    score += 6; signals.append("+VWAP")
                elif price < vwap * 0.998:
                    score -= 6; signals.append("-VWAP")

            # ── 6. Stochastic ────────────────────────────────────────────
            stoch_k, stoch_d = self._stochastic(high, low, close, 14, 3)
            if stoch_k.iloc[-1] < 25 and stoch_k.iloc[-1] > stoch_d.iloc[-1]:
                score += 8; signals.append("+STOCH_X")   # Oversold crossover
            elif stoch_k.iloc[-1] > 75 and stoch_k.iloc[-1] < stoch_d.iloc[-1]:
                score -= 8; signals.append("-STOCH_X")

            # ── 7. ADX (Trend Strength) ──────────────────────────────────
            adx, di_plus, di_minus = self._adx(high, low, close, 14)
            if adx.iloc[-1] > 25:
                if di_plus.iloc[-1] > di_minus.iloc[-1]:
                    score += 8; signals.append("+ADX_BULL")
                else:
                    score -= 8; signals.append("-ADX_BEAR")

            # ── 8. Williams %R ────────────────────────────────────────────
            willr = self._williams_r(high, low, close, 14)
            if willr.iloc[-1] < -80:
                score += 6; signals.append("+WILLR")
            elif willr.iloc[-1] > -20:
                score -= 6; signals.append("-WILLR")

            # ── 9. MFI (Money Flow Index) ────────────────────────────────
            mfi = self._mfi(high, low, close, vol, 14)
            if mfi.iloc[-1] < 25:
                score += 6; signals.append("+MFI")
            elif mfi.iloc[-1] > 75:
                score -= 6; signals.append("-MFI")

            # ── 10. OBV Trend ─────────────────────────────────────────────
            obv = (vol * np.sign(close.diff())).cumsum()
            obv_ema = obv.ewm(span=10).mean()
            if obv.iloc[-1] > obv_ema.iloc[-1]:
                score += 5; signals.append("+OBV")
            else:
                score -= 5; signals.append("-OBV")

            # ── 11. CCI ───────────────────────────────────────────────────
            cci = self._cci(high, low, close, 20)
            if cci.iloc[-1] < -100:
                score += 5; signals.append("+CCI")
            elif cci.iloc[-1] > 100:
                score -= 5; signals.append("-CCI")

            # ── 12. Volume Confirmation ───────────────────────────────────
            avg_vol = vol.rolling(20).mean()
            if vol.iloc[-1] > avg_vol.iloc[-1] * 1.5:
                # Volume surge - amplify the signal direction
                main_dir = "+VOL" if score > 50 else "-VOL"
                if score > 50:
                    score += 8; signals.append("+VOL_SURGE")
                else:
                    score -= 8; signals.append("-VOL_SURGE")
            
            # ── 13. Candlestick Patterns ──────────────────────────────────
            pattern = self._check_patterns(df)
            if pattern == "bullish":
                score += 8; signals.append("+CANDLE_BULL")
            elif pattern == "bearish":
                score -= 8; signals.append("-CANDLE_BEAR")

            # ── 14. Support/Resistance Break ─────────────────────────────
            sr_signal = self._sr_break(high, low, close)
            if sr_signal == "break_up":
                score += 10; signals.append("+SR_BREAK")
            elif sr_signal == "break_down":
                score -= 10; signals.append("-SR_BREAK")

        except Exception as e:
            logger.error(f"Scoring error {label}: {e}")

        score = max(0, min(100, score))
        return score, signals

    # ─── Indicator Calculations ───────────────────────────────────────────────

    def _rsi(self, close: pd.Series, period: int = 14) -> float:
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / (loss + 1e-8)
        rsi   = 100 - 100 / (1 + rs)
        return float(rsi.iloc[-1])

    def _macd(self, close: pd.Series, fast=12, slow=26, signal=9):
        ema_fast   = close.ewm(span=fast, adjust=False).mean()
        ema_slow   = close.ewm(span=slow, adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram  = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _bollinger(self, close: pd.Series, period=20, std_dev=2):
        mid  = close.rolling(period).mean()
        std  = close.rolling(period).std()
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        return upper, mid, lower

    def _vwap(self, df: pd.DataFrame) -> float:
        tp  = (df['high'] + df['low'] + df['close']) / 3
        vwap = (tp * df['volume']).cumsum() / df['volume'].cumsum()
        return float(vwap.iloc[-1])

    def _stochastic(self, high, low, close, k_period=14, d_period=3):
        lowest_low   = low.rolling(k_period).min()
        highest_high = high.rolling(k_period).max()
        k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-8)
        d = k.rolling(d_period).mean()
        return k, d

    def _adx(self, high, low, close, period=14):
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)

        dm_plus  = high.diff()
        dm_minus = -low.diff()
        dm_plus[dm_plus  < 0] = 0
        dm_minus[dm_minus < 0] = 0
        dm_plus[dm_plus < dm_minus] = 0
        dm_minus[dm_minus < dm_plus] = 0

        atr_s    = tr.rolling(period).mean()
        di_plus  = 100 * dm_plus.rolling(period).mean()  / (atr_s + 1e-8)
        di_minus = 100 * dm_minus.rolling(period).mean() / (atr_s + 1e-8)
        dx  = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus + 1e-8)
        adx = dx.rolling(period).mean()
        return adx, di_plus, di_minus

    def _williams_r(self, high, low, close, period=14):
        highest_high = high.rolling(period).max()
        lowest_low   = low.rolling(period).min()
        wr = -100 * (highest_high - close) / (highest_high - lowest_low + 1e-8)
        return wr

    def _mfi(self, high, low, close, volume, period=14):
        tp = (high + low + close) / 3
        mf = tp * volume
        pos_mf = mf.where(tp > tp.shift(1), 0)
        neg_mf = mf.where(tp < tp.shift(1), 0)
        mfr = pos_mf.rolling(period).sum() / (neg_mf.rolling(period).sum() + 1e-8)
        mfi = 100 - 100 / (1 + mfr)
        return mfi

    def _cci(self, high, low, close, period=20):
        tp   = (high + low + close) / 3
        sma  = tp.rolling(period).mean()
        mad  = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())))
        cci  = (tp - sma) / (0.015 * mad + 1e-8)
        return cci

    def _calc_atr(self, df: pd.DataFrame, period=14) -> float:
        high  = df['high']
        low   = df['low']
        close = df['close']
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])

    def _check_patterns(self, df: pd.DataFrame) -> str:
        """Check for bullish/bearish candle patterns"""
        o = df['open']; h = df['high']; l = df['low']; c = df['close']
        
        # Last 2 candles
        body1 = abs(c.iloc[-1] - o.iloc[-1])
        body2 = abs(c.iloc[-2] - o.iloc[-2])
        range1 = h.iloc[-1] - l.iloc[-1]

        # Hammer (bullish)
        lower_wick = min(o.iloc[-1], c.iloc[-1]) - l.iloc[-1]
        if lower_wick > body1 * 2 and c.iloc[-1] > o.iloc[-1]:
            return "bullish"

        # Bullish engulfing
        if (c.iloc[-2] < o.iloc[-2] and  # Previous was bearish
            c.iloc[-1] > o.iloc[-1] and  # Current is bullish
            c.iloc[-1] > o.iloc[-2] and  # Current close > prev open
            o.iloc[-1] < c.iloc[-2]):    # Current open < prev close
            return "bullish"

        # Shooting star / Bearish engulfing
        upper_wick = h.iloc[-1] - max(o.iloc[-1], c.iloc[-1])
        if upper_wick > body1 * 2 and c.iloc[-1] < o.iloc[-1]:
            return "bearish"

        if (c.iloc[-2] > o.iloc[-2] and
            c.iloc[-1] < o.iloc[-1] and
            c.iloc[-1] < o.iloc[-2] and
            o.iloc[-1] > c.iloc[-2]):
            return "bearish"

        return "neutral"

    def _sr_break(self, high, low, close) -> str:
        """Detect support/resistance breakout"""
        # Use last 20 candles as S/R zone
        lookback = 20
        recent_high = high.iloc[-lookback:-2].max()
        recent_low  = low.iloc[-lookback:-2].min()
        
        price = close.iloc[-1]
        prev_price = close.iloc[-2]

        if prev_price <= recent_high and price > recent_high * 1.001:
            return "break_up"
        if prev_price >= recent_low and price < recent_low * 0.999:
            return "break_down"
        return "none"

    def _estimate_hold(self, s15, s1h, s1d) -> str:
        """Estimate trade duration based on signal strength"""
        if s15 > 70 and s1h > 65:
            return "2-8 hours"
        elif s1h > 65:
            return "1-2 days"
        elif s1d > 65:
            return "2-5 days"
        else:
            return "1-3 days"

    def _get_reasons(self, signals: list, direction: str) -> list:
        """Convert signal codes to human-readable reasons"""
        mapping = {
            "+RSI_OB":    "RSI Oversold",
            "+MACD_X":    "MACD Bullish Cross",
            "+MACD_UP":   "MACD Positive",
            "+BB_LOW":    "Near BB Support",
            "+BB_SQZ":    "BB Squeeze → Breakout",
            "+EMA_BULL":  "Full EMA Alignment",
            "+EMA_X":     "EMA9×21 Cross",
            "+VWAP":      "Above VWAP",
            "+STOCH_X":   "Stoch Oversold Cross",
            "+ADX_BULL":  "Strong Uptrend (ADX)",
            "+WILLR":     "Williams %R Oversold",
            "+MFI":       "Money Flow Oversold",
            "+OBV":       "OBV Bullish",
            "+CCI":       "CCI Oversold",
            "+VOL_SURGE": "Volume Surge",
            "+CANDLE_BULL": "Bullish Pattern",
            "+SR_BREAK":  "Resistance Break",
            "-RSI_OS":    "RSI Overbought",
            "-MACD_X":    "MACD Bearish Cross",
            "-BB_HIGH":   "Near BB Resistance",
            "-EMA_BEAR":  "Full EMA Bear",
            "-VWAP":      "Below VWAP",
            "-STOCH_X":   "Stoch Overbought",
            "-ADX_BEAR":  "Strong Downtrend",
            "-WILLR":     "Williams %R Overbought",
            "-VOL_SURGE": "Volume Selling",
            "-CANDLE_BEAR": "Bearish Pattern",
            "-SR_BREAK":  "Support Break",
        }
        prefix = "+" if direction == "LONG" else "-"
        relevant = [mapping.get(s, s) for s in signals if s.startswith(prefix)]
        return list(dict.fromkeys(relevant))  # Deduplicate preserving order
