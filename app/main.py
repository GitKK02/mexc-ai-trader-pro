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
from app.confluence_engine import ConfluenceEngine
from app.live_database import LiveDatabase
from app.models import Signal
from app.multi_asset_confirm import MultiAssetConfirmService
from app.paper_engine import PaperEngine
from app.portfolio_manager import PortfolioRiskManager
from app.position_intelligence import DynamicPositionManager
from app.position_actions import ConfirmedPositionActions
from app.macro_guard import NewsMacroGuard
from app.scanner import Scanner
from app.scanner_watchlist import ScannerWatchlist
from app.whitelist_manager import LiveWhitelistManager
from app.telegram_ui import (
    confirm_plan_actions,
    live_position_actions,
    main_menu,
    position_actions,
    position_management_actions,
    position_be_confirm_actions,
    signal_actions,
    position_management_actions,
    position_be_confirm_actions,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

dispatcher = Dispatcher()
scanner = Scanner(settings)
scanner_watchlist = ScannerWatchlist(settings)
paper_db = Database(settings.database_path)
paper = PaperEngine(settings, paper_db)
live_db = LiveDatabase(settings.live_database_path)
confirm_service = MultiAssetConfirmService(settings, live_db)
portfolio_manager = PortfolioRiskManager(settings)
decision_engine = AIDecisionEngine(settings)
confluence_engine = ConfluenceEngine(settings)
dynamic_position_manager = DynamicPositionManager(settings)
macro_guard = NewsMacroGuard(settings)
whitelist_manager = LiveWhitelistManager(
    settings, live_db, scanner.exchange, confirm_service.public_get
)
confirmed_position_actions = ConfirmedPositionActions(
    settings,
    confirm_service,
)
position_action_pending: dict[str, tuple[object, datetime, bool]] = {}

scan_running = settings.auto_scan_on_start
last_signals: list[Signal] = []
last_near_signals: list[Signal] = []
watchlist_promotion_cache: dict[str, datetime] = {}
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
        f"Entry quality: {signal.entry_quality_score if signal.entry_quality_score is not None else '—'}/100\n"
        f"Confluence: {signal.confluence_confirmations}/{signal.confluence_total} "
        f"({signal.confluence_score if signal.confluence_score is not None else '—'}/100)\n"
        f"Timing: {signal.entry_timing} | Фаза: {signal.entry_phase}\n"
        f"От зоны: {signal.entry_distance_atr:+.2f} ATR "
        f"({signal.entry_distance_percent:.2f}%)\n"
        f"До TP1: {signal.entry_remaining_tp1_r:.2f}R\n"
        f"Волатильность: {signal.volatility_state}\n"
        f"Ликвидность: {signal.liquidity_state}\n"
        f"Режим 2.0: {signal.detailed_regime}\n"
        f"Regime adjustment: {signal.regime_score_adjustment:+d}\n"
        f"Macro Guard: {signal.macro_guard_state}\n"
        f"Risk multiplier: "
        f"{signal.volatility_guard_multiplier * signal.macro_guard_risk_multiplier:.2f}x\n"
        f"Компоненты: {signal.component_scores or {}}\n"
        f"Группа: {signal.portfolio_group or '—'}\n"
        f"ИИ: {signal.ai_decision}"
        f"{' — ' + signal.ai_summary if signal.ai_summary else ''}\n\n"
        f"Вход: {signal.entry:.8g}\nSL: {signal.stop_loss:.8g}\n"
        f"TP1: {signal.tp1:.8g}\nTP2: {signal.tp2:.8g}\n\n"
        f"Причины:\n{reasons}"
    )




def effective_trade_limit() -> int:
    return live_db.effective_trade_limit(
        settings.live_max_trades_per_day
    )


def effective_daily_loss_limit() -> float:
    return live_db.effective_daily_loss_limit(
        settings.live_daily_loss_limit_usdt
    )


def adaptive_scan_interval() -> int:
    normal = max(
        settings.adaptive_scanner_min_interval_seconds,
        settings.scan_interval_seconds,
    )
    if not settings.adaptive_scanner_enabled:
        return normal

    entries = scanner_watchlist.entries()
    if any(entry.status == "RISING" for entry in entries):
        return max(
            settings.adaptive_scanner_min_interval_seconds,
            settings.adaptive_scanner_rising_interval_seconds,
        )
    if last_near_signals:
        return max(
            settings.adaptive_scanner_min_interval_seconds,
            settings.adaptive_scanner_near_interval_seconds,
        )
    return normal

def near_signal_text(signal: Signal) -> str:
    reasons = "\n".join(
        f"• {reason}" for reason in signal.reasons[:5]
    )
    delta = (
        f"+{signal.watchlist_delta}"
        if signal.watchlist_delta > 0
        else str(signal.watchlist_delta)
    )
    return (
        f"🔥 {signal.symbol} {signal.side}\n"
        f"Scanner score: {signal.score}/100\n"
        f"До основного порога: {signal.missing_points} пунктов\n"
        f"Динамика: {delta} | streak={signal.watchlist_streak}\n"
        f"Статус: {signal.watchlist_status}\n"
        f"Режим: {signal.detailed_regime}\n"
        f"Macro: {signal.macro_guard_state}\n"
        f"Волатильность: {signal.volatility_state}\n\n"
        f"Наблюдения:\n{reasons}"
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
    global last_signals, last_near_signals
    signals = await scanner.run_once()
    try:
        positions, _equity = await live_portfolio_snapshot()
    except Exception:
        logger.exception("portfolio snapshot failed")
        positions = []
    signals = attach_portfolio_scores(signals, positions)
    if settings.confluence_engine_enabled:
        signals = [confluence_engine.attach(signal) for signal in signals]
    if settings.decision_engine_enabled:
        signals = decision_engine.rank(signals)
    last_signals = signals

    near = scanner.near_signals
    if settings.scanner_watchlist_enabled:
        entries = scanner_watchlist.update(
            [*near, *signals]
        )
        last_near_signals = [
            entry.signal
            for entry in entries
            if entry.signal.score
            < settings.min_signal_score_paper
        ]

        if settings.adaptive_scanner_notify_promotions:
            now_promotion = datetime.now(timezone.utc)
            for entry in entries:
                promoted = (
                    entry.status in {"RISING", "READY"}
                    and entry.previous_status != entry.status
                )
                if not promoted:
                    continue
                key = f"{entry.symbol}:{entry.side}:{entry.status}"
                previous_notice = watchlist_promotion_cache.get(key)
                if (
                    previous_notice
                    and (
                        now_promotion - previous_notice
                    ).total_seconds()
                    < settings.adaptive_scanner_promotion_cooldown_seconds
                ):
                    continue
                watchlist_promotion_cache[key] = now_promotion
                await bot.send_message(
                    chat_id,
                    f"📈 Кандидат усилился\n"
                    f"{entry.symbol} {entry.side}\n"
                    f"Score: {entry.score}/100 "
                    f"(Δ {entry.delta:+d})\n"
                    f"Streak: {entry.streak}\n"
                    f"Статус: {entry.status}"
                )
    else:
        last_near_signals = near

    if not signals:
        if last_near_signals:
            best = last_near_signals[0]
            await bot.send_message(
                chat_id,
                "Готовых сигналов пока нет. "
                f"В watchlist: {len(last_near_signals)}. "
                f"Лучший кандидат: {best.symbol} "
                f"{best.score}/100 — не хватает "
                f"{best.missing_points} пунктов. "
                "Открой «🔥 Почти готово»."
            )
        else:
            await bot.send_message(
                chat_id,
                "Готовых и близких сигналов сейчас нет."
            )
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
        active = []
        for signal in signals:
            key = f"{signal.symbol}:{signal.side}"
            previous = sent_cache.get(key)
            if not previous:
                continue
            remaining = max(
                0,
                settings.signal_cooldown_minutes
                - int((now - previous).total_seconds() // 60),
            )
            active.append(f"{signal.symbol} {remaining}м")
        details = ", ".join(active[:5]) or "по ранее отправленным парам"
        await bot.send_message(
            chat_id,
            "Скан завершён: подходящие сигналы уже отправлялись. "
            f"Cooldown: {details}. Автоскан продолжает работать.",
        )


@dispatcher.message(Command("start", "menu"))
@dispatcher.message(F.text == "🏠 Меню")
async def menu(message: Message):
    if not allowed(message.from_user): return
    await message.answer(
        f"MEXC AI Trader Pro v1.5.0\n"
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
    if signal.decision_created_at:
        try:
            decision_created = datetime.fromisoformat(signal.decision_created_at)
            decision_age = (
                datetime.now(timezone.utc) - decision_created
            ).total_seconds()
            if decision_age > settings.decision_cache_ttl_seconds:
                await callback.answer(
                    "Решение устарело. Запусти новый скан: рыночная "
                    f"оценка старше {settings.decision_cache_ttl_seconds} сек.",
                    show_alert=True,
                )
                return
        except ValueError:
            pass
    if (
        settings.decision_engine_enabled
        and signal.decision_action not in {"ENTER", "CONFIRM"}
    ):
        reasons = [
            *(signal.decision_reasons or []),
            *(signal.entry_reasons or []),
            *(signal.portfolio_reasons or []),
        ]
        unique_reasons = list(dict.fromkeys(reason for reason in reasons if reason))
        age_text = "неизвестен"
        if signal.decision_created_at:
            try:
                created = datetime.fromisoformat(signal.decision_created_at)
                age_text = f"{int((datetime.now(timezone.utc) - created).total_seconds())} сек"
            except ValueError:
                pass
        detail = "\n".join(f"• {reason}" for reason in unique_reasons[:4])
        await callback.answer(
            f"LIVE заблокирован: {signal.decision_action} "
            f"({signal.decision_score}/100, нужно ≥"
            f"{settings.decision_confirm_score}).\n"
            f"Entry: {signal.entry_quality_score}/100, {signal.entry_timing}.\n"
            f"Возраст решения: {age_text}.\n"
            f"{detail or 'Нет подробной причины.'}",
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
        f"Маржа: {plan.required_margin_usdt:.2f} USDT "
        f"({plan.margin_usage_percent:.2f}% equity)\n"
        f"Риск по SL: {plan.risk_usdt:.2f} USDT\n"
        f"Расходы: {plan.estimated_costs_usdt:.2f} USDT\n"
        f"Оценочный max loss: {plan.estimated_max_loss_usdt:.2f} USDT\n"
        f"Smart risk: {plan.risk_percent:.3f}% equity\n"
        f"Плечо: {plan.leverage}x\n"
        f"SL: {plan.stop_loss}\n"
        f"TP: {plan.take_profit}\n"
        f"Предупреждения: "
        f"{'; '.join(plan.smart_risk_warnings or []) or 'нет'}\n\n"
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
        if settings.position_actions_enabled:
            for position in positions:
                await message.answer(
                    f"Управление {position.get('symbol')} "
                    f"positionId={position.get('positionId')}",
                    reply_markup=position_management_actions(
                        int(position.get("positionId"))
                    ),
                )
    except Exception:
        logger.exception("position advice failed")
        await message.answer(
            "Не удалось получить рекомендации. Проверь LIVE-сверку и Docker-лог."
        )


@dispatcher.callback_query(F.data.startswith("position_be_prepare:"))
async def position_be_prepare(callback: CallbackQuery):
    if not allowed(callback.from_user):
        return
    if (
        not settings.position_actions_enabled
        or settings.position_actions_mode.upper() != "CONFIRM"
    ):
        await callback.answer(
            "Исполнение действий отключено",
            show_alert=True,
        )
        return

    position_id = int(callback.data.split(":", 1)[1])
    try:
        plan = await confirmed_position_actions.prepare_breakeven(
            position_id
        )
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    token = secrets.token_urlsafe(8)
    position_action_pending[token] = (
        plan,
        datetime.now(timezone.utc),
        False,
    )
    await callback.message.answer(
        f"⚠️ ПЕРЕНОС STOP LOSS В БЕЗУБЫТОК\n\n"
        f"{plan.symbol} {plan.side}\n"
        f"Текущий R: {plan.current_r:.2f}R\n"
        f"Вход: {plan.entry_price}\n"
        f"Текущая цена: {plan.current_price}\n"
        f"Старый SL: {plan.current_stop_loss}\n"
        f"Новый SL: {plan.proposed_stop_loss}\n"
        f"TP сохранится: {plan.take_profit or 'нет'}\n\n"
        f"После первой кнопки потребуется:\n"
        f"/confirm_position {settings.live_confirm_code}",
        reply_markup=position_be_confirm_actions(token),
    )
    await callback.answer()


@dispatcher.callback_query(F.data.startswith("position_be_first:"))
async def position_be_first(callback: CallbackQuery):
    if not allowed(callback.from_user):
        return
    token = callback.data.split(":", 1)[1]
    item = position_action_pending.get(token)
    if not item:
        await callback.answer("План устарел", show_alert=True)
        return
    plan, created, _ = item
    if (
        datetime.now(timezone.utc) - created
    ).total_seconds() > settings.position_actions_confirmation_ttl_seconds:
        position_action_pending.pop(token, None)
        await callback.answer("Время истекло", show_alert=True)
        return
    position_action_pending[token] = (plan, created, True)
    await callback.message.answer(
        f"Первое подтверждение принято. В течение "
        f"{settings.position_actions_confirmation_ttl_seconds} сек. отправь:\n"
        f"/confirm_position {settings.live_confirm_code}"
    )
    await callback.answer()


@dispatcher.callback_query(F.data.startswith("position_be_cancel:"))
async def position_be_cancel(callback: CallbackQuery):
    if not allowed(callback.from_user):
        return
    position_action_pending.pop(
        callback.data.split(":", 1)[1],
        None,
    )
    await callback.answer("Отменено")
    await callback.message.edit_reply_markup(reply_markup=None)


@dispatcher.message(Command("confirm_position"))
async def confirm_position_action(message: Message):
    if not allowed(message.from_user):
        return

    parts = (message.text or "").split(maxsplit=1)
    if (
        len(parts) != 2
        or parts[1].strip() != settings.live_confirm_code
    ):
        await message.answer("Неверный код.")
        return

    now = datetime.now(timezone.utc)
    valid = []
    for token, (plan, created, first) in list(
        position_action_pending.items()
    ):
        if (
            first
            and (now - created).total_seconds()
            <= settings.position_actions_confirmation_ttl_seconds
        ):
            valid.append((token, plan))

    if len(valid) != 1:
        await message.answer(
            "Нет одной действующей подтверждённой операции."
        )
        return

    token, plan = valid[0]
    position_action_pending.pop(token, None)
    live_db.add_position_action_event(
        position_id=str(plan.position_id),
        symbol=plan.symbol,
        action="BREAKEVEN",
        state="SUBMITTING",
        details=(
            f"old={plan.current_stop_loss}; "
            f"new={plan.proposed_stop_loss}"
        ),
    )

    try:
        await confirmed_position_actions.execute_breakeven(plan)
        live_db.add_position_action_event(
            position_id=str(plan.position_id),
            symbol=plan.symbol,
            action="BREAKEVEN",
            state="VERIFIED",
            details=f"new_stop={plan.proposed_stop_loss}",
        )
        await message.answer(
            f"✅ Stop Loss перенесён и подтверждён MEXC\n"
            f"{plan.symbol} {plan.side}\n"
            f"Новый SL: {plan.proposed_stop_loss}\n"
            f"TP: {plan.take_profit or 'нет'}"
        )
    except Exception as exc:
        logger.exception("breakeven action failed")
        live_db.add_position_action_event(
            position_id=str(plan.position_id),
            symbol=plan.symbol,
            action="BREAKEVEN",
            state="ERROR",
            details=f"{type(exc).__name__}: {exc}"[:500],
        )
        await message.answer(
            "🚨 Не удалось подтвердить перенос Stop Loss. "
            "Немедленно проверь TP/SL на MEXC вручную."
        )


@dispatcher.message(Command("position_actions_log"))
async def position_actions_log(message: Message):
    if not allowed(message.from_user):
        return
    rows = live_db.recent_position_action_events(20)
    if not rows:
        await message.answer("Журнал действий по позициям пуст.")
        return
    await message.answer(
        "\n\n".join(
            f"{row['action']} — {row['state']}\n"
            f"{row['symbol']} positionId={row['position_id']}\n"
            f"{row['details'] or ''}\n"
            f"{row['created_at']}"
            for row in rows
        )
    )


@dispatcher.message(Command("regimes"))
async def regimes_status(message: Message):
    if not allowed(message.from_user): return
    if not last_signals:
        await message.answer("Режимы пока не рассчитаны. Сначала запусти сканирование.")
        return
    blocks=[]
    for signal in last_signals[: settings.portfolio_top_limit]:
        reasons="\n".join(f"• {r}" for r in (signal.regime_reasons or [])[:4])
        blocks.append(f"{signal.symbol} {signal.side}\n{signal.detailed_regime}\nAdjustment: {signal.regime_score_adjustment:+d}\nAllowed: {'YES' if signal.regime_allowed is not False else 'NO'}\n{reasons}")
    await message.answer("\n\n".join(blocks))


@dispatcher.message(Command("macro"))
async def macro_status(message: Message):
    if not allowed(message.from_user):
        return
    result = macro_guard.evaluate(symbol="BTC_USDT")
    reasons = "\n".join(
        f"• {reason}" for reason in result.reasons
    ) or "Активных блокировок нет"
    await message.answer(
        f"🗓 News & Macro Guard\n"
        f"Состояние: {result.state}\n"
        f"Новые сделки: "
        f"{'РАЗРЕШЕНЫ' if result.allowed else 'ЗАБЛОКИРОВАНЫ'}\n"
        f"Risk multiplier: {result.risk_multiplier}x\n\n"
        f"{reasons}"
    )


@dispatcher.message(Command("macro_events"))
async def macro_events(message: Message):
    if not allowed(message.from_user):
        return
    try:
        events = macro_guard.upcoming(
            limit=settings.macro_guard_max_events_display
        )
    except Exception:
        logger.exception("macro events failed")
        await message.answer("Не удалось прочитать календарь.")
        return
    if not events:
        await message.answer("Будущих событий нет.")
        return
    await message.answer(
        "\n\n".join(
            f"{event.title}\n"
            f"{event.starts_at.isoformat()}\n"
            f"Impact: {event.impact_score}\n"
            f"Category: {event.category}\n"
            f"Symbols: {', '.join(event.symbols)}"
            for event in events
        )
    )


@dispatcher.message(Command("near"))
@dispatcher.message(F.text == "🔥 Почти готово")
async def near_signals(message: Message):
    if not allowed(message.from_user):
        return
    if not last_near_signals:
        await message.answer(
            "Близких сигналов пока нет. Запусти сканирование."
        )
        return

    selected = last_near_signals[
        : settings.scanner_near_display_limit
    ]
    await message.answer(
        "\n\n".join(
            near_signal_text(signal)
            for signal in selected
        )
    )


@dispatcher.message(Command("watchlist"))
@dispatcher.message(F.text == "👀 Watchlist")
async def watchlist_status(message: Message):
    if not allowed(message.from_user):
        return
    entries = scanner_watchlist.entries()
    if not entries:
        await message.answer(
            "Watchlist пуст. Запусти минимум один скан."
        )
        return

    rows = []
    for index, entry in enumerate(
        entries[: settings.scanner_watchlist_display_limit],
        start=1,
    ):
        delta = (
            f"+{entry.delta}"
            if entry.delta > 0
            else str(entry.delta)
        )
        rows.append(
            f"{index}. {entry.symbol} {entry.side}\n"
            f"Score: {entry.score}/100 | Δ {delta}\n"
            f"Streak: {entry.streak} | {entry.status}"
        )
    await message.answer("\n\n".join(rows))


@dispatcher.message(Command("trade_limit"))
async def set_trade_limit(message: Message):
    if not allowed(message.from_user):
        return
    if not settings.runtime_trade_limits_enabled:
        await message.answer("Изменение лимитов отключено в .env.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(
            "Использование:\n"
            "/trade_limit 5 — максимум 5 сделок\n"
            "/trade_limit 0 — без дневного лимита"
        )
        return
    try:
        value = int(parts[1].strip())
    except ValueError:
        await message.answer("Лимит должен быть целым числом.")
        return
    if value < 0 or value > 10000:
        await message.answer("Допустимый диапазон: 0–10000.")
        return

    live_db.set_control("live_max_trades_per_day", str(value))
    await message.answer(
        "✅ Дневной лимит сделок: "
        + ("без лимита" if value == 0 else str(value))
    )


@dispatcher.message(Command("daily_loss_limit"))
async def set_daily_loss_limit(message: Message):
    if not allowed(message.from_user):
        return
    if not settings.runtime_trade_limits_enabled:
        await message.answer("Изменение лимитов отключено в .env.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(
            "Использование:\n"
            "/daily_loss_limit 10 — стоп после -10 USDT\n"
            "/daily_loss_limit 0 — отключить monetary loss-stop"
        )
        return
    try:
        value = float(parts[1].replace(",", ".").strip())
    except ValueError:
        await message.answer("Лимит должен быть числом.")
        return
    if value < 0 or value > 1_000_000:
        await message.answer("Некорректное значение.")
        return

    live_db.set_control("live_daily_loss_limit_usdt", str(value))
    await message.answer(
        "✅ Дневной loss-stop: "
        + ("выключен" if value == 0 else f"{value:.2f} USDT")
    )


@dispatcher.message(Command("limits"))
async def limits_status(message: Message):
    if not allowed(message.from_user):
        return
    count, pnl = live_db.today()
    trade_limit = effective_trade_limit()
    loss_limit = effective_daily_loss_limit()
    trade_text = "без лимита" if trade_limit == 0 else str(trade_limit)
    loss_text = (
        "выключен"
        if loss_limit == 0
        else f"{loss_limit:.2f} USDT"
    )
    await message.answer(
        f"⚙️ Runtime Limits\n"
        f"Сделок сегодня: {count}\n"
        f"Лимит сделок: {trade_text}\n"
        f"Текущий PnL: {pnl:+.2f} USDT\n"
        f"Loss-stop: {loss_text}"
    )


@dispatcher.message(Command("whitelist"))
async def whitelist_status(message: Message):
    if not allowed(message.from_user):
        return
    symbols = sorted(whitelist_manager.effective())
    if not symbols:
        await message.answer("LIVE whitelist пуст. Реальные входы запрещены.")
        return
    chunks = [symbols[index:index + 40] for index in range(0, len(symbols), 40)]
    for index, chunk in enumerate(chunks, start=1):
        await message.answer(
            f"✅ LIVE whitelist: {len(symbols)} пар"
            + (f" — часть {index}/{len(chunks)}" if len(chunks) > 1 else "")
            + "\n\n"
            + ", ".join(chunk)
        )


@dispatcher.message(Command("allow"))
async def whitelist_allow(message: Message):
    if not allowed(message.from_user):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Использование: /allow DOGE_USDT")
        return
    symbol = parts[1].strip().upper()
    if not symbol.endswith("_USDT"):
        await message.answer("Разрешены только символы вида DOGE_USDT.")
        return
    try:
        spec = await confirm_service.contract_spec(symbol)
    except Exception:
        await message.answer("Контракт не найден на MEXC.")
        return
    if not spec.api_allowed or spec.state != 0:
        await message.answer("Контракт сейчас недоступен для API-торговли.")
        return
    symbols = whitelist_manager.allow(symbol)
    await message.answer(f"✅ {symbol} добавлена. Всего: {len(symbols)}")


@dispatcher.message(Command("deny"))
async def whitelist_deny(message: Message):
    if not allowed(message.from_user):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Использование: /deny DOGE_USDT")
        return
    symbol = parts[1].strip().upper()
    symbols = whitelist_manager.deny(symbol)
    await message.answer(f"✅ {symbol} удалена. Всего: {len(symbols)}")


@dispatcher.message(Command("clear_whitelist"))
async def whitelist_clear(message: Message):
    if not allowed(message.from_user):
        return
    whitelist_manager.clear()
    await message.answer(
        "⚠️ LIVE whitelist очищен. Все новые реальные входы запрещены."
    )


@dispatcher.message(Command("allow_bluechips"))
async def whitelist_bluechips(message: Message):
    if not allowed(message.from_user):
        return
    await message.answer("Проверяю blue-chip контракты MEXC...")
    try:
        result = await whitelist_manager.build_bluechips()
    except Exception:
        logger.exception("bluechip whitelist build failed")
        await message.answer("Не удалось обновить whitelist.")
        return
    await message.answer(
        f"✅ Blue-chip whitelist обновлён: {len(result.symbols)} пар."
    )


@dispatcher.message(Command("allow_all_top100"))
async def whitelist_top100(message: Message):
    if not allowed(message.from_user):
        return
    await message.answer(
        "Проверяю USDT-фьючерсы, ликвидность, спред и API-доступ..."
    )
    try:
        result = await whitelist_manager.build_top(100)
    except Exception:
        logger.exception("top100 whitelist build failed")
        await message.answer("Не удалось сформировать whitelist.")
        return
    rejected = ", ".join(
        f"{key}={value}" for key, value in sorted(result.rejected.items())
    ) or "нет"
    await message.answer(
        f"✅ LIVE whitelist обновлён: {len(result.symbols)} пар.\n"
        f"Отфильтровано: {rejected}\n\n"
        f"Проверь список командой /whitelist"
    )


@dispatcher.message(Command("status"))
@dispatcher.message(F.text == "📊 Статус")
async def status(message: Message):
    if not allowed(message.from_user): return
    count, pnl = live_db.today()
    trade_limit = effective_trade_limit()
    loss_limit = effective_daily_loss_limit()
    trade_limit_text = (
        "без лимита" if trade_limit == 0 else str(trade_limit)
    )
    loss_limit_text = (
        "выключен"
        if loss_limit == 0
        else f"{loss_limit:.2f} USDT"
    )
    await message.answer(
        f"Режим: {settings.trading_mode}\n"
        f"CONFIRM: {'разблокирован' if settings.confirm_unlocked else 'заблокирован'}\n"
        f"LIVE whitelist: {len(whitelist_manager.effective())} пар\n"
        f"Сделок сегодня: {count}/{trade_limit_text}\n"
        f"Дневной loss-stop: {loss_limit_text}\n"
        f"Зафиксированный дневной PnL: {pnl:+.2f} USDT\n"
        f"Автоскан: {'работает' if scan_running else 'пауза'}\n"
        f"Следующий интервал: {adaptive_scan_interval()} сек."
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



async def whitelist_auto_update_loop(bot: Bot):
    while True:
        await asyncio.sleep(
            max(1, settings.whitelist_auto_update_interval_hours) * 3600
        )
        if not (
            settings.whitelist_manager_enabled
            and settings.whitelist_auto_update_enabled
        ):
            continue
        try:
            result = await whitelist_manager.build_top(
                settings.whitelist_top_limit
            )
            for chat_id in settings.allowed_user_ids:
                await bot.send_message(
                    chat_id,
                    f"🔄 LIVE whitelist обновлён автоматически: "
                    f"{len(result.symbols)} пар."
                )
        except Exception:
            logger.exception("automatic whitelist update failed")


async def auto_scan_loop(bot: Bot):
    while True:
        await asyncio.sleep(adaptive_scan_interval())
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
        BotCommand(command="confirm_position", description="Подтвердить действие"),
        BotCommand(command="position_actions_log", description="Журнал действий"),
        BotCommand(command="regimes", description="Режимы рынка"),
        BotCommand(command="macro", description="Статус Macro Guard"),
        BotCommand(command="macro_events", description="Ближайшие события"),
        BotCommand(command="near", description="Почти готовые сигналы"),
        BotCommand(command="watchlist", description="Watchlist сканера"),
        BotCommand(command="limits", description="Текущие лимиты"),
        BotCommand(command="trade_limit", description="Лимит сделок 0=∞"),
        BotCommand(command="daily_loss_limit", description="Дневной loss-stop"),
        BotCommand(command="whitelist", description="LIVE whitelist"),
        BotCommand(command="allow", description="Разрешить пару"),
        BotCommand(command="deny", description="Запретить пару"),
        BotCommand(command="allow_bluechips", description="Blue-chip whitelist"),
        BotCommand(command="allow_all_top100", description="Топ-100 ликвидных пар"),
        BotCommand(command="confirm_trade", description="Подтвердить LIVE-сделку"),
    ])
    asyncio.create_task(auto_scan_loop(bot))
    asyncio.create_task(whitelist_auto_update_loop(bot))
    asyncio.create_task(position_intelligence_loop(bot))
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
