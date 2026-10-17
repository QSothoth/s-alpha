"""Verify all real ETF accounting artifacts without choosing profitable variants."""
import argparse,json
from pathlib import Path
from .replay import VARIANTS

def read(p):return [json.loads(x) for x in p.read_text().splitlines()]
def main():
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args();results={}
    for v in VARIANTS:
        eq=read(a.run/f'{v}_equity.jsonl');fills=read(a.run/f'{v}_fills.jsonl');trades=read(a.run/f'{v}_trades.jsonl')
        actions=read(a.run/f'{v}_corporate_actions.jsonl');strict=read(a.run/f'{v}_strict_orders.jsonl')
        cash=1000000.
        for e in eq:
            daily=[f for f in fills if f['filled_at'][:10]==e['date']]
            assert sum(f['price']*f['quantity']+f['fee_assumption'] for f in daily if f['side']=='buy')<=cash+1e-6
            for f in daily:
                assert f['information_cutoff']<f['order_created_at']<f['filled_at']
                assert abs(f['cash_before']-cash)<1e-5
                cash+=f['price']*f['quantity']*(1 if f['side']=='sell' else -1)-f['fee_assumption']
                assert abs(f['cash_after']-cash)<1e-5
            assert abs(cash-e['cash'])<1e-5 and cash>=-1e-6
            assert e['positions']<=5
            assert abs(cash+sum(p['quantity']*p['mark'] for p in e['inventory_lots'].values())-e['equity'])<1e-5
        assert all(t['entry_date']<t['exit_date'] for t in trades)
        assert all(x['quantity']==0 and x['filled_at'] is None for x in strict)
        assert all(abs(x['cost_before']-x['cost_after'])<1e-8 and abs(x['economic_value_rounding_residual']-x['rounding_credit_marked_value'])<1e-7 for x in actions)
        closed_net=sum(t.get('pnl_after_modeled_costs',t['pnl']) for t in trades)
        open_unreal_net=sum(p['quantity']*p['mark']-p['cost']-p.get('entry_fee',0) for p in eq[-1]['inventory_lots'].values())
        accounting_residual=eq[-1]['equity']-1000000.-closed_net-open_unreal_net
        assert abs(accounting_residual)<1e-5
        results[v]=dict(accounting_residual=accounting_residual,passed=True,equity_rows=len(eq),fills=len(fills),round_trips=len(trades),corporate_actions=len(actions),strict_fills=0)
    print(json.dumps(results,indent=2))
if __name__=='__main__':main()
