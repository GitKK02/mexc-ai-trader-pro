# MEXC AI Trader Pro v0.5.0 — AI Scanner Pro

Реальные сделки по нескольким разрешённым фьючерсным парам с обязательным ручным подтверждением.

## Реализовано

- PAPER и CONFIRM;
- LIVE whitelist;
- динамическое чтение contractSize, minVol, maxVol, volUnit, priceUnit;
- расчёт количества контрактов от equity, Stop Loss и процента риска;
- ограничение максимального номинала;
- лимит открытых позиций и сделок в день;
- проверка отклонения цены от сигнала;
- запрет повторной позиции по той же паре;
- двойное подтверждение;
- уникальный externalOid;
- SQLite LIVE-журнал;
- проверка позиции и TP/SL после входа;
- аварийное закрытие, если защита не подтверждена;
- LIVE-сверка;
- закрытие отдельной позиции через Telegram.

## Пока не реализовано

- полноценные отдельные TP1/TP2 с частичным исполнением;
- перенос реального SL в безубыток;
- реальный trailing manager;
- расчёт дневного PnL из истории MEXC;
- автоматический режим AUTO;
- WebSocket reconciliation.

Текущий релиз ставит один полный Take Profit и один полный Stop Loss. Частичное сопровождение будет отдельным релизом v0.4.1 после проверки исполнения CONFIRM.

## Безопасный первый запуск

```env
TRADING_MODE=PAPER
ENABLE_LIVE_TRADING=false
LIVE_TRADING_ACK=
```

```bash
docker compose up -d --build
docker compose logs -f bot
```

## Включение CONFIRM

```env
TRADING_MODE=CONFIRM
ENABLE_LIVE_TRADING=true
LIVE_TRADING_ACK=I_UNDERSTAND_REAL_ORDERS
LIVE_CONFIRM_CODE=СВОЙ_СЕКРЕТНЫЙ_КОД
```

Оставьте:

```env
LIVE_OPEN_TYPE=1
LIVE_MAX_LEVERAGE=1
LIVE_RISK_PER_TRADE_PERCENT=0.05
LIVE_MAX_NOTIONAL_USDT=25
LIVE_MAX_OPEN_POSITIONS=1
LIVE_MAX_TRADES_PER_DAY=1
```

для первых реальных проверок.

## Процесс

1. `/start`
2. `📡 Сканировать сейчас`
3. На хорошем сигнале нажать `⚠️ Подготовить LIVE`
4. Проверить контракт, номинал, риск, SL и TP
5. Нажать первое подтверждение
6. Отправить `/confirm_trade ВАШ_КОД`
7. Немедленно проверить позицию и защитные ордера в MEXC
8. Выполнить `🔄 LIVE-сверка`

## Важное предупреждение

Это экспериментальный CONFIRM-релиз. Первый тест выполняйте только на минимальном номинале, без других открытых позиций и с открытым приложением MEXC для ручного контроля.


## v0.4.1 Execution Safety

Реальный вход теперь выполняется в два этапа:

1. market-вход без встроенных TP/SL;
2. получение фактической позиции и средней цены;
3. отдельная установка полного market TP/SL по `positionId`;
4. повторная проверка активного Stop Loss;
5. аварийная попытка закрытия позиции, если защита не подтверждена.

Ошибки OpenAI больше не пересылают детали исключений или фрагменты ключа
в Telegram. Для совместимости используется fallback с Responses API на
Chat Completions.

Перед первым повторным LIVE-тестом рекомендуется:

```env
LIVE_MAX_NOTIONAL_USDT=25
LIVE_MAX_OPEN_POSITIONS=1
LIVE_MAX_LEVERAGE=1
LIVE_MAX_TRADES_PER_DAY=1
OPENAI_MODEL=gpt-4.1-mini
```


## v0.5.0 AI Scanner Pro

- анализ Min5, Min15, Min60 и Hour4;
- EMA20/50/200, RSI, ATR, ADX, Bollinger width;
- упрощённая структура HH/HL и LH/LL;
- классификация TREND, RANGE, COMPRESSION, HIGH_VOLATILITY;
- BTC-контекст;
- взвешенное объединение таймфреймов;
- параллельная загрузка данных;
- OpenAI получает только лучшие кандидаты;
- расширенные карточки сигналов.

AUTO и Execution Engine этим патчем не меняются.
