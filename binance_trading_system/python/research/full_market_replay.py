"""Full-market replay of short_first_v1 with switches for each audited behaviour.
Mirrors momentum_scanner state machine (live) on 1m bars. Research only."""
import os, glob, sys, json, numpy as np, numba as nb, datetime as D
T0=int(D.datetime(2026,9,1,tzinfo=D.timezone.utc).timestamp()*1000)
NB=int((D.datetime(2026,11,1,tzinfo=D.timezone.utc).timestamp()*1000-T0)//60000)
def load(dirp):
    syms=[];H=[];L=[];C=[];V=[];O=[]
    for f in sorted(glob.glob(os.path.join(dirp,'*.npz'))):
        z=np.load(f); t=z['t']; idx=((t-T0)//60000).astype(np.int64); m=(idx>=0)&(idx<NB); idx=idx[m]
        if len(idx)<3000: continue
        h=np.full(NB,np.nan);l=h.copy();c=h.copy();op=h.copy();v=np.zeros(NB)
        op[idx]=z['o'][m];h[idx]=z['h'][m];l[idx]=z['l'][m];c[idx]=z['c'][m];v[idx]=z['qv'][m]
        O.append(op);syms.append(os.path.basename(f)[:-4]);H.append(h);L.append(l);C.append(c)
        cs=np.concatenate([[0],np.cumsum(v)]); w=1440
        r=np.zeros(NB); r[w:]=cs[w+1:]-cs[1:NB-w+1]; r[:w]=cs[1:w+1]*(1440.0/np.maximum(1,np.arange(1,w+1))); V.append(r)
    return syms,np.array(H),np.array(L),np.array(C),np.array(V),np.array(O)

@nb.njit
def next_signal(h,l,c,o,start,end,stale,restart_bars,block_until):
    """first (bar,entry_px) >= start where a coin fires; entry at first 0.7% retrace touch."""
    state=0;peak=0.0;qual=0.0;pend=False
    for i in range(max(start,16),end):
        if restart_bars>0 and i%restart_bars==0:
            state=0;peak=0.0;qual=0.0;pend=False
        b=c[i-15];ci=c[i];hi=h[i]
        if not (b>0) or not (ci>0): continue
        ph=(hi-b)/b*100.0;pc=(ci-b)/b*100.0
        if state==0:
            if ph>=5.0:
                state=1;peak=hi;qual=ph
            else: continue
        if ph>=5.0 and ph>qual: qual=ph
        newhigh=hi>=peak
        if hi>peak: peak=hi
        floor=2.0
        if qual*0.45>floor: floor=qual*0.45
        level=peak*0.993
        low_after=l[i]
        if newhigh and ci>=o[i]: low_after=ci
        ep=-1.0
        if qual>=5.0 and low_after<=level:
            x=level
            if o[i]<x and not newhigh: x=o[i]
            pe=(x-b)/b*100.0;re=(peak-x)/peak*100.0
            if pe>=2.0 and pe>=floor and re<=12.0: ep=x
        if ep>0:
            if i>=block_until: return i,ep
            pend=True
        else:
            r=(peak-ci)/peak*100.0
            dead=pc<2.0 or r>12.0
            if stale:
                if pend and dead:
                    pend=False;qual=0.0
            else:
                if dead:
                    state=0;peak=0.0;qual=0.0;pend=False
    return -1,0.0

FEE=0.0004;SLIP=float(os.environ.get("SIM_SLIP","0.0005"))
@nb.njit
def trade(h,l,c,e,ep,end,l2m,defer_tp,part_loss,inv_slip,naked_only,tp_px_mode):
    """returns exit_i,reason,pnl,l1,l2,mae  reasons:0 TP 1 TRAIL 2 RESCUE 3 INV 4 SMART 5 PARTLOSS 6 MARK"""
    ent=ep*(1-SLIP); sq=250.0/ent; fees=250.0*(FEE+SLIP)
    tp=ent*0.975; trough=ent; maxadv=0.0
    l1=False;l2=False;l1e=0.0;l2e=0.0;l1q=0.0;l2q=0.0
    ex=-1;rs=6;xp=0.0
    for j in range(e+1,end):
        px=c[j];hi=h[j];lo=l[j]
        if not (px>0): continue
        adv=(hi-ent)/ent*100.0
        if adv>maxadv: maxadv=adv
        if lo<trough: trough=lo
        mfe=(ent-trough)/ent*100.0
        if not naked_only:
            if (not l1) and adv>=2.0 and adv<6.5:
                l1=True;l1e=ent*1.02*(1+SLIP);l1q=400.0/l1e;fees+=400.0*(FEE+SLIP)
            if (not l2) and l1 and adv>=4.0 and adv<6.5 and l2m>0:
                l2=True;l2e=ent*1.04*(1+SLIP);l2q=l2m*10.0/l2e;fees+=l2m*10.0*(FEE+SLIP)
        if l1:
            Q=l1q;S=l1e*l1q
            if l2:
                Q+=l2q;S+=l2e*l2q
            if Q>sq:
                xs=(S-ent*sq+1.0)/(Q-sq)
                if xs>ent and hi>=xs:
                    ex=j;rs=2;xp=xs;break
        if adv>=6.5:
            ex=j;rs=3;xp=ent*(1+(6.5+inv_slip)/100.0);break
        sp=(ent-px)*sq
        lp=0.0
        if l1: lp+=(px-l1e)*l1q
        if l2: lp+=(px-l2e)*l2q
        up=sp+lp
        if part_loss and up<=-100.0:
            ex=j;rs=5;xp=px;break
        if (l1 or l2) and sp<0 and lp>=-sp+1.0:
            ex=j;rs=2;xp=px;break
        hedged=l1 or l2
        if hedged and px<ent and up>=6.8:
            ex=j;rs=4;xp=px;break
        if lo<=tp:
            spt=(ent-tp)*sq;lpt=0.0
            if l1: lpt+=(tp-l1e)*l1q
            if l2: lpt+=(tp-l2e)*l2q
            if (not hedged) or (not defer_tp) or (spt+lpt>=0.8):
                ex=j;rs=0;xp=tp;break
        if hedged and mfe>=1.5 and px<ent and up>=0.8:
            if (px-trough)/trough*100.0>=1.5:
                ex=j;rs=1;xp=px;break
    if ex<0:
        ex=end-1
        while ex>e and not (c[ex]>0): ex-=1
        xp=c[ex];rs=6
    pnl=(ent-xp)*sq-250.0*(FEE+SLIP)
    if l1:
        pnl+=(xp-l1e)*l1q-400.0*(FEE+SLIP)
    if l2:
        pnl+=(xp-l2e)*l2q-l2m*10.0*(FEE+SLIP)
    return ex,rs,pnl-fees,(1 if l1 else 0),(1 if l2 else 0),maxadv

RN=['SHORT_TP','TRAIL','RESCUE','INVALIDATION','SMART_EXIT','PARTITION_LOSS','WINDOW_MARK']
def run(data,lo,hi,stale=True,restart_h=0,l2m=40.0,defer=False,part=False,inv_slip=1.0,min_vol=0.0,naked=False):
    syms,H,L,C,V,O=data
    n=len(syms); rb=restart_h*60
    def ns(s,a,blk): return next_signal(H[s],L[s],C[s],O[s],a,hi,stale,rb,blk)
    nxt=[ns(s,lo,lo) for s in range(n)]
    t=lo;out=[]
    while True:
        best=-1;bi=1<<60;bs=-1e18
        for s in range(n):
            while nxt[s][0]>=0 and nxt[s][0]<t:
                nxt[s]=ns(s,t,t)
            i=nxt[s][0]
            if i<0: continue
            if min_vol>0 and V[s][i]<min_vol:
                nxt[s]=ns(s,i+1,i+1)
                continue
            b=C[s][i-15];sc=(H[s][i]-b)/b
            if i<bi or (i==bi and sc>bs): bi=i;best=s;bs=sc
        if best<0: break
        s=best
        ex,rs,p,a,b2,mae=trade(H[s],L[s],C[s],bi,nxt[s][1],hi,l2m,defer,part,inv_slip,naked,0)
        out.append((syms[s],bi,ex,rs,p,a,b2,mae))
        cd=(20 if rs==3 else 10 if rs in(2,5) else 5)
        t=ex+1
        nxt[s]=ns(s,ex+1,ex+cd)
    return out
def day(i): return (D.datetime.fromtimestamp((T0+i*60000)/1000,D.timezone.utc)).strftime('%Y-%m-%d')
def bar(s): return int((D.datetime.strptime(s,'%Y-%m-%d').replace(tzinfo=D.timezone.utc).timestamp()*1000-T0)//60000)
def stats(o):
    if not o: return dict(n=0,net=0)
    p=np.array([x[4] for x in o]); hedged=np.array([x[5]>0 for x in o])
    eq=np.cumsum(p); dd=(np.maximum.accumulate(eq)-eq).max()
    by={}
    for x in o:
        r=by.setdefault(RN[x[3]],[0,0.0]); r[0]+=1; r[1]+=x[4]
    return dict(n=len(o),net=round(float(p.sum()),2),win=round(float((p>0).mean()*100),1),avgw=round(float(p[p>0].mean()),2) if (p>0).any() else 0,avgl=round(float(p[p<=0].mean()),2) if (p<=0).any() else 0,worst=round(float(p.min()),2),dd=round(float(dd),2),naked_n=int((~hedged).sum()),naked=round(float(p[~hedged].sum()),2),hedged_n=int(hedged.sum()),hedged=round(float(p[hedged].sum()),2),by={k:(v[0],round(v[1],1)) for k,v in by.items()})
