"""Verify HA cash fills against the actual two frozen cash-account paths."""
from dataclasses import replace
import gc
import json
from pathlib import Path

from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication import martin_continue_fo as fo
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication import martin_continue_gu as gu
from studies.trader_replication import martin_continue_gv as gv
from studies.trader_replication import martin_continue_gw as gw
from studies.trader_replication import martin_continue_ha as ha
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import nl_rules


def main():
    hp, gp, ip, wp = (du.REPORTS / f'strong_continue_{x}.json' for x in ('ha', 'gu', 'gi', 'gw'))
    h, g, i, w = (json.loads(p.read_text()) for p in (hp, gp, ip, wp))
    pinned = du.REPORTS / 'source_pins/system_pre_gz.py.txt'
    if (h['script_sha256'] != sha(Path(ha.__file__)) or h['system_sha256'] != sha(Path(system.__file__)) or
            g['script_sha256'] != sha(Path(gu.__file__)) or i['script_sha256'] != sha(Path(gi.__file__)) or
            w['script_sha256'] != sha(Path(gw.__file__)) or w['system_sha256'] != sha(pinned) or
            g['system_sha256'] != sha(pinned) or g['gi_sha256'] != sha(ip)):
        raise ValueError('reference source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    data_digest = dataset.digest()
    if any(x['dataset_digest'] != data_digest for x in (h, g, i, w)):
        raise ValueError('frozen data differs')
    cash_rows = {name: h['entries'][name] for name in ('C0:hit', 'C0:nohit')}
    cash_results = {name: w['results'][name] for name in cash_rows}
    core_counts, core_unknown = i['old_core_counts'], i['old_core_precision_unknown']
    precision_keys = {(r['day'], r['code'], r['kind']) for r in g['low_precision_unknown']}
    del h, g, i, w
    gc.collect()
    d = du.make_data(dataset)
    raw = [[e for e in row if e[2] > 0 and e[5] != 'list'] for row in d.reg]
    book, counts = dg.next_open(raw, d.A['open'], d.A['low'], d.days)
    book, unknown = fe.remove_precision_unknown(book, d.days, d.A['codes'])
    unknown = [r for r in unknown if panels.WINDOW[0] <= r[0] <= panels.WINDOW[1]]
    if counts != core_counts or unknown != core_unknown:
        raise AssertionError('core candidates differ')
    del d.fp, d.fwd, d.raw, raw
    gc.collect()
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'list', 'n1'})))
    results = {}
    for flag, suffix in ((True, 'hit'), (False, 'nohit')):
        selected, _ = gv.sensitive_book(book, d.days, d.A['codes'], precision_keys, flag)
        result = fo.account(d, selected, cash)
        name = 'C0:' + suffix
        if result != cash_results[name]:
            raise AssertionError('cash account differs: ' + name)
        px, ema = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, cash)
        _, _, trades = system.simulate(px, ema, cash, selected, *panels.WINDOW, audit=True)
        if digest(trades) != result['trades_digest']:
            raise AssertionError('cash trade digest differs')
        recorded = {(r['day'], r['code'], r['kind']): (r['fill'], r['stop']) for r in cash_rows[name]}
        actual = {(t['entry'], t['code'], t['kind']): (t['fill'], t['stop']) for t in trades}
        if recorded != actual or len(recorded) != len(trades):
            raise AssertionError('HA cash fill / stop mismatch: ' + name)
        results[name] = {'matched_entries': len(trades), 'trades_digest': digest(trades)}
    target = du.REPORTS / 'strong_continue_ha_check.json'
    out = {'dataset_digest': data_digest, 'ha_sha256': sha(hp), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'results': results}
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
