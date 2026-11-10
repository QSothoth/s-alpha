"""WF05 joint trading and allocation rules."""
from dataclasses import asdict, replace

from . import wf03_trading, wf05_engine


def rules(base, *, q2=False, c2=False, m3=False, p30=False):
    policy = wf05_engine.Rules(**asdict(wf03_trading.trading_rules(base, q2=q2)))
    return replace(policy, rotate_below=.02 if c2 else 0.,
                   rotate_rmax_r=3. if m3 else 0., rotate_min_days=3 if c2 or m3 else 0,
                   max_position=.30 if p30 else policy.max_position)
