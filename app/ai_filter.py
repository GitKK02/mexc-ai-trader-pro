import json
import logging

from openai import AsyncOpenAI

from app.models import Signal

logger = logging.getLogger(__name__)


class AiFilter:
    def __init__(
        self,
        api_key: str,
        model: str,
        enabled: bool,
    ) -> None:
        self.enabled = enabled and bool(api_key)
        self.model = model
        self.client = (
            AsyncOpenAI(api_key=api_key)
            if self.enabled
            else None
        )

    @staticmethod
    def _prompt(signal: Signal) -> dict:
        return {
            "symbol": signal.symbol,
            "side": signal.side,
            "score": signal.score,
            "entry": signal.entry,
            "stop_loss": signal.stop_loss,
            "tp1": signal.tp1,
            "tp2": signal.tp2,
            "reasons": signal.reasons,
        }

    @staticmethod
    def _parse(text: str, signal: Signal) -> Signal:
        parsed = json.loads(text.strip())
        signal.ai_decision = str(
            parsed.get("decision", "WAIT")
        ).upper()
        signal.ai_summary = str(
            parsed.get("summary", "")
        )[:500]
        return signal

    async def review(self, signal: Signal) -> Signal:
        if not self.enabled or self.client is None:
            signal.ai_decision = "SKIPPED"
            return signal

        system_text = (
            "Ты дополнительный риск-фильтр торговых сигналов. "
            "Верни только JSON с полями decision и summary. "
            "decision: APPROVE, WAIT или REJECT. "
            "Не обещай прибыль."
        )
        user_text = json.dumps(
            self._prompt(signal),
            ensure_ascii=False,
        )

        try:
            try:
                response = await self.client.responses.create(
                    model=self.model,
                    input=[
                        {
                            "role": "system",
                            "content": system_text,
                        },
                        {
                            "role": "user",
                            "content": user_text,
                        },
                    ],
                )
                return self._parse(
                    response.output_text,
                    signal,
                )
            except Exception:
                # Compatibility fallback for accounts/models where
                # Responses is unavailable but Chat Completions works.
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": system_text,
                        },
                        {
                            "role": "user",
                            "content": user_text,
                        },
                    ],
                    response_format={"type": "json_object"},
                )
                text = response.choices[0].message.content or "{}"
                return self._parse(text, signal)
        except Exception:
            logger.exception(
                "OpenAI signal review failed without exposing secrets"
            )
            signal.ai_decision = "ERROR"
            signal.ai_summary = (
                "ИИ временно недоступен. Детали сохранены только "
                "в локальном журнале без отправки ключа в Telegram."
            )
            return signal
