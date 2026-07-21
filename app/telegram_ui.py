from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def main_menu(running: bool, confirm_enabled: bool = False) -> ReplyKeyboardMarkup:
    scan_button = "⏸ Пауза" if running else "▶️ Запустить автоскан"
    rows = [
        [KeyboardButton(text="📡 Сканировать сейчас"), KeyboardButton(text="📊 Статус")],
        [KeyboardButton(text=scan_button), KeyboardButton(text="💼 Портфель")],
        [KeyboardButton(text="📈 Позиции"), KeyboardButton(text="📜 История")],
        [KeyboardButton(text="🏆 Топ сигналов"), KeyboardButton(text="🌐 Рынок")],
        [KeyboardButton(text="🔥 Почти готово"), KeyboardButton(text="👀 Watchlist")],
        [KeyboardButton(text="🛡 Риск")],
        [KeyboardButton(text="🧭 Совет по позициям")],
        [KeyboardButton(text="🧾 Отчёт"), KeyboardButton(text="🏠 Меню")],
    ]
    if confirm_enabled:
        rows.insert(0, [KeyboardButton(text="🔄 LIVE-сверка"), KeyboardButton(text="📒 LIVE-журнал")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def signal_actions(token: str, confirm_enabled: bool = False) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(text="✅ Открыть PAPER", callback_data=f"paper_open:{token}"),
        InlineKeyboardButton(text="❌ Пропустить", callback_data=f"paper_skip:{token}"),
    ]
    if confirm_enabled:
        row.insert(0, InlineKeyboardButton(text="⚠️ Подготовить LIVE", callback_data=f"confirm_prepare:{token}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def confirm_plan_actions(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⚠️ Первое подтверждение", callback_data=f"confirm_first:{token}"),
        InlineKeyboardButton(text="Отмена", callback_data=f"confirm_cancel:{token}"),
    ]])


def position_actions(position_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Закрыть PAPER", callback_data=f"paper_close:{position_id}")
    ]])


def live_position_actions(position_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚨 Закрыть LIVE", callback_data=f"live_close_position:{position_id}")
    ]])



def position_management_actions(position_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🟦 Подготовить безубыток",
            callback_data=f"position_be_prepare:{position_id}",
        )
    ]])


def position_be_confirm_actions(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚠️ Первое подтверждение BE",
            callback_data=f"position_be_first:{token}",
        ),
        InlineKeyboardButton(
            text="Отмена",
            callback_data=f"position_be_cancel:{token}",
        ),
    ]])
