//+------------------------------------------------------------------+
//| ExpertAdvisor.mq5 — Bilshenz auto-exec (TS logic via core)         |
//| Trailing, break-even, session filter, magic isolation             |
//+------------------------------------------------------------------+
#property copyright "Bilshenz / Jimplas"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>
#include <Bilshenz/BilshenzCore.mqh>

CTrade trade;

input ulong  InpMagic = 77002002;
input double InpLots = 0.01;
input int    InpSlPips = 20;          // stop distance in “pips” × InpPipSize
input int    InpTpOffsetPips = 0;     // TP beyond S/R (0 = use imm level)
input int    InpSlippagePt = 80;
input int    InpTf = PERIOD_M30;
input int    InpPivotL = 8;
input int    InpPivotR = 8;
input int    InpSrMax = 8;
input double InpPipSize = 0.1;
input double InpZoneHalfPips = 4;
input double InpMinRangePips = 25;
input int    InpLsBars = 40;
input int    InpLsChopMax = 3;
input double InpP1Wick = 0.55;
input double InpP2Body = 0.36;
input double InpE2NearPips = 3;
input bool   InpShowHistory = false;
input bool   InpUseSessionFilter = true;
input bool   InpOnePosition = true;
input bool   InpUseTrailing = true;
input int    InpTrailStartPips = 25;
input int    InpTrailStepPips = 15;
input bool   InpUseBreakEven = true;
input int    InpBeTriggerPips = 18;
input double InpBeOffsetPips = 12;
input double InpAthLow = 5278.0;
input double InpAthHigh = 5602.0;

static datetime s_lastBarTime = 0;

bool BzIsDoji(double o,double h,double l,double c)
  {
   BzWick w;
   BzWickAt(o,h,l,c,w);
   return w.isDoji;
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber((int)InpMagic);
   trade.SetDeviationInPoints(InpSlippagePt);
   trade.SetTypeFilling(ORDER_FILLING_IOC);
   return(INIT_SUCCEEDED);
  }
//+------------------------------------------------------------------+
bool HasMyPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!PositionSelectByIndex(i)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      return true;
     }
   return false;
  }
//+------------------------------------------------------------------+
void OnTick()
  {
   ManageTrailingAndBE();

   datetime t[];
   if(CopyTime(_Symbol, (ENUM_TIMEFRAMES)InpTf, 0, 2, t) < 2) return;
   datetime barOpen = t[0];
   if(barOpen == s_lastBarTime) return;
   s_lastBarTime = barOpen;

   const int need = 800;
   MqlRates rates[];
   int n = CopyRates(_Symbol, (ENUM_TIMEFRAMES)InpTf, 0, need, rates);
   if(n < 200) return;
   ArraySetAsSeries(rates, true);

   double O[], H[], L[], C[];
   ArrayResize(O, n);
   ArrayResize(H, n);
   ArrayResize(L, n);
   ArrayResize(C, n);
   for(int k = 0; k < n; k++)
     {
      int si = n - 1 - k;
      O[k] = rates[si].open;
      H[k] = rates[si].high;
      L[k] = rates[si].low;
      C[k] = rates[si].close;
     }

   int last = n - 1;
   double zone = InpZoneHalfPips * InpPipSize;
   double e2Near = InpE2NearPips * InpPipSize;

   BzSrSnap sr[];
   BzReplaySrBarByBar(O, H, L, C, n, InpPivotL, InpPivotR, InpSrMax, zone, sr);

   bool bullClean, bearClean;
   BzLeftSideScan(C, last, sr[last].immRes, sr[last].immSup, C[last], InpPipSize, InpLsBars, InpLsChopMax, InpMinRangePips, bullClean, bearClean);

   bool hasStruct = (sr[last].immRes != EMPTY_VALUE || sr[last].immSup != EMPTY_VALUE);
   bool structOk = hasStruct;
   datetime gmt = TimeGMT();
   MqlDateTime dt;
   TimeToStruct(gmt, dt);
   bool inSess = !InpUseSessionFilter || BzInFxSession(dt.hour);
   bool sessionGate = InpShowHistory || inSess;
   bool spreadBl = false;
   bool newsAct = false;
   bool nfp = false;
   bool masterBlock = (!InpShowHistory) && (newsAct || nfp || spreadBl || !structOk);
   bool liveGB = inSess && !masterBlock && structOk;
   bool liveGS = inSess && !masterBlock && structOk;
   bool histBull = InpShowHistory || bullClean;
   bool histBear = InpShowHistory || bearClean;
   bool pineGate = (InpShowHistory || inSess) && !spreadBl && !BzIsDoji(O[last], H[last], L[last], C[last]) && (bullClean || bearClean);
   bool athB = (C[last] >= InpAthLow && C[last] <= InpAthHigh);

   BzSignals sig;
   BzComputeSignalsAt(O, H, L, C, last, sr[last], zone, e2Near, InpP1Wick, InpP2Body,
                      pineGate, sessionGate, masterBlock, liveGB, liveGS, histBull, histBear,
                      InpShowHistory, athB, sig);

   if(InpOnePosition && HasMyPosition()) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double slDist = InpSlPips * InpPipSize;

   if(sig.anyBuy && sr[last].immRes != EMPTY_VALUE)
     {
      double sl = ask - slDist;
      double tp = sr[last].immRes + InpTpOffsetPips * InpPipSize;
      if(tp <= ask) return;
      if(!trade.Buy(InpLots, _Symbol, ask, sl, tp, "BZEA")) Print("Buy fail ", GetLastError());
     }
   else if(sig.anySell && sr[last].immSup != EMPTY_VALUE)
     {
      double sl = bid + slDist;
      double tp = sr[last].immSup - InpTpOffsetPips * InpPipSize;
      if(tp >= bid) return;
      if(!trade.Sell(InpLots, _Symbol, bid, sl, tp, "BZEA")) Print("Sell fail ", GetLastError());
     }
  }
//+------------------------------------------------------------------+
void ManageTrailingAndBE()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!PositionSelectByIndex(i)) continue;
      ulong tk = (ulong)PositionGetInteger(POSITION_TICKET);
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      long type = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      double price = (type == POSITION_TYPE_BUY) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);

      double profitPts = 0;
      if(type == POSITION_TYPE_BUY)
         profitPts = (price - open) / InpPipSize;
      else
         profitPts = (open - price) / InpPipSize;

      if(InpUseBreakEven && profitPts >= InpBeTriggerPips)
        {
         double be = open + ((type == POSITION_TYPE_BUY) ? 1 : -1) * InpBeOffsetPips * InpPipSize;
         if(type == POSITION_TYPE_BUY && sl < be)
            trade.PositionModify(tk, be, tp);
         if(type == POSITION_TYPE_SELL && (sl == 0 || sl > be))
            trade.PositionModify(tk, be, tp);
        }

      if(InpUseTrailing && profitPts >= InpTrailStartPips)
        {
         double step = InpTrailStepPips * InpPipSize;
         if(type == POSITION_TYPE_BUY)
           {
            double nsl = price - step;
            if(nsl > sl && nsl < price)
               trade.PositionModify(tk, nsl, tp);
           }
         else
           {
            double nsl = price + step;
            if((sl == 0 || nsl < sl) && nsl > price)
               trade.PositionModify(tk, nsl, tp);
           }
        }
     }
  }
//+------------------------------------------------------------------+
