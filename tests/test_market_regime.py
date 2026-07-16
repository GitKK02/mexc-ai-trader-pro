from app.market_regime import MarketRegimeEngine
from app.models import Signal
class Settings:
 market_regime_strong_trend_adx=28.0; market_regime_weak_trend_adx=18.0; market_regime_breakout_volume_ratio=1.25; market_regime_panic_atr_percent=5.0; market_regime_panic_momentum_percent=3.0; market_regime_countertrend_penalty=18; market_regime_aligned_bonus=8; market_regime_range_penalty=10; market_regime_compression_penalty=6; market_regime_breakout_bonus=10; market_regime_block_new_entries_in_panic=True

def sig(side='LONG',adx=30,atr=1,vol=1,mom=1,reg='TREND'):
 return Signal(symbol='BTC_USDT',side=side,score=90,entry=100,stop_loss=99,tp1=101,tp2=102,atr=1,reasons=['x'],market_regime=reg,diagnostics={'primary_adx':adx,'primary_atr_percent':atr,'primary_relative_volume':vol,'primary_momentum_percent':mom})
def test_aligned():
 r=MarketRegimeEngine(Settings()).classify(sig()); assert r.regime=='STRONG_BULL_TREND' and r.score_adjustment>0
def test_countertrend(): assert MarketRegimeEngine(Settings()).classify(sig(side='SHORT')).score_adjustment<0
def test_panic():
 r=MarketRegimeEngine(Settings()).classify(sig(atr=6)); assert r.regime=='PANIC' and r.allowed is False
def test_sideways():
 r=MarketRegimeEngine(Settings()).classify(sig(adx=10,mom=0,reg='RANGE')); assert r.regime=='SIDEWAYS' and r.score_adjustment<0
def test_breakout():
 r=MarketRegimeEngine(Settings()).classify(sig(adx=10,vol=1.4,mom=1.2,reg='MIXED')); assert r.regime=='BREAKOUT' and r.score_adjustment>0
