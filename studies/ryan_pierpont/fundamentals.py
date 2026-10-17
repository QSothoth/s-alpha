"""Read strict SEC event snapshots; unknown remains distinct from failed growth."""
import json,bisect
from collections import defaultdict
from pathlib import Path
class SnapshotGate:
 def __init__(self,path):
  self.rows=defaultdict(list)
  for line in Path(path).read_text().splitlines():
   x=json.loads(line);self.rows[x['symbol']].append(x)
  for s in self.rows:self.rows[s].sort(key=lambda x:x['available_on_or_after'])
 def evaluate(self,symbol,date,both=True):
  xs=self.rows.get(symbol,[]);i=bisect.bisect_right([x['available_on_or_after'] for x in xs],date)-1
  if i<0:return {'status':'UNKNOWN_NO_PRIOR_SNAPSHOT','pass':False,'snapshot':None}
  x=xs[i];names=['revenue_quarter_yoy']+(['net_income_quarter_yoy'] if both else []);m={k:x['metrics'].get(k,{}) for k in names}
  ok=all(v.get('status')=='OK' for v in m.values())
  return {'status':('PASS' if all(v['value']>=.25 for v in m.values()) else 'FAIL_GROWTH_THRESHOLD') if ok else 'UNKNOWN_METRIC','pass':ok and all(v['value']>=.25 for v in m.values()),'snapshot':x['available_on_or_after'],'metrics':m}
