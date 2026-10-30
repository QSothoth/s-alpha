"""Small display features from the existing panel; never fetch or replay strategies."""
from __future__ import annotations


RULES = {
    'volume_high': ('量能', '放量 ≥2倍', '成交量 / 前20个完整交易日平均量 ≥2'),
    'volume_low': ('量能', '缩量 ≤0.5倍', '成交量 / 前20个完整交易日平均量 ≤0.5；仅收盘后'),
    'volume_partial': ('量能', '累计量已达整日均量2倍', '原始快照累计量 / 前20个完整交易日平均量 ≥2；不推演全天量'),
    'near_high': ('价格位置', '接近一年高点', '最新价 ≥前252个交易日最高价的95%'),
    'strong': ('相对强弱', '20日强势组', '20日涨幅在同市场有效股票池的80%分位之上'),
    'weak': ('相对强弱', '20日弱势组', '20日涨幅在同市场有效股票池的20%分位之下'),
    'volatile': ('波动', '日均振幅 ≥4%', '前20个完整交易日平均(最高价/最低价−1) ≥4%'),
    'illiquid': ('流动性', '相对低成交额', '前20个完整交易日平均成交额在同市场有效股票池的20%分位之下'),
}


def market_features(panel, market, *, partial=False):
    """O(stocks * 252) bounded windows, O(stocks) output; exclude today from baselines.

    Partial input MUST be the original snapshot panel, never a confidence scenario.
    Ranks use strict quantiles so a tied/flat universe is not all 'strong' or 'weak'.
    """
    import numpy as np  # QQ cards run under system python without numpy

    p = panel
    close = np.asarray(p['close'][-1], dtype=float)
    count = len(close)
    empty = lambda: np.full(count, np.nan)

    def prior_mean(field):
        if len(p['days']) < 21:
            return empty()
        values = np.asarray(p[field][-21:-1], dtype=float)
        valid = np.all(np.isfinite(values) & (values >= 0), axis=0)
        return np.where(valid, np.mean(values, axis=0), np.nan)

    volume, turnover = prior_mean('volume'), prior_mean('turnover')
    with np.errstate(invalid='ignore', divide='ignore'):
        rvol = np.where(volume > 0, p['volume'][-1] / volume, np.nan)
        ret = close / p['close'][-21] - 1 if len(p['days']) >= 21 else empty()
        if len(p['days']) >= 21:
            high, low = p['high'][-21:-1], p['low'][-21:-1]
            valid = np.all(np.isfinite(high) & np.isfinite(low) & (low > 0) & (high >= low), axis=0)
            adr = np.where(valid, np.mean(high / low - 1, axis=0), np.nan)
        else:
            adr = empty()
        if len(p['days']) >= 253:
            highs = p['high'][-253:-1]
            valid = np.all(np.isfinite(highs) & (highs > 0), axis=0)
            high_ratio = np.where(valid, close / np.max(highs, axis=0), np.nan)
        else:
            high_ratio = empty()
    quoted = np.isfinite(close) & (close > 0) & np.isfinite(p['volume'][-1]) & (p['volume'][-1] > 0)
    pool = quoted & np.isfinite(turnover) & (turnover > 0)
    if market == 'us':
        pool &= (p['raw_close'][-1] >= 1) & (turnover >= 2e6)

    def percentile_mask(values, q, high=False):
        ok = pool & np.isfinite(values)
        threshold = float(np.quantile(values[ok], q)) if np.any(ok) else None
        hit = np.zeros(count, dtype=bool) if threshold is None else (
            values > threshold if high else values < threshold)
        return hit, threshold

    strong, strong_cut = percentile_mask(ret, .8, True)
    weak, weak_cut = percentile_mask(ret, .2)
    illiquid, liquid_cut = percentile_mask(turnover, .2)
    tests = {
        'volume_partial' if partial else 'volume_high': (rvol, rvol >= 2),
        'near_high': (high_ratio, high_ratio >= .95),
        'strong': (ret, strong), 'weak': (ret, weak),
        'volatile': (adr, adr >= .04), 'illiquid': (turnover, illiquid),
    }
    if not partial:
        tests['volume_low'] = (rvol, rvol <= .5)
    background = {}
    for key, (values, hit) in tests.items():
        ok = pool & np.isfinite(values)
        dimension, label, definition = RULES[key]
        background[key] = dict(dimension=dimension, label=label, definition=definition,
                               matched=int(np.sum(ok & hit)), valid=int(np.sum(ok)))
    stocks = {}
    for j, code in enumerate(p['codes']):
        if not quoted[j]:
            continue
        metrics = {key: float(values[j]) for key, values in (
            ('rvol20', rvol), ('return20', ret), ('high_ratio', high_ratio),
            ('adr20', adr), ('turnover20', turnover), ('price', close),
            ('volume', p['volume'][-1]), ('volume20', volume)) if np.isfinite(values[j])}
        tags = [key for key, (values, hit) in tests.items() if np.isfinite(values[j]) and hit[j]
                and (pool[j] or key not in ('strong', 'weak', 'illiquid'))]
        stocks[str(code)] = dict(metrics=metrics, tags=tags, in_pool=bool(pool[j]))
    return dict(asof=str(p['days'][-1]), digest=str(p['digest']),
                historical_through=str(p['days'][-2]) if len(p['days']) > 1 else None,
                basis='snapshot' if partial else 'close', stocks=stocks, background=background,
                pool=dict(eligible=int(np.sum(pool)), total=count,
                          definition='当日有成交且前20日成交额有效；美股另需股价≥1美元、均额≥200万美元'),
                thresholds=dict(strong=strong_cut, weak=weak_cut, illiquid=liquid_cut))


def enrich_cached(run):
    """Upgrade an older daily report using identical local inputs, without network I/O.

    Old intraday reports did not persist raw volume. Do not fill that gap with a
    later completed bar or with the scenario's modeled volume.
    """
    from . import aggregation
    existing = run.get('presentation', {}).get('aggregation')
    if existing and (existing['basis'] != 'unavailable' or run.get('provisional')):
        return
    features = None
    if run.get('digest') and run.get('mode') in ('live', 'frozen') and not run.get('provisional'):
        from studies import trader_data as TD
        from studies.trader_data import panel as TP
        ds = TD.dataset(run['market'], run['mode'])
        if ds.digest() == run['digest']:
            p = TP.build(ds, upto=run['last_day'], write_cache=False)
            if len(p['days']) and str(p['days'][-1]) == run['last_day']:
                features = market_features(p, run['market'])
    aggregation.attach(run, features)
