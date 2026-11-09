"""Read-only board smoke: existing data only, workspace outputs, no refresh or publishing."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import sys
from unittest.mock import patch

import numpy as np

from studies import trader_data as TD
from studies.trader_data import panel as TP, supplemental as SP
from studies.trader_screens import board, intraday, scan
from . import ie47_e1 as M
from .ie47_audit import WORK, progress, write

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = WORK.parent/'e1_board_smoke.json'


def offline():
    def audit(event, values):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo'):
            raise PermissionError('E1 smoke uses existing data only; network disabled')
        if event == 'open' and not isinstance(values[0], int):
            flags = values[2]
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if not Path(os.fsdecode(values[0])).resolve().is_relative_to(ROOT):
                    raise PermissionError('E1 smoke cannot write outside the worktree')
    sys.addaudithook(audit)


def inventory(mode):
    ds = TD.dataset('us', mode)
    p = TP.build(ds, write_cache=False)
    day = str(p['days'][-1])
    qqq, source = SP.benchmark('US.QQQ', p['days'], mode)
    from studies.trader_screens.martin_candidates import leader_columns
    scope = leader_columns(p, len(p['days'])-1)
    option, option_sources = SP.option_volume(p['codes'], [day], mode)
    missing = [str(p['days'][t]) for t in np.flatnonzero(~np.isfinite(qqq))]
    return dict(mode=mode, last_day=day, stocks=len(p['codes']), scope=len(scope),
                qqq_missing=missing, qqq_sources=source,
                option_available=int(np.isfinite(option[0, scope]).sum()),
                option_missing=int((~np.isfinite(option[0, scope])).sum()),
                option_files=len(option_sources), daily_digest=p['digest'])


def run(mode):
    results = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
    real_build = TP.build
    def cached_load(market, mode=None, version=None, upto=None, **kwargs):
        return real_build(TD.dataset(market, mode, version), upto=upto, write_cache=False)
    def read_only_build(ds, upto=None, cache=True, write_cache=True):
        return real_build(ds, upto=upto, cache=cache, write_cache=False)
    with patch.object(TD, 'load', cached_load), patch.object(TP, 'build', read_only_build):
        if mode == 'provisional':
            now = intraday.market_now('us')
            live = inventory('live')
            # There is no stored full-universe US quote snapshot that can be replayed as today's snapshot.
            reason = ('当前盘前，未读取今日真实快照' if now.time() < intraday.OPEN_AT['us'] else
                      '当前已有缓存不包含今日完整盘中快照')
            if live['qqq_missing']:
                reason += f"；QQQ 缺 {len(live['qqq_missing'])} 个交易日，最新比较范围期权量覆盖 " \
                          f"{live['option_available']}/{live['scope']}"
            results[mode] = dict(status='skipped', reason=reason, now=now.isoformat(),
                                 input_inventory=live, network=False, published=False)
        else:
            info = inventory(mode)
            try:
                r = scan.run('us', mode=mode, only={'martin_luk_ie47'})
                if len(r['traders']) != 1:
                    raise AssertionError('registered IE47 version was not selected by the board')
                t = r['traders'][0]
                path = WORK/f'board_{mode}.json'
                write(path, r)
                (WORK/f'board_{mode}.md').write_text(board.render(r), encoding='utf-8')
                results[mode] = dict(status='passed', last_day=r['last_day'], check=t['check'],
                                     buys=t['buys'], sells=t['sells'], holdings=t['holdings'],
                                     inventory=info, output=str(path.relative_to(ROOT)),
                                     network=False, published=False)
            except (ValueError, RuntimeError) as error:
                results[mode] = dict(status='unavailable', error=str(error), inventory=info,
                                     network=False, published=False)
    write(OUTPUT, results)
    progress(mode+' smoke: '+results[mode]['status'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('frozen', 'live', 'provisional'))
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
    WORK.mkdir(exist_ok=True)
    offline()
    run(args.mode)
