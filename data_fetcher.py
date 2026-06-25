"""
Data Fetcher - All API integrations
Twelve Data, Finnhub, Yahoo Finance (yfinance)
"""

import logging
import asyncio
import aiohttp
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
import json

logger = logging.getLogger(__name__)

class DataFetcher:
    def __init__(self, config):
        self.config = config
        self._cache = {}
        self._cache_ttl = {}

    def _is_cached(self, key: str, ttl: int = 60) -> bool:
        if key not in self._cache:
            return False
        age = (datetime.utcnow() - self._cache_ttl[key]).total_seconds()
        return age < ttl

    def _set_cache(self, key: str, data):
        self._cache[key] = data
        self._cache_ttl[key] = datetime.utcnow()

    def _get_cache(self, key: str):
        return self._cache.get(key)

    # Rate limiter: 144 credits/min limit
    # كل scan: 15 سهم × 3 timeframes = 45 طلب
    # نوزعها على 60 ثانية = طلب كل 1.4 ثانية
    _last_request_time = 0.0
    _request_count = 0
    _request_window_start = 0.0
    _MIN_INTERVAL = 1.4  # ثانية بين كل طلب

    async def _rate_limit(self):
        """144 credits/min — طلب كل 1.4 ثانية"""
        import time
        now = time.time()

        # إعادة تعيين العداد كل دقيقة
        if now - self.__class__._request_window_start >= 60:
            self.__class__._request_count = 0
            self.__class__._request_window_start = now

        # إذا اقتربنا من الحد (130) انتظر باقي الدقيقة
        if self.__class__._request_count >= 130:
            wait = 60 - (now - self.__class__._request_window_start)
            if wait > 0:
                logger.info(f"⏳ Rate limit pause: {wait:.1f}s")
                await asyncio.sleep(wait)
            self.__class__._request_count = 0
            self.__class__._request_window_start = time.time()

        # تأكد من مرور 1.4 ثانية بين كل طلب
        elapsed = now - self.__class__._last_request_time
        if elapsed < self._MIN_INTERVAL:
            await asyncio.sleep(self._MIN_INTERVAL - elapsed)

        self.__class__._last_request_time = time.time()
        self.__class__._request_count += 1

    async def get_candles(self, symbol: str, interval: str, outputsize: int = 96) -> Optional[pd.DataFrame]:
        """Fetch OHLCV data from Twelve Data"""
        cache_key = f"candles_{symbol}_{interval}"
        # Cache TTL: 15m=3min, 1h=10min, 1day=30min
        ttl = {"15min": 180, "1h": 600, "1day": 1800}.get(interval, 180)
        if self._is_cached(cache_key, ttl=ttl):
            return self._get_cache(cache_key)

        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol":     symbol,
            "interval":   interval,
            "outputsize": outputsize,
            "apikey":     self.config.TWELVE_DATA_KEY,
            "format":     "JSON",
        }

        try:
            await self._rate_limit()  # Respect API limits
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()

            if data.get("status") == "error" or "values" not in data:
                logger.warning(f"Twelve Data error for {symbol}/{interval}: {data.get('message','')}")
                return None

            df = pd.DataFrame(data["values"])
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.sort_values('datetime')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df.dropna(inplace=True)
            df.set_index('datetime', inplace=True)

            self._set_cache(cache_key, df)
            return df

        except Exception as e:
            logger.error(f"get_candles error {symbol}/{interval}: {e}")
            return None

    async def get_price(self, symbol: str) -> Optional[float]:
        """Get current price - fast"""
        url = "https://api.twelvedata.com/price"
        params = {"symbol": symbol, "apikey": self.config.TWELVE_DATA_KEY}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
            return float(data.get("price", 0)) or None
        except Exception as e:
            logger.error(f"get_price error {symbol}: {e}")
            return None

    async def get_quote(self, symbol: str) -> Optional[dict]:
        """Get full quote from Finnhub"""
        cache_key = f"quote_{symbol}"
        if self._is_cached(cache_key, ttl=30):
            return self._get_cache(cache_key)

        url = f"https://finnhub.io/api/v1/quote"
        params = {"symbol": symbol, "token": self.config.FINNHUB_KEY}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
            if data.get("c"):
                self._set_cache(cache_key, data)
                return data
        except Exception as e:
            logger.error(f"get_quote error {symbol}: {e}")
        return None

    async def get_news_sentiment(self, symbol: str) -> dict:
        """Get news sentiment from Finnhub"""
        cache_key = f"news_{symbol}"
        if self._is_cached(cache_key, ttl=300):
            return self._get_cache(cache_key)

        url = "https://finnhub.io/api/v1/company-news"
        from_date = (datetime.utcnow() - timedelta(days=3)).strftime('%Y-%m-%d')
        to_date   = datetime.utcnow().strftime('%Y-%m-%d')
        params = {
            "symbol": symbol,
            "from":   from_date,
            "to":     to_date,
            "token":  self.config.FINNHUB_KEY,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    articles = await resp.json()

            if not articles:
                return {"score": 0.0, "count": 0, "sentiment": "neutral"}

            # Simple sentiment analysis from headlines
            positive_words = {"surge", "jump", "beat", "record", "rally", "gain", "rise", "up", 
                              "positive", "strong", "bullish", "buy", "upgrade", "outperform", "growth"}
            negative_words = {"drop", "fall", "miss", "decline", "loss", "cut", "down", "weak",
                             "bearish", "sell", "downgrade", "underperform", "concern", "risk", "crash"}

            scores = []
            for article in articles[:10]:  # Last 10 articles
                headline = article.get('headline', '').lower()
                pos = sum(1 for w in positive_words if w in headline)
                neg = sum(1 for w in negative_words if w in headline)
                scores.append(pos - neg)

            avg_score = np.mean(scores) if scores else 0
            sentiment = "positive" if avg_score > 0.3 else ("negative" if avg_score < -0.3 else "neutral")

            result = {"score": float(avg_score), "count": len(articles), "sentiment": sentiment}
            self._set_cache(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"get_news_sentiment error {symbol}: {e}")
            return {"score": 0.0, "count": 0, "sentiment": "neutral"}

    async def get_earnings_calendar(self, symbol: str) -> dict:
        """Check if earnings are coming up (risk filter)"""
        cache_key = f"earnings_{symbol}"
        if self._is_cached(cache_key, ttl=3600):
            return self._get_cache(cache_key)

        url = "https://finnhub.io/api/v1/calendar/earnings"
        from_date = datetime.utcnow().strftime('%Y-%m-%d')
        to_date   = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d')
        params = {"from": from_date, "to": to_date, "symbol": symbol, "token": self.config.FINNHUB_KEY}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()

            earnings = data.get("earningsCalendar", [])
            upcoming = [e for e in earnings if e.get("symbol") == symbol]
            
            result = {
                "has_earnings": len(upcoming) > 0,
                "days_until": None,
                "date": upcoming[0].get("date") if upcoming else None
            }
            if upcoming:
                try:
                    earn_date = datetime.strptime(upcoming[0]['date'], '%Y-%m-%d')
                    result['days_until'] = (earn_date - datetime.utcnow()).days
                except:
                    pass

            self._set_cache(cache_key, result)
            return result

        except Exception as e:
            logger.error(f"get_earnings_calendar error {symbol}: {e}")
            return {"has_earnings": False, "days_until": None, "date": None}

    async def get_short_interest(self, symbol: str) -> Optional[float]:
        """Get short interest ratio from Finnhub"""
        cache_key = f"short_{symbol}"
        if self._is_cached(cache_key, ttl=3600):
            return self._get_cache(cache_key)

        url = "https://finnhub.io/api/v1/stock/short-interest"
        params = {"symbol": symbol, "token": self.config.FINNHUB_KEY}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
            
            shorts = data.get("data", [])
            if shorts:
                # Short ratio = short shares / avg daily volume
                short_shares = shorts[-1].get("shortInterest", 0)
                avg_vol = shorts[-1].get("avgVolume", 1)
                ratio = short_shares / avg_vol if avg_vol else 0
                self._set_cache(cache_key, ratio)
                return ratio
        except Exception as e:
            logger.error(f"get_short_interest error {symbol}: {e}")
        return None

    async def get_premarket_data(self, symbol: str) -> dict:
        """Get pre-market / after-hours data"""
        try:
            url = "https://api.twelvedata.com/quote"
            params = {
                "symbol":         symbol,
                "apikey":         self.config.TWELVE_DATA_KEY,
                "prepost":        "true",
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
            
            if data.get("status") == "error":
                return {}
            
            return {
                "pre_change_pct": float(data.get("percent_change", 0)),
                "pre_price":      float(data.get("close", 0)),
                "pre_volume":     int(data.get("volume", 0)),
            }
        except Exception as e:
            logger.error(f"get_premarket_data error {symbol}: {e}")
            return {}

    async def get_market_breadth(self) -> dict:
        """Get SPY data as market breadth indicator"""
        df = await self.get_candles("QQQ", "15min", outputsize=96)
        if df is None:
            return {"spy_trend": "unknown"}
        
        close = df['close']
        ema_short = close.ewm(span=8, adjust=False).mean()
        ema_long  = close.ewm(span=21, adjust=False).mean()
        
        spy_trend = "up" if ema_short.iloc[-1] > ema_long.iloc[-1] else "down"
        spy_momentum = ((close.iloc[-1] - close.iloc[-8]) / close.iloc[-8]) * 100
        
        return {
            "spy_trend":    spy_trend,
            "spy_momentum": float(spy_momentum),
        }
