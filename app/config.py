from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = "TEST_TOKEN"
    telegram_allowed_user_ids: str = "1"

    mexc_api_key: str = ""
    mexc_api_secret: str = ""
    mexc_base_url: str = "https://api.mexc.com"
    mexc_recv_window_seconds: int = 10

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    ai_enabled: bool = True
    ai_fail_mode: str = "SAFE"

    trading_mode: str = "PAPER"  # PAPER | CONFIRM
    enable_live_trading: bool = False
    live_trading_ack: str = ""
    live_confirm_code: str = ""
    confirmation_ttl_seconds: int = 90

    live_symbol_whitelist: str = "BTC_USDT,ETH_USDT,SOL_USDT,LINK_USDT"
    live_risk_per_trade_percent: float = 0.10
    live_max_risk_per_trade_percent: float = 0.25
    live_max_notional_usdt: float = 100.0
    live_max_open_positions: int = 2
    live_max_leverage: int = 2
    live_open_type: int = 1
    live_position_mode: int = 1
    live_stop_atr_multiplier: float = 1.5
    live_take_profit_r: float = 2.0
    live_max_entry_deviation_percent: float = 0.20
    live_daily_loss_limit_usdt: float = 10.0
    live_max_trades_per_day: int = 4
    live_min_contract_risk_usdt: float = 0.01

    paper_initial_balance_usdt: float = 10_000.0
    paper_taker_fee_percent: float = 0.055
    paper_slippage_percent: float = 0.03
    paper_price_poll_seconds: int = 10
    max_positions: int = 2

    risk_per_trade_percent: float = 0.5
    max_leverage: int = 3
    min_risk_reward: float = 2.0
    tp1_r: float = 1.0
    tp1_close_percent: float = 35.0
    tp2_r: float = 2.0
    tp2_close_percent: float = 35.0
    runner_percent: float = 30.0
    breakeven_buffer_percent: float = 0.03
    trailing_atr_multiplier: float = 1.8

    auto_scan_on_start: bool = False
    scan_interval_seconds: int = 300
    min_24h_turnover_usdt: float = 50_000_000
    max_spread_percent: float = 0.12
    max_deep_candidates: int = 10
    max_ai_candidates: int = 3
    max_signals_per_cycle: int = 3
    signal_cooldown_minutes: int = 60
    symbol_whitelist: str = "BTC_USDT,ETH_USDT,SOL_USDT,LINK_USDT"
    min_signal_score_paper: int = 70
    min_signal_score_confirm: int = 80

    scanner_timeframes: str = "Min5,Min15,Min60,Hour4"
    scanner_primary_timeframe: str = "Min15"
    scanner_btc_context_enabled: bool = True
    scanner_market_regime_enabled: bool = True
    scanner_min_history_bars: int = 220
    scanner_max_parallel_requests: int = 4
    scanner_require_volume_confirmation: bool = False
    scanner_min_relative_volume: float = 0.80
    scanner_min_atr_percent: float = 0.20
    scanner_max_atr_percent: float = 8.00
    scanner_ai_only_top_n: int = 3
    scanner_signal_expiration_seconds: int = 180

    portfolio_manager_enabled: bool = True
    portfolio_max_total_risk_percent: float = 0.50
    portfolio_max_same_direction_risk_percent: float = 0.35
    portfolio_max_group_risk_percent: float = 0.25
    portfolio_max_positions_per_group: int = 1
    portfolio_min_adjusted_score_confirm: int = 80
    portfolio_reduce_score_same_direction: int = 8
    portfolio_reduce_score_same_group: int = 15
    portfolio_block_same_symbol: bool = True
    portfolio_top_limit: int = 10

    decision_engine_enabled: bool = True
    decision_enter_score: int = 90
    decision_confirm_score: int = 82
    decision_wait_score: int = 72
    decision_require_ai_for_enter: bool = True
    decision_block_on_ai_error: bool = False
    decision_ai_approve_bonus: int = 6
    decision_ai_wait_penalty: int = 6
    decision_ai_reject_penalty: int = 30
    decision_trend_regime_bonus: int = 5
    decision_range_regime_penalty: int = 8
    decision_unstable_btc_penalty: int = 12
    decision_min_timeframe_agreement: int = 3

    position_intelligence_enabled: bool = True
    position_intelligence_poll_seconds: int = 20
    position_intelligence_mode: str = "SHADOW"
    position_intelligence_tp1_r: float = 1.0
    position_intelligence_breakeven_r: float = 1.0
    position_intelligence_trail_start_r: float = 1.5
    position_intelligence_exit_r: float = -1.0
    position_intelligence_notify_on_change_only: bool = True
    position_intelligence_min_notify_seconds: int = 120
    position_intelligence_max_positions: int = 10

    position_actions_enabled: bool = True
    position_actions_mode: str = "CONFIRM"
    position_actions_confirmation_ttl_seconds: int = 60
    position_actions_breakeven_buffer_percent: float = 0.03
    position_actions_min_r_for_breakeven: float = 1.0
    position_actions_require_existing_stop: bool = True
    portfolio_correlation_groups: str = (
        "BTC:BTC_USDT;"
        "LARGE_CAP:ETH_USDT,BNB_USDT;"
        "L1_BETA:SOL_USDT,AVAX_USDT,SUI_USDT,APT_USDT,NEAR_USDT,SEI_USDT;"
        "PAYMENTS:XRP_USDT,ADA_USDT,TRX_USDT;"
        "L2:ARB_USDT,OP_USDT;"
        "MEME:DOGE_USDT;"
        "ORACLE:LINK_USDT;"
        "TON:TON_USDT;"
        "DEFI:INJ_USDT"
    )

    database_path: str = "./data/trader.db"
    live_database_path: str = "./data/live_trader.db"
    log_level: str = "INFO"
    timezone: str = "Europe/Moscow"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_user_ids(self) -> set[int]:
        return {int(v.strip()) for v in self.telegram_allowed_user_ids.split(",") if v.strip().isdigit()}

    @property
    def whitelist(self) -> set[str]:
        return {v.strip().upper() for v in self.symbol_whitelist.split(",") if v.strip()}

    @property
    def configured_timeframes(self) -> list[str]:
        return [
            value.strip()
            for value in self.scanner_timeframes.split(",")
            if value.strip()
        ]

    @property
    def correlation_groups(self) -> dict[str, set[str]]:
        groups: dict[str, set[str]] = {}
        for raw_group in self.portfolio_correlation_groups.split(";"):
            raw_group = raw_group.strip()
            if not raw_group or ":" not in raw_group:
                continue
            name, raw_symbols = raw_group.split(":", 1)
            groups[name.strip().upper()] = {
                symbol.strip().upper()
                for symbol in raw_symbols.split(",")
                if symbol.strip()
            }
        return groups

    @property
    def live_whitelist(self) -> set[str]:
        return {v.strip().upper() for v in self.live_symbol_whitelist.split(",") if v.strip()}

    @property
    def confirm_unlocked(self) -> bool:
        return (
            self.trading_mode.upper() == "CONFIRM"
            and self.enable_live_trading
            and self.live_trading_ack == "I_UNDERSTAND_REAL_ORDERS"
            and len(self.live_confirm_code) >= 6
        )


settings = Settings()
