"""Where newer bars come from.  A Provider answers three questions for one market:

    sessions(start, end)       trading days in [start, end] (ISO)
    snapshot(codes)            the latest regular session's bar of every code, with the exchange's previous close
                               (adjusted on an ex-date: the corporate action is prev_close / our last raw close)
    history(codes, start, end) (code, raw rows, actions) for codes, a slower full re-read of a window

OpenDProvider serves US / HK (snapshot: get_market_snapshot, 400 codes a call, no subscription; history:
get_cur_kline + get_rehab through studies.trend_breakout.sources; calendar: request_trading_days).  SinaProvider serves
A-shares (OpenD has no A-share quotes here): the Market_Center list pages carry every stock's latest bar and
'settlement' (previous close); history via sources.CnHttpSource; calendar from OpenD.  None of them uses the
historical K-line quota.  A new source is one more subclass.
"""
from __future__ import annotations

import json
import time
import urllib.request
from abc import ABC, abstractmethod
from datetime import time as clock

OPEN = {'us': ('America/New_York', clock(9, 30)), 'hk': ('Asia/Hong_Kong', clock(9, 0)),
        'cn': ('Asia/Shanghai', clock(9, 15))}              # from here a snapshot shows today (HK / A-share auctions)
CLOSE = {'us': ('America/New_York', clock(16, 30)), 'hk': ('Asia/Hong_Kong', clock(16, 30)),
         'cn': ('Asia/Shanghai', clock(15, 30))}           # a little after the close: the day's bar is final


class Provider(ABC):
    market = ''

    @abstractmethod
    def sessions(self, start, end) -> list:
        ...

    @abstractmethod
    def snapshot(self, codes) -> dict:
        """{code: dict(open, high, low, close, volume, turnover, prev_close, trading)}"""

    @abstractmethod
    def history(self, codes, start, end):
        """yield (code, raw rows (code, day, o, h, l, c, v, t) or None, actions [(code, ex, a, b)])"""

    def close(self):
        pass


def opend_calendar(market, start, end):
    import futu as ft
    q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        ret, data = q.request_trading_days(market=getattr(ft.TradeDateMarket, market.upper()), start=start, end=end)
        if ret != ft.RET_OK:
            raise RuntimeError(f'request_trading_days: {data}')
        return sorted(d['time'][:10] for d in data)
    finally:
        q.close()


class OpenDProvider(Provider):
    BATCH = 400

    def __init__(self, market):
        import futu as ft
        self.market, self.ft = market, ft
        self.q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)

    def close(self):
        self.q.close()

    def sessions(self, start, end):
        return opend_calendar(self.market, start, end)

    def snapshot(self, codes):
        out = {}
        for k in range(0, len(codes), self.BATCH):
            ret, df = self.q.get_market_snapshot(list(codes[k:k + self.BATCH]))
            if ret != self.ft.RET_OK:
                raise RuntimeError(f'get_market_snapshot: {df}')
            for r in df.itertuples():
                out[r.code] = dict(open=float(r.open_price), high=float(r.high_price), low=float(r.low_price),
                                   close=float(r.last_price), volume=float(r.volume), turnover=float(r.turnover),
                                   prev_close=float(r.prev_close_price),
                                   trading=not bool(getattr(r, 'suspension', False)) and float(r.volume) > 0)
            time.sleep(.6)                                  # 60 snapshot calls / 30 s
        return out

    def history(self, codes, start, end):
        from studies.trend_breakout import sources
        src = sources.OpenDSource(self.market)
        try:
            for code, raw, qfq in src.bars(list(codes), start, end):
                acts = src.actions(code, raw, qfq) if raw and qfq else []
                yield code, raw, acts
        finally:
            src.close()


class SinaProvider(Provider):
    URL = ('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
           '?page={page}&num=100&sort=symbol&asc=1&node=hs_a&symbol=&_s_r_a=page')
    REFERER = 'https://finance.sina.com.cn/'
    market = 'cn'

    def sessions(self, start, end):
        return opend_calendar('cn', start, end)

    def snapshot(self, codes):
        want, out, page = set(codes), {}, 1
        while True:
            req = urllib.request.Request(self.URL.format(page=page), headers={'User-Agent': 'Mozilla/5.0',
                                                                               'Referer': self.REFERER})
            part = json.loads(urllib.request.urlopen(req, timeout=20).read().decode('gbk', 'replace'))
            if not part:
                break
            for r in part:
                code = r['symbol'][:2].upper() + '.' + r['symbol'][2:]
                if code in want:
                    vol = float(r.get('volume') or 0)
                    out[code] = dict(open=float(r['open']), high=float(r['high']), low=float(r['low']),
                                     close=float(r['trade']), volume=vol, turnover=float(r.get('amount') or 0),
                                     prev_close=float(r['settlement']), trading=vol > 0 and float(r['open']) > 0)
            page += 1
            time.sleep(1.0)
        return out

    def history(self, codes, start, end):
        from studies.trend_breakout import sources
        src = sources.CnHttpSource()
        for code, raw, qfq in src.bars(list(codes), start, end):
            acts = src.actions(code, raw, qfq) if raw and qfq else []
            yield code, raw, acts


def get(market) -> Provider:
    return SinaProvider() if market == 'cn' else OpenDProvider(market)
