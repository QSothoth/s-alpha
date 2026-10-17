"""Artifact invariants, separate from statistical results."""
import argparse,json
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args()
    events=[json.loads(x) for x in (a.run/'events.jsonl').read_text().splitlines()]
    orders=[json.loads(x) for x in (a.run/'orders.jsonl').read_text().splitlines()]
    audit=json.loads((a.run/'data_audit.json').read_text())
    assert audit['strict_final_cash']+audit['strict_inventory']==audit['strict_equity']
    assert all(o['filled_quantity']==0 and o['fees']==0 and not o['inventory_lots'] for o in orders)
    assert all(o['signal_at']<o['order_created_at'] and o['intended_session']>o['signal_at'][:10] for o in orders)
    completed=[e for e in events if e['status']=='completed']
    assert all(e['signal_date']<e['entry_date']<e['exit_date'] for e in completed)
    assert all(e['exit_information_cutoff'][:10]<e['exit_date'] for e in completed)
    assert all(abs(e['gross_price_markout']-(e['exit_price']/e['entry_price']-1))<1e-12 for e in completed)
    assert len({(e['variant'],e['setup_id']) for e in events})==len(events)
    result={'checks':'passed','events':len(events),'completed_events':len(completed),'orders':len(orders),'actual_fills':0}
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
