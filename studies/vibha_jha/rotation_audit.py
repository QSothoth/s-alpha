"""Real input overlap audit; no fabricated ETF-to-stock capital rotation."""
import csv,gzip,json,hashlib
from pathlib import Path

def main():
 etf=Path('data/trader-data/public-daily/xjcarter_TQQQ.csv');stocks=Path('data/salpha-champion-replication/data/trend-breakout-v1/us/bars_raw.csv.gz');sec=Path('data/sec-pit-fundamentals/pit_snapshots.jsonl')
 ds={r['Date'] for r in csv.DictReader(etf.open())};ss={r['date'] for r in csv.DictReader(gzip.open(stocks,'rt'))};fs={json.loads(r)['available_on_or_after'] for r in sec.read_text().splitlines()};common=sorted(ds&ss)
 r={'ETF_period':[min(ds),max(ds)],'stock_period':[min(ss),max(ss)],'SEC_snapshot_period':[min(fs),max(fs)],'ETF_stock_common_sessions':len(common),'status':'BLOCKED_NO_FULL_HISTORY_OVERLAP','actual_rotations_executed':0,'capital_double_counted':False,'why':'Old TQQQ/QQQ daily history ends2022; stock/SEC study starts2023. Recent TQQQ60session minute file does not close QQQ50day recovery warmup. Separate sleeve results cannot be added or called a combined account.','next_input':'actual TQQQ and QQQ daily/corporate-action history overlapping stock/PIT SEC window; freeze rotation trigger and reduction schedule before first combined PnL','files':{str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in [etf,stocks,sec]}}
 out=Path(__file__).parent/'reports/rotation_overlap_audit.json';out.write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
if __name__=='__main__':main()
