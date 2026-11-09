"""Bounded, causal expression evaluation and training-only genetic search."""
from collections import OrderedDict
import warnings

import numpy as np

WINDOWS = (1, 2, 3, 5, 10, 20, 50, 100, 250)
FIELDS = ('o', 'h', 'l', 'c', 'v', 't', 'qqq', 'iv', 'hv', 'option_volume',
          'call_volume', 'put_volume', 'option_open_interest',
          'call_open_interest', 'put_open_interest')
BINARY = ('add', 'sub', 'mul', 'div')
WINDOWED = ('lag', 'diff', 'mean', 'high', 'low', 'std', 'ema')
UNARY = ('neg', 'adr', 'history250', 'pool') + WINDOWED


def freeze(value):
    return tuple(freeze(x) if isinstance(x, (list, tuple)) else x for x in value)


def size(tree):
    return 1 + sum(size(x) for x in tree[1:] if isinstance(x, tuple))


def depth(tree):
    return max((1 + depth(x) for x in tree[1:] if isinstance(x, tuple)), default=0)


def valid(tree):
    if size(tree) > 7 or depth(tree) > 3:
        return False
    op = tree[0]
    if op == 'field':
        return len(tree) == 2 and tree[1] in FIELDS
    if op in BINARY:
        return len(tree) == 3 and all(isinstance(x, tuple) and valid(x) for x in tree[1:])
    if op in WINDOWED:
        return len(tree) == 3 and tree[1] in WINDOWS and valid(tree[2])
    return op in UNARY and len(tree) == 2 and valid(tree[1])


def expression(tree):
    op = tree[0]
    if op == 'field':
        return tree[1]
    if op in BINARY:
        sign = dict(add='+', sub='-', mul='*', div='/')[op]
        return '(' + expression(tree[1]) + sign + expression(tree[2]) + ')'
    if op in WINDOWED:
        return op + '(' + expression(tree[2]) + ',' + str(tree[1]) + ')'
    return op + '(' + expression(tree[1]) + ')'


def percentile(values, groups):
    """Average ranks, independently within each group, without a pair matrix."""
    values = np.asarray(values)
    out = np.full(len(values), np.nan, np.float32)
    good = np.flatnonzero(np.isfinite(values))
    if not len(good):
        return out
    order = good[np.lexsort((values[good], groups[good]))]
    v, g = values[order], groups[order]
    starts = np.r_[0, np.flatnonzero((v[1:] != v[:-1]) | (g[1:] != g[:-1])) + 1]
    stops = np.r_[starts[1:], len(order)]
    counts = np.bincount(g, minlength=int(np.max(groups)) + 1)
    offsets = np.r_[0, counts.cumsum()[:-1]]
    out[order] = np.repeat((starts + stops - 1) / 2, stops - starts) - offsets[g]
    out[order] /= np.maximum(counts[g] - 1, 1)
    out[order[counts[g] == 1]] = .5
    return out


def rolling(x, window, op):
    if op in ('high', 'low'):
        padded = np.pad(x, ((0, 0), (window - 1, 0)), constant_values=np.nan)
        view = np.lib.stride_tricks.sliding_window_view(padded, window, axis=1)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            return (np.nanmax if op == 'high' else np.nanmin)(view, axis=-1)
    finite = np.isfinite(x)
    count = np.pad(np.cumsum(finite, axis=1), ((0, 0), (1, 0)))
    total = np.pad(np.cumsum(np.where(finite, x, 0), axis=1, dtype=float), ((0, 0), (1, 0)))
    right = np.arange(1, x.shape[1] + 1)
    left = np.maximum(right - window, 0)
    n = count[:, right] - count[:, left]
    mean = np.divide(total[:, right] - total[:, left], n,
                     out=np.full(x.shape, np.nan), where=n > 0)
    if op == 'mean':
        return mean
    square = np.pad(np.cumsum(np.where(finite, x.astype(float) ** 2, 0), axis=1), ((0, 0), (1, 0)))
    moment = np.divide(square[:, right] - square[:, left], n,
                       out=np.full(x.shape, np.nan), where=n > 0)
    return np.sqrt(np.maximum(moment - mean ** 2, 0))


def time_operation(op, x, window=None):
    if op == 'neg':
        return -x
    if op in ('lag', 'diff'):
        lag = np.full_like(x, np.nan)
        if window < x.shape[1]:
            lag[:, window:] = x[:, :-window]
        return lag if op == 'lag' else x - lag
    if op in ('mean', 'high', 'low', 'std'):
        return rolling(x, window, op)
    if op == 'ema':
        result = np.full_like(x, np.nan)
        state = np.full(x.shape[0], np.nan)
        alpha = 2 / (window + 1)
        for t in range(x.shape[1]):
            finite = np.isfinite(x[:, t])
            state[finite] = np.where(np.isfinite(state[finite]),
                                     state[finite] + alpha * (x[finite, t] - state[finite]), x[finite, t])
            result[:, t] = state
        return result
    if op == 'history250':
        result = np.full_like(x, np.nan)
        for t in range(x.shape[1]):
            a = x[:, max(0, t - 249):t + 1]
            value = x[:, t, None]
            n = np.isfinite(a).sum(1)
            less = (a < value).sum(1)
            equal = (a == value).sum(1)
            rank = (less + (equal - 1) / 2) / np.maximum(n - 1, 1)
            result[:, t] = np.where(np.isfinite(value[:, 0]), np.where(n == 1, .5, rank), np.nan)
        return result
    raise ValueError(op)


class Engine:
    def __init__(self, fields, stock_rows, time_rows, groups):
        self.fields = fields
        self.stock_rows, self.time_rows, self.groups = stock_rows, time_rows, groups
        self.full_cache, self.column_cache = OrderedDict(), OrderedDict()
        self.shape = fields['c'].shape
        self.adr = rolling(fields['h'] / fields['l'] - 1, 20, 'mean')

    @staticmethod
    def remember(cache, key, value, limit):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)
        return value

    def panel(self, tree):
        if tree in self.full_cache:
            self.full_cache.move_to_end(tree)
            return self.full_cache[tree]
        op = tree[0]
        if op == 'field':
            return self.fields[tree[1]]
        if op in BINARY:
            a, b = self.panel(tree[1]), self.panel(tree[2])
            with np.errstate(all='ignore'):
                if op == 'add':
                    value = a + b
                elif op == 'sub':
                    value = a - b
                elif op == 'mul':
                    value = a * b
                else:
                    value = np.divide(a, b, out=np.full(self.shape, np.nan, np.float32), where=abs(b) > 1e-12)
        else:
            a = self.panel(tree[-1])
            if op == 'pool':
                value = np.full(self.shape, np.nan, np.float32)
                value[self.stock_rows, self.time_rows] = percentile(a[self.stock_rows, self.time_rows], self.groups)
            elif op == 'adr':
                value = np.divide(a, self.adr, out=np.full(self.shape, np.nan), where=abs(self.adr) > 1e-12)
            else:
                value = time_operation(op, a, tree[1] if op in WINDOWED else None)
        value = np.clip(value, -1e12, 1e12).astype(np.float32)
        value[~np.isfinite(value)] = np.nan
        return self.remember(self.full_cache, tree, value, 24)

    def column(self, tree):
        if tree in self.column_cache:
            self.column_cache.move_to_end(tree)
            return self.column_cache[tree]
        value = self.panel(tree)[self.stock_rows, self.time_rows]
        return self.remember(self.column_cache, tree,
                             np.nan_to_num(percentile(value, self.groups), nan=.5), 256)


def random_tree(rng, remaining=3):
    if remaining == 0 or rng.random() < .35:
        return ('field', FIELDS[int(rng.integers(len(FIELDS)))])
    op = (BINARY if rng.random() < .4 else UNARY)
    op = op[int(rng.integers(len(op)))]
    if op in BINARY:
        return (op, random_tree(rng, remaining - 1), random_tree(rng, remaining - 1))
    if op in WINDOWED:
        return (op, WINDOWS[int(rng.integers(len(WINDOWS)))], random_tree(rng, remaining - 1))
    return (op, random_tree(rng, remaining - 1))


def locations(tree, prefix=()):
    result = [prefix]
    for i, value in enumerate(tree):
        if isinstance(value, tuple):
            result.extend(locations(value, prefix + (i,)))
    return result


def subtree(tree, path):
    for i in path:
        tree = tree[i]
    return tree


def replace(tree, path, value):
    if not path:
        return value
    result = list(tree)
    result[path[0]] = replace(result[path[0]], path[1:], value)
    return tuple(result)


def fitness(column, targets, tree):
    means = []
    for records in targets.values():
        means.append(float(np.mean([np.mean(column[q]) if len(q) else .5 for q in records])))
    return min(means, default=.5) - .002 * size(tree)


def diverse(engine, candidates, targets, rows, limit=50):
    scored = sorted(((fitness(engine.column(t), targets, t), t) for t in set(candidates)),
                    key=lambda v: (-v[0], size(v[1]), expression(v[1])))
    result, representatives = [], []
    for value, tree in scored:
        x = percentile(engine.column(tree)[rows], np.zeros(len(rows), int)).astype(float)
        x -= x.mean()
        norm = np.linalg.norm(x)
        if not norm:
            if any(v is None for v in representatives):
                continue
            standardized = None
        else:
            standardized = x / norm
            if any(v is not None and float(v @ standardized) > .7 for v in representatives):
                continue
        result.append((value, tree))
        representatives.append(standardized)
        if len(result) == limit:
            break
    return result


def evolve(engine, targets, rows, seed, checkpoint=None, save=None, progress=None):
    rng = np.random.default_rng(seed)
    if checkpoint is not None:
        population = [freeze(t) for t in checkpoint['population']]
        rng.bit_generator.state = checkpoint['rng']
        start = checkpoint['generation'] + 1
        history = checkpoint['history']
    else:
        population = [('field', field) for field in FIELDS]
        start, history = 0, []
    ranked = []
    for generation in range(start, 20):
        proposals = list(population[:5] if generation else population)
        attempts = 0
        while len(set(proposals)) < 50 and attempts < 1000:
            attempts += 1
            if not generation:
                child = random_tree(rng)
            else:
                def parent():
                    indices = rng.integers(len(population), size=3)
                    return population[int(np.min(indices))]
                child = parent()
                draw = rng.random()
                paths = locations(child)
                where = paths[int(rng.integers(len(paths)))]
                if draw < .6:
                    other = parent()
                    paths = locations(other)
                    child = replace(child, where, subtree(other, paths[int(rng.integers(len(paths)))]))
                elif draw < .9:
                    child = replace(child, where, random_tree(rng, 3 - len(where)))
            if valid(child):
                proposals.append(child)
        ranked = diverse(engine, proposals, targets, rows)
        population = [tree for value, tree in ranked]
        row = dict(generation=generation, best=ranked[0][0], formula=expression(population[0]),
                   population=len(population), proposals=len(set(proposals)), attempts=attempts)
        history.append(row)
        if progress:
            progress(row)
        if save:
            save(dict(generation=generation, population=population, rng=rng.bit_generator.state, history=history))
    if not ranked:
        ranked = diverse(engine, population, targets, rows)
    return dict(formulas=[t for v, t in ranked[:5]], fitness=[v for v, t in ranked[:5]], history=history)
