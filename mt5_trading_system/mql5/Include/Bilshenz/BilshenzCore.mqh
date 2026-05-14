//+------------------------------------------------------------------+
//| BilshenzCore.mqh — logic aligned to myapp/engine (TS)            |
//| srEngine.replaySrBarByBar + signalEngine P1–P3 + wickEngine      |
//+------------------------------------------------------------------+
#ifndef __BILSHENZ_CORE_MQH__
#define __BILSHENZ_CORE_MQH__

struct BzSrSnap
  {
   double            immRes, immSup, flipSup, flipRes;
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

      double immRes = BzFImmRes(ph, phn, cl, zone);
      double immSup = BzFImmSup(pl, pln, cl, zone);

      out[conf].immRes = immRes;
      out[conf].immSup = immSup;
      out[conf].flipSup = flipSupLevel;
      out[conf].flipRes = flipResLevel;
      out[conf].r1 = (phn > 0) ? ph[0] : EMPTY_VALUE;
      out[conf].r2 = (phn > 1) ? ph[1] : EMPTY_VALUE;
      out[conf].r3 = (phn > 2) ? ph[2] : EMPTY_VALUE;
      out[conf].s1 = (pln > 0) ? pl[0] : EMPTY_VALUE;
      out[conf].s2 = (pln > 1) ? pl[1] : EMPTY_VALUE;
      out[conf].s3 = (pln > 2) ? pl[2] : EMPTY_VALUE;
      out[conf].r1f = r1Flipped;
      out[conf].r2f = r2Flipped;
      out[conf].r3f = r3Flipped;
      out[conf].s1f = s1Flipped;
      out[conf].s2f = s2Flipped;
      out[conf].s3f = s3Flipped;
     }
  }
//+------------------------------------------------------------------+
void BzLeftSideScan(const double &C[], int idx, double immRes, double immSup,
                    double close, double pip, int lsBars, int lsChopMax, double minPips,
                    bool &bullClean, bool &bearClean)
  {
   double distRes = (immRes == EMPTY_VALUE) ? 0 : (immRes - close) / pip;
   double distSup = (immSup == EMPTY_VALUE) ? 0 : (close - immSup) / pip;
   bool bullRangeOk = (immRes != EMPTY_VALUE && distRes >= minPips);
   bool bearRangeOk = (immSup != EMPTY_VALUE && distSup >= minPips);

   int bullChop = 0, bearChop = 0;
   if(immRes != EMPTY_VALUE)
     {
      for(int i = 1; i <= lsBars; i++)
        {
         int j = idx - i;
         if(j < 0) break;
         double ci = C[j];
         if(ci > close && ci < immRes) bullChop++;
        }
     }
   if(immSup != EMPTY_VALUE)
     {
      for(int i = 1; i <= lsBars; i++)
        {
         int j = idx - i;
         if(j < 0) break;
         double ci = C[j];
         if(ci < close && ci > immSup) bearChop++;
        }
     }
   bullClean = bullRangeOk && (bullChop <= lsChopMax);
   bearClean = bearRangeOk && (bearChop <= lsChopMax);
  }
//+------------------------------------------------------------------+
void BzComputeSignalsAt(const double &O[], const double &H[], const double &L[], const double &C[],
                        int idx, const BzSrSnap &sr,
                        double zone, double e2Near,
                        double p1WickMin, double p2BodyMin,
                        bool pineGate, bool sessionGate, bool masterBlock,
                        bool liveGateBuy, bool liveGateSell,
                        bool histBullOk, bool histBearOk,
                        bool cfgShowHistory,
                        bool riskAthBlock,
                        BzSignals &sig)
  {
   sig.p1Buy = sig.p1Sell = sig.p2Buy = sig.p2Sell = sig.p3Buy = sig.p3Sell = false;
   BzWick w;
   BzWickAt(O[idx], H[idx], L[idx], C[idx], w);
   if(idx < 0 || w.isDoji || !sessionGate || masterBlock) return;

   double o = O[idx], c = C[idx];
   bool bullBar = c > o;
   bool bearBar = c < o;
   bool okLwk = w.lwr >= p1WickMin;
   bool okUwk = w.uwr >= p1WickMin;
   bool okBodyP2 = w.br >= p2BodyMin;
   double rLwk = (w.range > 0) ? w.lw / w.range : 0;
   double rUwk = (w.range > 0) ? w.uw / w.range : 0;

   double immRes = sr.immRes;
   double immSup = sr.immSup;
   double flipSup = sr.flipSup;
   double flipRes = sr.flipRes;

   bool e1Bull = pineGate && !riskAthBlock && histBullOk && (immSup != EMPTY_VALUE) && okLwk && bullBar &&
                 L[idx] < immSup - zone && c > immSup + zone;
   bool e1Bear = pineGate && histBearOk && (immRes != EMPTY_VALUE) && okUwk && bearBar &&
                 H[idx] > immRes + zone && c < immRes - zone;

   if(cfgShowHistory || (liveGateBuy && histBullOk)) sig.p1Buy = e1Bull;
   if(cfgShowHistory || (liveGateSell && histBearOk)) sig.p1Sell = e1Bear;

   bool e2Bull = pineGate && !riskAthBlock && histBullOk && !sig.p1Buy && (immRes != EMPTY_VALUE) && bullBar &&
                 o > immRes - e2Near && c > immRes && okBodyP2 && rLwk > 0.05;
   bool e2Bear = pineGate && histBearOk && !sig.p1Sell && (immSup != EMPTY_VALUE) && bearBar &&
                 o < immSup + e2Near && c < immSup && okBodyP2 && rUwk > 0.05;

   if(cfgShowHistory || (liveGateBuy && histBullOk)) sig.p2Buy = e2Bull;
   if(cfgShowHistory || (liveGateSell && histBearOk)) sig.p2Sell = e2Bear;

   bool e3Bull = pineGate && !riskAthBlock && histBullOk && !sig.p1Buy && !sig.p2Buy && (flipSup != EMPTY_VALUE) &&
                 bullBar && rLwk > 0.2 && L[idx] <= flipSup + zone * 3 && c >= flipSup - zone;
   bool e3Bear = pineGate && histBearOk && !sig.p1Sell && !sig.p2Sell && (flipRes != EMPTY_VALUE) &&
                 bearBar && rUwk > 0.2 && H[idx] >= flipRes - zone * 3 && c <= flipRes + zone;

   if(cfgShowHistory || (liveGateBuy && histBullOk)) sig.p3Buy = e3Bull;
   if(cfgShowHistory || (liveGateSell && histBearOk)) sig.p3Sell = e3Bear;

   bool sessionOk = true;
   sig.anyBuy = (sig.p1Buy || sig.p2Buy || sig.p3Buy) && sessionOk;
   sig.anySell = (sig.p1Sell || sig.p2Sell || sig.p3Sell) && sessionOk;
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
