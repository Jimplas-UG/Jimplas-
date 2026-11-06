"""Download public 1m futures klines (Sep+Oct 2026 monthly) -> npz per symbol. Parses CSV only."""
import json, urllib.request, zipfile, io, sys, os, csv, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
OUT=sys.argv[1]
info=json.load(urllib.request.urlopen('https://fapi.binance.com/fapi/v1/exchangeInfo',timeout=30))
syms=sorted(s['symbol'] for s in info['symbols'] if s.get('contractType')=='PERPETUAL' and s.get('quoteAsset')=='USDT')
print('symbols',len(syms),flush=True)
def get(sym,tag):
    u=f'https://data.binance.vision/data/futures/um/monthly/klines/{sym}/1m/{sym}-1m-{tag}.zip'
    for a in range(3):
        try:
            b=urllib.request.urlopen(u,timeout=60).read()
            z=zipfile.ZipFile(io.BytesIO(b)); n=z.namelist()[0]
            rows=[]
            for ln in z.read(n).decode().splitlines():
                p=ln.split(',')
                if not p[0].isdigit(): continue
                rows.append((int(p[0]),float(p[1]),float(p[2]),float(p[3]),float(p[4]),float(p[7])))
            return rows
        except urllib.error.HTTPError as e:
            if e.code==404: return []
        except Exception as e:
            time.sleep(1.5)
    return []
def one(sym):
    p=os.path.join(OUT,sym+'.npz')
    if os.path.exists(p): return 1
    r=get(sym,'2026-09')+get(sym,'2026-10')
    if len(r)<2000: return 0
    a=np.array(r,dtype=np.float64)
    np.savez_compressed(p,t=a[:,0].astype(np.int64),o=a[:,1],h=a[:,2],l=a[:,3],c=a[:,4],qv=a[:,5])
    return 1
ok=0
with ThreadPoolExecutor(8) as ex:
    for i,r in enumerate(ex.map(one,syms)):
        ok+=r
        if i%50==0: print(i,ok,flush=True)
print('DONE',ok,flush=True)
