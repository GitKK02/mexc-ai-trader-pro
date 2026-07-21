# MEXC AI Trader Pro v1.3.3 — Whitelist Manager

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


## v0.6.0 Portfolio Manager

Добавлено:

- общий лимит риска портфеля;
- лимит риска в одном направлении;
- статические корреляционные группы;
- лимит риска и количества позиций в одной группе;
- снижение score для коррелированных кандидатов;
- блокировка повторной позиции по той же паре;
- ранжирование сигналов по Portfolio score;
- команды `/portfolio`, `/top`, `/risk`;
- Portfolio Manager встроен в LIVE CONFIRM preflight.

Расчёт риска восстановленных MEXC-позиций консервативный: если активный
Stop Loss недоступен в ответе позиции, резервируется настроенный риск сделки.
Это безопаснее, чем считать риск равным нулю.


## v0.7.0 AI Decision Engine

Decision Engine объединяет:

- Scanner score;
- среднюю оценку таймфреймов;
- momentum/ADX/volume;
- Portfolio score;
- режим рынка;
- BTC-контекст;
- консультативное решение OpenAI.

Итоговые действия:

- `ENTER` — сильный сигнал, Portfolio Manager разрешает вход, при настройке
  по умолчанию требуется `AI=APPROVE`;
- `CONFIRM` — сигнал подходит только для ручного подтверждения;
- `WAIT` — условия недостаточно сильные;
- `REJECT` — вход заблокирован.

`ENTER` в v0.7.0 не означает автоматическое размещение ордера. AUTO по-прежнему
отсутствует. В режиме CONFIRM пользователь всё равно проходит двойное
подтверждение.

Команда:

```text
/decisions
```

показывает причины итоговых решений.


## v0.8.0 Dynamic Position Manager

Добавлен SHADOW-менеджер открытых LIVE-позиций:

- читает реальные позиции и TP/SL;
- получает текущую цену;
- считает результат в единицах `R`;
- предлагает HOLD, TP1_REVIEW, BREAKEVEN_REVIEW, TRAIL_REVIEW,
  EXIT_REVIEW или PROTECTION_MISSING;
- сообщает только при изменении рекомендации или по таймеру;
- команда `/position_advice`;
- кнопка `🧭 Совет по позициям`.

В v0.8.0 менеджер **не изменяет ордера автоматически**. Это намеренное
ограничение для проверки логики на реальных позициях до добавления
исполняющего слоя.


## v0.9.0 Confirmed Position Actions

Добавлено реальное изменение существующего TP/SL-ордера:

- перенос Stop Loss в безубыток;
- разрешение только после настроенного значения `R`;
- сохранение существующего Take Profit;
- округление нового Stop Loss по `priceUnit`;
- двойное подтверждение через Telegram;
- повторная проверка нового Stop Loss через MEXC;
- постоянный журнал действий.

Порядок:

1. `/position_advice`;
2. `🟦 Подготовить безубыток`;
3. проверить старый и новый SL;
4. первое подтверждение;
5. `/confirm_position ВАШ_КОД`;
6. немедленно проверить TP/SL в приложении MEXC.

AUTO, частичное закрытие и trailing в этом релизе не включены.


## v1.0.0 Smart Risk Engine

Размер позиции учитывает equity, ATR, SL, спецификацию контракта, номинал, маржу, комиссии и проскальзывание.


## v1.1.0 Volatility & Liquidity Guard

Guard оценивает ATR, резкий импульс, спред, суточный оборот и относительный
объём. Он может блокировать вход либо уменьшать риск до передачи сделки
в Smart Risk Engine.


## v1.2.0 Market Regime Engine

Классифицирует тренд, боковик, сжатие, пробой и панический режим; корректирует Decision score и CONFIRM preflight.

## v1.3.0 News & Macro Guard

Локальный JSON-календарь, состояния SAFE/WAIT/BLOCKED, окна до/после
событий, снижение риска и блокировка CONFIRM.

```bash
mkdir -p data
cp docs/examples/macro_events.example.json data/macro_events.json
nano data/macro_events.json
```


## v1.3.1 Scanner Watchlist & Near Signals

Сканер больше не забывает кандидатов, которые немного не достигли
основного порога.

Добавлено:

- отдельный минимальный порог near signals;
- watchlist между циклами сканирования;
- динамика score;
- streak последовательных обнаружений;
- статусы WATCHING, IMPROVING, RISING, WEAKENING и READY;
- команды `/near` и `/watchlist`;
- кнопки `🔥 Почти готово` и `👀 Watchlist`.

LIVE-порог и защитные фильтры не снижены. Near signal нельзя подготовить
к реальной сделке, пока он не станет полноценным сигналом.


## v1.3.2 Adaptive Scanner & Flexible Limits

Сканер ускоряется при near signals и ещё сильнее при RISING-кандидатах.
Переходы в RISING/READY сопровождаются Telegram-уведомлением.

`LIVE_MAX_TRADES_PER_DAY=0` означает отсутствие дневного ограничения
количества сделок.

Команды:

```text
/trade_limit 5
/trade_limit 0
/daily_loss_limit 10
/daily_loss_limit 0
/limits
```

Runtime-значения сохраняются в SQLite и переживают перезапуск.
Остальные защитные слои продолжают действовать.


## v1.3.3 Whitelist Manager

Команды `/allow_all_top100`, `/allow_bluechips`, `/allow SYMBOL`,
`/deny SYMBOL`, `/whitelist`, `/clear_whitelist` управляют динамическим
LIVE whitelist. Данные сохраняются в SQLite.

`/allow_all_top100` выбирает только активные API-доступные USDT-фьючерсы,
проходящие минимальный оборот и максимальный спред. Это не отключает Smart
Risk, Portfolio Manager, Decision Engine или подтверждение сделки.

## v1.4.0 Entry Intelligence & Entry Flow

The scanner now separates signal strength from entry quality. It classifies the
current entry as EARLY, GOOD, LATE or CHASE, exposes the setup phase, measures
distance from the breakout/pullback anchor in ATR, and blocks chasing when too
little reward remains before TP1. Decision Engine defaults are softened to
CONFIRM=75 and WAIT=72, while hard portfolio, macro, volatility and panic guards
remain active. Telegram now explains the concrete reasons for WAIT instead of
showing only a generic rejection.

## Market Intelligence v1.5.1

The scanner now compares each candidate with BTC and the market median, ranks relative-strength leaders, measures LONG/SHORT market breadth, and can block entries that run against a strong market-wide direction. Telegram command: `/market`.
