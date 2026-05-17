//+------------------------------------------------------------------+
//| BilshenzCore.mqh — logic aligned to myapp/engine (TS)            |
//| srEngine.replaySrBarByBar + signalEngine P1–P3 + wickEngine      |
//+------------------------------------------------------------------+
#ifndef __BILSHENZ_CORE_MQH__
#define __BILSHENZ_CORE_MQH__

struct BzSrSnap
  {
   double            immRes, immSup, flipSup, flipRes;
   double            nearestRes, nearestSup, prevNearestRes, prevNearestSup;
   double            r1,r2,r3,s1,s2,s3;
   bool              r1f,r2f,r3f,s1f,s2f,s3f;
  };

struct BzWick
  {
   double            range, body, uw, lw, br, uwr, lwr;
   bool              isDoji;
  };

struct BzSignals
  {
   bool              p1Buy,p1Sell,p2Buy,p2Sell,p3Buy,p3Sell;
   bool              anyBuy,anySell;
  };

//+------------------------------------------------------------------+
double BzPivotHighAt(const double &high[], int n, int conf, int L, int R)
  {
   int center = conf - R;
   if(center < L || center >= n - R) return EMPTY_VALUE;
   double pv = high[center];
   for(int k = center - L; k <= center + R; k++)
     {
      if(k != center && high[k] >= pv) return EMPTY_VALUE;
     }
   return pv;
  }
//+------------------------------------------------------------------+
double BzPivotLowAt(const double &low[], int n, int conf, int L, int R)
  {
   int center = conf - R;
   if(center < L || center >= n - R) return EMPTY_VALUE;
   double pv = low[center];
   for(int k = center - L; k <= center + R; k++)
     {
      if(k != center && low[k] <= pv) return EMPTY_VALUE;
     }
   return pv;
  }
//+------------------------------------------------------------------+
void BzPhUnshift(double &ph[], int &phn, double v, int maxN)
  {
   if(phn < maxN)
     {
      phn++;
      ArrayResize(ph, phn);
      for(int i = phn - 1; i > 0; i--) ph[i] = ph[i - 1];
      ph[0] = v;
     }
   else
     {
      ArrayResize(ph, maxN);
      phn = maxN;
      for(int i = maxN - 1; i > 0; i--) ph[i] = ph[i - 1];
      ph[0] = v;
     }
  }
//+------------------------------------------------------------------+
void BzPlUnshift(double &pl[], int &pln, double v, int maxN)
  {
   if(pln < maxN)
     {
      pln++;
      ArrayResize(pl, pln);
      for(int i = pln - 1; i > 0; i--) pl[i] = pl[i - 1];
      pl[0] = v;
     }
   else
     {
      ArrayResize(pl, maxN);
      pln = maxN;
      for(int i = maxN - 1; i > 0; i--) pl[i] = pl[i - 1];
      pl[0] = v;
     }
  }
//+------------------------------------------------------------------+
double BzFImmRes(const double &ph[], int phn, double close, double zone)
  {
   double r = EMPTY_VALUE;
   for(int i = 0; i < phn; i++)
     {
      double v = ph[i];
      if(v > close + zone)
        {
         if(r == EMPTY_VALUE || v < r) r = v;
        }
     }
   return r;
  }
//+------------------------------------------------------------------+
double BzFImmSup(const double &pl[], int pln, double close, double zone)
  {
   double s = EMPTY_VALUE;
   for(int i = 0; i < pln; i++)
     {
      double v = pl[i];
      if(v < close - zone)
        {
         if(s == EMPTY_VALUE || v > s) s = v;
        }
     }
   return s;
  }
//+------------------------------------------------------------------+
double BzNearestResStack(double r1, double r2, double r3, double close)
  {
   if(r1 != EMPTY_VALUE && r1 > close) return r1;
   if(r2 != EMPTY_VALUE && r2 > close) return r2;
   if(r3 != EMPTY_VALUE && r3 > close) return r3;
   return EMPTY_VALUE;
  }
//+------------------------------------------------------------------+
double BzNearestSupStack(double s1, double s2, double s3, double close)
  {
   if(s1 != EMPTY_VALUE && s1 < close) return s1;
   if(s2 != EMPTY_VALUE && s2 < close) return s2;
   if(s3 != EMPTY_VALUE && s3 < close) return s3;
   return EMPTY_VALUE;
  }
//+------------------------------------------------------------------+
// Pine: pre_london 19-23, london 02-06, new_york 07-12 (America/New_York).
// barTime: chart bar open (broker server time) — converted to GMT then NY offset.
double BzClampTp1(bool isBuy, double entry, double sl, double rawTp, double pip,
                  double minRewardPips, double maxRewardPips)
  {
   if(rawTp == EMPTY_VALUE || !MathIsValidNumber(rawTp)) return EMPTY_VALUE;
   double minRp = MathMax(1.0, minRewardPips) * pip;
   double maxRp = MathMax(minRp, maxRewardPips) * pip;
   if(isBuy)
     {
      double riskD = entry - sl;
      if(riskD <= 0) return EMPTY_VALUE;
      double tp = rawTp;
      if(tp <= entry) tp = entry + minRp;
      double rew = tp - entry;
      if(rew < minRp) tp = entry + minRp;
      else if(rew > maxRp) tp = entry + maxRp;
      return tp;
     }
   double riskD = sl - entry;
   if(riskD <= 0) return EMPTY_VALUE;
   double tp = rawTp;
   if(tp >= entry) tp = entry - minRp;
   double rew = entry - tp;
   if(rew < minRp) tp = entry - minRp;
   else if(rew > maxRp) tp = entry - maxRp;
   return tp;
  }
//+------------------------------------------------------------------+
bool BzInPineSessionNY(datetime barTimeServer)
  {
   datetime barGmt = barTimeServer - (TimeCurrent() - TimeGMT());
   MqlDateTime dt;
   TimeToStruct(barGmt, dt);
   int month = dt.mon;
   bool dst = (month > 3 && month < 11) || (month == 3 && dt.day >= 8) || (month == 11 && dt.day < 7);
   int nyOff = dst ? -4 : -5;
   TimeToStruct(barGmt + nyOff * 3600, dt);
   int mins = dt.hour * 60 + dt.min;
   bool preLondon = (mins >= 19 * 60 && mins < 23 * 60);
   bool london = (mins >= 2 * 60 && mins < 6 * 60);
   bool newYork = (mins >= 7 * 60 && mins < 12 * 60);
   return preLondon || london || newYork;
  }
//+------------------------------------------------------------------+
double BzFPoiRes(const double &ph[], int phn, double close, double zone, double imm)
  {
   double r = EMPTY_VALUE;
   for(int i = 0; i < phn; i++)
     {
      double v = ph[i];
      if(v > close + zone && (imm == EMPTY_VALUE || v > imm + zone))
        {
         if(r == EMPTY_VALUE || v < r) r = v;
        }
     }
   return r;
  }
//+------------------------------------------------------------------+
double BzFPoiSup(const double &pl[], int pln, double close, double zone, double imm)
  {
   double s = EMPTY_VALUE;
   for(int i = 0; i < pln; i++)
     {
      double v = pl[i];
      if(v < close - zone && (imm == EMPTY_VALUE || v < imm - zone))
        {
         if(s == EMPTY_VALUE || v > s) s = v;
        }
     }
   return s;
  }
//+------------------------------------------------------------------+
void BzWickAt(double o,double h,double l,double c, BzWick &w)
  {
   w.range = h - l;
   w.body = MathAbs(c - o);
   w.uw = h - MathMax(o, c);
   w.lw = MathMin(o, c) - l;
   if(w.range > 0)
     {
      w.br = w.body / w.range;
      w.uwr = w.uw / w.range;
      w.lwr = w.lw / w.range;
     }
   else
     {
      w.br = w.uwr = w.lwr = 0;
     }
   w.isDoji = (w.br < 0.1);
  }
//+------------------------------------------------------------------+
void BzEmaSeries(int period, const double &c[], int n, double &emaOut[])
  {
   ArrayResize(emaOut, n);
   ArrayInitialize(emaOut, EMPTY_VALUE);
   if(n < period) return;
   double sum = 0;
   for(int j = 0; j < period; j++) sum += c[j];
   double ema = sum / period;
   emaOut[period - 1] = ema;
   double k = 2.0 / (period + 1);
   for(int i = period; i < n; i++)
     {
      ema = c[i] * k + ema * (1.0 - k);
      emaOut[i] = ema;
     }
  }
//+------------------------------------------------------------------+
// OHLC chronological: index 0 oldest, n-1 newest
//+------------------------------------------------------------------+
void BzReplaySrBarByBar(const double &O[], const double &H[], const double &L[], const double &C[],
                        int n, int Lp, int Rp, int srMax, double zone, BzSrSnap &out[])
  {
   ArrayResize(out, n);
   for(int i = 0; i < n; i++)
     {
      out[i].immRes = out[i].immSup = out[i].flipSup = out[i].flipRes = EMPTY_VALUE;
      out[i].nearestRes = out[i].nearestSup = out[i].prevNearestRes = out[i].prevNearestSup = EMPTY_VALUE;
      out[i].r1 = out[i].r2 = out[i].r3 = out[i].s1 = out[i].s2 = out[i].s3 = EMPTY_VALUE;
      out[i].r1f = out[i].r2f = out[i].r3f = out[i].s1f = out[i].s2f = out[i].s3f = false;
     }

   double ph[];
   double pl[];
   int phn = 0, pln = 0;
   ArrayResize(ph, 0);
   ArrayResize(pl, 0);

   double flipSupLevel = EMPTY_VALUE;
   double flipResLevel = EMPTY_VALUE;
   bool r1Flipped = false, r2Flipped = false, r3Flipped = false;
   bool s1Flipped = false, s2Flipped = false, s3Flipped = false;

   int start = Lp + Rp;
   for(int conf = start; conf < n; conf++)
     {
      double sh = BzPivotHighAt(H, n, conf, Lp, Rp);
      if(sh != EMPTY_VALUE)
         BzPhUnshift(ph, phn, sh, srMax);
      double sl = BzPivotLowAt(L, n, conf, Lp, Rp);
      if(sl != EMPTY_VALUE)
         BzPlUnshift(pl, pln, sl, srMax);

      double cl = C[conf];
      double cl1 = (conf >= 1) ? C[conf - 1] : cl;

      for(int i = 0; i < phn; i++)
        {
         double v = ph[i];
         if(cl > v + zone && cl1 <= v + zone)
           {
            if(flipSupLevel == EMPTY_VALUE || MathAbs(v - flipSupLevel) > zone * 2.0)
               flipSupLevel = v;
           }
        }
      for(int i = 0; i < pln; i++)
        {
         double v = pl[i];
         if(cl < v - zone && cl1 >= v - zone)
           {
            if(flipResLevel == EMPTY_VALUE || MathAbs(v - flipResLevel) > zone * 2.0)
               flipResLevel = v;
           }
        }

      if(phn > 0 && cl > ph[0] + zone) r1Flipped = true;
      if(phn > 1 && cl > ph[1] + zone) r2Flipped = true;
      if(phn > 2 && cl > ph[2] + zone) r3Flipped = true;
      if(pln > 0 && cl < pl[0] - zone) s1Flipped = true;
      if(pln > 1 && cl < pl[1] - zone) s2Flipped = true;
      if(pln > 2 && cl < pl[2] - zone) s3Flipped = true;
      if(sh != EMPTY_VALUE) r1Flipped = false;
      if(sl != EMPTY_VALUE) s1Flipped = false;

      double r1v = (phn > 0) ? ph[0] : EMPTY_VALUE;
      double r2v = (phn > 1) ? ph[1] : EMPTY_VALUE;
      double r3v = (phn > 2) ? ph[2] : EMPTY_VALUE;
      double s1v = (pln > 0) ? pl[0] : EMPTY_VALUE;
      double s2v = (pln > 1) ? pl[1] : EMPTY_VALUE;
      double s3v = (pln > 2) ? pl[2] : EMPTY_VALUE;
      double prevCl = (conf >= 1) ? C[conf - 1] : cl;

      out[conf].immRes = BzFImmRes(ph, phn, cl, zone);
      out[conf].immSup = BzFImmSup(pl, pln, cl, zone);
      out[conf].nearestRes = BzNearestResStack(r1v, r2v, r3v, cl);
      out[conf].nearestSup = BzNearestSupStack(s1v, s2v, s3v, cl);
      out[conf].prevNearestRes = BzNearestResStack(r1v, r2v, r3v, prevCl);
      out[conf].prevNearestSup = BzNearestSupStack(s1v, s2v, s3v, prevCl);
      out[conf].flipSup = flipSupLevel;
      out[conf].flipRes = flipResLevel;
      out[conf].r1 = r1v;
      out[conf].r2 = r2v;
      out[conf].r3 = r3v;
      out[conf].s1 = s1v;
      out[conf].s2 = s2v;
      out[conf].s3 = s3v;
      out[conf].r1f = r1Flipped;
      out[conf].r2f = r2Flipped;
      out[conf].r3f = r3Flipped;
      out[conf].s1f = s1Flipped;
      out[conf].s2f = s2Flipped;
      out[conf].s3f = s3Flipped;
     }
  }
//+------------------------------------------------------------------+
int BzConsolidationCount(const double &O[], const double &H[], const double &L[], const double &C[],
                         int idx, double zoneLow, double zoneHigh, int lookback)
  {
   int count = 0;
   for(int i = 1; i <= lookback; i++)
     {
      int j = idx - i;
      if(j < 0) break;
      double barHi = MathMax(O[j], C[j]);
      double barLo = MathMin(O[j], C[j]);
      if(barHi <= zoneHigh && barLo >= zoneLow) count++;
     }
   return count;
  }
//+------------------------------------------------------------------+
int BzWickRejectionCount(const double &O[], const double &H[], const double &L[], const double &C[],
                         int idx, double zoneLow, double zoneHigh, int lookback)
  {
   int count = 0;
   for(int i = 1; i <= lookback; i++)
     {
      int j = idx - i;
      if(j < 0) break;
      double barHi = MathMax(O[j], C[j]);
      double barLo = MathMin(O[j], C[j]);
      double rng = H[j] - L[j];
      double uw = H[j] - barHi;
      double lw = barLo - L[j];
      bool inZone = (H[j] >= zoneLow && L[j] <= zoneHigh);
      if(inZone && rng > 0 && (uw / rng > 0.6 || lw / rng > 0.6)) count++;
     }
   return count;
  }
//+------------------------------------------------------------------+
void BzLeftSideScan(const double &O[], const double &H[], const double &L[], const double &C[],
                    int idx, double nearestRes, double nearestSup,
                    double close, double pip, double minPips,
                    bool &bullClean, bool &bearClean, bool &bullRangeOk, bool &bearRangeOk)
  {
   double distRes = (nearestRes == EMPTY_VALUE) ? 0 : (nearestRes - close) / pip;
   double distSup = (nearestSup == EMPTY_VALUE) ? 0 : (close - nearestSup) / pip;
   bullRangeOk = (nearestRes != EMPTY_VALUE && distRes >= minPips);
   bearRangeOk = (nearestSup != EMPTY_VALUE && distSup >= minPips);
   bullClean = false;
   bearClean = false;
   if(nearestRes != EMPTY_VALUE && bullRangeOk && idx >= 1)
     {
      double consolZone = 15 * pip;
      int cb = BzConsolidationCount(O, H, L, C, idx, close, close + consolZone, 20);
      int wb = BzWickRejectionCount(O, H, L, C, idx, close, nearestRes, 30);
      bullClean = (cb <= 5 && wb <= 3);
     }
   if(nearestSup != EMPTY_VALUE && bearRangeOk && idx >= 1)
     {
      double consolZone = 15 * pip;
      int cs = BzConsolidationCount(O, H, L, C, idx, close - consolZone, close, 20);
      int ws = BzWickRejectionCount(O, H, L, C, idx, nearestSup, close, 30);
      bearClean = (cs <= 5 && ws <= 3);
     }
  }
//+------------------------------------------------------------------+
bool BzBrokenBelow(const double &C[], int idx, double level, int lookback)
  {
   for(int i = 1; i <= lookback; i++)
     {
      int j = idx - i;
      if(j < 0) break;
      if(C[j] < level) return true;
     }
   return false;
  }
//+------------------------------------------------------------------+
bool BzBrokenAbove(const double &C[], int idx, double level, int lookback)
  {
   for(int i = 1; i <= lookback; i++)
     {
      int j = idx - i;
      if(j < 0) break;
      if(C[j] > level) return true;
     }
   return false;
  }
//+------------------------------------------------------------------+
void BzComputeSignalsAt(const double &O[], const double &H[], const double &L[], const double &C[],
                        int idx, const BzSrSnap &sr,
                        bool inSession, bool sessionGate, bool masterBlock,
                        bool liveGateBuy, bool liveGateSell,
                        bool histBullOk, bool histBearOk,
                        bool cfgShowHistory, bool chopZone,
                        bool bullRangeOk, bool bearRangeOk,
                        bool isBullish, bool isBearish,
                        bool riskAthBlock, bool spreadBlocked, bool dxyBlocksBuy, bool geoHigh,
                        bool maxTradesReached, bool newsActive, bool nfpBlackout,
                        bool enableP3,
                        BzSignals &sig)
  {
   sig.p1Buy = sig.p1Sell = sig.p2Buy = sig.p2Sell = sig.p3Buy = sig.p3Sell = false;
   sig.anyBuy = sig.anySell = false;
   if(idx < 1) return;

   BzWick w;
   BzWickAt(O[idx], H[idx], L[idx], C[idx], w);
   if(w.isDoji || !sessionGate || masterBlock) return;

   double o = O[idx], c = C[idx];
   double prevRes = sr.prevNearestRes;
   double prevSup = sr.prevNearestSup;

   double wickRatio = (w.range > 0) ? MathMax(w.uw, w.lw) / w.range : 0;

   // P1 — liquidity sweep wick
   if(prevSup != EMPTY_VALUE && (cfgShowHistory || (liveGateBuy && bullRangeOk && histBullOk)))
     {
      bool sweptBelow = (L[idx - 1] < prevSup) || (L[idx] < prevSup);
      bool closedAbove = (c > prevSup);
      bool hasLowWick = (wickRatio >= 0.6 && w.lw >= w.uw);
      bool biasOkBuy = !isBearish;
      bool jimplasBuy = (idx >= 1 && O[idx - 1] > C[idx - 1] && c > o && w.lw > 0);
      bool jimplasSell = (idx >= 1 && O[idx - 1] < C[idx - 1] && c < o && w.uw > 0);
      bool jimplasOkBuy = jimplasBuy || (!jimplasBuy && !jimplasSell);
      if(sweptBelow && closedAbove && hasLowWick && biasOkBuy && jimplasOkBuy) sig.p1Buy = true;
     }

   if(prevRes != EMPTY_VALUE && (cfgShowHistory || (liveGateSell && bearRangeOk && histBearOk)))
     {
      bool sweptAbove = (H[idx - 1] > prevRes) || (H[idx] > prevRes);
      bool closedBelow = (c < prevRes);
      bool hasUpWick = (wickRatio >= 0.6 && w.uw >= w.lw);
      bool biasOkSell = !isBullish;
      bool jimplasBuy = (idx >= 1 && O[idx - 1] > C[idx - 1] && c > o && w.lw > 0);
      bool jimplasSell = (idx >= 1 && O[idx - 1] < C[idx - 1] && c < o && w.uw > 0);
      bool jimplasOkSell = jimplasSell || (!jimplasBuy && !jimplasSell);
      if(sweptAbove && closedBelow && hasUpWick && biasOkSell && jimplasOkSell) sig.p1Sell = true;
     }

   // P2 — breakout
   if(!chopZone && !sig.p1Buy && !sig.p1Sell)
     {
      if(prevRes != EMPTY_VALUE && (cfgShowHistory || (liveGateBuy && bullRangeOk && histBullOk)))
        {
         bool brokeUp = (c > prevRes && o <= prevRes);
         bool hasBody = (w.br >= 0.4);
         bool hasLowWick = ((H[idx] - L[idx]) > 0) && ((MathMin(o, c) - L[idx]) >= (H[idx] - L[idx]) * 0.1));
         if(brokeUp && hasBody && hasLowWick && isBullish) sig.p2Buy = true;
        }
      if(prevSup != EMPTY_VALUE && (cfgShowHistory || (liveGateSell && bearRangeOk && histBearOk)))
        {
         bool brokeDown = (c < prevSup && o >= prevSup);
         bool hasBody = (w.br >= 0.4);
         bool hasUpWick = ((H[idx] - L[idx]) > 0) && ((H[idx] - MathMax(o, c)) >= (H[idx] - L[idx]) * 0.1));
         if(brokeDown && hasBody && hasUpWick && isBearish) sig.p2Sell = true;
        }
     }

   // P3 — S/R flip (optional)
   if(enableP3 && !chopZone && !sig.p1Buy && !sig.p1Sell && !sig.p2Buy && !sig.p2Sell)
     {
      if(prevSup != EMPTY_VALUE && BzBrokenBelow(C, idx, prevSup, 10) &&
         (cfgShowHistory || (liveGateBuy && bullRangeOk && histBullOk)))
        {
         double upperWickPct = (H[idx] - L[idx]) > 0 ? (H[idx] - MathMax(o, c)) / (H[idx] - L[idx]) : 0;
         if(H[idx] >= prevSup && c < prevSup && upperWickPct >= 0.6 && !isBearish) sig.p3Buy = true;
        }
      if(prevRes != EMPTY_VALUE && BzBrokenAbove(C, idx, prevRes, 10) &&
         (cfgShowHistory || (liveGateSell && bearRangeOk && histBearOk)))
        {
         double lowerWickPct = (H[idx] - L[idx]) > 0 ? (MathMin(o, c) - L[idx]) / (H[idx] - L[idx]) : 0;
         if(L[idx] <= prevRes && c > prevRes && lowerWickPct >= 0.6 && !isBullish) sig.p3Sell = true;
        }
     }

   bool structOk = !(sr.r1 == EMPTY_VALUE && sr.r2 == EMPTY_VALUE && sr.r3 == EMPTY_VALUE &&
                     sr.s1 == EMPTY_VALUE && sr.s2 == EMPTY_VALUE && sr.s3 == EMPTY_VALUE);
   sig.anyBuy = (sig.p1Buy || sig.p2Buy || sig.p3Buy) && inSession && !maxTradesReached &&
                !newsActive && !nfpBlackout && !spreadBlocked && !dxyBlocksBuy && !riskAthBlock && !geoHigh && structOk;
   sig.anySell = (sig.p1Sell || sig.p2Sell || sig.p3Sell) && inSession && !maxTradesReached &&
                 !newsActive && !nfpBlackout && !spreadBlocked && !geoHigh && structOk;
  }
//+------------------------------------------------------------------+
double BzConfidencePct(bool inSession, bool newsAct, bool nfp, bool spreadBl,
                       bool structOk, bool maxTr, bool dxyBlock, bool athBlock, bool geoHigh,
                       bool bullClean, bool bearClean, bool yieldHigh, int geoMode)
  {
   int p = 0;
   if(inSession) p++;
   if(!newsAct) p++;
   if(!nfp) p++;
   if(!spreadBl) p++;
   if(structOk) p++;
   if(!maxTr) p++;
   if(!dxyBlock) p++;
   if(!athBlock) p++;
   if(!geoHigh) p++;
   if(bullClean || bearClean) p++;
   if(!yieldHigh) p++;
   if(geoMode <= 1) p++;
   p++; // live gate row
   return MathRound(1000.0 * (double)p / 12.0) / 10.0;
  }
//+------------------------------------------------------------------+
bool BzInFxSession(int hourUTC) // simplified London+NY overlap-style window
  {
   return (hourUTC >= 7 && hourUTC < 22);
  }
//+------------------------------------------------------------------+
#endif
