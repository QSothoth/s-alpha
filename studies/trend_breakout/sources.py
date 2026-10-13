"""One interface for every market, shared by the dataset fetch and the future online scan.

A source has three calls and fixed row formats, so a strategy never knows where the data came from:

    src = sources.get('us')                      # 'us', 'hk' (OpenD) or 'cn' (Sina HTTP)
    stocks = src.universe()                      # [{'code': 'US.AAPL', 'name': ...}, ...] liquid names now
    for code, raw, qfq in src.bars(codes, start, end):
        ...                                      # rows: (code, date, open, high, low, close, volume, turnover)
        src.actions(code, raw, qfq)              # [(code, ex_date, factor_a, factor_b), ...]

Codes use the OpenD form everywhere (US.AAPL, HK.00700, SH.600519, SZ.000001), so the A-share HTTP
source can be swapped for OpenD if the account ever gets A-share quotes. ``raw`` is unadjusted and
``qfq`` is the source's own forward adjustment. Corporate actions use OpenD's convention: a price
before the ex-date is worth ``factor_a * price + factor_b`` after it. OpenD returns them from
``get_rehab`` (no quota) and Sina from its qfq.js factors; panel.py turns them into one
multiplicative adjustment for every market.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

COLUMNS = ('code', 'date', 'open', 'high', 'low', 'close', 'volume', 'turnover')
ACTION_COLUMNS = ('code', 'ex_date', 'factor_a', 'factor_b')


def in_window(day, start, end):
    return start <= day <= end


class OpenDSource:
    """US / HK through OpenD: stock filter for the universe, subscribed K_DAY for bars (no history quota)."""
    FILTERS = {'us': ('US', 5.0, 50e6), 'hk': ('HK', None, 20e6)}  # futu market, min price, min avg turnover/day
    BATCH, HOLD, WARMUP = 200, 61.0, 8.0  # 300 subscriptions in total; leave 100 for other tools
    UNLISTED = ('US_PINK', 'US_OTC')

    def __init__(self, market, host='127.0.0.1', port=11111):
        import futu as ft
        self.ft, self.market = ft, market
        self.q = ft.OpenQuoteContext(host=host, port=port)

    def close(self):
        self.q.close()

    def describe(self):
        name, min_price, min_turnover = self.FILTERS[self.market]
        return {'source': 'OpenD get_stock_filter + get_cur_kline(K_DAY, 1000)',
                'filter': {'min_price': min_price, 'min_avg_turnover_20d': min_turnover}}

    def universe(self, extra_filters=()):
        """Liquid names now; ``extra_filters`` lets the online scan add e.g. a 52-week-high ratio filter."""
        ft = self.ft
        name, min_price, min_turnover = self.FILTERS[self.market]
        filters = list(extra_filters)
        if min_price is not None:
            f = ft.SimpleFilter()
            f.stock_field, f.filter_min, f.is_no_filter = ft.StockField.CUR_PRICE, min_price, False
            filters.append(f)
        f = ft.AccumulateFilter()  # TURNOVER is an accumulate field: the sum over `days`
        f.stock_field, f.days, f.filter_min, f.is_no_filter = ft.StockField.TURNOVER, 20, min_turnover * 20, False
        filters.append(f)
        stocks, begin = [], 0
        while True:
            ret, data = self.q.get_stock_filter(getattr(ft.Market, name), filters, begin=begin, num=200)
            if ret != ft.RET_OK:
                raise RuntimeError(f'get_stock_filter: {data}')
            last_page, _, items = data
            stocks += [{'code': s.stock_code, 'name': s.stock_name} for s in items]
            begin += len(items)
            if last_page or not items:
                break
            time.sleep(3.1)  # stock filter: 10 requests per 30 seconds
        # keep exchange-listed common stocks: OpenD serves no OTC quotes, and ETFs are not stock picks
        ret, info = self.q.get_stock_basicinfo(getattr(ft.Market, name), ft.SecurityType.STOCK)
        if ret != ft.RET_OK:
            raise RuntimeError(f'get_stock_basicinfo: {info}')
        exchange = dict(zip(info.code, info.exchange_type))
        return [dict(s, exchange=exchange[s['code']]) for s in stocks
                if s['code'] in exchange and exchange[s['code']] not in self.UNLISTED]

    def _rows(self, df, start, end):
        return [(r.code, r.time_key[:10], r.open, r.high, r.low, r.close, r.volume, r.turnover)
                for r in df.itertuples() if in_window(r.time_key[:10], start, end)]

    def bars(self, codes, start, end):
        """Yield (code, raw, qfq); raw/qfq is None when OpenD returned nothing usable."""
        ft = self.ft
        for b in range(0, len(codes), self.BATCH):
            batch = list(codes[b:b + self.BATCH])
            ret, err = self.q.subscribe(batch, [ft.SubType.K_DAY], subscribe_push=False)
            if ret != ft.RET_OK:
                raise RuntimeError(f'subscribe: {err}')
            t0 = time.time()
            time.sleep(self.WARMUP)  # HK returned only 60 bars right after subscribing
            try:
                for code in batch:
                    got = {}
                    for au, key in ((ft.AuType.NONE, 'raw'), (ft.AuType.QFQ, 'qfq')):
                        ret, df = self.q.get_cur_kline(code, 1000, ft.SubType.K_DAY, au)
                        if ret == ft.RET_OK and len(df) < 1000:  # warm-up or a recent listing: ask once more
                            time.sleep(2)
                            ret, df = self.q.get_cur_kline(code, 1000, ft.SubType.K_DAY, au)
                        got[key] = self._rows(df, start, end) if ret == ft.RET_OK else None
                    yield code, got['raw'], got['qfq']
            finally:
                time.sleep(max(0.0, self.HOLD - (time.time() - t0)))  # OpenD holds a subscription >= 1 minute
                self.q.unsubscribe(batch, [ft.SubType.K_DAY])

    def actions(self, code, raw=None, qfq=None):
        """Every corporate action OpenD knows for the stock (get_rehab: no quota, 60 calls / 30 s)."""
        time.sleep(0.55)
        ret, df = self.q.get_rehab(code)
        if ret != self.ft.RET_OK:
            raise RuntimeError(f'get_rehab {code}: {df}')
        return [(code, str(r.ex_div_date)[:10], float(r.forward_adj_factorA), float(r.forward_adj_factorB))
                for r in df.itertuples()]

    def history_quota(self):
        ret, quota = self.q.get_history_kl_quota(get_detail=False)
        return list(quota) if ret == self.ft.RET_OK else str(quota)


class CnHttpSource:
    """A-shares over plain HTTP from Sina (OpenD has no A-share permission here): market list, unadjusted
    daily bars and Sina's own forward-adjustment factors, two requests per stock."""
    MIN_MKTCAP = 100e8  # CNY
    CDN_LAST_YEAR = 2022  # Tencent's static yearly day files stop here; later years come from the API
    PAUSE = 0.5
    REFERER = 'https://finance.sina.com.cn/'

    def __init__(self):
        self._factors = {}

    def close(self):
        pass

    def describe(self):
        return {'source': 'Sina Market_Center hs_a list + CN_MarketData.getKLineData + qfq.js factors',
                'filter': {'min_mktcap_cny': self.MIN_MKTCAP, 'exclude': 'Beijing exchange'}}

    @staticmethod
    def get(url, referer, tries=4):
        for attempt in range(tries):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': referer})
                return urllib.request.urlopen(req, timeout=20).read()
            except Exception:
                if attempt == tries - 1:
                    raise
                time.sleep(2 * 2 ** attempt)

    def universe(self, min_mktcap=None, max_mktcap=None):
        """Shanghai / Shenzhen stocks with min_mktcap <= market cap (< max_mktcap when given)."""
        min_mktcap = self.MIN_MKTCAP if min_mktcap is None else min_mktcap
        rows, page = [], 1
        while True:
            url = ('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
                   f'?page={page}&num=100&sort=mktcap&asc=0&node=hs_a&symbol=&_s_r_a=page')
            part = json.loads(self.get(url, self.REFERER).decode('gbk', 'replace'))
            if not part:
                break
            rows += part
            if float(part[-1]['mktcap']) * 1e4 < min_mktcap:  # sorted by market cap, values in 10k CNY
                break
            page += 1
            time.sleep(1.0)
        keep = select_cn(rows, min_mktcap)
        return [s for s in keep if max_mktcap is None or s['mktcap_cny'] < max_mktcap]

    def history_tencent(self, code, start, end, pause=1.0):
        """Unadjusted day bars for history beyond Sina's ~1,000 bars; same row format as bars(). Years up to
        CDN_LAST_YEAR come from Tencent's static yearly files, later ones from Sina."""
        symbol = code[:2].lower() + code[3:]
        rows = []
        y0, y1 = int(start[:4]), int(end[:4])
        while y0 <= min(y1, self.CDN_LAST_YEAR):  # static yearly files: fast and not rate-limited like the API
            time.sleep(0.2)
            url = f'http://data.gtimg.cn/flashdata/hushen/daily/{y0 % 100:02d}/{symbol}.js'
            try:
                text = self.get(url, 'https://gu.qq.com/', tries=2).decode('utf-8', 'replace')
            except urllib.error.HTTPError as exc:
                if exc.code != 404:  # 404: no trading that year (not listed yet)
                    raise
                text = ''
            days = [ln.strip().rstrip('\\').split() for ln in text.replace('\\n', '\n').splitlines()]
            days = [['20' + d[0][:2] + '-' + d[0][2:4] + '-' + d[0][4:6]] + d[1:6] for d in days
                    if len(d) >= 6 and d[0].isdigit() and len(d[0]) == 6]
            rows += tencent_rows(code, days, start, end)
            y0 += 1
        if y0 > y1 and (not rows or rows[-1][1] >= end):
            return rows
        # the rest: Sina's unadjusted bars (about 1,000 bars back from today; Tencent's API rate-limits hard).
        # The 2022 static file stops on 2022-10-24, so Sina continues from the day after the last static bar.
        rest = max(start, rows[-1][1] + '~' if rows else f'{y0}-01-01')  # '~' sorts after any date suffix
        time.sleep(self.PAUSE)
        url = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
               f'?symbol={symbol}&scale=240&ma=no&datalen=1023')
        payload = json.loads(self.get(url, self.REFERER)) or []
        if rows and payload and payload[0]['day'] > rows[-1][1]:
            raise RuntimeError(f'gap for {code}: static bars end {rows[-1][1]}, Sina starts {payload[0]["day"]}')
        later = sina_rows(code, payload, rest, end)
        return rows + later

    def share_history(self, code):
        """[(change_date, total_shares)] oldest first, from Sina's total-share history page (point-in-time caps)."""
        time.sleep(self.PAUSE)
        url = ('https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_StockStructureHistory/stockid/'
               f'{code[3:]}/stocktype/TotalStock.phtml')
        return sina_shares(self.get(url, self.REFERER).decode('gbk', 'replace'))

    def factors(self, code):
        if code not in self._factors:
            symbol = code[:2].lower() + code[3:]
            time.sleep(self.PAUSE)
            text = self.get(f'https://finance.sina.com.cn/realstock/company/{symbol}/qfq.js', self.REFERER)
            self._factors[code] = sina_factors(text.decode('utf-8', 'replace'))
        return self._factors[code]

    def bars(self, codes, start, end):
        """Raw bars from Sina; the qfq rows are raw / Sina's factor, kept for audit like the other sources."""
        from datetime import date
        days = int((date.today() - date.fromisoformat(start)).days * 0.7) + 30  # trading days back to start
        for code in codes:
            try:
                symbol = code[:2].lower() + code[3:]
                time.sleep(self.PAUSE)
                url = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
                       f'?symbol={symbol}&scale=240&ma=no&datalen={min(days, 1023)}')
                raw = sina_rows(code, json.loads(self.get(url, self.REFERER)), start, end)
                factors = self.factors(code)
                qfq = [(c, d, *(round(x / factor_on(factors, d), 4) for x in v[:4]), v[4], v[5])
                       for c, d, *v in raw]
            except Exception:
                raw = qfq = None
            yield code, raw, qfq

    def actions(self, code, raw=None, qfq=None):
        """Sina factor f applies from its date until the next one (price / f); a step is f_new / f_old."""
        f = self.factors(code)
        return [(code, d, new / old, 0.0) for (_, old), (d, new) in zip(f, f[1:])]


def tencent_rows(code, days, start, end):
    """Tencent day rows [date, open, close, high, low, volume, ...]; turnover is shares x close. Volume is in
    lots of 100 shares, except on the STAR market (SH.688 / SH.689) where it is already in shares."""
    unit = 1 if code.startswith(('SH.688', 'SH.689')) else 100
    out = []
    for r in days:
        if in_window(r[0], start, end):
            o, c, h, l, vol = (float(x) for x in r[1:6])
            out.append((code, r[0], o, h, l, c, vol * unit, round(vol * unit * c, 2)))
    return out


def sina_shares(text):
    """Parse the total-share history table: date cell then '<n>万股' cell; returns shares (not 10k units)."""
    import re
    pairs = re.findall(r'(\d{4}-\d{2}-\d{2})</div></td>\s*<td><div align="center">([\d.]+)万股', text)
    return sorted({(d, float(n) * 1e4) for d, n in pairs})


def sina_factors(text):
    """Parse qfq.js into [(date, factor)] oldest first."""
    data = json.loads(text[text.index('{'):text.rindex('}') + 1])['data']
    return sorted((r['d'], float(r['f'])) for r in data)


def factor_on(factors, day):
    """The factor in force on ``day``: the latest entry dated on or before it (1.0 before any entry)."""
    current = factors[0][1] if factors else 1.0
    for d, f in factors:
        if d > day:
            break
        current = f
    return current


def sina_rows(code, payload, start, end):
    """Sina day rows: {day, open, high, low, close, volume in shares}; turnover is volume x close."""
    out = []
    for r in payload or []:
        if in_window(r['day'], start, end):
            o, h, l, c, v = (float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume'))
            out.append((code, r['day'], o, h, l, c, v, round(v * c, 2)))
    return out


def select_cn(rows, min_mktcap):
    """Shanghai / Shenzhen stocks at or above the cap; the Beijing exchange (+-30% limit) is excluded."""
    keep = [r for r in rows if r['symbol'][:2] in ('sh', 'sz') and float(r['mktcap']) * 1e4 >= min_mktcap]
    return [{'code': r['symbol'][:2].upper() + '.' + r['symbol'][2:], 'name': r['name'],
             'mktcap_cny': float(r['mktcap']) * 1e4, 'amount_today_cny': float(r['amount'])} for r in keep]


def get(market):
    return CnHttpSource() if market == 'cn' else OpenDSource(market)
