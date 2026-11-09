"""FI: summarize FG's fixed within-setup random-account comparison."""
import json
from pathlib import Path

from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ff as ff
from studies.trader_replication import martin_continue_fg as fg
from studies.trader_replication.martin_continue_dq import sha


def main():
    root = du.REPORTS
    path = root / 'strong_continue_fg.json'
    data = json.loads(path.read_text())
    if data['script_sha256'] != sha(Path(fg.__file__)) or len(data['random']) != fg.DRAWS:
        raise ValueError('FG source or draw count differs')
    clean = [x for x in data['random'] if not x['precision_unknown']]
    out = {'fg_sha256': sha(path), 'script_sha256': sha(Path(__file__)), 'width': data['width'],
           'pool_difference_stock_days': data['pool_difference_stock_days'],
           'unknown_draws': len(data['random']) - len(clean),
           'all': ff.summarize(data['real'], data['random']), 'precision_known': ff.summarize(data['real'], clean)}
    target = root / 'strong_continue_fi.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
