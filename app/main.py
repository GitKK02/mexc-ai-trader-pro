import asyncio
import logging
import secrets
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import BotCommand, CallbackQuery, Message

from app.config import settings
from app.database import Database
from app.decision_engine import AIDecisionEngine
from app.live_database import LiveDatabase
from app.models import Signal
from app.multi_asset_confirm import MultiAssetConfirmService
from app.paper_engine import PaperEngine
from app.portfolio_manager import PortfolioRiskManager
from app.position_intelligence import DynamicPositionManager
from app.scanner import Scanner
from app.telegram_ui import (
    confirm_plan_actions,
    live_position_actions,
    main_menu,
    position_actions,
    signal_actions,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

dispatcher = Dispatcher()
scanner = Scanner(settings)
paper_db = Database(settings.database_path)
paper = PaperEngine(settings, paper_db)
live_db = LiveDatabase(settings.live_database_path)
confirm_service = MultiAssetConfirmService(settings, live_db)
portfolio_manager = PortfolioRiskManager(settings)
decision_engine = AIDecisionEngine(settings)
dynamic_position_manager = DynamicPositionManager(settings)

scan_running = settings.auto_scan_on_start
last_signals: list[Signal] = []
pending_signals: dict[str, Signal] = {}
confirm_pending: dict[str, tuple[object, Signal, datetime, bool]] = {}
sent_cache: dict[str, datetime] = {}


def allowed(message_or_user) -> bool:
    user_id = getattr(message_or_user, "id", None)
    return bool(user_id and user_id in settings.allowed_user_ids)


def signal_text(signal: Signal) -> str:
    reasons = "\n".join(f"• {x}" for x in signal.reasons)
    return (
        f"{'🟢' if signal.side == 'LONG' else '🔴'} {signal.side} {signal.symbol}\n"
        f"Стратегия: {signal.strategy}\n"
        f"Режим рынка: {signal.market_regime}\n"
        f"BTC-контекст: {signal.btc_context}\n"
        f"Оценка: {signal.score}/100\n"
        f"Таймфреймы: {signal.timeframe_scores or {}}\n"
        f"Portfolio score: {signal.portfolio_score if signal.portfolio_score is not None else '—'}\n"
        f"Decision score: {signal.decision_score if signal.decision_score is not None else '—'}\n"
        f"Решение: {signal.decision_action} ({signal.decision_confidence})\n"
        f"Компоненты: {signal.component_scores or {}}\n"
        f"Группа: {signal.portfolio_group or '—'}\n"
        f"ИИ: {signal.ai_decision}"
        f"{' — ' + signal.ai_summary if signal.ai_summary else ''}\n\n"
        f"Вход: {signal.entry:.8g}\nSL: {signal.stop_loss:.8g}\n"
        f"TP1: {signal.tp1:.8g}\nTP2: {signal.tp2:.8g}\n\n"
        f"Причины:\n{reasons}"
    )


async def live_portfolio_snapshot():
    if not settings.confirm_unlocked:
        return [], 0.0
    positions = await confirm_service.private.open_positions()
    equity = await confirm_service.account_equity()
    normalized = portfolio_manager.positions_from_mexc(
        positions,
        equity,
    )
    return normalized, float(equity)


def attach_portfolio_scores(
    signals: list[Signal],
    positions,
) -> list[Signal]:
    requested = min(
        Decimal(str(settings.live_risk_per_trade_percent)),
        Decimal(str(settings.live_max_risk_per_trade_percent)),
    )
    ranked = portfolio_manager.rank(
        signals,
        positions,
        requested,
    )
    ordered: list[Signal] = []
    for signal, assessment in ranked:
        signal.portfolio_score = assessment.adjusted_score
        signal.portfolio_allowed = assessment.allowed
        signal.portfolio_group = assessment.correlation_group
        signal.portfolio_reasons = assessment.reasons
        ordered.append(signal)
    return ordered


async def send_scan(bot: Bot, chat_id: int, force: bool) -> None:
    global last_signals
    signals = await scanner.run_once()
    try:
        positions, _equity = await live_portfolio_snapshot()
    except Exception:
        logger.exception("portfolio snapshot failed")
        positions = []
    signals = attach_portfolio_scores(signals, positions)
    if settings.decision_engine_enabled:
        signals = decision_engine.rank(signals)
    last_signals = signals
    if not signals:
        await bot.send_message(chat_id, "Подходящих сигналов нет.")
        return
    now = datetime.now(timezone.utc)
    sent = 0
    for signal in signals:
        key = f"{signal.symbol}:{signal.side}"
        prev = sent_cache.get(key)
        if not force and prev and now - prev < timedelta(minutes=settings.signal_cooldown_minutes):
            continue
        token = secrets.token_urlsafe(7)
        pending_signals[token] = signal
        await bot.send_message(
            chat_id,
            signal_text(signal),
            reply_markup=signal_actions(token, settings.confirm_unlocked),
        )
        sent_cache[key] = now
        sent += 1
    if not sent:
        await bot.send_message(chat_id, "Новых сигналов нет: действует cooldown.")


@dispatcher.message(Command("start", "menu"))
@dispatcher.message(F.text == "🏠 Меню")
async def menu(message: Message):
    if not allowed(message.from_user): return
    await message.answer(
        f"MEXC AI Trader Pro v0.8.0\n"
        f"Режим: {settings.trading_mode}\n"
        f"CONFIRM: {'РАЗБЛОКИРОВАН' if settings.confirm_unlocked else 'заблокирован'}",
        reply_markup=main_menu(scan_running, settings.confirm_unlocked),
    )


@dispatcher.message(Command("scan"))
@dispatcher.message(F.text == "📡 Сканировать сейчас")
async def scan(message: Message, bot: Bot):
    if not allowed(message.from_user): return
    await message.answer("Сканирую разрешённые пары…")
    try:
        await send_scan(bot, message.chat.id, True)
    except Exception as exc:
        logger.exception("scan failed")
        await message.answer(f"Ошибка сканирования: {type(exc).__name__}: {exc}")


@dispatcher.callback_query(F.data.startswith("confirm_prepare:"))
async def confirm_prepare(callback: CallbackQuery):
    if not allowed(callback.from_user): return
    if not settings.confirm_unlocked:
        await callback.answer("CONFIRM заблокирован", show_alert=True); return
    token = callback.data.split(":", 1)[1]
    signal = pending_signals.get(token)
    if not signal:
        await callback.answer("Сигнал устарел", show_alert=True); return
    if (
        settings.decision_engine_enabled
        and signal.decision_action not in {"ENTER", "CONFIRM"}
    ):
        await callback.answer(
            f"Decision Engine: {signal.decision_action}. "
            "Реальная подготовка заблокирована.",
            show_alert=True,
        )
        return
    try:
        plan = await confirm_service.prepare(signal)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True); return
    plan_token = secrets.token_urlsafe(8)
    confirm_pending[plan_token] = (plan, signal, datetime.now(timezone.utc), False)
    await callback.message.answer(
        f"⚠️ РЕАЛЬНЫЙ CONFIRM-ОРДЕР\n\n"
        f"{plan.side} {plan.symbol}\n"
        f"Текущая цена: {plan.reference_price}\n"
        f"Контрактов: {plan.contracts}\n"
        f"Contract size: {plan.contract_size}\n"
        f"Номинал: {plan.notional_usdt:.2f} USDT\n"
        f"Риск по SL: {plan.risk_usdt:.2f} USDT\n"
        f"Плечо: {plan.leverage}x\n"
        f"SL: {plan.stop_loss}\n"
        f"TP: {plan.take_profit}\n\n"
        f"Проверь параметры. После первой кнопки потребуется:\n"
        f"/confirm_trade {settings.live_confirm_code}",
        reply_markup=confirm_plan_actions(plan_token),
    )
    await callback.answer()


@dispatcher.callback_query(F.data.startswith("confirm_first:"))
async def confirm_first(callback: CallbackQuery):
    if not allowed(callback.from_user): return
    token = callback.data.split(":", 1)[1]
    item = confirm_pending.get(token)
    if not item:
        await callback.answer("План устарел", show_alert=True); return
    plan, signal, created, _ = item
    if (datetime.now(timezone.utc) - created).total_seconds() > settings.confirmation_ttl_seconds:
        confirm_pending.pop(token, None)
        await callback.answer("Время истекло", show_alert=True); return
    confirm_pending[token] = (plan, signal, created, True)
    await callback.message.answer(
        f"Первое подтверждение принято. В течение {settings.confirmation_ttl_seconds} сек. отправь:\n"
        f"/confirm_trade {settings.live_confirm_code}"
    )
    await callback.answer()


@dispatcher.callback_query(F.data.startswith("confirm_cancel:"))
async def confirm_cancel(callback: CallbackQuery):
    if not allowed(callback.from_user): return
    confirm_pending.pop(callback.data.split(":", 1)[1], None)
    await callback.answer("Отменено")
    await callback.message.edit_reply_markup(reply_markup=None)


@dispatcher.message(Command("confirm_trade"))
async def confirm_trade(message: Message):
    if not allowed(message.from_user): return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or parts[1].strip() != settings.live_confirm_code:
        await message.answer("Неверный код."); return
    now = datetime.now(timezone.utc)
    valid = []
    for token, (plan, signal, created, first) in list(confirm_pending.items()):
        if first and (now - created).total_seconds() <= settings.confirmation_ttl_seconds:
            valid.append((token, plan, signal))
    if len(valid) != 1:
        await message.answer("Нет одной действующей подтверждённой заявки."); return
    token, plan, signal = valid[0]
    confirm_pending.pop(token, None)
    await message.answer("Отправляю реальный ордер и проверяю защиту…")
    try:
        result = await confirm_service.execute(plan, signal.score)
        pos = result["position"]
        await message.answer(
            f"✅ LIVE-позиция открыта и защищена\n"
            f"Trade ID: {result['trade_id']}\n"
            f"{plan.side} {plan.symbol}\n"
            f"Position ID: {pos.get('positionId')}\n"
            f"Цена: {pos.get('holdAvgPrice')}\n"
            f"Объём: {pos.get('holdVol')}\n"
            f"SL: {result['actual_stop_loss']}\n"
            f"TP: {result['actual_take_profit']}\n"
            f"TP/SL записей: {len(result['protection'])}",
            reply_markup=live_position_actions(int(pos.get("positionId"))),
        )
    except Exception as exc:
        logger.exception("confirm execution failed")
        await message.answer(
            "🚨 LIVE-операция не завершена. "
            "Проверь вкладки «Позиции» и TP/SL на MEXC, "
            "затем нажми «LIVE-сверка». "
            "Техническая причина записана в локальный LIVE-журнал."
        )


@dispatcher.message(Command("reconcile"))
@dispatcher.message(F.text == "🔄 LIVE-сверка")
async def reconcile(message: Message):
    if not allowed(message.from_user): return
    if not settings.confirm_unlocked:
        await message.answer("CONFIRM заблокирован."); return
    try:
        data = await confirm_service.reconcile()
        await message.answer(
            f"🔄 Сверка MEXC\nОткрытых позиций: {len(data['positions'])}\n"
            f"Активных TP/SL: {len(data['tpsl'])}"
        )
        for p in data["positions"]:
            await message.answer(
                f"{p.get('symbol')} positionId={p.get('positionId')}\n"
                f"Тип: {p.get('positionType')}\nОбъём: {p.get('holdVol')}\n"
                f"Средняя: {p.get('holdAvgPrice')}",
                reply_markup=live_position_actions(int(p.get("positionId"))),
            )
    except Exception as exc:
        await message.answer(f"Ошибка сверки: {type(exc).__name__}: {exc}")


@dispatcher.callback_query(F.data.startswith("live_close_position:"))
async def close_live_position(callback: CallbackQuery):
    if not allowed(callback.from_user): return
    position_id = int(callback.data.split(":", 1)[1])
    try:
        await confirm_service.close_position(position_id)
        await callback.message.answer(f"🚨 Команда закрытия позиции {position_id} отправлена. Проверь MEXC.")
    except Exception as exc:
        await callback.message.answer(f"Ошибка закрытия: {type(exc).__name__}: {exc}")
    await callback.answer()


@dispatcher.message(F.text == "📒 LIVE-журнал")
async def live_journal(message: Message):
    if not allowed(message.from_user): return
    rows = live_db.recent(10)
    if not rows:
        await message.answer("LIVE-журнал пуст."); return
    await message.answer("\n\n".join(
        f"#{r['id']} {r['symbol']} {r['side']} — {r['state']}\n"
        f"Риск: {r['requested_risk_usdt']:.2f} USDT, контрактов: {r['contracts']}\n"
        f"{r['error'] or ''}"
        for r in rows
    ))


@dispatcher.callback_query(F.data.startswith("paper_open:"))
async def paper_open(callback: CallbackQuery):
    if not allowed(callback.from_user): return
    signal = pending_signals.pop(callback.data.split(":", 1)[1], None)
    if not signal:
        await callback.answer("Сигнал устарел", show_alert=True); return
    try:
        p = paper.open_from_signal(signal)
        await callback.message.answer(f"PAPER-позиция #{p.id} открыта", reply_markup=position_actions(p.id))
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)


@dispatcher.callback_query(F.data.startswith("paper_skip:"))
async def paper_skip(callback: CallbackQuery):
    if not allowed(callback.from_user): return
    pending_signals.pop(callback.data.split(":", 1)[1], None)
    await callback.answer("Пропущено")


@dispatcher.message(Command("top"))
@dispatcher.message(F.text == "🏆 Топ сигналов")
async def top_signals(message: Message):
    if not allowed(message.from_user):
        return
    if not last_signals:
        await message.answer("Рейтинг сигналов пока пуст. Запусти сканирование.")
        return
    rows = []
    for index, signal in enumerate(
        last_signals[: settings.portfolio_top_limit],
        start=1,
    ):
        verdict = "✅" if signal.portfolio_allowed is not False else "⛔"
        rows.append(
            f"{index}. {verdict} {signal.symbol} {signal.side}\n"
            f"Scanner: {signal.score}/100 | "
            f"Portfolio: {signal.portfolio_score if signal.portfolio_score is not None else '—'}/100\n"
            f"Decision: {signal.decision_score if signal.decision_score is not None else '—'}/100 "
            f"— {signal.decision_action}\n"
            f"Группа: {signal.portfolio_group or 'OTHER'}"
        )
    await message.answer("\n\n".join(rows))


@dispatcher.message(Command("portfolio"))
async def portfolio_status(message: Message):
    if not allowed(message.from_user):
        return
    if not settings.confirm_unlocked:
        await message.answer("LIVE Portfolio доступен только в разблокированном CONFIRM.")
        return
    try:
        positions, equity = await live_portfolio_snapshot()
    except Exception as exc:
        logger.exception("portfolio status failed")
        await message.answer(
            "Не удалось получить портфель MEXC. Проверь LIVE-сверку и журнал Docker."
        )
        return

    total_risk = sum(
        (position.risk_percent for position in positions),
        Decimal("0"),
    )
    if not positions:
        await message.answer(
            f"💼 LIVE Portfolio\n"
            f"Equity: {equity:.2f} USDT\n"
            f"Открытых позиций: 0\n"
            f"Зарезервированный риск: 0.00% / "
            f"{settings.portfolio_max_total_risk_percent:.2f}%"
        )
        return

    lines = [
        f"💼 LIVE Portfolio",
        f"Equity: {equity:.2f} USDT",
        f"Открытых позиций: {len(positions)}",
        f"Зарезервированный риск: {total_risk:.3f}% / "
        f"{settings.portfolio_max_total_risk_percent:.3f}%",
        "",
    ]
    for position in positions:
        lines.append(
            f"{position.symbol} {position.side} — "
            f"риск {position.risk_percent:.3f}% — "
            f"группа {portfolio_manager.group_for(position.symbol)}"
        )
    await message.answer("\n".join(lines))


@dispatcher.message(Command("risk"))
@dispatcher.message(F.text == "🛡 Риск")
async def risk_status(message: Message):
    if not allowed(message.from_user):
        return
    await message.answer(
        "🛡 Portfolio Risk Limits\n"
        f"Риск сделки: {settings.live_risk_per_trade_percent:.3f}%\n"
        f"Общий риск: {settings.portfolio_max_total_risk_percent:.3f}%\n"
        f"Одно направление: "
        f"{settings.portfolio_max_same_direction_risk_percent:.3f}%\n"
        f"Одна группа: {settings.portfolio_max_group_risk_percent:.3f}%\n"
        f"Позиций в группе: {settings.portfolio_max_positions_per_group}\n"
        f"Минимальный Portfolio score: "
        f"{settings.portfolio_min_adjusted_score_confirm}"
    )


@dispatcher.message(Command("decisions"))
async def decisions_status(message: Message):
    if not allowed(message.from_user):
        return
    if not last_signals:
        await message.answer(
            "Решений пока нет. Сначала запусти сканирование."
        )
        return

    blocks = []
    for signal in last_signals[: settings.portfolio_top_limit]:
        reasons = "\n".join(
            f"• {reason}"
            for reason in (signal.decision_reasons or [])[:5]
        )
        blocks.append(
            f"{signal.symbol} {signal.side}\n"
            f"{signal.decision_action} — "
            f"{signal.decision_score}/100 "
            f"({signal.decision_confidence})\n"
            f"{reasons}"
        )
    await message.answer("\n\n".join(blocks))


@dispatcher.message(Command("position_advice"))
@dispatcher.message(F.text == "🧭 Совет по позициям")
async def position_advice(message: Message):
    if not allowed(message.from_user):
        return
    if not settings.confirm_unlocked:
        await message.answer("Position Manager доступен только в CONFIRM.")
        return

    try:
        positions = await confirm_service.private.open_positions()
        protection = await confirm_service.private.current_tpsl()
        if not positions:
            await message.answer("Открытых LIVE-позиций нет.")
            return

        blocks = []
        for position in positions[: settings.position_intelligence_max_positions]:
            symbol = str(position.get("symbol") or "")
            ticker = await confirm_service.public_get(
                "/api/v1/contract/ticker",
                {"symbol": symbol},
            )
            plan = dynamic_position_manager.evaluate(
                position,
                Decimal(str(ticker["lastPrice"])),
                protection,
            )
            r_text = (
                f"{plan.current_r:.2f}R"
                if plan.current_r is not None
                else "не рассчитан"
            )
            blocks.append(
                f"{plan.symbol} {plan.side}\n"
                f"{plan.action} — {plan.confidence}\n"
                f"Результат: {r_text}\n"
                + "\n".join(f"• {reason}" for reason in plan.reasons)
            )
        await message.answer("\n\n".join(blocks))
    except Exception:
        logger.exception("position advice failed")
        await message.answer(
            "Не удалось получить рекомендации. Проверь LIVE-сверку и Docker-лог."
        )


@dispatcher.message(Command("status"))
@dispatcher.message(F.text == "📊 Статус")
async def status(message: Message):
    if not allowed(message.from_user): return
    count, pnl = live_db.today()
    await message.answer(
        f"Режим: {settings.trading_mode}\n"
        f"CONFIRM: {'разблокирован' if settings.confirm_unlocked else 'заблокирован'}\n"
        f"LIVE whitelist: {', '.join(sorted(settings.live_whitelist))}\n"
        f"Сделок сегодня: {count}/{settings.live_max_trades_per_day}\n"
        f"Зафиксированный дневной PnL: {pnl:+.2f} USDT\n"
        f"Автоскан: {'работает' if scan_running else 'пауза'}"
    )


@dispatcher.message(Command("pause"))
@dispatcher.message(F.text == "⏸ Пауза")
async def pause(message: Message):
    global scan_running
    if not allowed(message.from_user): return
    scan_running = False
    await message.answer("Автоскан остановлен.", reply_markup=main_menu(False, settings.confirm_unlocked))


@dispatcher.message(Command("resume"))
@dispatcher.message(F.text == "▶️ Запустить автоскан")
async def resume(message: Message):
    global scan_running
    if not allowed(message.from_user): return
    scan_running = True
    await message.answer("Автоскан запущен.", reply_markup=main_menu(True, settings.confirm_unlocked))


@dispatcher.message(F.text.in_({"💼 Портфель", "📈 Позиции", "📜 История", "🧾 Отчёт"}))
async def paper_info(message: Message):
    if not allowed(message.from_user): return
    balance, initial = paper_db.account()
    positions = paper_db.open_positions()
    await message.answer(
        f"PAPER баланс: {balance:.2f} USDT\n"
        f"Начальный: {initial:.2f} USDT\n"
        f"Открытых PAPER-позиций: {len(positions)}"
    )


async def position_intelligence_loop(bot: Bot):
    while True:
        await asyncio.sleep(settings.position_intelligence_poll_seconds)
        if (
            not settings.position_intelligence_enabled
            or not settings.confirm_unlocked
        ):
            continue

        try:
            positions = await confirm_service.private.open_positions()
            if not positions:
                continue
            protection = await confirm_service.private.current_tpsl()

            for position in positions[: settings.position_intelligence_max_positions]:
                symbol = str(position.get("symbol") or "")
                ticker = await confirm_service.public_get(
                    "/api/v1/contract/ticker",
                    {"symbol": symbol},
                )
                current_price = Decimal(str(ticker["lastPrice"]))
                plan = dynamic_position_manager.evaluate(
                    position,
                    current_price,
                    protection,
                )

                state = live_db.position_intelligence_state(
                    plan.position_id
                )
                now = datetime.now(timezone.utc)
                should_notify = True
                if state:
                    last_action = str(state["last_action"])
                    last_time = datetime.fromisoformat(
                        str(state["last_notified_at"])
                    )
                    age = (now - last_time).total_seconds()
                    if (
                        settings.position_intelligence_notify_on_change_only
                        and last_action == plan.action
                        and age
                        < settings.position_intelligence_min_notify_seconds
                    ):
                        should_notify = False

                if not should_notify:
                    continue

                r_text = (
                    f"{plan.current_r:.2f}R"
                    if plan.current_r is not None
                    else "не рассчитан"
                )
                reasons = "\n".join(
                    f"• {reason}" for reason in plan.reasons
                )
                for chat_id in settings.allowed_user_ids:
                    await bot.send_message(
                        chat_id,
                        f"🧭 Position Manager [{settings.position_intelligence_mode}]\n"
                        f"{plan.symbol} {plan.side}\n"
                        f"Действие: {plan.action} ({plan.confidence})\n"
                        f"Текущий результат: {r_text}\n"
                        f"Вход: {plan.entry_price}\n"
                        f"Текущая цена: {plan.current_price}\n"
                        f"SL: {plan.stop_loss or 'не найден'}\n"
                        f"TP: {plan.take_profit or 'не найден'}\n\n"
                        f"{reasons}\n\n"
                        f"Ордеры автоматически не изменялись."
                    )

                live_db.upsert_position_intelligence_state(
                    plan.position_id,
                    plan.action,
                    now.isoformat(),
                )
        except Exception:
            logger.exception("position intelligence loop failed")


async def auto_scan_loop(bot: Bot):
    while True:
        await asyncio.sleep(settings.scan_interval_seconds)
        if scan_running:
            for chat_id in settings.allowed_user_ids:
                try:
                    await send_scan(bot, chat_id, False)
                except Exception:
                    logger.exception("auto scan failed")


async def main():
    if settings.trading_mode.upper() not in {"PAPER", "CONFIRM"}:
        raise RuntimeError("v0.4.0 supports PAPER or CONFIRM only")
    if settings.trading_mode.upper() == "CONFIRM" and not settings.confirm_unlocked:
        raise RuntimeError("CONFIRM mode requested but safety acknowledgement is incomplete")
    if settings.live_open_type != 1:
        raise RuntimeError("v0.4.0 requires isolated margin: LIVE_OPEN_TYPE=1")
    paper_db.ensure_account(settings.paper_initial_balance_usdt)
    bot = Bot(settings.telegram_bot_token)
    await bot.set_my_commands([
        BotCommand(command="menu", description="Меню"),
        BotCommand(command="scan", description="Сканировать"),
        BotCommand(command="status", description="Статус"),
        BotCommand(command="reconcile", description="LIVE-сверка"),
        BotCommand(command="portfolio", description="LIVE-портфель"),
        BotCommand(command="top", description="Рейтинг сигналов"),
        BotCommand(command="risk", description="Лимиты риска"),
        BotCommand(command="decisions", description="Решения AI Engine"),
        BotCommand(command="position_advice", description="Совет по позициям"),
        BotCommand(command="confirm_trade", description="Подтвердить LIVE-сделку"),
    ])
    asyncio.create_task(auto_scan_loop(bot))
    asyncio.create_task(position_intelligence_loop(bot))
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
