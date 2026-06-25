"""
Stock Scanner - Rotating Scan System
يقسم الـ 141 سهم على دفعات، كل scan يغطي دفعة مختلفة
كل دورة كاملة = ~9 دقائق (3 scans × 3 دقائق)
الـ quick_score يستخدم 15m فقط = 1 طلب لكل سهم
"""

import logging
import asyncio
from typing import List, Optional
from data_fetcher import DataFetcher

logger = logging.getLogger(__name__)

BATCH_SIZE = 45  # 45 سهم × 1 طلب = 45 credit → أقل من 144/دقيقة

class StockScanner:
    def __init__(self, config):
        self.config = config
        self.fetcher = DataFetcher(config)
        self._batch_index = 0  # تتبع الدفعة الحالية

    async def get_candidates(self) -> List[str]:
        """
        Rotating scan:
        - يقسم الـ watchlist على دفعات 45 سهم
        - كل scan يفحص دفعة مختلفة
        - كل 3 scans (9 دقائق) غطى الـ 141 كلها
        """
        watchlist = self.config.get_watchlist()
        etfs = {"SPY", "QQQ", "TQQQ", "SQQQ", "SOXL", "SOXS"}
        stocks = [s for s in watchlist if s not in etfs]

        # تقسيم على دفعات
        batches = [stocks[i:i+BATCH_SIZE] for i in range(0, len(stocks), BATCH_SIZE)]
        total_batches = len(batches)

        # اختر الدفعة الحالية
        current_batch = batches[self._batch_index % total_batches]
        self._batch_index += 1

        logger.info(f"🔄 Batch {(self._batch_index-1) % total_batches + 1}/{total_batches} | {len(current_batch)} symbols")

        # جلب SPY للسياق
        market = await self.fetcher.get_market_breadth()
        logger.info(f"Market: QQQ={market.get('spy_trend')} {market.get('spy_momentum',0):.2f}%")

        # Quick score للدفعة الحالية — طلب واحد فقط لكل سهم (15m)
        scored = []
        semaphore = asyncio.Semaphore(3)

        async def quick_score(symbol: str):
            async with semaphore:
                try:
                    score = await self._quick_score(symbol, market)
                    if score > 0:
                        scored.append((symbol, score))
                except Exception as e:
                    logger.debug(f"Quick score error {symbol}: {e}")

        await asyncio.gather(*[quick_score(s) for s in current_batch])

        # أفضل 10 من الدفعة للتحليل الكامل
        scored.sort(key=lambda x: x[1], reverse=True)
        candidates = [s for s, _ in scored[:10]]

        # استبعاد الأسهم على cooldown
        candidates = [s for s in candidates if not self.config.is_on_cooldown(s)]

        logger.info(f"📋 Candidates: {candidates}")
        return candidates

    async def _quick_score(self, symbol: str, market: dict) -> float:
        """
        فلتر سريع باستخدام 15m فقط = 1 طلب API
        """
        df = await self.fetcher.get_candles(symbol, "15min", outputsize=20)
        if df is None or len(df) < 15:
            return 0

        close = df['close']
        vol   = df['volume']
        price = float(close.iloc[-1])

        if not (self.config.MIN_PRICE <= price <= self.config.MAX_PRICE):
            return 0

        score = 0

        # حجم التداول
        avg_vol    = vol.iloc[:-1].mean()
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
                return 0  # تداول ميت

        # زخم الأسعار (آخر 4 شمعات)
        if len(close) >= 5:
            momentum = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100
            if abs(momentum) > 0.5:
                score += 20
            elif abs(momentum) > 0.2:
                score += 10
        else:
            momentum = 0

        # اتساق الشمعات (3 شمعات في نفس الاتجاه)
        try:
            last_3_green = all(df['close'].iloc[-i] > df['open'].iloc[-i] for i in range(1, 4))
            last_3_red   = all(df['close'].iloc[-i] < df['open'].iloc[-i] for i in range(1, 4))
            if last_3_green or last_3_red:
                score += 15
        except:
            pass

        # توافق مع السوق
        spy_trend = market.get('spy_trend', 'unknown')
        if spy_trend == 'up' and momentum > 0:
            score += 10
        elif spy_trend == 'down' and momentum < 0:
            score += 5

        return score

    async def get_price(self, symbol: str) -> Optional[float]:
        return await self.fetcher.get_price(symbol)
