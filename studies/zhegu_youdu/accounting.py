"""Conversion inventory accounting; no price-arbitrage claim."""
import math

def convert(bond_face, conversion_price, credited_at, sellable_at):
    if conversion_price<=0 or bond_face<0 or sellable_at<credited_at:raise ValueError('invalid conversion')
    shares=math.floor(bond_face/conversion_price)
    return {'shares':shares,'fractional_face':bond_face-shares*conversion_price,'credited_at':credited_at,'sellable_at':sellable_at}

def can_sell(lot,at):
    return at>=lot['sellable_at']

def flow_neutral_pnl(start,end,deposits=0,withdrawals=0):
    return end-start-deposits+withdrawals
