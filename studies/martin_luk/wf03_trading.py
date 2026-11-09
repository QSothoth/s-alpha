"""WF03 trading components, using the frozen C062 execution inputs."""
from dataclasses import asdict, replace

import numpy as np

from . import e15_research as E15, ie47_e1 as IE, wf03_engine


def entry_book(A, picks, *, pullback=False):
    dated = {str(A['days'][t]): names for t, names in picks.items()}
    book = IE.entry_book(A, dated, **IE.E6['E6c'], pullback=pullback)[0]
    book = E15.P.retry_book(A, book, {}, E15.SPECS['C062'])[0]
    return [[tuple(e[:7]) + (None, .30) + tuple(e[9:]) for e in row] for row in book]


def confirm_signal(A):
    signal = np.zeros_like(A['close'], dtype=bool)
    signal[1:] = A['close'][1:] > A['high'][:-1]
    return signal


def trading_rules(base, *, q1=False, q2=False, q3=False):
    rules = wf03_engine.Rules(**asdict(base))
    return replace(rules, proof_stop='stop0' if q1 else rules.proof_stop,
                   confirmed_close_stop=q2,
                   proof_confirm_signal='wf03_confirm' if q3 else rules.proof_confirm_signal)
