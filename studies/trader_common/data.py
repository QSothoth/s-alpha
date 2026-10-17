"""Strict public-release CSV adapter; no data retrieval, no credentials."""
import csv,gzip,hashlib,json
from pathlib import Path
from collections import defaultdict
import numpy as np

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()

def verify_manifest(root, relative_paths):
    root=Path(root)
    rows={line.split(maxsplit=1)[1].strip().lstrip('*'):line.split()[0] for line in (root/'CHECKSUMS.sha256').read_text().splitlines() if line.strip()}
    result=[]
    for p in relative_paths:
        actual=sha256(root/p)
        if rows.get(p)!=actual:raise ValueError('unverified or corrupt data: '+p)
        result.append({'path':p,'sha256':actual,'size':(root/p).stat().st_size})
    return result

def load_daily(path):
    out=defaultdict(list)
    with gzip.open(path,'rt') as f:
        for r in csv.DictReader(f):
            vals=[float(r[k]) for k in ('open','high','low','close','volume')]
            o,h,l,c,v=vals
            if not(0<l<=min(o,c)<=max(o,c)<=h and v>=0):raise ValueError('invalid OHLCV: '+str(r))
            out[r['code']].append((r['date'],*vals))
    result={}
    for s,rows in out.items():
        rows.sort()
        if len({r[0] for r in rows})!=len(rows):raise ValueError('duplicate day '+s)
        result[s]={'dates':np.array([r[0] for r in rows]),'values':np.array([r[1:] for r in rows])}
    return result

def sma(a,n):
    out=np.full(len(a),np.nan)
    if len(a)>=n:out[n-1:]=np.convolve(a,np.ones(n)/n,'valid')
    return out

def prior_extreme(a,n,fn=max):
    out=np.full(len(a),np.nan)
    for i in range(n,len(a)):out[i]=fn(a[i-n:i])
    return out

def features(values):
    o,h,l,c,v=values.T
    tr=np.maximum(h-l,np.maximum(abs(h-np.r_[c[0],c[:-1]]),abs(l-np.r_[c[0],c[:-1]])))
    atr=np.full(len(c),np.nan)
    if len(c)>=14:
        atr[13]=np.mean(tr[:14])
        for i in range(14,len(c)):atr[i]=(13*atr[i-1]+tr[i])/14
    d={'atr14':atr,'adr20':sma((h/l-1)*100,20),'dollar20':sma(c*v,20),'vol10':sma(v,10)}
    for n in (10,20,50,150,200):d['sma'+str(n)]=sma(c,n)
    d['high252']=prior_extreme(h,252);d['pivot10']=prior_extreme(h,10);d['stop10']=prior_extreme(l,10,min)-.01
    d['range10']=prior_extreme(h,10)-prior_extreme(l,10,min)
    d['range10_prev']=np.r_[np.full(10,np.nan),d['range10'][:-10]]
    d['vol10_prior']=np.r_[np.nan,d['vol10'][:-1]]
    d['vol10_older']=np.r_[np.full(11,np.nan),d['vol10'][:-11]]
    d['sma200_prev21']=np.r_[np.full(21,np.nan),d['sma200'][:-21]]
    return d
