"""
Stock Scanner - Finds high-probability candidates
Filters by: momentum, volume surge, gap, pre-market activity
"""

import logging
import asyncio
from typing import List, Optional
from data_fetcher import DataFetcher

logger = logging.getLogger(__name__)

class StockScanner:
    def __init__(self, config):
        self.config = config
        self.fetcher = DataFetcher(config)

    async def get_candidates(self) -> List[str]:
        """
        Multi-stage filtering to find top candidates:
        1. Get watchlist
        2. Filter by momentum + volume 
        3. Sort by opportunity score
        4. Return top N
        """
        watchlist = self.config.get_watchlist()
        
        # Skip SPY/QQQ/ETFs for individual analysis (they have different dynamics)
        etfs = {"SPY", "QQQ", "TQQQ", "SQQQ", "SOXL", "SOXS"}
        stocks = [s for s in watchlist if s not in etfs]
        
        # Get market context first
        market = await self.fetcher.get_market_breadth()
        logger.info(f"Market: SPY trend={market.get('spy_trend')} momentum={market.get('spy_momentum',0):.2f}%")
        
        # Score each symbol quickly (lightweight check)
        scored = []
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
        
        async def quick_score(symbol: str):
            async with semaphore:
                try:
                    score = await self._quick_score(symbol, market)
                    if score > 0:
                        scored.append((symbol, score))
                except Exception as e:
                    logger.debug(f"Quick score error {symbol}: {e}")
        
        await asyncio.gather(*[quick_score(s) for s in stocks])
        
        # Sort by score, return top 15
        scored.sort(key=lambda x: x[1], reverse=True)
        candidates = [s for s, _ in scored[:15]]
        
        # Skip symbols on cooldown
        candidates = [s for s in candidates if not self.config.is_on_cooldown(s)]
        
        logger.info(f"Candidates after filter: {candidates[:10]}")
        return candidates

    async def _quick_score(self, symbol: str, market: dict) -> float:
        """
        Lightweight score to decide if worth full analysis.
        Uses only 15m candles and volume.
        """
        df = await self.fetcher.get_candles(symbol, "15min", outputsize=20)
        if df is None or len(df) < 15:
            return 0
        
        close = df['close']
        vol   = df['volume']
        
        score = 0
        price = float(close.iloc[-1])
        
        # Basic price filter
        if not (self.config.MIN_PRICE <= price <= self.config.MAX_PRICE):
            return 0
        
        # Volume surge (most important quick filter)
        avg_vol = vol.iloc[:-1].mean()
        recent_vol = vol.iloc[-1]
        if avg_vol > 0:
            vol_ratio = recent_vol / avg_vol
            if vol_ratio > 2.0:
                score += 30
            elif vol_ratio > 1.5:
                score += 15
            elif vol_ratio > 1.2:
                score += 5
            elif vol_ratio < 0.5:
                return 0  # Dead volume = skip
        
        # Recent price momentum (last 4 candles)
        momentum_4 = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100
        if abs(momentum_4) > 0.5:
            score += 20
        elif abs(momentum_4) > 0.2:
            score += 10
        
        # Candle direction consistency
        last_3_green = all(df['close'].iloc[-i] > df['open'].iloc[-i] for i in range(1, 4))
        last_3_red   = all(df['close'].iloc[-i] < df['open'].iloc[-i] for i in range(1, 4))
        if last_3_green or last_3_red:
            score += 15
        
        # Market alignment bonus
        spy_trend = market.get('spy_trend', 'unknown')
        if spy_trend == 'up' and momentum_4 > 0:
            score += 10
        elif spy_trend == 'down' and momentum_4 < 0:
            score += 5  # Short opportunity
        
        return score

    async def get_price(self, symbol: str) -> Optional[float]:
        return await self.fetcher.get_price(symbol)

    async def get_movers(self) -> List[str]:
        """Get top movers from Finnhub (bonus method)"""
        import aiohttp
        try:
            url = "https://finnhub.io/api/v1/stock/market-status"
            params = {"exchange": "US", "token": self.config.FINNHUB_KEY}
            # This is a placeholder - Finnhub doesn't have free movers
            # Use our watchlist scan instead
            return []
        except:
            return []
