from dataclasses import dataclass
from app.models import Signal

@dataclass(slots=True)
class MarketRegimeResult:
    regime: str
    score_adjustment: int
    allowed: bool
    reasons: list[str]

class MarketRegimeEngine:
    def __init__(self, settings): self.settings=settings

    def classify(self, signal: Signal) -> MarketRegimeResult:
        d=signal.diagnostics or {}
        adx=float(d.get('primary_adx',0) or 0)
        atr=float(d.get('primary_atr_percent',0) or 0)
        volume=float(d.get('primary_relative_volume',0) or 0)
        momentum=float(d.get('primary_momentum_percent',0) or 0)
        base=(signal.market_regime or 'UNKNOWN').upper()
        reasons=[]; allowed=True; adj=0
        if atr>=self.settings.market_regime_panic_atr_percent or abs(momentum)>=self.settings.market_regime_panic_momentum_percent or signal.volatility_state=='PANIC':
            if self.settings.market_regime_block_new_entries_in_panic: allowed=False
            return MarketRegimeResult('PANIC',0,allowed,['Экстремальная волатильность или импульс'])
        if adx>=self.settings.market_regime_strong_trend_adx:
            regime='STRONG_BULL_TREND' if momentum>0 else 'STRONG_BEAR_TREND' if momentum<0 else 'STRONG_TREND'
        elif adx>=self.settings.market_regime_weak_trend_adx:
            regime='WEAK_BULL_TREND' if momentum>0 else 'WEAK_BEAR_TREND' if momentum<0 else 'WEAK_TREND'
        elif base=='COMPRESSION': regime='COMPRESSION'
        elif base=='RANGE': regime='SIDEWAYS'
        elif volume>=self.settings.market_regime_breakout_volume_ratio and abs(momentum)>=0.5: regime='BREAKOUT'
        else: regime='MIXED'
        aligned=(regime in {'STRONG_BULL_TREND','WEAK_BULL_TREND'} and signal.side=='LONG') or (regime in {'STRONG_BEAR_TREND','WEAK_BEAR_TREND'} and signal.side=='SHORT')
        counter=(regime in {'STRONG_BULL_TREND','WEAK_BULL_TREND'} and signal.side=='SHORT') or (regime in {'STRONG_BEAR_TREND','WEAK_BEAR_TREND'} and signal.side=='LONG')
        if aligned: adj+=self.settings.market_regime_aligned_bonus; reasons.append('Сигнал совпадает с направлением режима')
        elif counter: adj-=self.settings.market_regime_countertrend_penalty; reasons.append('Сигнал направлен против режима')
        if regime=='SIDEWAYS': adj-=self.settings.market_regime_range_penalty; reasons.append('Боковой рынок ослабляет трендовый вход')
        elif regime=='COMPRESSION': adj-=self.settings.market_regime_compression_penalty; reasons.append('Нужен подтверждённый выход из сжатия')
        elif regime=='BREAKOUT': adj+=self.settings.market_regime_breakout_bonus; reasons.append('Пробой подтверждён объёмом и импульсом')
        return MarketRegimeResult(regime,adj,allowed,reasons)

    def attach(self, signal: Signal) -> Signal:
        r=self.classify(signal); signal.detailed_regime=r.regime; signal.regime_score_adjustment=r.score_adjustment; signal.regime_allowed=r.allowed; signal.regime_reasons=r.reasons; return signal
