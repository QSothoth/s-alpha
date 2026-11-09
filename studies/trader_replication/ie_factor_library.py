"""Frozen IE indicator inventory and bounded, causal single-stock calculations."""
from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np

WINDOWS = (3, 5, 10, 14, 20, 50, 100, 200)
TRANSFORMS = ('pct', 'delta5', 'history250')
PATTERNS = tuple(('2crows 3blackcrows 3inside 3linestrike 3outside 3starsinsouth '
    '3whitesoldiers abandonedbaby advanceblock belthold breakaway closingmarubozu '
    'concealbabyswall counterattack darkcloudcover doji dojistar dragonflydoji engulfing '
    'eveningdojistar eveningstar gapsidesidewhite gravestonedoji hammer hangingman harami '
    'haramicross highwave hikkake hikkakemod homingpigeon identical3crows inneck '
    'invertedhammer kicking kickingbylength ladderbottom longleggeddoji longline marubozu '
    'matchinglow mathold morningdojistar morningstar onneck piercing rickshawman '
    'risefall3methods separatinglines shootingstar shortline spinningtop stalledpattern '
    'sticksandwich takuri tasukigap thrusting tristar unique3river upsidegap2crows '
    'xsidegap3methods').split())


@dataclass(frozen=True)
class Spec:
    name: str
    family: str
    parameter: int
    metric: str
    formula: str


def inventory():
    out = []
    def add(family, params, formulas):
        for p in params:
            for metric, formula in formulas.items():
                name = metric if family == 'original53' else f'{family}.{metric}.{p}'
                out.append(Spec(name, family, p, metric, formula))
    original = {}
    for n in (1, 3, 5, 10, 21, 63, 126):
        original[f'g{n}'] = f'c/c[-{n}]-1'
        original[f'rs{n}'] = f'g{n}-QQQ_g{n}'
    for n in (20, 60, 120):
        original[f'low{n}'] = f'c/min(c,{n})-1'
    for n in (20, 60, 252):
        original[f'high{n}'] = f'c/max(h,{n})-1'
    for n in (20, 60):
        original[f'fresh_high{n}'] = f'-age(h>=max(h[-1],{n}),120)'
    original.update(money20='mean(T,20)', rvol1='v/mean(v,20)',
        rvol3='mean(v,3)/mean(v,20)', rvol5='mean(v,5)/mean(v,20)',
        adr20='mean(h/l-1,20)', contract5='-mean(h/l-1,5)/ADR20',
        range10='-(max(h,10)/min(l,10)-1)/ADR20', close_position='(c-l)/(h-l)')
    for n in (9, 21, 50):
        original[f'ema{n}'] = f'c/EMA(c,{n})-1'
        original[f'near_ema{n}'] = f'-abs(c/EMA(c,{n})-1)/ADR20'
        original[f'cross{n}'] = f'-age(c>EMA{n} and c[-1]<=EMA{n}[-1],120)'
    original.update(ema_stack='1(EMA9>EMA21)+1(EMA21>EMA50)',
        gap20='max(max(o/c[-1]-1,0)/ADR20[-1],20)',
        fresh_gap='-age(o/c[-1]-1>=2*ADR20[-1],60)',
        pot_count20='sum(corrected_potent,20)', fresh_pot='-age(corrected_potent,60)',
        earn_age='-min(120,calendar_days_since_known_past_earnings)',
        peer_g5='mean(g5 of original residual-correlation peers)',
        peer_rank='original peer_rank',
        **{f'h4_{x}': 'original H4 group percentile; t-1 clock' for x in
           ('activity', 'momentum', 'history', 'stack', 'peers', 'coil')})
    add('original53', (0,), original)
    add('overlap', WINDOWS, {
        'sma': 'c/SMA(c,n)-1', 'ema': 'c/EMA(c,n)-1', 'wma': 'c/WMA(c,n)-1',
        'dema': 'c/(2*EMA-EMA(EMA,n))-1', 'tema': 'c/(3*EMA-3*EMA2+EMA3)-1',
        'trima': 'c/SMA(SMA(c,ceil(n/2)),floor(n/2)+1)-1',
        'kama': 'c/KAMA(n,fast=2,slow=30)-1', 't3': 'c/T3(n,v=.7)-1',
        'mama': 'c/MAMA(fast=2/(n+1),slow=fast/10,causal Hilbert phase)-1',
        'fama': 'c/FAMA(alpha=MAMA_alpha/2)-1',
        'midpoint': 'c/((max(c,n)+min(c,n))/2)-1',
        'midprice': 'c/((max(h,n)+min(l,n))/2)-1',
        'bb_position': '(c-SMA(c,n))/(2*std(c,n))',
        'bb_width': '-4*std(c,n)/SMA(c,n)',
        'sar': '(c-PSAR(step=2/(n+1)*.1,max=.2))/c',
        'sarext': '(c-PSAR(step=2/(n+1)*.2,max=.4))/c'})
    add('momentum', WINDOWS, {
        'roc': 'c/c[-n]-1', 'rocp': '(c-c[-n])/c[-n]',
        'rocr': 'c/c[-n]', 'rocr100': '100*c/c[-n]', 'mom': '(c-c[-n])/ATR(n)',
        'rsi': 'Wilder(up,n)/(Wilder(up,n)+Wilder(down,n))',
        'cmo': '(sum(up,n)-sum(down,n))/sum(abs(change),n)',
        'cci': '(typical-mean(typical,n))/(.015*mean_abs_deviation(typical,n))',
        'dx': 'abs(DIplus-DIminus)/(DIplus+DIminus)',
        'adx': 'Wilder(DX,n)', 'adxr': '(ADX+ADX[-n])/2',
        'plus_di': 'Wilder(DMplus,n)/ATR(n)', 'minus_di': '-Wilder(DMminus,n)/ATR(n)',
        'plus_dm': 'Wilder(DMplus,n)/ATR(n)', 'minus_dm': '-Wilder(DMminus,n)/ATR(n)',
        'aroon_up': 'argmax(h,n)/(n-1)', 'aroon_down': '-argmin(l,n)/(n-1)',
        'aroonosc': 'aroon_up+aroon_down', 'willr': '(c-max(h,n))/(max(h,n)-min(l,n))',
        'stoch_k': '(c-min(l,n))/(max(h,n)-min(l,n))',
        'stoch_d': 'SMA(stoch_k,3)', 'stochrsi': '(RSI-min(RSI,n))/(max(RSI,n)-min(RSI,n))',
        'trix': 'EMA(EMA(EMA(c,n),n),n)/previous-1',
        'bop': 'SMA((c-o)/(h-l),n)', 'apo': '(EMA(c,n)-EMA(c,2n))/c',
        'ppo': 'EMA(c,n)/EMA(c,2n)-1', 'macd': '(EMA(c,n)-EMA(c,2n))/ATR(n)',
        'macd_signal': 'EMA(macd,max(2,n//3))', 'macd_hist': 'macd-macd_signal',
        'mfi': 'sum(typical*v where typical rises,n)/sum(directional typical*v,n)',
        'ultosc': '(4*BP/TR(n)+2*BP/TR(2n)+BP/TR(4n))/7'})
    add('volume', WINDOWS, {
        'ad': 'sum(((2c-h-l)/(h-l))*v,n)/sum(v,n)',
        'adosc': '(EMA(cumulative_AD,n)-EMA(cumulative_AD,3n))/mean(v,n)',
        'obv': 'sum(sign(change(c))*v,n)/sum(v,n)',
        'cmf': 'sum(((2c-h-l)/(h-l))*v,n)/sum(v,n)',
        'vwap': 'c/(sum(typical*v,n)/sum(v,n))-1',
        'pvt': 'sum((c/c[-1]-1)*v,n)/sum(v,n)',
        'nvi': 'sum(log(c/c[-1]) where v<v[-1],n)',
        'pvi': 'sum(log(c/c[-1]) where v>v[-1],n)',
        'rvol': 'v/mean(v,n)', 'dollar_volume': 'mean(T,n)',
        'volume_trend': 'linear_slope(v,n)/mean(v,n)',
        'up_down': 'sum(v where c>c[-1],n)/sum(v where c<c[-1],n)',
        'price_volume_corr': 'corr(log(c/c[-1]),log(v/v[-1]),n)',
        'volume_z': '(v-mean(v,n))/std(v,n)',
        'amihud': '-mean(abs(c/c[-1]-1)/T,n)'})
    add('volatility', WINDOWS, {
        'atr': 'Wilder(TR,n)/c', 'natr': '100*ATR(n)/c',
        'trange': 'mean(TR,n)/c', 'adr': 'mean(h/l-1,n)',
        'hv': 'std(log(c/c[-1]),n)*sqrt(252)',
        'parkinson': 'sqrt(mean(log(h/l)^2,n)/(4log(2)))',
        'garman_klass': 'sqrt(max(0,mean(.5log(h/l)^2-(2log(2)-1)*log(c/o)^2,n)))',
        'rogers_satchell': 'sqrt(max(0,mean(log(h/o)*log(h/c)+log(l/o)*log(l/c),n)))',
        'downside': '-sqrt(mean(min(log(c/c[-1]),0)^2,n))',
        'upside': 'sqrt(mean(max(log(c/c[-1]),0)^2,n))',
        'compression': '-std(log(c/c[-1]),n)/std(log(c/c[-1]),2n)',
        'range_compression': '-mean(h/l-1,n)/mean(h/l-1,2n)',
        'ulcer': '-sqrt(mean((c/max(c,n)-1)^2,n))',
        'choppiness': '-log10(sum(TR,n)/(max(h,n)-min(l,n)))/log10(n)'})
    add('statistics', WINDOWS, {
        'beta': 'cov(stock_log_return,QQQ_log_return,n)/var(QQQ_log_return,n)',
        'correl': 'corr(stock_log_return,QQQ_log_return,n)',
        'alpha': 'mean(stock_return,n)-beta*mean(QQQ_return,n)',
        'linearreg': '(LINEARREG(c,n)-c)/c', 'linearreg_slope': 'linear_slope(c,n)/mean(c,n)',
        'linearreg_angle': 'atan(n*linear_slope(c,n)/mean(c,n))',
        'linearreg_intercept': 'linear_intercept(c,n)/c-1',
        'tsf': 'linear_prediction(c,n,one_step)/c-1',
        'stddev': 'std(c,n)/mean(c,n)', 'var': 'var(c,n)/mean(c,n)^2',
        'zscore': '(c-mean(c,n))/std(c,n)',
        'skew': 'mean((return-mean(return,n))^3,n)/std(return,n)^3',
        'kurtosis': 'mean((return-mean(return,n))^4,n)/std(return,n)^4-3',
        'autocorr': 'corr(return,return[-1],n)',
        'efficiency': 'abs(c-c[-n])/sum(abs(change(c)),n)',
        'r_squared': 'corr(c,time,n)^2', 't_score': 'mean(return,n)/std(return,n)*sqrt(n)',
        'maxindex': 'argmax(c,n)/(n-1)', 'minindex': '-argmin(c,n)/(n-1)',
        'sum': 'sum(return,n)'})
    add('price_transform', WINDOWS, {
        'avgprice': '((o+h+l+c)/4)/mean(c,n)-1', 'medprice': '((h+l)/2)/mean(c,n)-1',
        'typprice': '((h+l+c)/3)/mean(c,n)-1', 'wclprice': '((h+l+2c)/4)/mean(c,n)-1',
        'ln': 'log(c/mean(c,n))', 'sqrt': 'sqrt(c/mean(c,n))-1',
        'exp': 'expm1(clip(c/mean(c,n)-1,-5,5))',
        'sin': 'sin(clip(c/mean(c,n)-1,-pi/2,pi/2))',
        'cos': '-cos(clip(c/mean(c,n)-1,-pi/2,pi/2))',
        'atan': 'atan(c/mean(c,n)-1)', 'add': 'mean((h+l)/c-2,n)',
        'sub': 'mean((h-l)/c,n)', 'mult': 'mean(o*c/c[-1]^2-1,n)',
        'div': 'mean(c/o-1,n)', 'max': 'c/max(c,n)-1', 'min': 'c/min(c,n)-1'})
    add('hilbert', (4, 8, 16), {x: 'causal Ehlers quadrature FIR (.0962,.5769,-.5769,-.0962), lag 0/2/4/6; '+s
        for x, s in dict(dcperiod='smoothed period 6..50', dcphase='atan2(Q,I)',
        inphase='I/c', quadrature='Q/c', sine='sin(phase)', leadsine='sin(phase+pi/4)',
        trendmode='1(abs(c-trendline)>ATR14)', trendline='c/adaptive_period_mean-1').items()})
    add('candles', (5, 10, 20), {x: PATTERN_FORMULAS[x] for x in PATTERNS})
    add('chips', (20, 50, 100), dict(profit='original profit_ratio, step=.02, turnover proxy v/(20*mean(v,n)) clipped 0..1',
        cost='c/original cost_line(average_price,turnover_proxy)-1',
        concentration='-(volume_weighted_price_std(n)/volume_weighted_mean(n))',
        cost_near='-abs(c/cost-1)/ADR20', overhang='-sum(v where typical>c,n)/sum(v,n)',
        support='sum(v where .95c<=typical<=c,n)/sum(v,n)'))
    add('chan', (13, 26, 52), dict(buy2='daily causal chan_stock lookback=n,min_gap=4 buy2',
        buy3='daily causal chan_stock buy3', support='c/last_confirmed_support-1',
        weekly_buy2='completed-week chan_stock lookback=n buy2',
        weekly_buy3='completed-week chan_stock buy3', weekly_support='c/confirmed_weekly_support-1'))
    add('smc', (2, 3, 5), dict(bias='last confirmed structural break direction',
        bos='signed break count in 20 days', choch='signed change-of-character count in 20 days',
        sweep='low_sweep-high_sweep counts in 20 days',
        range_position='(c-confirmed_low)/(confirmed_high-confirmed_low)',
        support_near='-abs(c/confirmed_low-1)/ADR20', resistance='c/confirmed_high-1',
        fvg_balance='unfilled bullish minus bearish three-bar gaps, max age60',
        fvg_near='negative distance to nearest live bullish gap / ATR20',
        order_block='c/last bearish-candle-low preceding confirmed up-break-1'))
    add('price_cycle', (5, 10, 20), {x: 'daily_technical.cycle rules generalized with fast=n,slow=2n,prior range=n; '+x
        for x in ('advancing', 'declining', 'extended', 'base_break', 'wedge_pop',
                  'wedge_drop', 'crossback', 'reversal', 'extension')})
    add('avwap', WINDOWS, dict(high='c/VWAP since trailing-n highest high-1',
        low='c/VWAP since trailing-n lowest low-1', volume='c/VWAP since trailing-n max volume-1',
        gap='c/VWAP since trailing-n largest positive gap-1',
        earnings='c/VWAP since last occurred earnings within n sessions-1',
        breakout='c/VWAP since most recent n-high breakout within n sessions-1'))
    add('ichimoku', (0, 1, 2), dict(tenkan='c/midHL(a)-1', kijun='c/midHL(b)-1',
        cloud='c/max(spanA[-b],spanB[-b])-1', thickness='(spanA[-b]-spanB[-b])/c',
        cross='(tenkan-kijun)/c', lagging='c/c[-b]-1', future_cloud='(spanA-spanB)/c; known now, not shifted backwards'))
    add('supertrend', (7, 10, 14), dict(direction='Supertrend ATRn multiplier3 trend sign',
        distance='(c-Supertrend)/ATRn', flip='-age(bullish Supertrend flip,60)'))
    add('channels', WINDOWS, dict(donchian='(c-min(l,n))/(max(h,n)-min(l,n))',
        width='-(max(h,n)/min(l,n)-1)', breakout='c/max(h[-1],n)-1',
        keltner='(c-EMA(c,n))/(2*ATRn)', keltner_width='-4*ATRn/EMA(c,n)',
        squeeze='1(2*std(c,n)<1.5*ATRn)', range_position='(c-min(c,n))/(max(c,n)-min(c,n))',
        high_age='-age(h>=max(h[-1],n),120)'))
    add('vortex', WINDOWS, dict(positive='sum(abs(h-l[-1]),n)/sum(TR,n)',
        negative='-sum(abs(l-h[-1]),n)/sum(TR,n)', spread='positive+negative'))
    add('kst', (1, 2, 3), dict(value='sum(i*SMA(ROC(c,scale*[10,15,20,30][i]),scale*[10,10,10,15][i]))',
        signal='SMA(KST,9*scale)', hist='KST-signal'))
    add('elder', WINDOWS, dict(bull='(h-EMA(c,n))/ATRn', bear='(l-EMA(c,n))/ATRn',
        impulse='sign(EMA-EMA[-1])+sign(MACDhist-MACDhist[-1])',
        ray='(c-EMA(c,n))/ATRn'))
    add('force', WINDOWS, dict(value='EMA((c-c[-1])*v,n)/mean(v*c,n)',
        change='force-force[-5]'))
    add('eom', WINDOWS, dict(value='mean(((h+l)/2-(h[-1]+l[-1])/2)*(h-l)/v,n)*mean(v,n)/c^2',
        change='EOM-EOM[-5]'))
    add('darvas', (10, 20, 50), dict(position='(c-confirmed_box_low)/(confirmed_box_high-confirmed_box_low)',
        breakout='1(c>last confirmed box high)', width='-box_high/box_low+1',
        age='-age(breakout,120); box extremum confirmed by 3 following bars'))
    add('vcp', (10, 20, 50), dict(range='-range(n)/range(2n)', volume='-mean(v,n)/mean(v,2n)',
        higher_low='min(l,n)/min(l,2n)-1', score='count(contracting ranges,falling volume,higher low,close>EMA50)'))
    add('minervini', (50, 100, 200), dict(score='sum(trend template conditions)',
        above50='1(c>SMA50)', above150='1(c>SMA150)', above200='1(c>SMA200)',
        stack='1(SMA50>SMA150>SMA200)', slope='SMA200/SMA200[-20]-1',
        offlow='c/min(l,252)-1', nearhigh='c/max(h,252)-1',
        quality='score*efficiency(c,n)'))
    add('weinstein', (10, 30, 40), dict(stage2='1(completed_week_c>SMA(week_c,n) and SMA rising)',
        stage4='-1(week_c<SMA and SMA falling)', slope='weekly_SMA/weekly_SMA[-4]-1',
        distance='c/completed_week_SMA-1'))
    add('ibd_rs', (63, 126, 252), dict(weighted='(.4*g63+.2*g126+.2*g189+.2*g252)-QQQ counterpart',
        recent='g(n)-QQQ_g(n)', high='relative_price/max(relative_price,n)-1',
        improving='(g(n)-QQQ_g(n))-(g(n)-QQQ_g(n))[-5]'))
    add('complexity', (20, 50, 100, 200), dict(hurst='log((max(cumsum(centered returns))-min(...))/std(returns))/log(n)',
        fractal='-1-log(path_length/price_range)/log(n)', efficiency='abs(c-c[-n])/sum(abs(change),n)',
        entropy='-binary_entropy(fraction_positive_returns(n))',
        permutation='-entropy of 6 ordinal triples over trailing n / log(6)',
        runs='-number of return sign changes/n', roughness='-sum(abs(second_difference(c)),n)/sum(abs(change(c)),n)'))
    add('events', WINDOWS, dict(earn_age='-min(n,calendar days since occurred earnings)',
        earn_gap='last occurred earnings first-next-session gap; only when session has occurred',
        earn_drift='c/close_at_first_observable_post_earnings_session-1, age<=n',
        gap_count='sum(o/c[-1]-1>=2*ADR20[-1],n)', gap_size='max(positive_gap/ADR20[-1],n)',
        potent_count='sum(corrected_potent,n)', potent_age='-age(corrected_potent,n)',
        high_count='sum(h>=max(h[-1],20),n)'))
    add('options', WINDOWS, dict(iv='mean(historical_iv,n)', hv='mean(historical_hv,n)',
        iv_hv='mean(iv/hv,n)', iv_spread='mean(iv-hv,n)',
        iv_rank='(iv-min(iv,n))/(max(iv,n)-min(iv,n))',
        iv_change='iv/iv[-n]-1', volume='mean(option_volume,n)',
        relative_volume='option_volume/mean(option_volume,n)',
        call_share='mean(call_volume/option_volume,n)',
        pcr='-mean(put_volume/call_volume,n)',
        oi_pcr='-mean(put_open_interest/call_open_interest,n)',
        oi_change='option_open_interest/option_open_interest[-n]-1',
        turnover='mean(option_volume/option_open_interest,n)',
        volume_change='option_volume/option_volume[-n]-1',
        iv_percentile='own trailing-n IV percentile',
        divergence='(iv/iv[-n]-1)-(c/c[-n]-1)'))
    add('group', WINDOWS, dict(peer_return='mean(g(n) among fixed <=300 original peers)',
        peer_excess='g(n)-peer_return', peer_positive='fraction of peers with g(n)>0',
        peer_volume='mean(v/mean(v,n) among peers)',
        peer_potent='mean(sum(corrected_potent,n)/n among peers)',
        peer_dispersion='-std(g(n) among peers)',
        peer_rank='fraction peer g(n)<=own g(n)', breadth='fraction active300 with g(n)>0'))
    assert len(original) == 53 and len(PATTERNS) == 61
    assert len({s.name for s in out}) == len(out)
    return tuple(out)


def lag(x, n=1):
    out = np.full_like(x, np.nan, dtype=float)
    if n < len(x):
        out[n:] = x[:-n]
    return out


def roll(x, n, kind='mean'):
    x = np.asarray(x, float)
    out = np.full_like(x, np.nan)
    if len(x) < n:
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    valid = np.isfinite(w).all(-1)
    if kind == 'mean':
        value = np.mean(w, -1)
    elif kind == 'sum':
        value = np.sum(w, -1)
    elif kind == 'min':
        value = np.min(w, -1)
    elif kind == 'max':
        value = np.max(w, -1)
    elif kind == 'std':
        value = np.std(w, -1)
    elif kind == 'argmax':
        value = np.argmax(w, -1)
    elif kind == 'argmin':
        value = np.argmin(w, -1)
    else:
        raise ValueError(kind)
    out[n-1:] = np.where(valid, value, np.nan)
    return out


def smooth(x, n, wilder=False):
    x = np.asarray(x, float)
    out = np.full_like(x, np.nan)
    current = np.nan
    alpha = 1/n if wilder else 2/(n+1)
    for i, value in enumerate(x):
        if math.isfinite(value):
            current = current + alpha*(value-current) if math.isfinite(current) else value
        out[i] = current
    return out


def divide(a, b):
    with np.errstate(all='ignore'):
        out = np.asarray(a)/np.asarray(b)
    return np.where(np.isfinite(out) & (np.asarray(b) != 0), out, np.nan)


def corr(a, b, n):
    return divide(roll(a*b,n)-roll(a,n)*roll(b,n), roll(a,n,'std')*roll(b,n,'std'))


def age(flag, limit):
    out = np.full(len(flag), float(limit))
    last = -limit
    for i, value in enumerate(flag):
        if value:
            last = i
        out[i] = min(limit, i-last)
    return out


def history_rank(x, rows, window=250):
    """Only requested rows; never allocate a stock x factor x history tensor."""
    out = np.full((len(rows), x.shape[1]), np.nan, np.float32)
    for k, i in enumerate(rows):
        w = x[max(0,i-window+1):i+1]
        valid = np.isfinite(w)
        count = valid.sum(0)
        less = ((w<x[i]) & valid).sum(0)
        equal = ((w==x[i]) & valid).sum(0)
        out[k] = np.where(np.isfinite(x[i]) & (count>=2), (less+(equal-1)/2)/np.maximum(count-1,1), np.nan)
    return out


class Stock:
    """At most one stock's history and a small indicator block are resident."""
    def __init__(self, arrays, days, qqq, extras=None):
        self.a, self.days, self.q, self.extras = arrays, days, qqq, extras or {}
        self.o,self.h,self.l,self.c,self.v,self.t = (np.asarray(arrays[k],float) for k in ('o','h','l','c','v','t'))
        # A fixed index base makes even the chip log-grid independent of a
        # later corporate action's common rescaling of an earlier prefix.
        valid=np.flatnonzero(np.isfinite(self.c)&(self.c>0))
        scale=100/self.c[valid[0]] if len(valid) else 1.
        self.o,self.h,self.l,self.c=(x*scale for x in (self.o,self.h,self.l,self.c))
        self.v=self.v/scale
        self.pc=lag(self.c)
        self.change=self.c-self.pc
        self.r=divide(self.c,self.pc)-1
        self.lr=np.log1p(self.r)
        self.tr=np.maximum(self.h-self.l,np.maximum(abs(self.h-self.pc),abs(self.l-self.pc)))
        first=np.flatnonzero(np.isfinite(self.c))
        if len(first):
            self.tr[first[0]]=self.h[first[0]]-self.l[first[0]]
        self.tp=(self.h+self.l+self.c)/3
        self.adr=roll(divide(self.h,self.l)-1,20)

    @lru_cache(maxsize=24)
    def ema(self,n):
        return smooth(self.c,n)

    def evaluate(self,family,n):
        with np.errstate(all='ignore'):
            result=getattr(self,'f_'+family)(n)
        return {k:np.where(np.isfinite(v),v,np.nan) for k,v in result.items()}

    def f_original53(self,n):
        c,h,l,v=self.c,self.h,self.l,self.v
        out={}
        for k in (1,3,5,10,21,63,126):
            out[f'g{k}']=divide(c,lag(c,k))-1
            out[f'rs{k}']=out[f'g{k}']-(divide(self.q,lag(self.q,k))-1)
        for k in (20,60,120): out[f'low{k}']=divide(c,roll(c,k,'min'))-1
        for k in (20,60,252): out[f'high{k}']=divide(c,roll(h,k,'max'))-1
        for k in (20,60): out[f'fresh_high{k}']=-age(h>=roll(lag(h),k,'max'),120)
        out.update(money20=roll(self.t,20),rvol1=divide(v,roll(v,20)),
            rvol3=divide(roll(v,3),roll(v,20)),rvol5=divide(roll(v,5),roll(v,20)),
            adr20=self.adr,contract5=-divide(roll(divide(h,l)-1,5),self.adr),
            range10=-divide(divide(roll(h,10,'max'),roll(l,10,'min'))-1,self.adr),
            close_position=divide(c-l,h-l))
        for k in (9,21,50):
            e=self.ema(k)
            out[f'ema{k}']=divide(c,e)-1
            out[f'near_ema{k}']=-divide(abs(out[f'ema{k}']),self.adr)
            out[f'cross{k}']=-age((c>e)&(self.pc<=lag(e)),120)
        gap=divide(self.o,self.pc)-1
        pot=self.extras.get('pot',np.zeros(len(c)))
        out.update(ema_stack=(self.ema(9)>self.ema(21)).astype(float)+(self.ema(21)>self.ema(50)),
            gap20=roll(divide(np.maximum(gap,0),lag(self.adr)),20,'max'),
            fresh_gap=-age(gap>=2*lag(self.adr),60),pot_count20=roll(pot,20,'sum'),
            fresh_pot=-age(pot>0,60),earn_age=-np.minimum(120,self.extras['earn_days']))
        for k in ('peer_g5','peer_rank','h4_activity','h4_momentum','h4_history','h4_stack','h4_peers','h4_coil'):
            out[k]=self.extras.get(k,np.full(len(c),np.nan))
        return out

    def f_overlap(self,n):
        c=self.c; e1=self.ema(n);e2=smooth(e1,n);e3=smooth(e2,n)
        w=np.arange(1,n+1); wma=np.full(len(c),np.nan)
        if len(c)>=n: wma[n-1:]=np.lib.stride_tricks.sliding_window_view(c,n)@w/w.sum()
        efficiency=divide(abs(c-lag(c,n)),roll(abs(self.change),n,'sum'))
        sc=(np.nan_to_num(efficiency)*(2/3-2/31)+2/31)**2
        kama=self.adaptive(c,sc)
        e4=smooth(e3,n);e5=smooth(e4,n);e6=smooth(e5,n);a=.7
        t3=-a**3*e6+(3*a*a+3*a**3)*e5+(-6*a*a-3*a-3*a**3)*e4+(1+3*a+a**3+3*a*a)*e3
        phase=self.f_hilbert(4)['dcphase']
        delta=np.maximum(1,np.abs(np.diff(phase,prepend=np.nan))*180/np.pi)
        alpha=np.clip(divide(2/(n+1),delta),2/(n+1)/10,2/(n+1))
        mama=self.adaptive(c,np.nan_to_num(alpha,nan=2/(n+1)))
        fama=self.adaptive(mama,np.nan_to_num(alpha/2,nan=1/(n+1)))
        values=dict(sma=roll(c,n),ema=e1,wma=wma,dema=2*e1-e2,tema=3*e1-3*e2+e3,
            trima=roll(roll(c,math.ceil(n/2)),n//2+1),kama=kama,t3=t3,mama=mama,fama=fama,
            midpoint=(roll(c,n,'max')+roll(c,n,'min'))/2,
            midprice=(roll(self.h,n,'max')+roll(self.l,n,'min'))/2)
        out={k:divide(c,v)-1 for k,v in values.items()}
        out.update(bb_position=divide(c-roll(c,n),2*roll(c,n,'std')),
            bb_width=-divide(4*roll(c,n,'std'),roll(c,n)),
            sar=divide(c-self.psar(2/(n+1)*.1,.2),c),
            sarext=divide(c-self.psar(2/(n+1)*.2,.4),c))
        return out

    @staticmethod
    def adaptive(x,alpha):
        out=np.full(len(x),np.nan);last=np.nan
        for i,v in enumerate(x):
            if math.isfinite(v): last=v if not math.isfinite(last) else last+alpha[i]*(v-last)
            out[i]=last
        return out

    def psar(self,step,cap):
        out=np.full(len(self.c),np.nan);bull=True;ep=sar=np.nan;af=step
        for i in range(len(out)):
            h,l=self.h[i],self.l[i]
            if not math.isfinite(h+l): continue
            if not math.isfinite(sar): sar=l;ep=h
            else:
                sar+=af*(ep-sar)
                previous=self.l if bull else self.h
                for k in (i-1,i-2):
                    if k>=0 and math.isfinite(previous[k]):
                        sar=min(sar,previous[k]) if bull else max(sar,previous[k])
                if (bull and l<sar) or (not bull and h>sar): bull=not bull;sar=ep;ep=h if bull else l;af=step
                elif (bull and h>ep) or (not bull and l<ep): ep=h if bull else l;af=min(cap,af+step)
            out[i]=sar
        return out

    def f_momentum(self,n):
        c=self.c;up=np.maximum(self.change,0);dn=np.maximum(-self.change,0)
        atr=smooth(self.tr,n,True);pu=smooth(up,n,True);pd=smooth(dn,n,True)
        dh=self.h-lag(self.h);dl=lag(self.l)-self.l
        plus=divide(smooth(np.where((dh>dl)&(dh>0),dh,0.),n,True),atr)
        minus=divide(smooth(np.where((dl>dh)&(dl>0),dl,0.),n,True),atr)
        dx=divide(abs(plus-minus),plus+minus);adx=smooth(dx,n,True)
        hi=roll(self.h,n,'max');lo=roll(self.l,n,'min');k=divide(c-lo,hi-lo)
        tpmean=roll(self.tp,n);mad=np.full(len(c),np.nan)
        if len(c)>=n:
            w=np.lib.stride_tricks.sliding_window_view(self.tp,n)
            mad[n-1:]=np.mean(abs(w-tpmean[n-1:,None]),axis=1)
        rsi=divide(pu,pu+pd);macd=divide(self.ema(n)-self.ema(2*n),atr)
        signal=smooth(macd,max(2,n//3));triple=smooth(smooth(self.ema(n),n),n)
        flow=self.tp*self.v;pos=roll(np.where(self.tp>lag(self.tp),flow,0),n,'sum')
        neg=roll(np.where(self.tp<lag(self.tp),flow,0),n,'sum')
        bp=c-np.minimum(self.l,self.pc)
        u=sum(weight*divide(roll(bp,n*m,'sum'),roll(self.tr,n*m,'sum')) for weight,m in ((4,1),(2,2),(1,4)))/7
        au=roll(self.h,n,'argmax')/(n-1);ad=-roll(self.l,n,'argmin')/(n-1)
        roc=divide(c,lag(c,n))-1
        return dict(roc=roc,rocp=roc,rocr=roc+1,rocr100=(roc+1)*100,
            mom=divide(c-lag(c,n),atr),rsi=rsi,cmo=divide(roll(up,n,'sum')-roll(dn,n,'sum'),roll(up+dn,n,'sum')),
            cci=divide(self.tp-tpmean,.015*mad),dx=dx,adx=adx,adxr=(adx+lag(adx,n))/2,
            plus_di=plus,minus_di=-minus,plus_dm=plus,minus_dm=-minus,
            aroon_up=au,aroon_down=ad,aroonosc=au+ad,willr=k-1,stoch_k=k,stoch_d=roll(k,3),
            stochrsi=divide(rsi-roll(rsi,n,'min'),roll(rsi,n,'max')-roll(rsi,n,'min')),
            trix=divide(triple,lag(triple))-1,bop=roll(divide(c-self.o,self.h-self.l),n),
            apo=divide(self.ema(n)-self.ema(2*n),c),ppo=divide(self.ema(n),self.ema(2*n))-1,
            macd=macd,macd_signal=signal,macd_hist=macd-signal,mfi=divide(pos,pos+neg),ultosc=u)

    def f_volume(self,n):
        c,v=self.c,self.v;money=divide((2*c-self.h-self.l),self.h-self.l)*v
        ad=divide(roll(money,n,'sum'),roll(v,n,'sum'))
        cumulative=np.cumsum(np.nan_to_num(money))
        mean=roll(v,n);slope=self.regression(v,n)[0]
        return dict(ad=ad,adosc=divide(smooth(cumulative,n)-smooth(cumulative,3*n),mean),
            obv=divide(roll(np.sign(self.change)*v,n,'sum'),roll(v,n,'sum')),cmf=ad,
            vwap=divide(c,divide(roll(self.tp*v,n,'sum'),roll(v,n,'sum')))-1,
            pvt=divide(roll(self.r*v,n,'sum'),roll(v,n,'sum')),
            nvi=roll(np.where(v<lag(v),self.lr,0),n,'sum'),pvi=roll(np.where(v>lag(v),self.lr,0),n,'sum'),
            rvol=divide(v,mean),dollar_volume=roll(self.t,n),volume_trend=divide(slope,mean),
            up_down=divide(roll(np.where(self.change>0,v,0),n,'sum'),roll(np.where(self.change<0,v,0),n,'sum')),
            price_volume_corr=corr(self.lr,np.log(divide(v,lag(v))),n),
            volume_z=divide(v-mean,roll(v,n,'std')),amihud=-roll(divide(abs(self.r),self.t),n))

    def f_volatility(self,n):
        c=self.c;r=self.lr;hl=np.log(divide(self.h,self.l));co=np.log(divide(c,self.o))
        rv=roll(r,n,'std');trsum=roll(self.tr,n,'sum')
        return dict(atr=divide(smooth(self.tr,n,True),c),natr=100*divide(smooth(self.tr,n,True),c),
            trange=divide(roll(self.tr,n),c),adr=roll(divide(self.h,self.l)-1,n),hv=rv*np.sqrt(252),
            parkinson=np.sqrt(roll(hl**2,n)/(4*np.log(2))),
            garman_klass=np.sqrt(np.maximum(0,roll(.5*hl**2-(2*np.log(2)-1)*co**2,n))),
            rogers_satchell=np.sqrt(np.maximum(0,roll(np.log(divide(self.h,self.o))*np.log(divide(self.h,c))+
                np.log(divide(self.l,self.o))*np.log(divide(self.l,c)),n))),
            downside=-np.sqrt(roll(np.minimum(r,0)**2,n)),upside=np.sqrt(roll(np.maximum(r,0)**2,n)),
            compression=-divide(rv,roll(r,2*n,'std')),
            range_compression=-divide(roll(divide(self.h,self.l)-1,n),roll(divide(self.h,self.l)-1,2*n)),
            ulcer=-np.sqrt(roll((divide(c,roll(c,n,'max'))-1)**2,n)),
            choppiness=-np.log10(divide(trsum,roll(self.h,n,'max')-roll(self.l,n,'min')))/np.log10(n))

    @staticmethod
    def regression(x,n):
        slope=np.full(len(x),np.nan);intercept=slope.copy()
        if len(x)>=n:
            t=np.arange(n)-(n-1)/2
            w=np.lib.stride_tricks.sliding_window_view(x,n)
            slope[n-1:]=w@t/(t@t)
            intercept[n-1:]=w.mean(1)-slope[n-1:]*(n-1)/2
        return slope,intercept

    def f_statistics(self,n):
        c=self.c;r=self.r;q=np.log(divide(self.q,lag(self.q)));x=self.lr
        beta=divide(roll(x*q,n)-roll(x,n)*roll(q,n),roll(q,n,'std')**2)
        slope,intercept=self.regression(c,n);mean=roll(c,n);std=roll(c,n,'std')
        z=self.window_moments(x,n)
        return dict(beta=beta,correl=corr(x,q,n),alpha=roll(x,n)-beta*roll(q,n),
            linearreg=divide(intercept+slope*(n-1)-c,c),linearreg_slope=divide(slope,mean),
            linearreg_angle=np.arctan(divide(n*slope,mean)),linearreg_intercept=divide(intercept,c)-1,
            tsf=divide(intercept+slope*n,c)-1,stddev=divide(std,mean),var=divide(std**2,mean**2),
            zscore=divide(c-mean,std),skew=z[0],kurtosis=z[1],autocorr=corr(x,lag(x),n),
            efficiency=divide(abs(c-lag(c,n)),roll(abs(self.change),n,'sum')),
            r_squared=divide(slope**2*(n*n-1)/12,std**2),t_score=divide(roll(x,n),roll(x,n,'std'))*np.sqrt(n),
            maxindex=roll(c,n,'argmax')/(n-1),minindex=-roll(c,n,'argmin')/(n-1),sum=roll(x,n,'sum'))

    @staticmethod
    def window_moments(x,n):
        skew=np.full(len(x),np.nan);kurt=skew.copy()
        if len(x)>=n:
            w=np.lib.stride_tricks.sliding_window_view(x,n)
            z=divide(w-w.mean(1,keepdims=True),w.std(1,keepdims=True))
            skew[n-1:]=np.mean(z**3,1);kurt[n-1:]=np.mean(z**4,1)-3
        return skew,kurt

    def f_price_transform(self,n):
        c=self.c;mean=roll(c,n);z=divide(c,mean)-1
        return dict(avgprice=divide((self.o+self.h+self.l+c)/4,mean)-1,
            medprice=divide((self.h+self.l)/2,mean)-1,typprice=divide(self.tp,mean)-1,
            wclprice=divide((self.h+self.l+2*c)/4,mean)-1,ln=np.log1p(z),sqrt=np.sqrt(z+1)-1,
            exp=np.expm1(np.clip(z,-5,5)),sin=np.sin(np.clip(z,-np.pi/2,np.pi/2)),
            cos=-np.cos(np.clip(z,-np.pi/2,np.pi/2)),atan=np.arctan(z),
            add=roll(divide(self.h+self.l,c)-2,n),sub=roll(divide(self.h-self.l,c),n),
            mult=roll(divide(self.o*c,self.pc**2)-1,n),div=roll(divide(c,self.o)-1,n),
            max=divide(c,roll(c,n,'max'))-1,min=divide(c,roll(c,n,'min'))-1)

    @lru_cache(maxsize=3)
    def f_hilbert(self,n):
        c=self.c;s=roll(c,n);length=len(c)
        det=np.zeros(length);i1=det.copy();q1=det.copy();re=det.copy();im=det.copy()
        period=np.full(length,20.);phase=np.full(length,np.nan)
        i2=q2=0.
        for t in range(6,length):
            if not np.isfinite(s[t-6:t+1]).all(): continue
            adj=.075*period[t-1]+.54
            det[t]=(.0962*s[t]+.5769*s[t-2]-.5769*s[t-4]-.0962*s[t-6])*adj
            q1[t]=(.0962*det[t]+.5769*det[t-2]-.5769*det[t-4]-.0962*det[t-6])*adj
            i1[t]=det[t-3]
            ji=(.0962*i1[t]+.5769*i1[t-2]-.5769*i1[t-4]-.0962*i1[t-6])*adj
            jq=(.0962*q1[t]+.5769*q1[t-2]-.5769*q1[t-4]-.0962*q1[t-6])*adj
            ni=.2*(i1[t]-jq)+.8*i2;nq=.2*(q1[t]+ji)+.8*q2
            re[t]=.2*(ni*i2+nq*q2)+.8*re[t-1];im[t]=.2*(ni*q2-nq*i2)+.8*im[t-1]
            angle=np.arctan2(im[t],re[t])
            p=2*np.pi/abs(angle) if abs(angle)>1e-8 else period[t-1]
            p=min(max(p,.67*period[t-1]),1.5*period[t-1]);p=min(max(p,6),50)
            period[t]=.2*p+.8*period[t-1];phase[t]=np.arctan2(q1[t],i1[t]);i2,q2=ni,nq
        trend=np.full(length,np.nan)
        for t in range(length):
            k=int(round(period[t]));w=c[max(0,t-k+1):t+1]
            if len(w)==k and np.isfinite(w).all(): trend[t]=w.mean()
        valid=np.isfinite(phase)
        return dict(dcperiod=np.where(valid,period,np.nan),dcphase=phase,inphase=np.where(valid,divide(i1,c),np.nan),
            quadrature=np.where(valid,divide(q1,c),np.nan),sine=np.sin(phase),leadsine=np.sin(phase+np.pi/4),
            trendmode=np.where(valid,(abs(c-trend)>smooth(self.tr,14,True)).astype(float),np.nan),
            trendline=divide(c,trend)-1)

    def f_candles(self,n):
        o,h,l,c=self.o,self.h,self.l,self.c
        body=abs(c-o);span=h-l;upper=h-np.maximum(o,c);lower=np.minimum(o,c)-l
        avg=roll(lag(body),n);rng=roll(lag(span),n)
        white=c>o;black=c<o;long=body>avg;short=body<avg
        doji=body<=.1*rng;maru=(upper<=.1*rng)&(lower<=.1*rng)&long
        hammer=(lower>=2*body)&(upper<=.1*rng)&short
        inverted=(upper>=2*body)&(lower<=.1*rng)&short
        trend=c>lag(c,n)
        def P(x,k=1): return lag(np.asarray(x,float),k)
        def B(x): return np.asarray(x,bool).astype(float)
        def within(a,b): return abs(a-b)<=.05*rng
        env=dict(o=o,h=h,l=l,c=c,body=body,span=span,upper=upper,lower=lower,avg=avg,rng=rng,
            white=white,black=black,long=long,short=short,doji=doji,maru=maru,hammer=hammer,
            inverted=inverted,trend=trend,P=P,B=B,within=within,np=np,abs=np.abs)
        out={}
        for name,expr in PATTERN_FORMULAS.items():
            value=np.asarray(eval(expr,{'__builtins__':{}},env),float)
            valid=np.isfinite(avg)&np.isfinite(c)&np.isfinite(P(c,4))
            out[name]=np.where(valid,value,np.nan)
        return out

    def f_chips(self,n):
        from studies.trend_breakout.chips import cost_line,profit_ratio
        v,c=self.v,self.c;turn=np.clip(divide(v,20*roll(v,n)),0,1)
        price=divide(self.t,v)
        price=np.where((price>=self.l*.98)&(price<=self.h*1.02),price,self.tp)
        cost=cost_line(c[:,None],price[:,None],turn[:,None])[:,0]
        profit=profit_ratio(self.h[:,None],self.l[:,None],c[:,None],turn[:,None],np.arange(len(c)),step=.02)[:,0]
        mean=divide(roll(v*self.tp,n,'sum'),roll(v,n,'sum'))
        std=np.sqrt(np.maximum(0,divide(roll(v*self.tp**2,n,'sum'),roll(v,n,'sum'))-mean**2))
        over=np.full(len(c),np.nan);support=over.copy()
        for t in range(n-1,len(c)):
            p=self.tp[t-n+1:t+1];vv=v[t-n+1:t+1]
            if np.isfinite(p+vv).all() and vv.sum()>0:
                over[t]=-vv[p>c[t]].sum()/vv.sum();support[t]=vv[(p>=.95*c[t])&(p<=c[t])].sum()/vv.sum()
        return dict(profit=profit,cost=divide(c,cost)-1,concentration=-divide(std,mean),
            cost_near=-divide(abs(divide(c,cost)-1),self.adr),overhang=over,support=support)

    def weekly(self):
        from studies.trend_breakout.chan import week_rows
        first,last=week_rows(self.days)
        completed=np.array([i for i,t in enumerate(last) if
            t+1<len(self.days) or __import__('datetime').date.fromisoformat(self.days[t]).weekday()==4],int)
        first,last=first[completed],last[completed]
        h=np.array([np.nanmax(self.h[a:b+1]) for a,b in zip(first,last)])
        l=np.array([np.nanmin(self.l[a:b+1]) for a,b in zip(first,last)])
        return last,h,l,self.c[last]

    def expand_week(self,last,x):
        idx=np.searchsorted(last,np.arange(len(self.c)),side='right')-1
        out=np.full(len(self.c),np.nan);valid=idx>=0
        out[valid]=x[idx[valid]]
        return out

    def f_chan(self,n):
        from studies.trend_breakout.chan import chan_stock
        b3,_,b2,_,_,support=chan_stock(self.h,self.l,lookback=n)
        last,h,l,c=self.weekly();w3,_,w2,_,_,ws=chan_stock(h,l,lookback=n)
        return dict(buy2=b2.astype(float),buy3=b3.astype(float),support=divide(self.c,support)-1,
            weekly_buy2=self.expand_week(last,w2.astype(float)),weekly_buy3=self.expand_week(last,w3.astype(float)),
            weekly_support=divide(self.c,self.expand_week(last,ws))-1)

    def f_smc(self,n):
        length=len(self.c);names=('bias','bos','choch','sweep','range_position','support_near','resistance','fvg_balance','fvg_near','order_block')
        out={k:np.full(length,np.nan) for k in names};bos=np.zeros(length);choch=bos.copy();sweep=bos.copy()
        hi=lo=ob=np.nan;bias=0;gaps=[];used=set();hip=lop=-1
        for t in range(length):
            c,h,l=self.c[t],self.h[t],self.l[t]
            if not np.isfinite(c+h+l): continue
            p=t-n
            if p>=n:
                hh=self.h[p-n:p+n+1];ll=self.l[p-n:p+n+1]
                if np.isfinite(hh).all() and self.h[p]>np.max(np.delete(hh,n)): hi=self.h[p];hip=p
                if np.isfinite(ll).all() and self.l[p]<np.min(np.delete(ll,n)): lo=self.l[p];lop=p
            if t:
                for level,direction,pivot in ((hi,1,hip),(lo,-1,lop)):
                    if not np.isfinite(level): continue
                    cross=self.c[t-1]<=level<c if direction==1 else self.c[t-1]>=level>c
                    if cross and (direction,pivot) not in used:
                        if bias and bias!=direction: choch[t]+=direction
                        else: bos[t]+=direction
                        bias=direction;used.add((direction,pivot))
                        if direction==1:
                            bear=np.flatnonzero(self.c[max(0,t-20):t]<self.o[max(0,t-20):t])
                            if len(bear): ob=self.l[max(0,t-20)+bear[-1]]
                    if (direction,pivot) not in used:
                        if direction==1 and h>level>c and self.c[t-1]<=level: sweep[t]-=1
                        if direction==-1 and l<level<c and self.c[t-1]>=level: sweep[t]+=1
            live=[]
            for start,direction,lower,upper in gaps:
                if t-start>60 or (direction==1 and l<=lower) or (direction==-1 and h>=upper): continue
                live.append((start,direction,lower,min(upper,l)) if direction==1 else (start,direction,max(lower,h),upper))
            if t>=2:
                if l>self.h[t-2]: live.append((t,1,self.h[t-2],l))
                elif h<self.l[t-2]: live.append((t,-1,h,self.l[t-2]))
            gaps=live
            out['bias'][t]=bias;out['range_position'][t]=divide(c-lo,hi-lo) if hi>lo else np.nan
            out['support_near'][t]=-divide(abs(divide(c,lo)-1),self.adr[t]);out['resistance'][t]=divide(c,hi)-1
            out['fvg_balance'][t]=sum(g[1] for g in gaps)
            bullish=[abs((g[2]+g[3])/2-c) for g in gaps if g[1]==1]
            if bullish: out['fvg_near'][t]=-divide(min(bullish),self.adr[t]*c)
            out['order_block'][t]=divide(c,ob)-1
        for k,v in (('bos',bos),('choch',choch),('sweep',sweep)): out[k]=roll(v,20,'sum')
        return out

    def f_price_cycle(self,n):
        c=self.c;e=self.ema(n);e2=self.ema(2*n);atr=smooth(self.tr,14,True)
        hi=roll(lag(self.h),n,'max');lo=roll(lag(self.l),n,'min');ext=divide(c-e,atr)
        up=(c>e)&(e>e2)&(e2>lag(e2,5));down=(c<e)&(e<e2)&(e2<lag(e2,5))
        hadup=roll(lag(((c>e)&(e>e2)).astype(float)),n,'max')>0
        weak=roll(lag((c<e2).astype(float)),n,'max')>0
        predicates=[('wedge_drop',(c<np.minimum(np.minimum(e,e2),lo))&hadup),('extended',ext>=2.5),
            ('wedge_pop',up&(c>hi)&weak),('base_break',up&(c>hi)&(hi-lo<=4*atr)),
            ('crossback',up&hadup&(self.l<=np.maximum(lag(e),lag(e2)))&(c>np.maximum(self.o,self.pc))),
            ('advancing',up),('declining',down),('reversal',weak&(c>np.maximum(self.o,self.pc))&(c>e))]
        taken=np.zeros(len(c),bool);out={}
        for k,flag in predicates:
            selected=flag&~taken;taken|=flag
            out[k]=np.where(np.isfinite(hi),selected.astype(float)*(-1 if k in ('declining','wedge_drop') else 1),np.nan)
        out['extension']=ext
        return out

    def f_avwap(self,n):
        c=self.c;out={k:np.full(len(c),np.nan) for k in ('high','low','volume','gap','earnings','breakout')}
        gap=divide(self.o,self.pc)-1;breakout=self.h>=roll(lag(self.h),n,'max')
        earn=self.extras['earn_index']
        for t in range(n-1,len(c)):
            start=t-n+1
            anchors={}
            for k,x,fn in (('high',self.h,np.argmax),('low',self.l,np.argmin),('volume',self.v,np.argmax),('gap',gap,np.argmax)):
                w=x[start:t+1]
                if np.isfinite(w).all(): anchors[k]=start+int(fn(w))
            if start<=earn[t]<=t: anchors['earnings']=int(earn[t])
            br=np.flatnonzero(breakout[start:t+1])
            if len(br): anchors['breakout']=start+int(br[-1])
            for k,a in anchors.items():
                w=self.v[a:t+1];p=self.tp[a:t+1]
                if np.isfinite(w+p).all(): out[k][t]=divide(c[t],divide(np.sum(w*p),np.sum(w)))-1
        return out

    def f_ichimoku(self,n):
        a,b,d=((9,26,52),(7,22,44),(10,30,60))[n]
        mid=lambda k:(roll(self.h,k,'max')+roll(self.l,k,'min'))/2
        ten,kij,spanb=mid(a),mid(b),mid(d);spana=(ten+kij)/2
        return dict(tenkan=divide(self.c,ten)-1,kijun=divide(self.c,kij)-1,
            cloud=divide(self.c,np.maximum(lag(spana,b),lag(spanb,b)))-1,
            thickness=divide(lag(spana,b)-lag(spanb,b),self.c),cross=divide(ten-kij,self.c),
            lagging=divide(self.c,lag(self.c,b))-1,future_cloud=divide(spana-spanb,self.c))

    def f_supertrend(self,n):
        atr=smooth(self.tr,n,True);mid=(self.h+self.l)/2
        upper=mid+3*atr;lower=mid-3*atr;line=np.full(len(mid),np.nan);direction=line.copy();bull=True
        for t in range(len(mid)):
            if not np.isfinite(upper[t]+lower[t]+self.c[t]): continue
            if t and np.isfinite(line[t-1]):
                if self.c[t-1]<=upper[t-1]: upper[t]=min(upper[t],upper[t-1])
                if self.c[t-1]>=lower[t-1]: lower[t]=max(lower[t],lower[t-1])
                if bull and self.c[t]<lower[t]: bull=False
                elif not bull and self.c[t]>upper[t]: bull=True
            direction[t]=1 if bull else -1;line[t]=lower[t] if bull else upper[t]
        return dict(direction=direction,distance=divide(self.c-line,atr),flip=-age((direction>0)&(lag(direction)<0),60))

    def f_channels(self,n):
        c=self.c;hi=roll(self.h,n,'max');lo=roll(self.l,n,'min');atr=smooth(self.tr,n,True)
        return dict(donchian=divide(c-lo,hi-lo),width=-(divide(hi,lo)-1),breakout=divide(c,roll(lag(self.h),n,'max'))-1,
            keltner=divide(c-self.ema(n),2*atr),keltner_width=-divide(4*atr,self.ema(n)),
            squeeze=np.where(np.isfinite(roll(c,n,'std')),(2*roll(c,n,'std')<1.5*atr).astype(float),np.nan),
            range_position=divide(c-roll(c,n,'min'),roll(c,n,'max')-roll(c,n,'min')),
            high_age=-age(self.h>=roll(lag(self.h),n,'max'),120))

    def f_vortex(self,n):
        pos=divide(roll(abs(self.h-lag(self.l)),n,'sum'),roll(self.tr,n,'sum'))
        neg=-divide(roll(abs(self.l-lag(self.h)),n,'sum'),roll(self.tr,n,'sum'))
        return dict(positive=pos,negative=neg,spread=pos+neg)

    def f_kst(self,n):
        val=sum((i+1)*roll(divide(self.c,lag(self.c,a*n))-1,b*n) for i,(a,b) in enumerate(zip((10,15,20,30),(10,10,10,15))))
        sig=roll(val,9*n)
        return dict(value=val,signal=sig,hist=val-sig)

    def f_elder(self,n):
        e=self.ema(n);atr=smooth(self.tr,n,True);mac=self.f_momentum(n)['macd_hist']
        return dict(bull=divide(self.h-e,atr),bear=divide(self.l-e,atr),
            impulse=np.sign(e-lag(e))+np.sign(mac-lag(mac)),ray=divide(self.c-e,atr))

    def f_force(self,n):
        x=divide(smooth(self.change*self.v,n),roll(self.v*self.c,n))
        return dict(value=x,change=x-lag(x,5))

    def f_eom(self,n):
        mid=(self.h+self.l)/2
        x=divide(roll(divide((mid-lag(mid))*(self.h-self.l),self.v),n)*roll(self.v,n),self.c**2)
        return dict(value=x,change=x-lag(x,5))

    def f_darvas(self,n):
        hi=np.full(len(self.c),np.nan);lo=hi.copy();ch=cl=np.nan
        for t in range(n+2,len(self.c)):
            p=t-3
            if np.isfinite(self.h[p-n+1:t+1]).all() and self.h[p]>=max(self.h[p-n+1:p+1]) and np.all(self.h[p+1:t+1]<self.h[p]):
                ch=self.h[p];cl=min(self.l[p-n+1:t+1])
            hi[t]=ch;lo[t]=cl
        flag=self.c>hi
        return dict(position=divide(self.c-lo,hi-lo),breakout=np.where(np.isfinite(hi),flag.astype(float),np.nan),
            width=1-divide(hi,lo),age=-age(flag,120))

    def f_vcp(self,n):
        rng=lambda k:divide(roll(self.h,k,'max'),roll(self.l,k,'min'))-1
        contraction=divide(rng(n),rng(2*n));volume=divide(roll(self.v,n),roll(self.v,2*n));hl=divide(roll(self.l,n,'min'),roll(self.l,2*n,'min'))-1
        score=(contraction<1).astype(float)+(volume<1)+(hl>0)+(self.c>self.ema(50))
        return dict(range=-contraction,volume=-volume,higher_low=hl,score=np.where(np.isfinite(contraction+volume+hl),score,np.nan))

    def f_minervini(self,n):
        c=self.c;ma50,ma150,ma200=(roll(c,k) for k in (50,150,200))
        off=divide(c,roll(self.l,252,'min'))-1;near=divide(c,roll(self.h,252,'max'))-1
        slope=divide(ma200,lag(ma200,20))-1
        stack=(ma50>ma150)&(ma150>ma200)
        score=(c>ma50).astype(float)+(c>ma150)+(c>ma200)+stack+(slope>0)+(off>=.3)+(near>=-.25)
        valid=np.isfinite(off+near+slope)
        return dict(score=np.where(valid,score,np.nan),above50=np.where(np.isfinite(ma50),(c>ma50).astype(float),np.nan),
            above150=np.where(np.isfinite(ma150),(c>ma150).astype(float),np.nan),above200=np.where(np.isfinite(ma200),(c>ma200).astype(float),np.nan),
            stack=np.where(np.isfinite(ma200),stack.astype(float),np.nan),slope=slope,offlow=off,nearhigh=near,
            quality=np.where(valid,score*divide(abs(c-lag(c,n)),roll(abs(self.change),n,'sum')),np.nan))

    def f_weinstein(self,n):
        last,h,l,c=self.weekly();ma=roll(c,n);sl=divide(ma,lag(ma,4))-1
        valid=np.isfinite(c+sl+ma)
        return dict(stage2=self.expand_week(last,np.where(valid,((c>ma)&(sl>0)).astype(float),np.nan)),
            stage4=self.expand_week(last,np.where(valid,-((c<ma)&(sl<0)).astype(float),np.nan)),
            slope=self.expand_week(last,sl),distance=divide(self.c,self.expand_week(last,ma))-1)

    def f_ibd_rs(self,n):
        rel=divide(self.c,self.q);g=lambda k:divide(self.c,lag(self.c,k))-divide(self.q,lag(self.q,k))
        recent=g(n)
        return dict(weighted=.4*g(63)+.2*g(126)+.2*g(189)+.2*g(252),recent=recent,
            high=divide(rel,roll(rel,n,'max'))-1,improving=recent-lag(recent,5))

    def f_complexity(self,n):
        c=self.c;x=self.lr;out={k:np.full(len(c),np.nan) for k in ('hurst','fractal','entropy','permutation','runs')}
        for t in range(n,len(c)):
            w=x[t-n+1:t+1];p=c[t-n+1:t+1]
            if not np.isfinite(w).all() or not np.isfinite(p).all(): continue
            cs=np.cumsum(w-w.mean());sd=w.std();span=np.ptp(p);path=np.sum(abs(np.diff(p)))
            if sd>0 and np.ptp(cs)>0: out['hurst'][t]=np.log(np.ptp(cs)/sd)/np.log(n)
            if span>0: out['fractal'][t]=-1-np.log(path/span)/np.log(n)
            prob=np.mean(w>0)
            out['entropy'][t]=sum(v*np.log(v) for v in (prob,1-prob) if v>0)
            triples=np.lib.stride_tricks.sliding_window_view(w,3)
            order=np.argsort(triples,axis=1,kind='stable');keys=order@np.array([1,3,9])
            _,counts=np.unique(keys,return_counts=True);freq=counts/counts.sum()
            out['permutation'][t]=np.sum(freq*np.log(freq))/np.log(6)
            out['runs'][t]=-np.sum(np.sign(w[1:])!=np.sign(w[:-1]))/n
        out['efficiency']=divide(abs(c-lag(c,n)),roll(abs(self.change),n,'sum'))
        out['roughness']=-divide(roll(abs(self.change-lag(self.change)),n,'sum'),roll(abs(self.change),n,'sum'))
        return out

    def f_events(self,n):
        earn=self.extras['earn_index'];days=self.extras['earn_days'];gap=divide(self.o,self.pc)-1
        eg=np.full(len(self.c),np.nan);drift=eg.copy()
        for t,a in enumerate(earn):
            if 0<=a<=t and t-a<=n:
                eg[t]=gap[a];drift[t]=divide(self.c[t],self.c[a])-1
        pot=self.extras.get('pot',np.zeros(len(self.c)))
        return dict(earn_age=-np.minimum(n,days),earn_gap=eg,earn_drift=drift,
            gap_count=roll((gap>=2*lag(self.adr)).astype(float),n,'sum'),
            gap_size=roll(divide(np.maximum(gap,0),lag(self.adr)),n,'max'),
            potent_count=roll(pot,n,'sum'),potent_age=-age(pot>0,n),
            high_count=roll((self.h>=roll(lag(self.h),20,'max')).astype(float),n,'sum'))

    def f_options(self,n):
        e=self.extras;nan=np.full(len(self.c),np.nan)
        iv,hv,ov,cv,pv,oi,co,po=(e.get(k,nan) for k in ('iv','hv','option_volume','call_volume','put_volume',
            'option_open_interest','call_open_interest','put_open_interest'))
        change=divide(iv,lag(iv,n))-1
        w=np.lib.stride_tricks.sliding_window_view(np.pad(iv,(n-1,0),constant_values=np.nan),n)
        count=np.isfinite(w).sum(1);equal=(w==iv[:,None]).sum(1)
        ivpct=np.where(np.isfinite(iv)&(count>=2),((w<iv[:,None]).sum(1)+(equal-1)/2)/np.maximum(count-1,1),np.nan)
        return dict(iv=roll(iv,n),hv=roll(hv,n),iv_hv=roll(divide(iv,hv),n),iv_spread=roll(iv-hv,n),
            iv_rank=divide(iv-roll(iv,n,'min'),roll(iv,n,'max')-roll(iv,n,'min')),
            iv_change=change,volume=roll(ov,n),relative_volume=divide(ov,roll(ov,n)),
            call_share=roll(divide(cv,ov),n),pcr=-roll(divide(pv,cv),n),oi_pcr=-roll(divide(po,co),n),
            oi_change=divide(oi,lag(oi,n))-1,turnover=roll(divide(ov,oi),n),
            volume_change=divide(ov,lag(ov,n))-1,iv_percentile=ivpct,
            divergence=change-(divide(self.c,lag(self.c,n))-1))

    def f_group(self,n):
        return {k:self.extras.get(f'group.{k}.{n}',np.full(len(self.c),np.nan)) for k in
            ('peer_return','peer_excess','peer_positive','peer_volume','peer_potent','peer_dispersion','peer_rank','breadth')}


# P(x,k) means k bars ago; B converts a predicate to 0/1. All adaptive
# thresholds use *prior* candles. These are disclosed OHLC proxies, not a
# claim of binary compatibility with TA-Lib's private candle settings.
PATTERN_FORMULAS = {
 '2crows': '-B((P(white,2)>0)&(P(black)>0)&black&(P(o)>P(c,2))&(o<P(o))&(c>P(c,2))&(c<P(c)))',
 '3blackcrows': '-B(black&(P(black)>0)&(P(black,2)>0)&(c<P(c))&(P(c)<P(c,2))&(o>P(c))&(o<P(o)))',
 '3inside': 'B((P(black,2)>0)&(P(white)>0)&white&(P(o)>P(c,2))&(P(c)<P(o,2))&(c>P(o,2)))-B((P(white,2)>0)&(P(black)>0)&black&(P(o)<P(c,2))&(P(c)>P(o,2))&(c<P(o,2)))',
 '3linestrike': 'B(white&(P(black)>0)&(P(black,2)>0)&(P(black,3)>0)&(P(c)<P(c,2))&(P(c,2)<P(c,3))&(o<P(c))&(c>P(o,3)))-B(black&(P(white)>0)&(P(white,2)>0)&(P(white,3)>0)&(P(c)>P(c,2))&(P(c,2)>P(c,3))&(o>P(c))&(c<P(o,3)))',
 '3outside': 'B((P(black,2)>0)&(P(white)>0)&white&(P(o)<P(c,2))&(P(c)>P(o,2))&(c>P(c)))-B((P(white,2)>0)&(P(black)>0)&black&(P(o)>P(c,2))&(P(c)<P(o,2))&(c<P(c)))',
 '3starsinsouth': 'B(black&(P(black)>0)&(P(black,2)>0)&(l>P(l))&(P(l)>P(l,2))&(h<P(h))&(P(body)<P(body,2))&(body<P(body)))',
 '3whitesoldiers': 'B(white&(P(white)>0)&(P(white,2)>0)&(c>P(c))&(P(c)>P(c,2))&(o<P(c))&(o>P(o)))',
 'abandonedbaby': 'B((P(black,2)>0)&(P(doji)>0)&white&(P(h)<P(l,2))&(l>P(h)))-B((P(white,2)>0)&(P(doji)>0)&black&(P(l)>P(h,2))&(h<P(l)))',
 'advanceblock': '-B(white&(P(white)>0)&(P(white,2)>0)&(c>P(c))&(P(c)>P(c,2))&(body<P(body))&(upper>P(upper)))',
 'belthold': 'B(white&long&(lower<=.1*rng)&~trend)-B(black&long&(upper<=.1*rng)&trend)',
 'breakaway': 'B((P(black,4)>0)&(P(o,3)<P(c,4))&(P(c)<P(c,3))&white&(c>P(o,3))&(c<P(c,4)))-B((P(white,4)>0)&(P(o,3)>P(c,4))&(P(c)>P(c,3))&black&(c<P(o,3))&(c>P(c,4)))',
 'closingmarubozu': 'B(white&long&(upper<=.1*rng))-B(black&long&(lower<=.1*rng))',
 'concealbabyswall': 'B((P(black,3)>0)&(P(black,2)>0)&(P(maru,3)>0)&(P(maru,2)>0)&(P(black)>0)&(P(upper)>.2*rng)&black&(h>P(h))&(l<P(l)))',
 'counterattack': 'B((P(black)>0)&white&long&(P(long)>0)&within(c,P(c)))-B((P(white)>0)&black&long&(P(long)>0)&within(c,P(c)))',
 'darkcloudcover': '-B((P(white)>0)&black&(o>P(h))&(c<(P(o)+P(c))/2)&(c>P(o)))',
 'doji': 'B(doji)', 'dojistar': 'B(doji&~trend&(h<P(l)))-B(doji&trend&(l>P(h)))',
 'dragonflydoji': 'B(doji&(upper<=.1*rng)&(lower>.6*span))',
 'engulfing': 'B(white&(P(black)>0)&(o<=P(c))&(c>=P(o)))-B(black&(P(white)>0)&(o>=P(c))&(c<=P(o)))',
 'eveningdojistar': '-B((P(white,2)>0)&(P(doji)>0)&black&(P(o)>P(c,2))&(c<(P(o,2)+P(c,2))/2))',
 'eveningstar': '-B((P(white,2)>0)&(P(short)>0)&black&(P(o)>P(c,2))&(c<(P(o,2)+P(c,2))/2))',
 'gapsidesidewhite': 'B(white&(P(white)>0)&within(o,P(o))&within(body,P(body))&(l>P(h,2)))-B(white&(P(white)>0)&within(o,P(o))&within(body,P(body))&(h<P(l,2)))',
 'gravestonedoji': '-B(doji&(lower<=.1*rng)&(upper>.6*span))',
 'hammer': 'B(hammer&~trend)', 'hangingman': '-B(hammer&trend)',
 'harami': 'B((P(black)>0)&white&(c<P(o))&(o>P(c)))-B((P(white)>0)&black&(o<P(c))&(c>P(o)))',
 'haramicross': 'B((P(black)>0)&doji&(h<P(o))&(l>P(c)))-B((P(white)>0)&doji&(h<P(c))&(l>P(o)))',
 'highwave': '(B(white)-B(black))*B(short&(upper>body)&(lower>body))',
 'hikkake': 'B((P(h)<P(h,2))&(P(l)>P(l,2))&(h>P(h))&(l>P(l)))-B((P(h)<P(h,2))&(P(l)>P(l,2))&(h<P(h))&(l<P(l)))',
 'hikkakemod': 'B((P(h,2)<P(h,3))&(P(l,2)>P(l,3))&(P(h)<P(h,2))&(c>P(h,2)))-B((P(h,2)<P(h,3))&(P(l,2)>P(l,3))&(P(l)>P(l,2))&(c<P(l,2)))',
 'homingpigeon': 'B(black&(P(black)>0)&(o<P(o))&(c>P(c))&short)',
 'identical3crows': '-B(black&(P(black)>0)&(P(black,2)>0)&within(o,P(c))&within(P(o),P(c,2))&(c<P(c))&(P(c)<P(c,2)))',
 'inneck': '-B((P(black)>0)&white&(o<P(l))&(c>P(c))&(c<P(c)+.1*rng))',
 'invertedhammer': 'B(inverted&~trend)',
 'kicking': 'B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l)))',
 'kickingbylength': '(B(white&maru&(P(black)>0)&(P(maru)>0)&(l>P(h)))-B(black&maru&(P(white)>0)&(P(maru)>0)&(h<P(l))))*np.where(body>P(body),1.,-1.)',
 'ladderbottom': 'B((P(black,4)>0)&(P(black,3)>0)&(P(black,2)>0)&(P(c,3)<P(c,4))&(P(c,2)<P(c,3))&(P(upper)>P(body))&white&(c>P(h)))',
 'longleggeddoji': 'B(doji&(upper>.3*span)&(lower>.3*span))',
 'longline': '(B(white)-B(black))*B(long&(span>rng))',
 'marubozu': '(B(white)-B(black))*B(maru)',
 'matchinglow': 'B(black&(P(black)>0)&within(c,P(c)))',
 'mathold': 'B((P(white,4)>0)&(P(long,4)>0)&(P(o,3)>P(c,4))&(P(l,2)>P(o,4))&(P(l)>P(o,4))&white&(c>P(h,4)))',
 'morningdojistar': 'B((P(black,2)>0)&(P(doji)>0)&white&(P(o)<P(c,2))&(c>(P(o,2)+P(c,2))/2))',
 'morningstar': 'B((P(black,2)>0)&(P(short)>0)&white&(P(o)<P(c,2))&(c>(P(o,2)+P(c,2))/2))',
 'onneck': '-B((P(black)>0)&white&(o<P(l))&within(c,P(l)))',
 'piercing': 'B((P(black)>0)&white&(o<P(l))&(c>(P(o)+P(c))/2)&(c<P(o)))',
 'rickshawman': 'B(doji&(upper>.3*span)&(lower>.3*span)&(abs(c-(h+l)/2)<.1*span))',
 'risefall3methods': 'B((P(white,4)>0)&(P(black,3)>0)&(P(black,2)>0)&(P(black)>0)&(P(h,2)<P(h,4))&(P(l)>P(l,4))&white&(c>P(c,4)))-B((P(black,4)>0)&(P(white,3)>0)&(P(white,2)>0)&(P(white)>0)&(P(l,2)>P(l,4))&(P(h)<P(h,4))&black&(c<P(c,4)))',
 'separatinglines': 'B(white&(P(black)>0)&within(o,P(o))&trend)-B(black&(P(white)>0)&within(o,P(o))&~trend)',
 'shootingstar': '-B(inverted&trend)',
 'shortline': '(B(white)-B(black))*B(short&(span<rng))',
 'spinningtop': '(B(white)-B(black))*B(short&(upper>body)&(lower>body)&~doji)',
 'stalledpattern': '-B(white&(P(white)>0)&(P(white,2)>0)&(c>P(c))&(P(c)>P(c,2))&short&(upper>body))',
 'sticksandwich': 'B((P(black,2)>0)&(P(white)>0)&black&within(c,P(c,2))&(P(l)>P(c,2)))',
 'takuri': 'B(doji&(lower>3*body)&(upper<=.1*rng)&~trend)',
 'tasukigap': 'B((P(white,2)>0)&(P(white)>0)&(P(l)>P(h,2))&black&(o<P(c))&(o>P(o))&(c<P(o))&(c>P(h,2)))-B((P(black,2)>0)&(P(black)>0)&(P(h)<P(l,2))&white&(o>P(c))&(o<P(o))&(c>P(o))&(c<P(l,2)))',
 'thrusting': '-B((P(black)>0)&white&(o<P(l))&(c>P(c))&(c<(P(o)+P(c))/2))',
 'tristar': 'B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(h)<P(l,2))&(l>P(h)))-B(doji&(P(doji)>0)&(P(doji,2)>0)&(P(l)>P(h,2))&(h<P(l)))',
 'unique3river': 'B((P(black,2)>0)&(P(black)>0)&(P(l)<P(l,2))&(P(c)>P(c,2))&white&short&(c<P(c)))',
 'upsidegap2crows': '-B((P(white,2)>0)&(P(black)>0)&black&(P(c)>P(c,2))&(o>P(o))&(c<P(c))&(c>P(c,2)))',
 'xsidegap3methods': 'B((P(white,2)>0)&(P(white)>0)&(P(l)>P(h,2))&black&(o>P(o))&(c<P(c,2)))-B((P(black,2)>0)&(P(black)>0)&(P(h)<P(l,2))&white&(o<P(o))&(c>P(c,2)))',
}
