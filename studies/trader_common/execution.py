"""Causal long-only minute price-path simulator; not quote/order-book execution.
A completed entry bar has unknown high/low order: stop dominates target and
ambiguous fills are explicitly logged. Capacity is per bar, including exits.
"""
from dataclasses import dataclass, asdict
from datetime import datetime
from math import floor

@dataclass(frozen=True)
class Bar:
    symbol: str
    start: str
    end: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    def validate(self):
        assert self.start < self.end
        assert 0 < self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high
        assert self.volume >= 0

@dataclass(frozen=True)
class Order:
    client_id: str
    symbol: str
    created_at: str
    active_at: str
    expires_at: str
    trigger: float
    stop: float
    risk_fraction: float = .0025
    max_weight: float = .20
    target_r: float | None = None
    partial_fraction: float = 1.
    breakeven_after_partial: bool = False
    source_rule_id: str = ''
    hypothesis_id: str = ''
    order_type: str = 'stop'

class Engine:
    def __init__(self, cash=100000., cost_bps=10., per_share=.005, participation=.01):
        self.cash = cash
        self.initial_cash = cash
        self.cost_bps = cost_bps
        self.per_share = per_share
        self.participation = participation
        self.orders = {}
        self.seen = set()
        self.positions = {}
        self.pending_exits = {}
        self.events = []
        self.fills = []
        self.nav = []
        self.marks = {}
        self.last_end = {}
        self.last_batch_end = ''
        self._batch_equity = None
        self._batch_budget = None
        self._batch_risk = None
        self._held_at_start = set()
    def fee(self, price, qty):
        return qty * (price*self.cost_bps/10000+self.per_share)
    def equity(self):
        if self._batch_equity is not None: return self._batch_equity
        return self.cash + sum(p['qty']*self.marks.get(s,p['entry']) for s,p in self.positions.items())
    def submit(self, order):
        if order.client_id in self.seen:
            self.events.append({'event':'duplicate_rejected','client_id':order.client_id})
            return False
        if order.active_at < order.created_at or order.expires_at <= order.active_at:
            raise ValueError('noncausal order timestamps')
        if not 0 < order.stop < order.trigger or not 0 < order.partial_fraction <= 1:
            raise ValueError('invalid protective stop or partial fraction')
        self.seen.add(order.client_id)
        self.orders[order.client_id] = order
        self.events.append({'event':'order','order':asdict(order)})
        return True
    def cancel(self, client_id, at):
        if client_id in self.orders:
            if at < self.orders[client_id].created_at: raise ValueError('noncausal cancel')
            del self.orders[client_id]
            self.events.append({'event':'cancel_confirmed','client_id':client_id,'at':at})
    def exit_next_open(self, symbol, created_at, reason):
        self.pending_exits[symbol] = (created_at, reason)
    def _sell(self, symbol, price, qty, bar, reason, capacity):
        p=self.positions[symbol]
        qty=min(qty,p['qty'],capacity)
        if qty<=0: return 0
        fee=self.fee(price,qty)
        self.cash+=price*qty-fee
        p['qty']-=qty
        self.fills.append({'symbol':symbol,'at':bar.end if reason in ('stop','target','entry_bar_stop_pessimistic','target_then_breakeven_pessimistic') else bar.start,'fill_time_lower':bar.start,'fill_time_upper':bar.end,'intrabar_timestamp_unknown':reason in ('stop','target','entry_bar_stop_pessimistic','target_then_breakeven_pessimistic'),'bar_end':bar.end,'side':'SELL','price':price,'qty':qty,'fee':fee,'reason':reason,'client_id':p['id'],'entry':p['entry'],'initial_stop':p['initial_stop'],'pnl':(price-p['entry'])*qty-fee-p['entry_fee_per_share']*qty})
        if not p['qty']:
            del self.positions[symbol]
            self.pending_exits.pop(symbol,None)
        return qty
    def process_bar(self, bar):
        """Single-stream convenience. Concurrent symbols MUST use process_batch."""
        return self.process_batch([bar])
    def process_batch(self, bars):
        bars=sorted(bars,key=lambda b:b.symbol)
        if not bars:return
        start,end=bars[0].start,bars[0].end
        if any(b.start!=start or b.end!=end for b in bars):raise ValueError('batch interval mismatch')
        if len({b.symbol for b in bars})!=len(bars):raise ValueError('duplicate symbol in batch')
        if start<self.last_batch_end:raise ValueError('global time reversal: batch concurrent symbols together')
        self._held_at_start=set(self.positions)
        self._batch_equity=self.equity()
        self._batch_budget=self.cash
        self._batch_risk=sum(max(0,p['entry']-p['stop'])*p['qty'] for p in self.positions.values())
        # Conservative: no intrabar proceeds or released risk finances another same-bar order.
        for bar in bars:self._process_bar(bar)
        self._batch_equity=None;self._batch_budget=None;self._batch_risk=None
        self.last_batch_end=end
        return self.snapshot(end,self.marks)
    def _process_bar(self, bar):
        bar.validate()
        if self.last_end.get(bar.symbol,'') > bar.start: raise ValueError('overlapping/out-of-order bars')
        self.last_end[bar.symbol]=bar.end
        capacity=floor(bar.volume*self.participation)
        s=bar.symbol
        # Open-time decisions use last observed marks, never current close.
        if s in self.positions and s in self.pending_exits and self.pending_exits[s][0] <= bar.start:
            reason=self.pending_exits[s][1]
            sold=self._sell(s,bar.open,self.positions[s]['qty'],bar,reason,capacity)
            capacity-=sold
        # Existing protection is evaluated before new orders. Unresolved stop/target: stop first.
        if s in self.positions and s not in self.pending_exits:
            p=self.positions[s]
            hit_stop=bar.low<=p['stop']
            hit_target=p['target'] is not None and not p['target_done'] and bar.high>=p['target']
            if hit_stop:
                if hit_target:self.events.append({'event':'ambiguous_stop_target','symbol':s,'at':bar.end})
                sold=self._sell(s,min(bar.open,p['stop']),p['qty'],bar,'stop',capacity); capacity-=sold
                if s in self.positions:self.pending_exits[s]=(bar.end,'stop_capacity_carry')
            elif hit_target:
                if p.get('target_remaining') is None:p['target_remaining']=max(1,floor(p['qty']*p['fraction']))
                qty=p['target_remaining']
                sold=self._sell(s,max(bar.open,p['target']),qty,bar,'target',capacity);capacity-=sold
                if s in self.positions:
                    # Partial target completion recorded only once full requested lot sold.
                    p=self.positions[s]
                    p['target_remaining']-=sold
                    p['target_done']=p['target_remaining']==0
                    if p['target_done'] and p['breakeven']:
                        p['stop']=max(p['stop'],p['entry'])
                        if bar.low<=p['stop']:
                            self.events.append({'event':'ambiguous_target_breakeven','symbol':s,'at':bar.end})
                            sold=self._sell(s,p['stop'],p['qty'],bar,'target_then_breakeven_pessimistic',capacity);capacity-=sold
                            if s in self.positions:self.pending_exits[s]=(bar.end,'stop_capacity_carry')
        for key,o in list(self.orders.items()):
            if o.symbol != s: continue
            if bar.start>=o.expires_at:
                self.cancel(key,bar.start);continue
            if bar.start<o.active_at or bar.start<o.created_at or s in self.positions or s in self._held_at_start: continue
            price=bar.open if o.order_type=='market' else max(bar.open,o.trigger)
            risk=price-o.stop
            if risk<=0:
                self.events.append({'event':'gap_below_stop_rejected','client_id':key,'at':bar.start});del self.orders[key];continue
            eq=self.equity()
            open_risk=self._batch_risk
            risk_cash=min(eq*o.risk_fraction,max(0,eq*.01-open_risk))
            requested_qty=floor(min(risk_cash/risk,eq*o.max_weight/price,min(self.cash,self._batch_budget)/(price+price*self.cost_bps/10000+self.per_share)))
            self._batch_budget-=requested_qty*(price+price*self.cost_bps/10000+self.per_share)
            self._batch_risk+=requested_qty*risk
            if o.order_type=='stop' and bar.high<o.trigger:continue
            qty=min(requested_qty,capacity)
            self.events.append({'event':'capacity_bound','client_id':key,'requested_qty_known_at_open':requested_qty,'filled_qty_ex_post_bar_volume_bound':qty,'known_fill_at':bar.end})
            del self.orders[key] # IOC remainder cancels
            if qty<=0:
                self.events.append({'event':'risk_or_cash_rejected','client_id':key,'at':bar.start});continue
            fee=self.fee(price,qty);self.cash-=price*qty+fee;capacity-=qty
            self.positions[s]={'id':key,'entry':price,'qty':qty,'stop':o.stop,'initial_stop':o.stop,'entry_fee_per_share':fee/qty,'target':None if o.target_r is None else price+o.target_r*risk,'target_done':False,'fraction':o.partial_fraction,'breakeven':o.breakeven_after_partial}
            self.fills.append({'symbol':s,'at':bar.end if o.order_type=='stop' and bar.open<o.trigger else bar.start,'fill_time_lower':bar.start,'fill_time_upper':bar.end,'bar_end':bar.end,'side':'BUY','price':price,'qty':qty,'requested_qty':requested_qty,'fill_capacity_known_at':bar.end,'fee':fee,'reason':'next_open_market' if o.order_type=='market' else 'resting_stop_buy','client_id':key,'initial_stop':o.stop,'planned_risk':qty*risk,'intrabar_timestamp_unknown':o.order_type=='stop' and bar.open<o.trigger})
            # Do not use final entry-bar low in eligibility. After fill, conservative stop stress.
            if bar.low<=o.stop:
                self.events.append({'event':'entry_stop' if o.order_type=='market' or bar.open>=o.trigger else 'ambiguous_entry_stop','symbol':s,'at':bar.end,'optimistic_bound':'market/open entries have known entry before intrabar low; stop-buy may survive if low preceded trigger','pessimistic_policy':'stop after entry'})
                sold=self._sell(s,min(price,o.stop),qty,bar,'entry_bar_stop_pessimistic',capacity);capacity-=sold
                if s in self.positions:self.pending_exits[s]=(bar.end,'stop_capacity_carry')
        self.marks[s]=bar.close

    def snapshot(self, at, marks):
        self.marks.update(marks)
        equity=self.equity()
        self.nav.append({'at':at,'cash':self.cash,'market_value':equity-self.cash,'equity':equity,'positions':len(self.positions),'max_position_weight':max((p['qty']*self.marks.get(s,p['entry'])/equity for s,p in self.positions.items()),default=0),'exposure':(equity-self.cash)/equity if equity else 0})
        assert self.cash>=-1e-7
        assert all(p['qty']>0 and isinstance(p['qty'],int) for p in self.positions.values())
        return self.nav[-1]
