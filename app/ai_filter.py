import json
from openai import AsyncOpenAI

from app.models import Signal


class AiFilter:
    def __init__(self, api_key: str, model: str, enabled: bool) -> None:
        self.enabled = enabled and bool(api_key)
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key) if self.enabled else None

    async def review(self, signal: Signal) -> Signal:
        if not self.enabled or self.client is None:
            signal.ai_decision = "SKIPPED"
            return signal

        prompt = {
            "symbol": signal.symbol,
            "side": signal.side,
            "score": signal.score,
            "entry": signal.entry,
            "stop_loss": signal.stop_loss,
            "tp1": signal.tp1,
            "tp2": signal.tp2,
            "reasons": signal.reasons,
        }

        try:
            response = await self.client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Ты дополнительный риск-фильтр торговых сигналов. "
                            "Верни только JSON с полями decision и summary. "
                            "decision: APPROVE, WAIT или REJECT. "
                            "Не обещай прибыль."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            )
            text = response.output_text.strip()
            parsed = json.loads(text)
            signal.ai_decision = str(parsed.get("decision", "WAIT")).upper()
            signal.ai_summary = str(parsed.get("summary", ""))
        except Exception as exc:
            signal.ai_decision = "ERROR"
            signal.ai_summary = f"{type(exc).__name__}: {exc}"
        return signal
