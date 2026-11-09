"""Daily-bar portfolio of a replicated trader: close-confirmed entries, fixed-risk sizing, partials, EMA trail,
both sides, and a placebo that swaps every entry for a random name from the same list on the same day.

Entries are tuples (priority, column, side, fill, stop, kind[, day_exit[, size_risk[, max_position[, risk_mult]]]]) placed on
day d and filled at `fill` on day d (normally that day's close); management starts on day d + 1.  side is +1 (long)
or -1 (short).  An intraday entry that was already stopped later the same day carries its exit price as day_exit;
size_risk (a fraction of the fill) sizes the trade when it is wider than the stop distance (gap risk), and
max_position caps that trade below rules.max_position (small caps); risk_mult multiplies its risk (a sizing tier).
The placebo keeps all three.
Same-day ordering is conservative: when a day reaches both the stop and a partial level, the stop comes first
unless the open is already beyond the partial level; an open already beyond the breakeven level moves the stop to
the fill before the day's stop check.
Fill time: an entry of a kind in rules.intraday_kinds, or whose fill is not that day's close, was filled during the
day (at the open or a level).  Such entries are opened after the open's gap stops and before anything else of the
day, sized on the equity and gross valued at the open, with the open slots as of then (positions exited later that
day still count). Same-day stops of new intraday entries run only after all intraday entries have been admitted;
daily bars cannot establish the ordering of fills across different names. Close entries come after the day's
management, on the equity at the close. The placebo keeps each entry's fill time: an intraday
entry's random name is bought or sold at its open (stopped that day when its range reaches the stop), a close
entry's at its close.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections import Counter, deque
from datetime import date

import numpy as np

from . import allocation


@dataclass(frozen=True)
class Rules:
    risk: float = .005              # equity fraction lost at the initial stop
    max_position: float = .30       # of equity, per name
    max_gross: float = 2.0          # long + short market value / equity
    trims: tuple = (3, 5)           # R multiples where trim_frac of the original size is taken off
    trim_frac: float = .15
    trail: str = 'e9'               # EMA name for the close trail ('' = none); armed after a close on the right side
    trail_next_open: bool = False   # execute a confirmed close-through trail at the next valid open
    arm_trail_on_entry: bool = False  # include the completed entry close when arming the EMA trail
    stop_ema_buffer: float = -1.0   # >= 0: after arming, the stop also trails the EMA minus/plus this fraction
    stop_ema_only: bool = False     # use the armed EMA stop without a separate close-through-EMA exit
    max_days: int = 0               # > 0: exit at the close after this many days
    max_days_next_open: bool = False  # confirm one session before max_days; exit at the deadline's open
    nft_days: int = 0               # > 0: exit at that day's close if the trade is still on the wrong side of its fill
    feedback: int = 0               # > 0: risk_low per trade while the last `feedback` closed trades sum to < 0 R
    feedback_opened: bool = False   # use latest opened positions, marked at the previous session close
    feedback_prior_close: bool = False  # freeze closed-trade feedback before today's opening exits for early entries
    management_by_kind: dict = field(default_factory=dict)  # entry kind -> position management overrides
    max_open_by_kind: dict = field(default_factory=dict)    # entry kind -> at most this many open positions of
                                                            # that kind (inside max_open; absent kinds: no own cap)
    risk_low: float = .0025
    risk_high: float = 0.0          # > 0: risk per trade while the last `feedback` closed trades sum to > 0 R
    short_trims: tuple | None = None  # shorts' partial levels (None = same as longs)
    short_max_days: int = 0           # shorts' holding limit (0 = same as longs)
    short_targets: tuple = ()         # names of lines in `ema` a short covers at, in order, once the day's low reaches
    short_target_frac: float = 0.0    # the line's value at the previous close (at the open when it opens below):
                                      # short_target_frac of the original size at each but the last, which covers the
                                      # rest (0: the first covers all); a line not below the fill is not a target yet
    short_trim_day: int = 0           # > 0: at the close this many sessions after entry a short covers
    short_trim_day_frac: float = 0.0  # short_trim_day_frac of its original size, once, when that close is below the fill
    short_trim_next_open: bool = False  # defer that profitable, close-confirmed timed cover to the next open
    max_open: int = 0               # > 0: no new trade while this many are open
    max_new_long: int = 0           # > 0: count successful new long positions per trading session
    max_new_by_kind: dict = field(default_factory=dict)     # entry kind -> its own limit of successful new longs a
                                                            # session, not counted in max_new_long
    exit_signal: str = ''           # name of a boolean (days x codes) array in `ema`: longs exit at that close
    exit_signal_cancel_add: bool = False  # skip close adds when a previously known close exit is scheduled
    short_exit_signal: str = ''     # the same for shorts: they cover at that close ('' = none)
    trail_after_trim: str = ''      # EMA name the close trail switches to after the first partial ('' = keep)
    breakeven_r: float = 0.0        # > 0: once the day's best price reaches this R multiple, the stop moves to the fill
    trim_signal: str = ''           # boolean (days x codes) array in `ema`: longs sell trim_frac of the original size
                                    # at that close (at most once a day)
    trim_signal_frac: float = 0.0   # fraction for signal trims (0 = trim_frac)
    trim_signal_max: int = 0        # > 0: at most this many signal trims a position (0 = every day the array is true)
    unit_adr: str = ''              # (days x codes) ADR-percent array in `ema`: the trims' and breakeven's unit is
                                    # this many percent of the fill as of the session before entry instead of the
                                    # initial stop distance R (his "2 ADR"); stops and sizing still use R
    trim_signal2: str = ''          # a second boolean array in `ema`: a long sells trim_signal2_frac of its original
    trim_signal2_frac: float = 0.0  # size at the first close it is true, once per position (Kell: half off at the 10 EMA)
    add_r: float = 0.0              # > 0: once a long closes at least this R above its fill, buy add_frac of the original
    add_frac: float = 1.0           # size at that close (once) and move the whole stop to the original fill
    add_cap_mult: float = 0.0       # > 0: such an add may take the position up to this multiple of its own cap
    add_cap_limit: float = 1.0      # ... never above this share of equity (Kell: a 15% core doubled to 30%)
    add_stop: str = 'fill'          # 'cost': after such an add the whole stop goes to the position's average cost
                                    # instead (Marios' free-roll: the add risks only the open profit)
    add_levels: tuple = ()          # several R levels instead of add_r, one add at each; an add the position or gross
                                    # caps leave no room for still uses up its level (no breakeven then)
    add_next_open: bool = False     # queue a close-confirmed R add for the next valid qualifying open
    add_filter: str = ''            # optional boolean array: an R add also needs a fresh setup at confirmation
    add_after_entries: bool = False # at the close, give new entries priority over adds to surviving old positions
    risk_scale: str = ''            # 1-D (days) array in `ema`: risk per new trade is multiplied by its value that day
    trail_alt: str = ''             # EMA name the close trail uses instead while the conditions below hold
    trail_alt_dd: float = 0.0       # > 0: ... while equity (as of the previous close) is this far below its peak
    dd_risk: float = 0.0            # > 0: while equity (as of the previous close) is this far below its peak, the risk
    dd_risk_mult: float = .5        # of new trades is multiplied by dd_risk_mult (a drawdown brake)
    trail_alt_days: str = ''        # 1-D bool array in `ema`: ... on these days (both set: both must hold)
    trim_day: int = 0               # > 0: at the close this many sessions after entry a long sells trim_day_frac of
    trim_day_frac: float = 0.0      # its original size, once (only when that close is above the fill if
    trim_day_profit: bool = True    # trim_day_profit) ...
    trim_day_breakeven: bool = False  # ... and then has its stop moved to the fill
    add_signal: str = ''            # boolean (days x codes) array in `ema`: a held long buys add_signal_frac (0 =
    add_signal_frac: float = 0.0    # add_frac) of its original size at that close, at most add_signal_max times
    add_signal_max: int = 0         # (0 = no limit), not on its entry day; then the stop is kept ('keep'), moved to
    add_signal_stop: str = 'keep'   # the original fill ('fill') or raised to the add day's low ('low')
    add_signal_profit: bool = False  # signal adds only while that close is above the fill (winners only)
    month_loss_cap: float = 0.0     # > 0: no new trades for the rest of a calendar month once equity (as of the previous
    month_cap_ladder: tuple = ()    # close) is this far below the month's opening equity; after 1, 2, ... losing
                                    # months in a row the cap is month_cap_ladder[0], [1], ... (the last one repeats)
    month_cap_basis: str = 'equity'  # 'opened': measure the month by the trades opened in it (realized plus marked at
                                    # the previous close, as a fraction of the month's opening equity) instead
    buy_cost: float = .0005
    sell_cost: float = .0005
    margin_rate: float = .07        # yearly, on long value above equity
    borrow_rate: float = 0.0        # > 0: yearly stock-borrow fee on short market value, charged at each session's
                                    # start on the shorts held at the previous close (an overnight short pays one day)
    max_new_all: int = 0            # > 0: successful new positions a session, longs and shorts of every kind together
                                    # (max_new_long and max_new_by_kind still apply inside it)
    max_new_year: int = 0           # > 0: successful new positions a calendar year, both sides
    no_rebuy_day: bool = False      # a name sold or stopped (any exit, partial or whole) is not opened again that session
    gross_cost: bool = False        # the gross room of an entry or add includes its buying cost (no margin is drawn)
    cap_adds_entry: bool = False    # adds stay inside the entry's own max_position (the tuple's), not only the policy's
    intraday_kinds: tuple = ()      # entry kinds filled during the day (open, limit or stop level), never at the close
    rotate_min_days: int = 0        # rotation only sells a long held at least this many sessions
    rotate_below: float = 0.0       # > 0: a close long entry with no slot or room sells the weakest long held since an
                                    # earlier day and up less than this fraction, at this close, then opens
    gross_close: bool = False       # at each close a gross above max_gross (shorts that rose, fees) is brought back to it:
                                    # shorts covered first (largest first), then longs sold, at that close ('gross')
    trail_strict: bool = False      # equality with the trail does not confirm a close-through exit
    entry_day_exit_signal: bool = False  # completed entry-session close may trigger the named exit signal
    close_stop_days: int = 0        # > 0: for this many sessions after entry a long's stop needs a close below it (exit
    hard_stop_mult: float = 2.0     # at that close); intraday and at the open only fill - hard_stop_mult * R runs
    stop_slip_r: float = 0.0        # intraday stop fills (not gaps) this many R worse, never beyond the day's range
    probe_hard_mult: float = 0.0    # > 0: size a long probe at this times its R; use that hard stop and a close below
                                    # stop0 until a profitable-close signal add actually confirms the position
    proof_risk: bool = False        # at confirmation target twice the initial K2 shares; each add's stop limits the
                                    # whole trade's cash loss (fees and realized trims included) to twice initial risk
    proof_confirm_signal: str = ''  # optional completed-close structural evidence before the first proof add
    proof_add_signal: str = ''      # later close adds, one initial K2 share block each, never on the confirmation day
    proof_add_max: int = 2
    probe_close_days: int = 0       # > 0: end the probe's close-stop window after this many sessions
    proof_stop: str = ''            # opt-in structural sizing: 'low', 'fill', or 'budget' at confirmation;
                                    # later adds use the day's low; risk caps shares instead of lowering this stop
    proof_target_mult: float = 0.0  # > 0: confirmation's total target in initial K2 share blocks (0 = legacy two)
    proof_trail: str = ''           # switch to this armed close EMA from the session after proof/conditions below
    proof_trail_adds: int = 0       # successful later adds or proof_trail_r reached (both zero: at confirmation)
    proof_trail_r: float = 0.0
    dd_risk_inclusive: bool = False # include equality with the drawdown threshold (legacy behavior is strict)
    make_room_kind: dict = field(default_factory=dict)  # close-entry kind -> the only kind it may evict at max_open
    make_room_confirmed: bool = False  # after unconfirmed probes, also allow confirmed positions of that kind
    rotate_score: str = ''          # opt-in completed-close score; replace a lower-score losing, unadded probe
    equity_ma_days: int = 0         # completed account closes; below this mean, halve new-entry risk
    confirm_trail: str = ''         # opt-in profitable-close confirmation: stop at fill, switch EMA next session
    confirm_close_r: float = 0.0    # confirmation also needs this many initial R at the completed close
    trail_confirm_days: int = 1     # consecutive completed closes through the armed EMA before exit
    reentry_days: int = 0           # opt-in one retry after an actual clean stop, on the first close above old fill
    reentry_adr: str = ''           # prior-session ADR percent, caps retry stop at min(5%, half ADR), floor 1%
    reentry_filter: str = ''        # optional completed-close permission for that retry
    max_new_risk: float = 0.0       # opt-in daily sum of initial stop risk / admission equity; exits do not refund
    rotate_actual_adds: bool = False  # protect successful adds instead of consumed add levels during scored rotation
    entry_familiar: str = ''        # opt-in prior-night familiar mask; actual account fills also teach the name
    entry_exception: str = ''       # completed-day event permission for an otherwise unfamiliar long
    entry_episode: str = ''         # causal episode IDs; successful long entries count within each name's episode
    entry_episode_max: int = 0
    entry_group_risk: bool = False  # px['entry_groups'][day]: column -> group; at most 3 new longs share one risk
    equity_state_days: int = 0      # opt-in absolute risk: above prior equity mean -> risk_high, drawdown -> risk_low
    equity_state_drawdown: float = .10


@dataclass
class Pos:
    j: int
    side: int
    kind: str
    d0: int
    fill: float
    stop: float
    stop0: float
    size0: float                    # shares (positive)
    size: float
    trims: int = 0
    adds: int = 0
    sig_adds: int = 0
    day_trimmed: bool = False
    sig2_trimmed: bool = False
    sig_trimmed: int = 0            # signal trims taken (Rules.trim_signal_max)
    targets: int = 0
    armed: bool = False
    trail_pending: bool = False
    trail_signal_day: int = -1
    add_pending: float | None = None
    add_signal_day: int = -1
    short_trim_pending: bool = False
    time_pending: bool = False
    cash: float = 0.0               # signed cash flow of the trade so far
    exits: list = field(default_factory=list)
    invested: float = 0.0
    executions: list = field(default_factory=list)
    management: Rules | None = None
    state: dict | None = None       # audit: an open position's state at the last close ('end')
    cap: float = 0.0                # its own max_position (the policy's, or the entry's when lower)
    tier: float | None = None       # the entry's risk multiplier (sizing tier), when it carried one
    add_mult: float | None = None   # the entry's own add_cap_mult (its sizing tier's), overriding the rules'
    avg: float = 0.0                # average cost of the shares held once it has been added to (0 = the fill)
    risk_unit: float = 0.0          # planned per-share risk for a gap-through entry; otherwise use the actual fill
    confirmed: bool = False
    confirmed_day: int = -1
    proof_adds: int = 0
    risk_budget: float = 0.0
    k2_size: float = 0.0
    proof_trail_day: int = -1
    entry_priority: tuple = ()      # opt-in slot release: (age, originating pick index, nightly rank, code)
    trail_below: int = 0
    trail_last_day: int = -1
    reentry_clean: bool = True
    disaster_stop: float = 0.0
    high_since_entry: float = 0.0


def risk_limited_stop(cash, shares, budget, sell_cost=0.0):
    """Long liquidation price whose cumulative cash result is exactly -budget, including exit fees."""
    return (-budget - cash) / (shares * (1 - sell_cost))


def risk_limited_shares(cash, shares, price, stop, budget, buy_cost=0.0, sell_cost=0.0):
    """Maximum extra long shares whose liquidation at a fixed stop loses at most budget."""
    cash, shares, price, stop, budget, buy_cost, sell_cost = map(
        float, (cash, shares, price, stop, budget, buy_cost, sell_cost))
    return max(0., (budget + cash + shares * stop * (1 - sell_cost)) /
               (price * (1 + buy_cost) - stop * (1 - sell_cost)))


def simulate(px, ema, rules, entries, start, end, placebo=None, pool=None, audit=False, track=None,
             preopen=False, preopen_gap_moc=False, preopen_fill_stop_pct_by_kind=None,
             preopen_fill_stop_hit=True, preopen_add_stop_gap=False, preopen_entry_close_add=False,
             daily_tolerance=None, entry_close_stops=False):
    """Run between ISO dates; return (equity array, dates, trades).

    px: dict of (days x codes) 'open', 'high', 'low', 'close' and 'dates', 'codes';  ema: dict name -> array;
    entries: list over days of entry tuples;  placebo: numpy Generator -> each real entry becomes a random
    pool[d] name of the same side, with the same stop distance in percent and the same fill time (see the module
    docstring); px['kind_pools'] (optional, kind -> days x codes) replaces pool for entries of that kind.
    Optional px['session'] numbers trading days and px['daily_close'] marks their final bars. Stops/trims
    run every bar; daily management and financing retain their daily clocks. px['mark'] may contain
    forward-filled, already observed closes for valuation only; never use it as tradable OHLC.
    track: a dict that receives per-session lists 'gross' (long + short value / equity at the close), 'open'
    (positions held at the close), 'new' (positions opened) and the total 'margin' interest paid.
    preopen: opt into the research-only fixed-share opening-limit reservation model.
    preopen_gap_moc: defer gap-through entries to an assumed same-day market-on-close exit.
    preopen_fill_stop_pct_by_kind: set a protective stop after the opening fill for specified kinds.
    preopen_add_stop_gap: after an opening add, execute an already-breached raised stop at that open.
    preopen_entry_close_add: let a surviving new position confirm an R add at its completed entry close.
    daily_tolerance: opt-in close-managed longs with separate ADR disaster stops, probe-to-cap adds,
    weekly/long/theme limits and rolling stop retries. None preserves every legacy execution path.
    entry_close_stops: count an opening entry's session as the first close-stop session; ordinary
    day-zero management stays disabled except for its hard stop and close stop.
    """
    o, h, l, c, dates = px['open'], px['high'], px['low'], px['close'], px['dates']
    rotation_days = px.get('allocation_rotate')
    session = px.get('session', np.arange(len(dates)))
    daily_close = px.get('daily_close')
    mark = px.get('mark')
    d0, d1 = int(np.searchsorted(dates, start)), int(np.searchsorted(dates, end, side='right'))
    trail = ema.get(rules.trail) if rules.trail else None
    sig_exit = ema[rules.exit_signal] if rules.exit_signal else None
    sig_exit_s = ema[rules.short_exit_signal] if rules.short_exit_signal else None
    trail2 = ema.get(rules.trail_after_trim) if rules.trail_after_trim else None
    sig_trim = ema[rules.trim_signal] if rules.trim_signal else None
    sig_trim2 = ema[rules.trim_signal2] if rules.trim_signal2 else None
    scale = ema[rules.risk_scale] if rules.risk_scale else None
    rotation_score = ema[rules.rotate_score] if rules.rotate_score else None
    trail3 = ema[rules.trail_alt] if rules.trail_alt else None
    alt_days = ema[rules.trail_alt_days] if rules.trail_alt_days else None
    if rules.add_next_open and (rules.add_signal or rules.add_after_entries):
        raise ValueError('next-open R adds do not support signal adds or close-entry priority')
    if not 0 <= rules.max_new_risk < 1 or (preopen and rules.max_new_risk):
        raise ValueError('daily new-entry risk requires a budget in [0, 1) and ordinary admission')
    if preopen and (placebo is not None or rules.feedback_opened or
                    (rules.feedback and not rules.feedback_prior_close) or rules.rotate_below or rules.gross_close):
        raise ValueError('unsupported preopen account configuration')
    if preopen_gap_moc and not preopen:
        raise ValueError('gap market-on-close requires preopen mode')
    if preopen_add_stop_gap and not preopen:
        raise ValueError('opening add stop gaps require preopen mode')
    if preopen_entry_close_add and not (preopen and rules.add_next_open):
        raise ValueError('entry-close R confirmation requires preopen next-open adds')
    if entry_close_stops and (not rules.close_stop_days or preopen or rules.probe_hard_mult):
        raise ValueError('entry close stops require ordinary close-stop management')
    fill_stop_pct = preopen_fill_stop_pct_by_kind or {}
    if fill_stop_pct and not preopen:
        raise ValueError('fill-relative stops require preopen mode')
    if any(not np.isfinite(p) or not 0 < p < 1 for p in fill_stop_pct.values()):
        raise ValueError('invalid fill-relative stop percentage')
    if preopen and not rules.add_next_open and (rules.add_r or rules.add_levels or
            any(v.get('add_r') or v.get('add_levels') for v in rules.management_by_kind.values())):
        raise ValueError('preopen adds require next-open confirmation')
    sig_add = ema[rules.add_signal] if rules.add_signal else None
    proof_add = ema[rules.proof_add_signal] if rules.proof_add_signal else None
    proof_confirm = ema[rules.proof_confirm_signal] if rules.proof_confirm_signal else None
    add_filter = ema[rules.add_filter] if rules.add_filter else None
    targets = [ema[k] for k in rules.short_targets]
    unit_adr = ema[rules.unit_adr] if rules.unit_adr else None
    kind_pools = px.get('kind_pools') or {}
    if rules.add_signal_stop not in ('keep', 'fill', 'low'):
        raise ValueError('add_signal_stop')
    peak = 1.0
    braked = False
    cash, pos, trades, curve = 1.0, {}, [], []
    month_trades = []
    sold_today = set()
    new_all, year_new, year_ = 0, 0, ''
    new_risk = 0.0
    margin_paid = 0.0
    recent_positions = deque(maxlen=rules.feedback or 1)
    opened_feedback = None
    prior_closed_feedback = None
    allowed_management = {'max_position', 'trims', 'trim_frac', 'trail', 'add_r', 'add_levels',
                          'arm_trail_on_entry', 'stop_ema_buffer', 'stop_ema_only'}
    for overrides in rules.management_by_kind.values():
        if set(overrides) - allowed_management:
            raise ValueError('unsupported position management override')
    management = {kind: replace(rules, **overrides) for kind, overrides in rules.management_by_kind.items()}
    for policy in (rules, *management.values()):
        if policy.stop_ema_only and (not policy.trail or policy.trail not in ema or not 0 <= policy.stop_ema_buffer < 1):
            raise ValueError('EMA-stop-only mode requires an available trail and a buffer in [0, 1)')
    if rules.proof_stop not in ('', 'low', 'fill', 'budget'):
        raise ValueError('proof_stop')
    if rules.proof_trail and rules.proof_trail not in ema:
        raise ValueError('proof trail requires an available EMA')
    if rules.trail_confirm_days < 1 or rules.confirm_close_r < 0:
        raise ValueError('invalid close confirmation policy')
    if rules.confirm_trail and rules.confirm_trail not in ema:
        raise ValueError('confirmation requires an available EMA')
    if rules.reentry_days and (rules.reentry_days < 0 or rules.reentry_adr not in ema or 'e9' not in ema):
        raise ValueError('reentry requires ADR and EMA9')
    retries = {}
    familiar = ema[rules.entry_familiar] if rules.entry_familiar else None
    exception = ema[rules.entry_exception] if rules.entry_exception else None
    episodes = ema[rules.entry_episode] if rules.entry_episode else None
    groups = px.get('entry_groups') if rules.entry_group_risk else None
    if rules.entry_episode_max and (rules.entry_episode_max < 1 or episodes is None):
        raise ValueError('entry episode limit requires causal episode IDs')
    if rules.entry_group_risk and (groups is None or preopen or placebo is not None):
        raise ValueError('group risk requires ordinary real entries and explicit groups')
    if rules.equity_state_days and (rules.equity_state_days < 1 or not 0 < rules.equity_state_drawdown < 1):
        raise ValueError('invalid equity state policy')
    familiar_names, episode_counts = set(), {}
    state_risk = rules.risk
    tol_stops, tol_retries = {}, {}
    tol_closed, tol_braked, tol_week, tol_week_new = deque(maxlen=5), False, None, 0
    if daily_tolerance is not None:
        if preopen or placebo is not None or daily_close is not None:
            raise ValueError('daily tolerance requires ordinary daily close entries')
        if any(e[2] > 0 and (e[5] in rules.intraday_kinds or e[3] != c[d, e[1]])
               for d, row in enumerate(entries) for e in row):
            raise ValueError('daily tolerance longs must fill at the completed close')

    def tolerance_victim(j, d):
        if not daily_tolerance['probe']:
            return None
        cap = daily_tolerance['max_long']
        held = [q for q in pos.values() if q.side > 0]
        if not cap or len(held) < cap or j not in daily_tolerance['groups'][d]:
            return None
        probes = [q for q in held if not q.confirmed and q.d0 < d and np.isfinite(c[d, q.j])]
        def weakness(q):
            strength = daily_tolerance['strength'][d, q.j]
            return (float(strength) if np.isfinite(strength) else -np.inf,
                    c[d, q.j]/q.fill, q.d0, str(px['codes'][q.j]))
        return min(probes, key=weakness) if probes else None

    def tolerance_block(j, d):
        if j in pos:
            return ''
        if j in sold_today:
            return 'no_rebuy_day'
        if daily_tolerance['feedback'] and not daily_tolerance['breadth_ok'][d]:
            return 'leader_breadth'
        if daily_tolerance['weekly'] and tol_week_new >= daily_tolerance['weekly']:
            return 'weekly_long'
        victim = tolerance_victim(j, d)
        if daily_tolerance['max_long'] and sum(q.side > 0 for q in pos.values()) >= daily_tolerance['max_long'] \
                and victim is None:
            return 'long_slots'
        membership = daily_tolerance['groups'][d]
        group = membership.get(j)
        if group is not None and sum(q.side > 0 and q is not victim and membership.get(q.j) == group
                                     for q in pos.values()) >= 2:
            return 'theme_slots'
        stopped = tol_stops.get(j)
        if stopped is not None and 0 < session[d]-session[stopped] <= 10:
            if not daily_tolerance['retry']:
                return 'retry_disabled'
            if not daily_tolerance['forms'][d, j] & 3 or c[d, j] <= daily_tolerance['e50'][d, j]:
                return 'retry_shape_or_ema50'
            if sum(session[d]-session[t] < 10 for t in tol_retries.get(j, ())) >= 2:
                return 'retry_limit'
        return ''

    def entry_block(j, side, d, group):
        if side < 0:
            return ''
        if daily_tolerance is not None:
            return tolerance_block(j, d)
        if familiar is not None and j not in familiar_names and not familiar[d, j] and \
                not (exception is not None and exception[d, j]) and group is None:
            return 'unfamiliar'
        if rules.entry_episode_max and episode_counts.get(j, (None, 0)) == \
                (int(episodes[d, j]), rules.entry_episode_max):
            return 'episode_limit'
        return ''

    def last(j, d):
        if mark is not None:
            return float(mark[d, j]) if rules.proof_stop else mark[d, j]
        k = d
        while k > 0 and np.isnan(c[k, j]):
            k -= 1
        return float(c[k, j]) if rules.proof_stop else c[k, j]

    def value(d):
        return sum(q.side * q.size * last(q.j, d) for q in pos.values())

    def gross(d):
        return sum(q.size * last(q.j, d) for q in pos.values())

    def at_open(j, d):                              # what a held name is worth at day d's open
        x = o[d, j]
        if rules.proof_stop:
            x = float(x)
        return x if np.isfinite(x) else last(j, d - 1)

    def gross_open(d):
        return sum(q.size * at_open(q.j, d) for q in pos.values())

    def unit(q):
        """The trims' and breakeven's unit: R, or (unit_adr) the ADR percent of the fill as of the session before
        entry."""
        if unit_adr is not None and q.d0 > 0 and np.isfinite(unit_adr[q.d0 - 1, q.j]):
            return q.fill * unit_adr[q.d0 - 1, q.j] / 100
        return abs(q.fill - q.stop0)

    def slipped(q, price, d):
        if not rules.stop_slip_r:
            return price
        price -= q.side * rules.stop_slip_r * abs(q.fill - q.stop0)
        return max(price, l[d, q.j]) if q.side > 0 else min(price, h[d, q.j])

    def close_window(q, d):
        if rules.probe_hard_mult and q.side > 0:
            age = session[d] - session[q.d0]
            return not q.confirmed and age > 0 and (not rules.probe_close_days or age <= rules.probe_close_days)
        age = session[d] - session[q.d0]
        within = 0 <= age < rules.close_stop_days if entry_close_stops else 0 < age <= rules.close_stop_days
        return bool(rules.close_stop_days) and q.side > 0 and within

    def live_stop(q, d):
        """The stop that runs at the open and intraday (close_stop_days: the hard stop inside the window)."""
        if daily_tolerance is not None and q.side > 0:
            return q.disaster_stop
        if close_window(q, d):
            if rules.probe_hard_mult:
                return q.fill - rules.probe_hard_mult * abs(q.fill - q.stop0)
            return min(q.stop, q.fill - rules.hard_stop_mult * abs(q.fill - q.stop0))
        return q.stop

    def intraday(e, d):
        """Filled before the close: a kind declared intraday, or a fill that is not that day's close."""
        return e[5] in rules.intraday_kinds or not e[3] == c[d, e[1]]

    def close_part(q, size, price, d, why):
        nonlocal cash, tol_braked
        if rules.proof_stop:
            price = float(price)
        size = min(size, q.size)
        if size <= 0:
            return
        if audit and why == 'end':                  # a position still open: its state for the next session
            R, U = abs(q.fill - q.stop0), unit(q)
            pol = q.management
            levels = pol.trims if q.side > 0 or rules.short_trims is None else rules.short_trims
            adds = pol.add_levels or ((pol.add_r,) if pol.add_r else ())
            q.state = dict(stop=float(q.stop), shares=float(q.size), shares0=float(q.size0), trims=q.trims,
                           armed=bool(q.armed), trail=pol.trail, stop_ema_only=pol.stop_ema_only,
                           next_trim=float(q.fill + q.side * levels[q.trims] * U) if q.trims < len(levels) else None,
                           trim_frac=pol.trim_frac,
                           next_add=float(q.fill + adds[q.adds] * R) if q.side > 0 and q.adds < len(adds) else None,
                           day_trim_pending=bool(rules.trim_day and not q.day_trimmed), trim_day=rules.trim_day,
                           trim_day_frac=rules.trim_day_frac, trim_day_profit=rules.trim_day_profit,
                           sig2_done=q.sig2_trimmed,
                           max_days=rules.max_days if q.side > 0 else (rules.short_max_days or rules.max_days),
                           short_trim_day_pending=bool(q.side < 0 and rules.short_trim_day and not q.day_trimmed),
                           short_trim_day=rules.short_trim_day, short_trim_day_frac=rules.short_trim_day_frac,
                           trim_signal=rules.trim_signal if q.side > 0 and rules.trim_signal
                           and (not rules.trim_signal_max or q.sig_trimmed < rules.trim_signal_max) else '',
                           trim_signal_frac=rules.trim_signal_frac or rules.trim_frac,
                           breakeven=float(q.fill + q.side * rules.breakeven_r * U)
                           if rules.breakeven_r and (q.stop - q.fill) * q.side < 0 else None,
                           next_target=float(targets[q.targets][d, q.j]) if q.side < 0 and q.targets < len(targets)
                           else None, target_name=rules.short_targets[q.targets]
                           if q.side < 0 and q.targets < len(targets) else '')
            if q.trail_pending:
                q.state['trail_pending'] = True
            if q.time_pending:
                q.state['time_pending'] = True
            if q.add_pending is not None:
                q.state['add_pending'] = {'level': float(q.add_pending), 'signal_day': str(dates[q.add_signal_day])}
            if daily_tolerance is not None and q.side > 0:
                q.state.update(disaster_stop=q.disaster_stop, high_since_entry=q.high_since_entry,
                               confirmed=q.confirmed, trail='e9' if q.sig_trimmed else '',
                               next_trim=None if q.sig_trimmed else q.fill+3*R, next_add=None)
        if q.side > 0:
            flow = size * price * (1 - rules.sell_cost)
        else:
            flow = -size * price * (1 + rules.buy_cost)
        cash += flow
        q.cash += flow
        q.size -= size
        q.exits.append((d, price, size, why))
        if why != 'end':
            sold_today.add(q.j)
        if audit:
            q.executions.append(dict(time=str(dates[d]), action=why, price=float(price), shares=float(size)))
        if q.size <= 1e-12 * q.size0:
            pos.pop(q.j, None)
            if daily_tolerance is not None and q.side > 0 and why != 'end':
                stopped = why in ('stop', 'gap_stop', 'close_stop')
                tol_closed.append(stopped)
                if daily_tolerance['feedback'] and len(tol_closed) == 5 and sum(tol_closed) >= 4:
                    tol_braked = True
                if stopped:
                    tol_stops[q.j] = d
            if rules.reentry_days and q.side > 0 and q.kind != 'reentry_close' and q.reentry_clean \
                    and not q.trims and not q.adds and not q.sig_adds \
                    and why in ('stop', 'gap_stop', 'close_stop'):
                retries[q.j] = (d, q.fill)
            risk = q.size0 * (q.risk_unit or abs(q.fill - q.stop0))
            gross0 = q.size0 * q.fill
            trades.append(dict(code=str(px['codes'][q.j]), side=q.side, kind=q.kind, entry=str(dates[q.d0]),
                               exit=str(dates[d]), days=int(session[d] - session[q.d0]), fill=q.fill, stop=q.stop0,
                               risk_pct=abs(q.fill - q.stop0) / q.fill, pnl=q.cash,
                               r=q.cash / risk if risk > 0 else 0.0, ret=q.cash / gross0,
                               ret_invested=q.cash / q.invested, why=why, add_tries=q.adds))
            if q.tier is not None:
                trades[-1]['tier'] = q.tier
            if rules.probe_hard_mult or rules.proof_risk:
                trades[-1].update(confirmed=q.confirmed,
                                 confirmed_day=str(dates[q.confirmed_day]) if q.confirmed else None,
                                 proof_adds=q.proof_adds, risk_budget=q.risk_budget, k2_shares=q.k2_size)
            if rules.proof_trail:
                trades[-1]['proof_trail_day'] = str(dates[q.proof_trail_day]) if q.proof_trail_day >= 0 else None
            if rules.confirm_trail:
                trades[-1].update(confirmed=q.confirmed,
                    confirmed_day=str(dates[q.confirmed_day]) if q.confirmed else None)
            if daily_tolerance is not None and q.side > 0:
                trades[-1].update(confirmed=q.confirmed,
                    confirmed_day=str(dates[q.confirmed_day]) if q.confirmed else None,
                    disaster_stop=q.disaster_stop, cap=q.cap, tolerance_trimmed=bool(q.sig_trimmed))
            if q.trail_signal_day >= 0:
                trades[-1]['trail_signal'] = str(dates[q.trail_signal_day])
            if audit:
                trades[-1]['executions'] = q.executions
                if why == 'end':
                    trades[-1]['state'] = q.state

    def open_pos(j, side, fill, stop, kind, d, equity, size_risk=None, max_pos=None, mult=None, add_mult=None,
                 early=False, fixed=None, priority=()):
        nonlocal cash, new_risk
        if j in pos or not np.isfinite(fill) or fill <= 0:
            return
        if rules.no_rebuy_day and j in sold_today:
            return
        victim = None
        scored_rotation = False
        if daily_tolerance is not None and side > 0:
            victim = tolerance_victim(j, d)
        if rotation_score is not None and not early and side > 0 and (rotation_days is None or rotation_days[d]):
            tight = rules.max_gross * equity - gross(d) < .05 * equity
            tight |= bool(allocation.slots_full(rules.max_open, pos, d, px.get('allocation_max_open')))
            incoming = rotation_score[d, j]
            if tight and np.isfinite(incoming):
                candidates = [q for q in pos.values() if q.side > 0 and q.d0 < d
                    and not q.confirmed and not (q.avg if rules.rotate_actual_adds else q.adds or q.sig_adds)
                    and np.isfinite(c[d, q.j]) and 0 < c[d, q.j] <= q.fill
                    and (not np.isfinite(rotation_score[d, q.j]) or rotation_score[d, q.j] < incoming)]
                if candidates:
                    victim = min(candidates, key=lambda q: (
                        rotation_score[d, q.j] if np.isfinite(rotation_score[d, q.j]) else -np.inf,
                        c[d, q.j]/q.fill, q.d0, str(px['codes'][q.j])))
                    scored_rotation = True
        if victim is None and not rules.make_room_kind.get(kind):
            if allocation.slots_full(rules.max_open, pos, d, px.get('allocation_max_open')):
                return
        elif victim is None and allocation.slots_full(rules.max_open, pos, d, px.get('allocation_max_open')):
            target = rules.make_room_kind.get(kind)
            if early or side < 0 or not target or (rotation_days is not None and not rotation_days[d]):
                return
            candidates = [q for q in pos.values() if q.side > 0 and q.kind == target
                          and (not q.confirmed or rules.make_room_confirmed)
                          and np.isfinite(c[d, q.j]) and c[d, q.j] > 0]
            if not candidates:
                return
            if any(len(q.entry_priority) < 3 for q in candidates):
                raise ValueError('slot release requires the originating pick index and nightly rank')
            victim = min(candidates, key=lambda q: (q.confirmed, q.entry_priority[1], q.entry_priority[2],
                                                     str(px['codes'][q.j]), q.d0))
        if kind in rules.max_open_by_kind and \
                sum(q.kind == kind for q in pos.values()) >= rules.max_open_by_kind[kind]:
            return
        risk = abs(fill - stop) / fill
        if fixed is None and (not (0 < risk < 1) or (stop - fill) * side >= 0):
            return
        if victim is not None:
            equity -= victim.size * float(c[d, victim.j]) * rules.sell_cost
        frac = rules.risk
        if rules.feedback_opened:
            recent = opened_feedback
        elif early and rules.feedback_prior_close:
            recent = prior_closed_feedback
        else:
            recent = (sum(t['r'] for t in trades[-rules.feedback:])
                      if rules.feedback and len(trades) >= rules.feedback else None)
        if recent is not None:
            if recent < 0:
                frac = rules.risk_low
            elif recent > 0 and rules.risk_high > 0:
                frac = rules.risk_high
        if scale is not None and np.isfinite(scale[d]):
            frac *= scale[d]
        if braked:
            frac *= rules.dd_risk_mult
        if rules.equity_ma_days and len(curve) >= rules.equity_ma_days and \
                equity < np.mean(curve[-rules.equity_ma_days:]):
            frac *= .5
        if rules.equity_state_days:
            frac = state_risk
        if mult is not None:
            frac *= mult
        if daily_tolerance is not None and side > 0:
            frac = .0075
            if daily_tolerance['feedback']:
                frac *= .5 if tol_braked else 1.
                frac *= .5 if not daily_tolerance['qqq_good'][d] else 1.
        policy = management.get(kind, rules)
        if early and policy.stop_ema_only and policy.arm_trail_on_entry:   # would read the fill day's close EMA
            raise ValueError('EMA-stop-only arming on entry requires a close entry')
        cap = policy.max_position if max_pos is None else min(policy.max_position, max_pos)
        width = risk if size_risk is None else max(risk, size_risk)
        if rules.probe_hard_mult and side > 0:
            width = max(width, risk * rules.probe_hard_mult)
        marked_gross = gross_open(d) if early else gross(d)
        if victim is not None:
            marked_gross -= victim.size * float(c[d, victim.j])
        room = rules.max_gross * equity - marked_gross
        if rules.gross_cost:
            current_value = sum(q.side * q.size * at_open(q.j, d) for q in pos.values()) if early else value(d)
            current_equity = cash + current_value
            if victim is not None:
                current_equity -= victim.size * float(c[d, victim.j]) * rules.sell_cost
            cost = rules.buy_cost if side > 0 else rules.sell_cost
            room = (rules.max_gross * current_equity - marked_gross) / (1 + rules.max_gross * cost)
        val = fixed['shares'] * fill if fixed is not None else min(frac * equity / width, cap * equity, room)
        if daily_tolerance is not None and side > 0:
            val = min(frac * equity / width, .10 * equity, cap * equity, room) \
                if daily_tolerance['probe'] else min(cap * equity, room)
        if rules.max_new_risk:
            val = min(val, max(0., rules.max_new_risk-new_risk) * equity / risk)
        if fixed is None and val <= .001 * equity:
            return
        if victim is not None:
            close_part(victim, victim.size, float(c[d, victim.j]), d, 'make_room')
            if track is not None and scored_rotation:
                track.setdefault('score_rotation', []).append(dict(day=str(dates[d]),
                    evicted=str(px['codes'][victim.j]), incoming=str(px['codes'][j]),
                    old_score=float(rotation_score[d, victim.j]), new_score=float(rotation_score[d, j])))
            elif track is not None and daily_tolerance is None:
                track.setdefault('make_room', []).append(dict(day=str(dates[d]),
                    evicted=str(px['codes'][victim.j]), entry=str(dates[victim.d0]),
                    confirmed=victim.confirmed, picked=str(dates[victim.entry_priority[1]]),
                    incoming=str(px['codes'][j]), incoming_kind=kind))
        size = val / fill
        flow = -val * (1 + rules.buy_cost) if side > 0 else val * (1 - rules.sell_cost)
        cash += flow
        pos[j] = Pos(j, side, kind, d, fill, stop, stop, size, size, cash=flow, invested=val, management=policy,
                     cap=cap, tier=mult, add_mult=add_mult,
                     risk_unit=fixed['risk_unit'] if fixed is not None and fill < stop else 0.0)
        if daily_tolerance is not None and side > 0:
            pos[j].disaster_stop = max(fill*.85, fill-daily_tolerance['disaster']*daily_tolerance['adr'][d, j])
            pos[j].high_since_entry = float(h[d, j])
            if track is not None:
                track.setdefault('tolerance_entries', []).append(dict(day=str(dates[d]), code=str(px['codes'][j]),
                    equity=float(equity), initial_fraction=float(val/equity), cap=float(cap),
                    risk_fraction=float(frac), disaster_stop=float(pos[j].disaster_stop),
                    group=daily_tolerance['groups'][d].get(j), kind=kind,
                    evicted=str(px['codes'][victim.j]) if victim is not None else None,
                    retry=j in tol_stops and 0 < session[d]-session[tol_stops[j]] <= 10))
        if rules.max_new_risk:
            new_risk += val * risk / equity
            if track is not None:
                track.setdefault('new_risk', []).append(dict(day=str(dates[d]), code=str(px['codes'][j]),
                    used=float(new_risk), budget=rules.max_new_risk))
        if rules.make_room_kind:
            pos[j].entry_priority = priority
        if (rules.probe_hard_mult or rules.proof_risk) and side > 0:
            pos[j].risk_budget = 2 * frac * equity
            pos[j].k2_size = min(frac * equity / risk, .25 * equity, room) / fill
        month_trades.append(pos[j])
        if rules.feedback_opened:
            recent_positions.append(pos[j])
        initial_trail = trail3 if alt else ema.get(policy.trail)
        if policy.arm_trail_on_entry and initial_trail is not None and np.isfinite(initial_trail[d,j]):
            pos[j].armed = (fill-initial_trail[d,j])*side > 0
            if pos[j].armed and policy.stop_ema_only:
                level = initial_trail[d, j] * (1 - side * policy.stop_ema_buffer)
                pos[j].stop = max(pos[j].stop, level) if side > 0 else min(pos[j].stop, level)
        if audit:
            pos[j].executions.append(dict(time=str(dates[d]), action='entry', price=float(fill), shares=float(size)))
        return True

    def add_pos(q, price, d, frac=None, signal=False, early=False, fixed_shares=None, stop_price=None):
        nonlocal cash
        if rules.proof_stop:
            price = float(price)
        eq = cash + (sum(p.side * p.size * at_open(p.j, d) for p in pos.values()) if early else value(d))
        room = rules.max_gross * eq - (gross_open(d) if early else gross(d))
        if rules.gross_cost:
            room /= 1 + rules.max_gross * rules.buy_cost
        cap = min(q.management.max_position, q.cap) if rules.cap_adds_entry else q.management.max_position
        mult = rules.add_cap_mult if q.add_mult is None else q.add_mult
        if mult > 0 and not signal:
            cap = min(cap * mult, rules.add_cap_limit)
        val = (fixed_shares * price if fixed_shares is not None else
               min((rules.add_frac if frac is None else frac) * q.size0 * price, cap * eq - q.size * price, room))
        if track is not None and 'management_attempts' in track:
            track['management_attempts'].append(dict(day=str(dates[d]), code=str(px['codes'][q.j]),
                entry=str(dates[q.d0]), action='signal_add' if signal else 'R_add',
                desired=float((rules.add_frac if frac is None else frac)*q.size0*price),
                allowed=float(max(0., val)), equity=float(eq), gross_room=float(room),
                position_room=float(cap*eq-q.size*price),
                filled=bool(fixed_shares is not None or val > .001*eq)))
        if signal:
            q.sig_adds += 1
        else:
            q.adds += 1
        if fixed_shares is None and val <= .001 * eq:
            if signal and rules.probe_hard_mult:
                q.sig_adds -= 1
            return
        flow = -val * (1 + rules.buy_cost)
        cash += flow
        q.cash += flow
        q.avg = ((q.avg or q.fill) * q.size + val) / (q.size + val / price)
        q.size += val / price
        q.invested += val
        if audit:
            q.executions.append(dict(time=str(dates[d]), action='add', price=float(price), shares=float(val / price)))
        if stop_price is not None:
            q.stop = max(q.stop, stop_price)
        elif not signal:
            q.stop = max(q.stop, q.avg if rules.add_stop == 'cost' else q.fill)
        elif rules.add_signal_stop == 'fill':
            q.stop = max(q.stop, q.fill)
        elif rules.add_signal_stop == 'low' and np.isfinite(l[d, q.j]):
            q.stop = max(q.stop, l[d, q.j])
        if rules.probe_hard_mult or rules.proof_risk:
            if not q.confirmed:
                q.confirmed, q.confirmed_day = True, d
            if audit:
                q.executions[-1].update(stop=float(q.stop), risk_budget=q.risk_budget,
                                       risk_at_stop=float(-(q.cash + q.size*q.stop*(1-rules.sell_cost))))
        return True

    def try_proof(q, d):
        price = float(c[d, q.j]) if rules.proof_stop else c[d, q.j]
        first = not q.confirmed
        if session[d] <= session[q.d0] or not np.isfinite(price):
            return
        if first:
            if price <= q.fill or (proof_confirm is not None and not proof_confirm[d, q.j]):
                return
            shares = (rules.proof_target_mult or 2) * q.k2_size - q.size
        else:
            if d == q.confirmed_day or q.proof_adds >= rules.proof_add_max:
                return
            if rules.proof_stop and q.management.add_levels:
                levels = q.management.add_levels
                if q.adds >= len(levels) or price < q.fill + levels[q.adds] * abs(q.fill-q.stop0):
                    return
                q.adds += 1
            elif proof_add is None or not proof_add[d, q.j]:
                return
            shares = q.k2_size
        eq = cash + value(d)
        shares = min(shares, (q.management.max_position * eq - q.size * price) /
                     (price * (1 + q.management.max_position * rules.buy_cost)),
                     (rules.max_gross * eq - gross(d)) / (price * (1 + rules.max_gross * rules.buy_cost)))
        status, stop = 'budget_rejected', None
        if shares * price > .001 * eq:
            if rules.proof_stop and not (first and rules.proof_stop == 'budget'):
                floor = q.fill if first and rules.proof_stop == 'fill' else l[d, q.j]
                stop = float(max(q.stop0, q.stop, floor))
                if stop < price:
                    shares = min(shares, risk_limited_shares(q.cash, q.size, price, stop,
                                                           q.risk_budget, rules.buy_cost, rules.sell_cost))
            else:
                after_cash = q.cash - shares * price * (1 + rules.buy_cost)
                stop = max(q.stop0, q.stop, risk_limited_stop(after_cash, q.size + shares,
                                                            q.risk_budget, rules.sell_cost))
            status = 'risk_rejected'
            if stop < price and shares * price > .001 * eq:
                add_pos(q, price, d, signal=True, fixed_shares=shares, stop_price=stop)
                if not first:
                    q.proof_adds += 1
                status = 'filled'
        if track is not None:
            track.setdefault('proof_orders', []).append(dict(code=str(px['codes'][q.j]),
                entry=str(dates[q.d0]), day=str(dates[d]), phase='confirm' if first else 'pyramid',
                status=status, shares=float(max(0, shares)), stop=float(stop) if stop is not None else None))

    def switch_proof_trail(q, d):
        if not rules.proof_trail or not q.confirmed or q.proof_trail_day >= 0:
            return
        if rules.proof_trail_adds or rules.proof_trail_r:
            added = rules.proof_trail_adds > 0 and q.proof_adds >= rules.proof_trail_adds
            profit = rules.proof_trail_r > 0 and c[d, q.j] >= q.fill + rules.proof_trail_r * abs(q.fill-q.stop0)
            if not (added or profit):
                return
        q.management = replace(q.management, trail=rules.proof_trail, stop_ema_only=False,
                               stop_ema_buffer=-1., trail_strict=True)
        q.armed, q.proof_trail_day = True, d

    def add_event(q, d, status, opening=None):
        if track is not None:
            track.setdefault('add_orders', []).append(dict(code=str(px['codes'][q.j]), kind=q.kind,
                entry_day=str(dates[q.d0]),
                signal_day=str(dates[q.add_signal_day]), day=str(dates[d]), status=status,
                level=float(q.add_pending), opening=float(opening) if opening is not None and np.isfinite(opening) else None))

    def try_adds(q, d):
        j = q.j
        cancel = rules.exit_signal_cancel_add and sig_exit is not None and sig_exit[d, j]
        if q.side < 0 or cancel:
            return
        if daily_tolerance is not None:
            return
        if rules.probe_hard_mult or rules.proof_risk:
            if (sig_exit is not None and sig_exit[d, j]) or \
                    (rules.nft_days and session[d]-session[q.d0] == rules.nft_days and c[d, j] < q.fill) or \
                    (rules.max_days and session[d]-session[q.d0] >= rules.max_days):
                return
            if rules.proof_risk:
                try_proof(q, d)
                return
        levels = q.management.add_levels or ((q.management.add_r,) if q.management.add_r else ())
        if q.adds < len(levels) and (add_filter is None or add_filter[d, j]) \
                and c[d, j] >= q.fill + levels[q.adds] * abs(q.fill - q.stop0):
            if rules.add_next_open:
                q.add_pending = float(q.fill + levels[q.adds] * abs(q.fill - q.stop0))
                q.add_signal_day = d
                add_event(q, d, 'confirmed')
            else:
                add_pos(q, c[d, j], d)
        if sig_add is not None and sig_add[d, j] and session[d] > session[q.d0] \
                and (not rules.add_signal_max or q.sig_adds < rules.add_signal_max) \
                and (not rules.add_signal_profit or c[d, j] > q.fill):
            add_pos(q, c[d, j], d, rules.add_signal_frac or rules.add_frac, signal=True)

    def cover_targets(q, d, reach):
        """A short's target lines the day reaches (reach = the open on a stop day, else the low), in order."""
        j = q.j
        while q.targets < len(targets) and j in pos and d > 0:
            lv = targets[q.targets][d - 1, j]
            if not (np.isfinite(lv) and lv < q.fill and reach <= lv):
                break
            last_ = q.targets == len(targets) - 1 or not rules.short_target_frac
            close_part(q, q.size if last_ else rules.short_target_frac * q.size0, min(o[d, j], lv), d, 'target')
            q.targets = len(targets) if last_ else q.targets + 1


    def swap(tagged, d):
        """The placebo: every (intraday, entry) for a random name of its kind's pool, with its stop distance and
        fill time."""
        out = []
        for early_, e in tagged:
            pr, j, side, fill, stop, kind = e[:6]
            base = kind_pools.get(kind, pool)
            ok = base[d] & np.isfinite(c[d])
            if early_:
                ok = ok & np.isfinite(o[d])
            cand = np.flatnonzero(ok)
            if not len(cand):
                continue
            k = int(placebo.choice(cand))
            pct = abs(fill - stop) / fill
            kind_ = kind if kind in management or kind in rules.max_open_by_kind \
                or kind in rules.max_new_by_kind else 'placebo'
            if early_:                              # bought / sold at its open: stopped that day if reached
                f = float(o[d, k])
                st = f * (1 - side * pct)
                hit = (l[d, k] <= st) if side > 0 else (h[d, k] >= st)
                out.append((True, (pr, k, side, f, st, kind_, st if hit else None) + tuple(e[7:10])))
            else:
                out.append((False, (pr, k, side, c[d, k], c[d, k] * (1 - side * pct), kind_, None) + tuple(e[7:10])))
        return out

    preplanned = None
    gap_moc_exits = []

    def take(lst, d, eq_now, early):
        """Open the day's entries of one fill time, in priority order, under the day's caps."""
        nonlocal new_all, year_new, new_longs, tol_week_new
        day_stops = []
        day_groups = groups[d] if groups is not None else {}
        group_sizes = Counter(day_groups[e[1]] for e in lst if e[2] > 0 and e[1] in day_groups
                              and e[1] not in pos and not entry_block(e[1], e[2], d, day_groups[e[1]]))
        group_fills = Counter()
        for e in sorted(lst, key=lambda x: x[0]):
            pr, j, side, fill, stop, kind = e[:6]
            group = day_groups.get(j) if side > 0 else None
            attempt = None
            if track is not None and 'entry_attempts' in track:
                attempt = dict(day=str(dates[d]), code=str(px['codes'][j]), kind=kind,
                    positions=len(pos), held=[dict(code=str(px['codes'][q.j]), kind=q.kind,
                    entry=str(dates[q.d0]), confirmed=q.confirmed) for q in pos.values()],
                    new_longs=new_longs, new_all=new_all, same_code=j in pos,
                    priority=pr, reason='pending')
                track['entry_attempts'].append(attempt)
            blocked = entry_block(j, side, d, group)
            if group is not None and group_fills[group] >= 3:
                blocked = 'group_limit'
            if blocked:
                if attempt is not None:
                    attempt['reason'] = blocked
                continue
            if month_blocked:
                if attempt is not None:
                    attempt['reason'] = 'month'
                break
            own = side > 0 and kind in rules.max_new_by_kind
            reason = allocation.daily_reason(rules, side, kind, new_by_kind, new_longs, new_all, year_new)
            if reason:
                if attempt is not None:
                    attempt['reason'] = reason
                continue
            fixed = preplanned['entries'].get((kind, j)) if preopen and early else None
            if preopen and early:
                if fixed is None:
                    continue
                rec = preplanned['entry_trace'][(kind, j)]
                if not np.isfinite(fill) or fill <= 0:
                    rec['execution'] = 'missing_open'
                    continue
                rec['opening'] = float(fill)
                pct = fill_stop_pct.get(kind)
                if np.float32(fill) == np.float32(fixed['limit']) or (
                        pct is None and np.float32(fill) == np.float32(stop)):
                    rec['execution'] = 'precision_unknown'
                    continue
                if fill > fixed['limit']:
                    rec['execution'] = 'limit_expired'
                    continue
                if pct is not None:
                    if not np.isfinite(l[d, j]) or l[d, j] <= 0:
                        raise ValueError('a filled opening has no valid same-day low')
                    stop = float(fill * (1 - pct))
                    unknown = np.float32(l[d, j]) == np.float32(stop)
                    touched = preopen_fill_stop_hit if unknown else l[d, j] <= stop
                    rec.update(fill_stop=float(stop), stop_precision_unknown=bool(unknown))
                    e = tuple(e[:4]) + (stop, kind, stop if touched else None) + tuple(e[7:])
                else:
                    if len(e) > 11 and not e[11] and not (preopen_gap_moc and fill < stop):
                        raise ValueError('a filled opening has no valid same-day low')
                    if fill < stop and (len(e) < 7 or e[6] is None):
                        raise ValueError('gap-through entry requires an observed stress exit')
                    if preopen_gap_moc and fill < stop and (not np.isfinite(c[d, j]) or c[d, j] <= 0 or
                                                             e[6] != c[d, j]):
                        raise ValueError('a gap market-on-close exit needs the valid same-day close')
            had = j in pos
            if len(e) > 6 and e[6] is not None and not early:
                raise ValueError('same-day stop requires a declared or identifiable intraday entry')
            if entry_close_stops and side > 0 and len(e) > 6 and e[6] is not None:
                raise ValueError('entry close stops must not carry a precomputed day-zero exit')
            if rules.rotate_below and side > 0 and not early and j not in pos and (rotation_days is None or rotation_days[d]):
                short_room = rules.max_gross * eq_now - gross(d) < .05 * eq_now
                if short_room or (allocation.slots_full(rules.max_open, pos, d, px.get('allocation_max_open'))):
                    q = allocation.rotation_victim(rules, pos, c, d)
                    if q is not None:
                        close_part(q, q.size, float(c[d, q.j]), d, 'rotate')
            mult = e[9] if len(e) > 9 else None
            if group is not None:
                mult = (mult if mult is not None else 1.)/min(3, max(1, group_sizes[group]))
            admission_equity = cash+value(d) if daily_tolerance is not None and side > 0 else eq_now
            opened = open_pos(j, side, fill, stop, kind, d, admission_equity, e[7] if len(e) > 7 else None,
                              e[8] if len(e) > 8 else None, mult,
                              e[10] if len(e) > 10 else None, early=early, fixed=fixed, priority=pr)
            if attempt is not None:
                attempt['reason'] = ('filled' if opened else 'same_code' if had else
                    'no_rebuy_day' if rules.no_rebuy_day and j in sold_today else
                    'max_open' if allocation.slots_full(rules.max_open, pos, d, px.get('allocation_max_open')) else
                    'max_open_kind' if kind in rules.max_open_by_kind and
                    sum(q.kind == kind for q in pos.values()) >= rules.max_open_by_kind[kind] else 'risk_or_gross')
            if preopen and early:
                if not opened:
                    raise AssertionError('a reserved valid opening was unexpectedly rejected')
                opening_equity = cash + sum(q.side * q.size * at_open(q.j, d) for q in pos.values())
                rec.update(execution=('gap_moc' if preopen_gap_moc else 'gap_stress') if fill < stop else 'filled',
                           opening=float(fill),
                           cash_after=float(cash), positions_after=len(pos),
                           gross_after=float(gross_open(d) / opening_equity) if opening_equity > 0 else None)
            if opened:
                new_all += 1
                year_new += 1
                if daily_tolerance is not None and side > 0:
                    tol_week_new += 1
                    stopped = tol_stops.get(j)
                    if stopped is not None and 0 < session[d]-session[stopped] <= 10:
                        history = tol_retries.setdefault(j, deque())
                        while history and session[d]-session[history[0]] >= 10:
                            history.popleft()
                        history.append(d)
                if familiar is not None:
                    familiar_names.add(j)
                if side > 0 and rules.entry_episode_max:
                    episode = int(episodes[d, j])
                    old_episode, count = episode_counts.get(j, (None, 0))
                    episode_counts[j] = (episode, count+1 if old_episode == episode else 1)
                if group is not None:
                    group_fills[group] += 1
                if track is not None and (familiar is not None or episodes is not None or
                                           groups is not None or rules.equity_state_days):
                    track.setdefault('habit_entries', []).append(dict(day=str(dates[d]), code=str(px['codes'][j]),
                        group=group, side=side, equity=float(eq_now), shares=float(pos[j].size0),
                        notional_fraction=float(pos[j].size0*fill/eq_now),
                        stop_risk_fraction=float(pos[j].size0*abs(fill-stop)/eq_now),
                        state_risk=state_risk if rules.equity_state_days else None,
                        episode=int(episodes[d, j]) if side > 0 and episodes is not None else None))
            if opened and own:
                new_by_kind[kind] = new_by_kind.get(kind, 0) + 1
            elif opened and side > 0:
                new_longs += 1
            if len(e) > 6 and e[6] is not None and j in pos and not had:
                if preopen_gap_moc and fixed is not None and fill < stop:
                    gap_moc_exits.append((j, e[6]))
                else:
                    day_stops.append((j, e[6]))
        for j, price in day_stops:
            q = pos[j]
            price = slipped(q, price, d)
            close_part(q, q.size, price, d, 'stop_day0')

    month_open, month_losses, month_cap, month_blocked = 1.0, 0, rules.month_loss_cap, False
    if rules.month_cap_basis not in ('equity', 'opened'):
        raise ValueError('month_cap_basis')

    def month_pnl(d):
        """Profit of the trades opened this month, marked at the previous close."""
        return sum(q.cash + (q.side * q.size * last(q.j, d - 1) if q.size > 0 else 0.0) for q in month_trades)

    def tolerance_manage(q, d):
        nonlocal tol_braked
        j, price = q.j, float(c[d, q.j])
        if not np.isfinite(price):
            return
        R = q.fill-q.stop0
        if daily_tolerance['distribution'][d, j]:
            close_part(q, q.size, price, d, 'distribution')
            return
        if price < q.stop:
            close_part(q, q.size, price, d, 'close_stop')
            return
        if q.sig_trimmed and price < ema['e9'][d, j]:
            close_part(q, q.size, price, d, 'trail')
            return
        proof = price >= q.fill+R or price > q.high_since_entry
        if daily_tolerance['probe'] and q.adds < 2 and proof:
            eq = cash+value(d)
            amount = min((q.cap*eq-q.size*price)/(1+q.cap*rules.buy_cost),
                         (rules.max_gross*eq-gross(d))/(1+rules.max_gross*rules.buy_cost))
            filled = amount > .001*eq and add_pos(q, price, d, fixed_shares=amount/price,
                                                 stop_price=max(q.stop, q.fill))
            if filled:
                if not q.confirmed:
                    q.confirmed, q.confirmed_day = True, d
                tol_braked = False
            if track is not None:
                track.setdefault('tolerance_adds', []).append(dict(day=str(dates[d]), code=str(px['codes'][j]),
                    entry=str(dates[q.d0]), filled=bool(filled), amount=float(max(0., amount)),
                    cap=q.cap, equity=float(eq), proof_R=price >= q.fill+R,
                    proof_high=price > q.high_since_entry, stop=float(q.stop)))
        if not q.sig_trimmed and (price >= q.fill+3*R or daily_tolerance['stretch'][d, j]):
            q.sig_trimmed = 1
            close_part(q, .15*q.size, price, d, 'signal_trim')
        q.high_since_entry = max(q.high_since_entry, float(h[d, j]))

    for d in range(d0, d1):
        if daily_tolerance is not None:
            week = date.fromisoformat(str(dates[d])).isocalendar()[:2]
            if week != tol_week:
                tol_week, tol_week_new = week, 0
        gap_moc_exits = []
        equity = cash + value(d - 1) if d > d0 else 1.0
        if rules.month_loss_cap > 0:
            if d > d0 and str(dates[d])[:7] != str(dates[d - 1])[:7]:     # a new month opens at the previous close
                lost = month_pnl(d) < 0 if rules.month_cap_basis == 'opened' else equity < month_open
                month_losses = month_losses + 1 if lost else 0
                month_trades.clear()
                ladder = rules.month_cap_ladder
                month_cap = ladder[min(month_losses, len(ladder)) - 1] if month_losses and ladder \
                    else rules.month_loss_cap
                month_open, month_blocked = equity, False
            now = month_open + month_pnl(d) if rules.month_cap_basis == 'opened' else equity
            month_blocked = month_blocked or now <= month_open * (1 - month_cap)
        peak = max(peak, equity)
        if rules.equity_state_days:
            state_risk = rules.risk
            if equity < peak*(1-rules.equity_state_drawdown):
                state_risk = rules.risk_low
            elif len(curve) >= rules.equity_state_days and equity > np.mean(curve[-rules.equity_state_days:]):
                state_risk = rules.risk_high
        braked = rules.dd_risk > 0 and (equity <= peak * (1 - rules.dd_risk) if rules.dd_risk_inclusive
                                      else equity < peak * (1 - rules.dd_risk))
        alt = trail3 is not None and (rules.trail_alt_dd > 0 or alt_days is not None) \
            and (rules.trail_alt_dd <= 0 or equity < peak * (1 - rules.trail_alt_dd)) \
            and (alt_days is None or bool(alt_days[d]))
        if d == d0 or session[d] != session[d - 1]:
            new_longs = 0
            new_risk = 0.0
            new_by_kind = {}
            new_all = 0
            sold_today.clear()
            if str(dates[d])[:4] != year_:
                year_, year_new = str(dates[d])[:4], 0
            if rules.feedback_prior_close and not rules.feedback_opened:
                prior_closed_feedback = (sum(t['r'] for t in trades[-rules.feedback:])
                                         if rules.feedback and len(trades) >= rules.feedback else None)
            if rules.feedback_opened and rules.feedback and len(recent_positions) >= rules.feedback:
                opened_feedback = sum(
                    (q.cash + (q.side * q.size * last(q.j, d - 1) if q.size > 0 else 0))
                    / (q.size0 * abs(q.fill - q.stop0)) for q in recent_positions)
                if abs(opened_feedback) < 1e-10:
                    opened_feedback = 0.0
            longs = sum(q.size * last(q.j, d - 1) for q in pos.values() if q.side > 0)
            cash -= rules.margin_rate / 252 * max(0.0, longs - equity)
            margin_paid += rules.margin_rate / 252 * max(0.0, longs - equity)
            if track is not None and 'daily_margin' in track:
                track['daily_margin'].append(rules.margin_rate / 252 * max(0.0, longs - equity))
            if rules.borrow_rate:                       # each short carries its fee in its own result too
                for q in pos.values():
                    if q.side < 0:
                        fee = rules.borrow_rate / 252 * q.size * last(q.j, d - 1)
                        cash -= fee
                        q.cash -= fee
        if preopen:
            from .preopen import plan
            if d > d0 and session[d] == session[d - 1]:
                raise ValueError('preopen requires one bar per session')
            rows = entries[d] if d < len(entries) and not month_blocked else []
            if any(e[5] not in rules.intraday_kinds for e in rows):
                raise ValueError('preopen orders must be explicitly opening kinds')
            candidates = [(e[0], e[1], e[2], e[4], e[5],
                           e[7] if len(e) > 7 else None, e[8] if len(e) > 8 else None,
                           e[9] if len(e) > 9 else None, e[10] if len(e) > 10 else None) for e in rows]
            holding = [dict(j=q.j, code=str(px['codes'][q.j]), kind=q.kind, side=q.side,
                            shares=q.size, shares0=q.size0, mark=float(last(q.j, d - 1)),
                            pending=q.add_pending, trail_pending=q.trail_pending, entry_index=q.d0,
                            management=q.management, cap=q.cap, add_mult=q.add_mult) for q in pos.values()]
            fraction = rules.risk
            if prior_closed_feedback is not None:
                if prior_closed_feedback < 0:
                    fraction = rules.risk_low
                elif prior_closed_feedback > 0 and rules.risk_high > 0:
                    fraction = rules.risk_high
            if scale is not None and np.isfinite(scale[d]):
                fraction *= scale[d]
            if braked:
                fraction *= rules.dd_risk_mult
            previous_close = c[d - 1] if d > 0 else np.full(c.shape[1], np.nan)
            preplanned = plan(candidates, holding, previous_close, equity, cash, rules, fraction, year_new,
                              fill_stop_pct_by_kind=fill_stop_pct)
            preplanned['entry_trace'] = {(r['kind'], r['j']): r for r in preplanned['trace']
                                         if r['type'] == 'entry'}
            preplanned['add_trace'] = {r['j']: r for r in preplanned['trace'] if r['type'] == 'add'}
            if track is not None:
                track.setdefault('preopen_plans', []).append(dict(day=str(dates[d]), equity=float(equity),
                    cash=float(cash), fraction=float(fraction), orders=preplanned['trace'],
                    unreserved_gross=float(preplanned['unreserved_gross']),
                    unreserved_cash=preplanned['unreserved_cash']))
        for q in list(pos.values()):                # the open: a gap through the stop covers there
            opening = o[d, q.j]
            if (q.trail_pending or q.add_pending is not None) and (not np.isfinite(opening) or opening <= 0):
                continue
            if np.isfinite(opening) and (opening - live_stop(q, d)) * q.side <= 0:
                if q.add_pending is not None:
                    add_event(q, d, 'position_exit', opening)
                    if preopen and q.j in preplanned['add_trace']:
                        preplanned['add_trace'][q.j]['execution'] = 'position_exit'
                close_part(q, q.size, opening, d, 'gap_stop')
            elif q.trail_pending:
                if q.add_pending is not None:
                    add_event(q, d, 'position_exit', opening)
                    if preopen and q.j in preplanned['add_trace']:
                        preplanned['add_trace'][q.j]['execution'] = 'position_exit'
                close_part(q, q.size, opening, d, 'time_open' if q.time_pending else 'trail_open')
        for q in list(pos.values()):
            opening = o[d, q.j]
            if q.short_trim_pending and np.isfinite(opening) and opening > 0:
                q.short_trim_pending = False
                close_part(q, rules.short_trim_day_frac * q.size0, opening, d, 'day_trim_open')
        if rules.add_next_open:
            for q in sorted(pos.values(), key=lambda p: (p.d0, str(px['codes'][p.j]))):
                if q.add_pending is None:
                    continue
                opening = o[d, q.j]
                if preopen:
                    rec = preplanned['add_trace'][q.j]
                    fixed = preplanned['adds'].get(q.j)
                    if fixed is None:
                        status = 'preopen_not_submitted'
                    elif not np.isfinite(opening) or opening <= 0:
                        status = 'missing_open'
                    elif np.float32(opening) == np.float32(fixed['limit']):
                        status = 'precision_unknown'
                    elif opening > fixed['limit']:
                        status = 'preopen_limit_expired'
                    else:
                        if not add_pos(q, opening, d, early=True, fixed_shares=fixed['shares']):
                            raise AssertionError('reserved add was unexpectedly rejected')
                        status = 'preopen_filled'
                    rec['execution'] = status
                    if np.isfinite(opening):
                        rec.update(opening=float(opening), cash_after=float(cash))
                    if status == 'preopen_filled':
                        opening_equity = cash + sum(p.side * p.size * at_open(p.j, d) for p in pos.values())
                        rec.update(positions_after=len(pos),
                                   gross_after=float(gross_open(d) / opening_equity) if opening_equity > 0 else None)
                    add_event(q, d, status, opening)
                    q.add_pending = None
                    if (preopen_add_stop_gap and status == 'preopen_filled'
                            and (opening - q.stop) * q.side <= 0):
                        close_part(q, q.size, opening, d, 'add_stop_open')
                    continue
                if not np.isfinite(opening) or opening <= 0:
                    add_event(q, d, 'missing_open', opening)
                    continue
                if np.float32(opening) == np.float32(q.add_pending):
                    add_event(q, d, 'precision_unknown', opening)
                elif opening <= q.add_pending:
                    add_event(q, d, 'open_below_level', opening)
                else:
                    filled = add_pos(q, opening, d, early=True)
                    add_event(q, d, 'filled' if filled else 'budget_rejected', opening)
                q.add_pending = None
        tagged = [(intraday(e, d), e) for e in (entries[d] if d < len(entries) else [])]
        if placebo is not None:
            tagged = swap(tagged, d)
        early = [e for f, e in tagged if f]
        late = [e for f, e in tagged if not f]
        if early:                                   # filled during the day: the account as of the open
            take(early, d, cash + sum(q.side * q.size * at_open(q.j, d) for q in pos.values()), True)
        deferred_adds = []
        for q in list(pos.values()):
            j, s = q.j, q.side
            if preopen_entry_close_add and q.d0 == d:
                try_adds(q, d)
            if q.d0 == d and entry_close_stops and s > 0:
                hard = live_stop(q, d)
                if l[d, j] <= hard:
                    close_part(q, q.size, hard, d, 'stop_day0')
                elif c[d, j] < q.stop:
                    close_part(q, q.size, c[d, j], d, 'close_stop')
                continue
            if q.d0 == d and rules.entry_day_exit_signal:
                signal = sig_exit if s > 0 else sig_exit_s
                if signal is not None and signal[d, j] \
                        and (daily_close is None or daily_close[d]):
                    close_part(q, q.size, c[d, j], d, 'signal')
                continue
            if q.d0 == d or q.trail_pending or q.add_pending is not None or np.isnan(o[d, j]):
                continue
            if daily_tolerance is not None and s > 0:
                if l[d, j] <= q.disaster_stop:
                    close_part(q, q.size, q.disaster_stop, d, 'stop')
                else:
                    tolerance_manage(q, d)
                continue
            policy = q.management
            R = abs(q.fill - q.stop0)
            U = unit(q)
            if rules.breakeven_r and (o[d, j] - (q.fill + s * rules.breakeven_r * U)) * s >= 0:
                q.stop = max(q.stop, q.fill) if s > 0 else min(q.stop, q.fill)    # already beyond at the open
            trims = policy.trims if s > 0 or rules.short_trims is None else rules.short_trims
            levels = [q.fill + s * k * U for k in trims[q.trims:]]
            worst, best = (l[d, j], h[d, j]) if s > 0 else (h[d, j], l[d, j])
            stop_now = live_stop(q, d)
            if (worst - stop_now) * s <= 0:
                while levels and (o[d, j] - levels[0]) * s >= 0:
                    close_part(q, policy.trim_frac * q.size0, o[d, j], d, 'trim')
                    q.trims += 1
                    levels.pop(0)
                if targets and s < 0:
                    cover_targets(q, d, o[d, j])
                if j in pos:
                    close_part(q, q.size, slipped(q, stop_now, d), d, 'stop')
                continue
            while levels and (best - levels[0]) * s >= 0 and j in pos:
                px_ = max(o[d, j], levels[0]) if s > 0 else min(o[d, j], levels[0])
                close_part(q, policy.trim_frac * q.size0, px_, d, 'trim')
                q.trims += 1
                levels.pop(0)
            if targets and s < 0 and j in pos:
                cover_targets(q, d, l[d, j])
            if j not in pos:
                continue
            if rules.breakeven_r and (best - (q.fill + s * rules.breakeven_r * U)) * s >= 0:
                q.stop = max(q.stop, q.fill) if s > 0 else min(q.stop, q.fill)
            if daily_close is not None and not daily_close[d]:
                continue
            if close_window(q, d) and c[d, j] < (q.stop0 if rules.probe_hard_mult else q.stop):
                close_part(q, q.size, c[d, j], d, 'close_stop')
                continue
            deadline = rules.max_days if s > 0 else (rules.short_max_days or rules.max_days)
            if rules.max_days_next_open and deadline and session[d] - session[q.d0] >= deadline - 1:
                q.trail_pending = True
                q.trail_signal_day = d
                q.time_pending = True
                continue
            tr_ = trail3 if alt else (trail2 if trail2 is not None and q.trims else ema.get(policy.trail))
            if tr_ is not None and np.isfinite(tr_[d, j]):
                consecutive = q.trail_last_day == session[d]-1
                q.trail_last_day = session[d]
                if (c[d, j] - tr_[d, j]) * s > 0:
                    q.armed = True
                    q.trail_below = 0
                elif q.armed and not policy.stop_ema_only and (not policy.trail_strict or (c[d, j]-tr_[d, j])*s < 0):
                    q.trail_below = q.trail_below+1 if consecutive else 1
                    if q.trail_below >= policy.trail_confirm_days:
                        if policy.trail_next_open:
                            q.trail_pending = True
                            q.trail_signal_day = d
                        else:
                            close_part(q, q.size, c[d, j], d, 'trail')
                        continue
                else:
                    q.trail_below = 0
                if q.armed and policy.stop_ema_buffer >= 0:
                    level = tr_[d, j] * (1 - s * policy.stop_ema_buffer)
                    q.stop = max(q.stop, level) if s > 0 else min(q.stop, level)
            if sig_trim is not None and s > 0 and sig_trim[d, j] \
                    and (not rules.trim_signal_max or q.sig_trimmed < rules.trim_signal_max):
                q.sig_trimmed += 1
                close_part(q, (rules.trim_signal_frac or rules.trim_frac) * q.size0, c[d, j], d, 'signal_trim')
                if j not in pos:
                    continue
            if sig_trim2 is not None and s > 0 and not q.sig2_trimmed and sig_trim2[d, j]:
                q.sig2_trimmed = True
                close_part(q, rules.trim_signal2_frac * q.size0, c[d, j], d, 'signal_trim2')
                if j not in pos:
                    continue
            if rules.trim_day and s > 0 and not q.day_trimmed and session[d] - session[q.d0] == rules.trim_day:
                q.day_trimmed = True
                if not rules.trim_day_profit or c[d, j] > q.fill:
                    close_part(q, rules.trim_day_frac * q.size0, c[d, j], d, 'day_trim')
                    if j not in pos:
                        continue
                    if rules.trim_day_breakeven:
                        q.stop = max(q.stop, q.fill)
            if rules.short_trim_day and s < 0 and not q.day_trimmed                     and session[d] - session[q.d0] == rules.short_trim_day:
                q.day_trimmed = True
                if c[d, j] < q.fill:
                    if rules.short_trim_next_open:
                        q.short_trim_pending = True
                    else:
                        close_part(q, rules.short_trim_day_frac * q.size0, c[d, j], d, 'day_trim')
                    if j not in pos:
                        continue
            if rules.add_after_entries:
                deferred_adds.append(q)
            else:
                try_adds(q, d)
                switch_proof_trail(q, d)
            if rules.confirm_trail and s > 0 and not q.confirmed and c[d, j] > q.fill \
                    and c[d, j] >= q.fill+rules.confirm_close_r*R:
                q.confirmed, q.confirmed_day = True, d
                q.stop = max(q.stop, q.fill)
                q.management = replace(q.management, trail=rules.confirm_trail)
                q.armed, q.trail_below = True, 0
            if rules.reentry_days and s > 0 and (c[d, j] < ema['e9'][d, j] or h[d, j] >= q.fill+3*R):
                q.reentry_clean = False
            if sig_exit is not None and s > 0 and sig_exit[d, j]:
                close_part(q, q.size, c[d, j], d, 'signal')
                continue
            if sig_exit_s is not None and s < 0 and sig_exit_s[d, j]:
                close_part(q, q.size, c[d, j], d, 'signal')
                continue
            if rules.nft_days and session[d] - session[q.d0] == rules.nft_days and (c[d, j] - q.fill) * s < 0:
                close_part(q, q.size, c[d, j], d, 'no_follow')
                continue
            hold = rules.max_days if s > 0 else (rules.short_max_days or rules.max_days)
            if hold and session[d] - session[q.d0] >= hold:
                close_part(q, q.size, c[d, j], d, 'time')
        if daily_tolerance is not None:
            membership = daily_tolerance['groups'][d]
            held_groups = {membership[q.j] for q in pos.values() if q.side > 0 and q.j in membership}
            for group in sorted(held_groups):
                held = [q for q in pos.values() if q.side > 0 and membership.get(q.j) == group]
                def weakness(q):
                    strength = daily_tolerance['strength'][d, q.j]
                    return (q.confirmed, float(strength) if np.isfinite(strength) else -np.inf,
                            c[d, q.j]/q.fill, q.d0, str(px['codes'][q.j]))
                for q in sorted(held, key=weakness)[:-2]:
                    close_part(q, q.size, float(c[d, q.j]), d, 'theme_cap')
        if late:
            take(late, d, cash + value(d), False)
        if rules.reentry_days:
            retry_entries = []
            for j, (stopped, old_fill) in list(retries.items()):
                age = session[d]-session[stopped]
                if age > rules.reentry_days or j in pos:
                    del retries[j]
                    continue
                fill = c[d, j]
                if age <= 0 or not np.isfinite(fill) or fill <= old_fill:
                    continue
                # Consume the first reclaim even when the filter, stop or account rejects it (E10 convention).
                del retries[j]
                if rules.reentry_filter and not ema[rules.reentry_filter][d, j]:
                    continue
                adr = ema[rules.reentry_adr][d-1, j]
                if not np.isfinite(adr) or not np.isfinite(l[d, j]):
                    continue
                cap = min(.05, float(adr)/200.)
                if cap < .01:
                    continue
                stop = float(min(l[d, j], fill*.99))
                if (fill-stop)/fill > cap+1e-12:
                    stop = fill*(1-cap)
                retry_entries.append(((0,), j, 1, float(fill), float(stop), 'reentry_close', None))
            if retry_entries:
                take(retry_entries, d, cash + value(d), False)
        for q in deferred_adds:
            if pos.get(q.j) is q:
                try_adds(q, d)
                switch_proof_trail(q, d)
        for j, price in gap_moc_exits:
            if j not in pos:
                raise AssertionError('gap position vanished before the close')
            close_part(pos[j], pos[j].size, price, d, 'gap_moc')
        if rules.gross_close and (daily_close is None or daily_close[d]):
            for side_ in (-1, 1):
                for q in sorted([q for q in pos.values() if q.side == side_ and np.isfinite(c[d, q.j])],
                                key=lambda q: -q.size * c[d, q.j]):
                    eq_c = cash + value(d)
                    excess = gross(d) - rules.max_gross * eq_c
                    if excess <= 1e-12:
                        break
                    cost = rules.buy_cost if side_ < 0 else rules.sell_cost
                    x = excess / (1 - rules.max_gross * cost) * (1 + 1e-9)    # value to take off at this close
                    close_part(q, min(q.size, x / c[d, q.j]), c[d, q.j], d, 'gross')
        curve.append(cash + value(d))
        if track is not None:
            if daily_tolerance is not None:
                track.setdefault('tolerance_holdings', []).append(dict(day=str(dates[d]),
                    equity=float(curve[-1]), weekly_new=tol_week_new, feedback_braked=tol_braked,
                    holdings=[dict(code=str(px['codes'][q.j]), entry=str(dates[q.d0]), kind=q.kind,
                        confirmed=q.confirmed, adds=q.adds, trimmed=bool(q.sig_trimmed), stop=float(q.stop),
                        cap=q.cap, value=float(q.size*last(q.j, d)),
                        group=daily_tolerance['groups'][d].get(q.j)) for q in pos.values() if q.side > 0]))
            track.setdefault('gross', []).append(gross(d) / curve[-1] if curve[-1] > 0 else float('inf'))
            track.setdefault('open', []).append(len(pos))
            track.setdefault('new', []).append(new_all if (d + 1 >= d1 or session[d + 1] != session[d]) else None)
    if track is not None:
        track['new'] = [x for x in track.get('new', []) if x is not None]
        track['margin'] = margin_paid
    for q in list(pos.values()):                                    # mark open trades at the last close
        close_part(q, q.size, last(q.j, d1 - 1), d1 - 1, 'end')
    return np.array(curve), dates[d0:d1], trades


def stats(curve, dates, trades):
    curve = np.asarray(curve)
    if not len(curve):
        return {}
    years = max(len(curve) / 252, 1e-9)
    peak = np.maximum.accumulate(curve)
    r = np.array([t['r'] for t in trades]) if trades else np.zeros(0)
    ret = np.array([t['ret'] for t in trades]) if trades else np.zeros(0)
    win = ret > 0
    by_year = {}
    for y in sorted({str(d)[:4] for d in dates}):
        idx = np.flatnonzero(np.char.startswith(dates.astype(str), y))
        base = curve[idx[0] - 1] if idx[0] > 0 else 1.0
        by_year[y] = float(curve[idx[-1]] / base - 1)
    return dict(total=float(curve[-1] - 1), cagr=float(curve[-1] ** (1 / years) - 1),
                maxdd=float(np.max(1 - curve / peak)), trades=len(trades), per_year=len(trades) / years,
                win=float(win.mean()) if len(ret) else float('nan'),
                avg_win=float(ret[win].mean()) if win.any() else float('nan'),
                avg_loss=float(ret[~win].mean()) if (~win).any() else float('nan'),
                exp_r=float(r.mean()) if len(r) else float('nan'),
                days_win=float(np.mean([t['days'] for t in trades if t['ret'] > 0])) if win.any() else float('nan'),
                days_loss=float(np.mean([t['days'] for t in trades if t['ret'] <= 0])) if (~win).any() else float('nan'),
                by_year=by_year)


def placebo_rank(px, ema, rules, entries, start, end, pool, draws=100, seed=1):
    """Real total return vs the same entry stream with random names from `pool` on the same days."""
    real = simulate(px, ema, rules, entries, start, end)[0]
    rng = np.random.default_rng(seed)
    pl = np.array([simulate(px, ema, rules, entries, start, end, placebo=rng, pool=pool)[0][-1] - 1
                   for _ in range(draws)])
    tot = float(real[-1] - 1)
    return dict(real=tot, median=float(np.median(pl)), p90=float(np.percentile(pl, 90)),
                rank=float((pl < tot).mean()))
