"""The registered trader systems: one definition per trader and version, used by everything that runs a trader
(the comparison, the trader-screens board, live running).  A system is a study module (its build), the configuration
carried out of the research, a version label and the freeze day (the last day of the data it was chosen on, so
later days are out of sample).  A better configuration out of the research is a new version here; the forward
record restarts at its freeze day.  docs/TRADER_PROTOCOL_CN.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FREEZE = '2026-10-16'                 # the last day of trader-data-v1
START = '2024-01-02'                  # every account starts here (panels.WINDOW)


@dataclass
class System:
    id: str
    version: str                      # the research configuration it carries, e.g. 'R15 C4'
    status: str                       # 'frozen' (approved by the user) | 'research' (carried, not frozen) | 'baseline'
    loader: object = field(repr=False)  # () -> (study, configuration)
    freeze: str = FREEZE

    @property
    def label(self):
        return {'frozen': f'{self.version}（已冻结）', 'baseline': f'{self.version}（B 级，基线）'}.get(self.status,
                                                                                                  self.version)

    def load(self):
        """(study, configuration); the study is wrapped by shorts.LongShort, which adds the short side when the
        configuration has a 'short' dict and otherwise calls the study's own build unchanged."""
        if not hasattr(self, '_loaded'):
            from .shorts import wrap
            st, cfg = self.loader()
            self._loaded = wrap(st), cfg
        return self._loaded

    @property
    def study(self):
        return self.load()[0]

    @property
    def config(self):
        return self.load()[1]

    @property
    def name(self):
        return self.study.name

    @property
    def strategy(self):
        return dict(zip(('选股与形态', '入场与止损', '离场', '仓位与市况'), STRATEGY[self.id][1:]))


def _short(st, short):
    """The short side carried by a short round (studies/<id>/reports/s*.json, key) or None."""
    if not short:
        return None
    report, key = short
    return json.loads((st.reports / report).read_text(encoding='utf-8'))['configs'][key]


def _martin(short=None):
    def load():
        from .martin import Martin
        m = Martin()
        m.unified = True
        cfg = json.loads((ROOT / 'studies/martin_luk/reports/final_system_r74.json').read_text(encoding='utf-8'))['config']
        sc = _short(m, short)
        return m, dict(cfg, short=sc) if sc else cfg
    return load


def _study(module, report, short=None):
    """The study's carried long configuration from a round report, plus (short = (report, key)) the short side of a
    short round (docs/TRADER_PROTOCOL_CN.md section 5)."""
    def load():
        import importlib
        st = importlib.import_module(f'studies.{module}.replicate').STUDY
        cfg, sc = st.config(report), _short(st, short)
        return st, dict(cfg, short=sc) if sc else cfg
    return load


def all_():
    # 2026-10-19: long-short versions frozen by the user (gate v2, studies/<id>/notes/SHORTS_CONCLUSION_CN.md)
    return [System('martin_luk', 'R74 + S7', 'frozen', _martin(('s7.json', 'S7C'))),
            System('christian_flanders', 'R15 C4 + S4', 'frozen',
                   _study('christian_flanders', 'r15.json', ('s4.json', 'F4A'))),
            System('clement_ang', 'R15 AA3 + S5', 'frozen', _study('clement_ang', 'r15.json', ('s5.json', 'C5A'))),
            System('qullamaggie', 'R11 N3 + S7', 'frozen', _study('qullamaggie', 'r11.json', ('s7.json', 'Q7C'))),
            System('oliver_kell', 'R6 A5 + S5', 'frozen', _study('oliver_kell', 'r6.json', ('s5.json', 'K5B'))),
            System('mark_minervini', 'R0b', 'baseline', _study('mark_minervini', 'r0b.json'))]


def get(id_):
    return next(x for x in all_() if x.id == id_)


STRATEGY = {        # (source label, 选股与形态, 入场与止损, 离场, 仓位与市况); hand-written from each configuration
    'martin_luk': ('R74 + S7（已冻结）',
                   '流动池里 1 / 3 / 6 月涨幅前 10%（近 5 天出现过）进观察名单；突破、内包、周线突破、基底路径，加 EP 跳空（≥ max(5%, 1 ADR)、2 倍量、收在开盘上方）',
                   '收盘买，当日低点止损，宽度 1% ~ min(5%, 0.5 ADR)，宽了就上移到上限',
                   '+10R 卖 30%，余下收盘跌破 21 日 EMA',
                   '每笔风险 0.5%（近 5 笔赚钱时 0.8%），指数回踩 9 / 21 EMA 时 ×1.6；+10R、+20R 加码；单只 ≤ 50%，总敞口 ≤ 280%；池等权指数在 50 EMA 上方才开新多，每天 ≤ 4 笔。'
                   '空头 S7：前领涨股（成交额 ≥ 1 亿）前一日收在下行 21 EMA 下方，次日反抽到它限价卖空，止损 min(5%, 半个 ADR)；指数 < 50 EMA 才开、每天 1 笔；第 1 天盈利回补一半、余下站上 9 EMA 回补，最多 5 天'),
    'christian_flanders': ('R15 C4 + S4（已冻结）',
                           '10 天底部后的 52 周新高突破（20 日成交额 ≥ 2000 万、ADR ≥ 2%、50 日线上方，按相对强度排序）；EP（跳空 ≥ 10%、3 倍量、离 52 周低点 ≥ 50%，可来自 ≥ 2 美元、500 万成交额的小盘）',
                           '收盘买，当日低点止损，宽度 1% ~ 6%',
                           '第 3 天卖一半，余下收盘跌破 10 日线',
                           '每笔风险 0.5%，单只 ≤ 30%，总敞口 ≤ 100%，最多 8 只，每天 ≤ 2 笔；无市况过滤。'
                           '空头 S4：前一日收在下行 200 日线下方、该线 60 天内压回过反抽，次日反抽到它限价卖空，止损 min(5%, 半个 ADR)；指数 < 50 EMA 才开、每天 1 笔；第 1 天盈利全部回补，最多 3 天'),
    'clement_ang': ('R15 AA3 + S5（已冻结）',
                    '精选清单（ADR ≥ 4%、离 52 周高 25% 内、高出 50 日线不到 4 ATR、5 日窄幅）越过昨高；清单内的 10 / 20 EMA 回踩；EP。池：成交额 ≥ 5000 万、ADR ≥ 3%、50 日线上方，按成交额排序',
                    '收盘买，当日低点止损（≥ 1%，不封顶）',
                    '+2R 卖 1/3 并保本，高出 50 日线 8 ATR 再卖 1/3，余下收盘跌破 20 EMA',
                    '每笔风险 0.5%，单只 ≤ 30%，总敞口 ≤ 200%，最多 30 只，每天 ≤ 10 笔；池等权指数在 20 EMA 上方才开新仓。'
                    '空头 S5：晚期失败底部——大型前领涨股（成交额 ≥ 5 亿、3 个月高点 ≥ 52 周低点 2 倍）收破 20 EMA 后缩量反抽，次日到 20 EMA 限价卖空；指数连续 5 个收盘 < 50 EMA 才开、每天 1 笔；站上 10 EMA 回补，最多 5 天'),
    'qullamaggie': ('R11 N3 + S7（已冻结）',
                    'EP 优先；10 天收紧底部的突破（1 / 3 / 6 月强度前 2%）。池：成交额 ≥ 2000 万、ADR ≥ 4%',
                    '收盘买，当日低点止损；突破单止损宽于 1 ADR 就不做',
                    '第 3 天赚钱时卖一半，最好价到 +2R 才把止损移到成本（R11，偏离“卖后立刻保本”），余下收盘跌破 20 EMA',
                    '每笔风险 0.3%，单只 ≤ 30%，总敞口 ≤ 100%，最多 15 只，每天 ≤ 5 笔；池等权指数 10 日线在 20 日线上方且都向上（他的“绿灯”）。'
                    '空头 S7：小盘抛物线（20 日涨 ≥ 300%、连涨 ≥ 3 天）收红后，次日开盘或反弹到 VWAP 近似价卖空，止损在顶部上方且 ≤ 1.5 ADR；10 日线回补，最多 10 天'),
    'oliver_kell': ('R6 A5 + S5（已冻结）',
                    'Wedge Pop、EMA Crossback、10 / 20 EMA 回踩、VCP、52 周突破、两根内包、跌破又收回 20 EMA；只做相对强度前 10%。池：成交额 ≥ 1 亿、ADR ≥ 3%，按成交额排序',
                    '收盘买，当日低点止损（≥ 1%，不封顶）',
                    '高出 10 日线 30% 卖 1/3，余下收盘跌破 20 EMA',
                    '每笔风险 0.5%，单只 ≤ 9%，总敞口 ≤ 150%，最多 12 只，每天 ≤ 4 笔；池等权指数在 20 EMA 上方才开新仓。'
                    '空头 S5：Wedge Drop 后反抽到下行 10 / 20 EMA，次日到线限价卖空，止损 min(5%, 半个 ADR)；指数 < 50 EMA 才开、每天 ≤ 2 笔；站上 10 EMA 回补，最多 10 天'),
    'mark_minervini': ('R0b（B 级，基线）',
                       '趋势模板 + VCP 突破（看板初版）。池：成交额 ≥ 2000 万',
                       '收盘买，当日低点止损（≥ 1%）',
                       '收盘跌破 50 日线',
                       '每笔风险 0.5%，单只 ≤ 30%，总敞口 ≤ 100%，最多 8 只，每天 ≤ 2 笔；无市况过滤'),
}
