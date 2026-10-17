"""Portable offline replay plan; --run executes only after all hashes match."""
import argparse,json,subprocess,sys,hashlib,shlex
from pathlib import Path

def commands(base):
    us=base/'salpha-champion-replication/data/trend-breakout-v1';market=base/'trader-data';sec=base/'sec-pit-fundamentals/pit_snapshots.jsonl';cn=base/'salpha-champion-replication/data'
    args=[['studies.trader_common.run_swing','--data',us],['studies.trader_common.run_minute','--eval-data',market/'opend_us_options_eval_v2','--raw-data',us,'--pit',sec],['studies.sean_ryan.run','--data',us/'us'],['studies.sean_ryan.locked_exits','--data',us/'us'],['studies.ryan_pierpont.run','--data',us/'us'],['studies.ryan_pierpont.run_growth','--data',us/'us','--fundamentals',sec],['studies.vibha_jha.run','--data',market/'public-daily'],['studies.vibha_jha.growth','--data',us/'us','--fundamentals',sec],['studies.goverdhan_gajjala.replay','--data',market/'opend_us_options_eval_v2/klines_1m.csv.gz'],['studies.goverdhan_gajjala.replay_smallcap','--data',market/'kaggle-v59'],['studies.goverdhan_gajjala.stress','--minute',market/'opend_us_options_eval_v2/klines_1m.csv.gz','--smallcap',market/'kaggle-v59'],['studies.erchi.replay','--data-root',cn,'--output','studies/erchi/reports/reproduced'],['studies.li666.screen','--data',cn/'trend-breakout-cn-pit-v1/hist/cn/bars_raw.csv.gz'],['studies.ty_rajnus.events','--data',market/'kaggle-v59'],['studies.zhang_qi.replay','--data-root',market/'china-etf','--output','studies/zhang_qi/reports/reproduced'],['studies.trader_common.benchmarks','--raw',us/'us/bars_raw.csv.gz','--eval-day',market/'opend_us_options_eval_v2/klines_day.csv.gz'],['studies.trader_common.check_fills','--raw',us/'us/bars_raw.csv.gz','--minute',market/'opend_us_options_eval_v2/klines_1m.csv.gz'],['studies.trader_common.causality_audit','--eval-data',market/'opend_us_options_eval_v2','--raw',us/'us/bars_raw.csv.gz','--pit',sec]]
    args.extend([['studies.zhang_qi.replay','--data-root',market/'china-etf','--output',f'studies/zhang_qi/reports/reproduced_cost{cost}','--cost-bps',cost] for cost in (10,30)])
    return [[sys.executable,'-m',*(str(x) for x in row)] for row in args]
def main():
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--run',action='store_true');a=p.parse_args();manifest=json.loads(Path(__file__).with_name('DATA_INPUTS.json').read_text())
    missing=[]
    for r in manifest['files']:
        f=a.data_root/r['relative_path']
        if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest()!=r['sha256']:missing.append(r['relative_path'])
    if missing:raise SystemExit('Missing/mismatched inputs: '+', '.join(missing))
    for cmd in commands(a.data_root):
        print(shlex.join(cmd),flush=True)
        if a.run:subprocess.run(cmd,check=True)
if __name__=='__main__':main()
