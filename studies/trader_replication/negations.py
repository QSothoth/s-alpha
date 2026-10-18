"""The negation register of a trader study (skills/trader-replication METHOD_CN section 0): every candidate a round
did not carry, with the configuration the rest of the system had at the time, so that a negation can be retested
once the rest changes.

Rows live in studies/<id>/notes/NEGATIONS.json (written by study.Study.round, or by hand for first-stage rounds):
round, stage, candidate, change (what the candidate altered), base (report, key), chosen, reason, objective,
evidence, base_config.  A row is stale when any configuration key the candidate did not change differs between its
base_config and the current configuration: the negation was made in a context that no longer holds.
"""
from __future__ import annotations

import json
from pathlib import Path


def load(path):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def add(path, row):
    """Append (or replace the same round + candidate) and keep the file sorted by round."""
    path = Path(path)
    rows = [r for r in load(path) if (r['round'], r['candidate']) != (row['round'], row['candidate'])]
    rows.append(row)
    rows.sort(key=lambda r: (int(''.join(c for c in r['round'] if c.isdigit()) or 0), r['round'], r['candidate']))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=float), encoding='utf-8')
    return rows


def changed_keys(old, new, ignore=()):
    """Top-level keys (and one level into dicts) whose values differ, except those in `ignore`."""
    out = []
    for k in sorted(set(old) | set(new)):
        if k in ignore:
            continue
        a, b = old.get(k), new.get(k)
        if isinstance(a, dict) or isinstance(b, dict):
            a, b = a or {}, b or {}
            out += [f'{k}.{s}' for s in sorted(set(a) | set(b)) if a.get(s) != b.get(s)]
        elif a != b:
            out.append(k)
    return out


def stale(path, current):
    """Rows whose context changed: some key the candidate did not touch differs from `current`."""
    out = []
    for r in load(path):
        change = r.get('change', {})

        def touched(key):
            top, _, sub = key.partition('.')
            if top not in change:
                return False
            return not sub or not isinstance(change[top], dict) or sub in change[top]
        diff = [k for k in changed_keys(r.get('base_config', {}), current) if not touched(k)]
        if diff and r.get('status') != 'retested':
            out.append(dict(r, changed=diff))
    return out


def render(path, title):
    """A Markdown table of the register next to the JSON."""
    rows = load(path)
    lines = [f'# {title} 否定登记表', '', '每个没被带入的候选一行（自动写入）；“当时的配置”一列是那一轮的基础配置报告。下游大改后，'
             '用 `negations` 动作列出依赖旧配置的行，在新配置上重测。', '',
             '| 轮次 | 环节 | 候选 | 改了什么 | 当时的配置 | 带入 | 否定依据 | 状态 |', '|---|---|---|---|---|---|---|---|']
    for r in rows:
        ch = json.dumps(r.get('change', {}), ensure_ascii=False)
        ev = r.get('evidence', {})
        tot = ev.get('total')
        why = r.get('reason', '') + (f"；全区间 {tot:+.0%}（带入 {ev.get('best_total', 0):+.0%}）" if tot is not None else '')
        lines.append(f"| {r['round']} | {r.get('stage', '')} | {r['candidate']} | `{ch}` | {':'.join(r.get('base', []))} | "
                     f"{r.get('chosen', '')} | {why} | {r.get('status', 'open')} |")
    out = Path(path).with_name('NEGATIONS_CN.md')
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return out
