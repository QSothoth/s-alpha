"""OR2's frozen cost and date-cluster statistics; no market-data access."""
from datetime import date
from math import floor, fsum, isfinite
import random


PRIMARY_COST = 0.001
STRESS_COST = 0.002
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20260925
HALF_SPLIT = '2022-06-01'


def _summary(rows):
    sessions = sum(row['n_sessions'] for row in rows)
    trades = sum(row['trades'] for row in rows)
    wins = sum(row['wins'] for row in rows)
    losses = sum(row['losses'] for row in rows)
    profit = fsum(row['profit'] for row in rows)
    loss = fsum(row['loss'] for row in rows)
    net = fsum(row['net_sum'] for row in rows)
    return {
        'n_sessions': sessions, 'n_dates': len(rows),
        'trading_days': sum(row['trades'] > 0 for row in rows),
        'signals': trades, 'trades': trades,
        'coverage': trades / sessions if sessions else 0.0,
        'gross_mean_bp': 10000 * fsum(row['gross_sum'] for row in rows) / trades if trades else None,
        'net_mean_bp': 10000 * net / trades if trades else None,
        'stress_mean_bp': 10000 * (net / trades - (STRESS_COST - PRIMARY_COST)) if trades else None,
        'wins': wins, 'losses': losses, 'zero_net_trades': trades - wins - losses,
        'win_rate': wins / trades if trades else None,
        'payoff_ratio': (profit / wins) / (loss / losses) if wins and losses else None,
        'profit_factor': profit / loss if loss else None,
        'gross_profit_bp': 10000 * profit, 'gross_loss_bp': 10000 * loss,
        'all_sessions_mean_bp': 10000 * net / sessions if sessions else None,
        'day_equal_mean_bp': 10000 * fsum(row['day_mean'] for row in rows) / len(rows) if rows else None,
    }


def _lower(values):
    """Sample fifth percentile, linearly interpolated at (n - 1) * 0.05."""
    if not values:
        return None
    values.sort()
    index = (len(values) - 1) * 0.05
    left = floor(index)
    return values[left] + (index - left) * (values[min(left + 1, len(values) - 1)] - values[left])


def _bootstrap(rows):
    rng = random.Random(BOOTSTRAP_SEED)
    trade_means, day_means = [], []
    if rows:
        # Each sampled date contributes its whole cross-section; no resampling matrix.
        for _ in range(BOOTSTRAP_DRAWS):
            net = daily = 0.0
            trades = 0
            for _ in range(len(rows)):
                row = rng.choice(rows)
                net += row['net_sum']
                trades += row['trades']
                daily += row['day_mean']
            if trades:
                trade_means.append(10000 * net / trades)
            day_means.append(10000 * daily / len(rows))
    return {
        'net_mean_lower_95_bp': _lower(trade_means),
        'day_equal_mean_lower_95_bp': _lower(day_means),
        'bootstrap': {
            'draws': BOOTSTRAP_DRAWS if rows else 0, 'seed': BOOTSTRAP_SEED,
            'unit': 'date', 'quantile': 0.05, 'quantile_method': 'linear_(n-1)*q',
            'undefined_trade_draws': len(day_means) - len(trade_means),
            'empty_trade_draw_policy': 'Undefined ratios are excluded; zero-trade dates remain in every date draw.',
        },
    }


def summarize_days(days):
    """Summarize eligible dates with n_sessions and gross fractional trade returns.

    Each date must have positive n_sessions and at most one return per session.
    OR2's complete-day execution requires every signal to fill; upstream execution
    errors must abort rather than disappear from this input. Thus signals = trades.
    None represents undefined ratios, never infinity in the serializable result.
    """
    rows = []
    for day in sorted(days):
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError('canonical ISO date required')
        item = days[day]
        sessions, returns = item['n_sessions'], item['returns']
        if type(sessions) is not int or sessions <= 0:
            raise ValueError('n_sessions must be a positive integer')
        if not isinstance(returns, list) or len(returns) > sessions:
            raise ValueError('returns must be a list with at most one trade per session')
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not isfinite(value) for value in returns):
            raise ValueError('finite gross return proportions required')
        net = [value - PRIMARY_COST for value in returns]
        net_sum = fsum(net)
        rows.append({'day': day, 'n_sessions': sessions, 'trades': len(net),
                     'gross_sum': fsum(returns), 'net_sum': net_sum,
                     'wins': sum(value > 0 for value in net), 'losses': sum(value < 0 for value in net),
                     'profit': fsum(value for value in net if value > 0),
                     'loss': -fsum(value for value in net if value < 0),
                     'day_mean': net_sum / sessions})
    summary = _summary(rows)
    summary.update(_bootstrap(rows))
    summary['halves'] = {
        'before_2022_06_01': _summary([row for row in rows if row['day'] < HALF_SPLIT]),
        'from_2022_06_01': _summary([row for row in rows if row['day'] >= HALF_SPLIT]),
    }
    summary['costs_bp'] = {'primary_round_trip': 10, 'stress_round_trip': 20}
    positive = lambda value: value is not None and value > 0
    profit_factor = summary['profit_factor']
    summary['gates'] = {
        'at_least_60_trading_days': summary['trading_days'] >= 60,
        'at_least_100_trades': summary['trades'] >= 100,
        'positive_net_mean': positive(summary['net_mean_bp']),
        'positive_trade_mean_lower_95': positive(summary['net_mean_lower_95_bp']),
        'profit_factor_at_least_1_2': (profit_factor >= 1.2 if profit_factor is not None
                                     else summary['gross_profit_bp'] > 0 and summary['gross_loss_bp'] == 0),
        'positive_early_half': positive(summary['halves']['before_2022_06_01']['net_mean_bp']),
        'positive_late_half': positive(summary['halves']['from_2022_06_01']['net_mean_bp']),
        'positive_stress_mean': positive(summary['stress_mean_bp']),
    }
    summary['selected_eligible'] = all(summary['gates'].values())
    return summary
