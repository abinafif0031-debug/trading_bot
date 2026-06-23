"""
AI Gatekeeper - Claude Haiku final signal approval
Analyzes the signal context and gives a final verdict with brief comment
"""

import logging
import json
import aiohttp
from typing import Tuple

logger = logging.getLogger(__name__)

class AIGatekeeper:
    def __init__(self, config):
        self.config = config
        self.api_url = "https://api.anthropic.com/v1/messages"
        self.model   = "claude-haiku-4-5"

    async def approve(self, signal: dict) -> Tuple[bool, str]:

        """
        Returns (approved: bool, comment: str)
        Quick AI judgment on signal quality.
        """
        if not self.config.ANTHROPIC_KEY:
            logger.warning("No Anthropic key - skipping AI gate")
            return True, ""

        prompt = self._build_prompt(signal)

        try:
            headers = {
                "x-api-key":         self.config.ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            }
            payload = {
                "model":      self.model,
                "max_tokens": 150,
                "system": (
                    "You are an expert US stock day trader. "
                    "Evaluate trading signals and respond ONLY with valid JSON. "
                    "Be direct and decisive. Favor quality over quantity. "
                    "Respond with: {\"approve\": true/false, \"comment\": \"max 10 words\"}"
                ),
                "messages": [{"role": "user", "content": prompt}],
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    data = await resp.json()

            raw = data.get("content", [{}])[0].get("text", "")
            parsed = json.loads(raw.strip())
            approved = bool(parsed.get("approve", False))
            comment  = str(parsed.get("comment", "")).strip()

            logger.info(f"AI gate {signal['symbol']}: {'✅' if approved else '❌'} — {comment}")
            return approved, comment

        except json.JSONDecodeError:
            # If AI response isn't valid JSON, still approve based on score
            return signal['score'] >= 70, "Good setup"
        except Exception as e:
            logger.error(f"AI gate error: {e}")
            return True, ""  # Default approve on error

    def _build_prompt(self, s: dict) -> str:
        reasons = ', '.join(s.get('reasons', [])[:3]) or 'None'
        return (
            f"Signal: {s['symbol']} {s['direction']}\n"
            f"Score: {s['score']}/100 | Confirmations: {s['confirmations']}\n"
            f"Entry: ${s['entry']:.2f} | TP1: ${s['tp1']:.2f} | TP2: ${s['tp2']:.2f} | SL: ${s['stop_loss']:.2f}\n"
            f"Setup: {reasons}\n"
            f"Volume: {s.get('volume_surge', 1):.1f}x avg\n"
            f"Session: {s.get('session', 'open')}\n"
            f"15m Score: {s.get('score_15m', 0)} | 1h Score: {s.get('score_1h', 0)} | 1d Score: {s.get('score_1d', 0)}\n\n"
            f"Approve this speculative trade? JSON only."
        )
