//+------------------------------------------------------------------+
//| Indicator.mq5 — Bilshenz signals (S/R replay + P1–P3, TS-aligned) |
//| Requires: MQL5/Include/Bilshenz/BilshenzCore.mqh                 |
//+------------------------------------------------------------------+
#property copyright "Bilshenz / Jimplas"
#property link      "https://github.com/Jimplas-UG"
#property version   "1.01"
#property indicator_chart_window
#property indicator_buffers 3
#property indicator_plots   3

#property indicator_label1  "BZ Buy"
#property indicator_type1     DRAW_ARROW
#property indicator_color1    clrDodgerBlue
#property indicator_width1    2

#property indicator_label2  "BZ Sell"
#property indicator_type2     DRAW_ARROW
#property indicator_color2    clrTomato
#property indicator_width2    2

#property indicator_label3  "BZ Conf %"
#property indicator_type3     DRAW_LINE
#property indicator_color3    clrGold
#property indicator_width3    1

#include <Bilshenz/BilshenzCore.mqh>

input int    InpPivotL = 8;
input int    InpPivotR = 8;
input int    InpSrMax  = 8;
input double InpPipSize = 0.1;
input double InpZoneHalfPips = 4;
input double InpMinRangePips = 25;
input int    InpLsBars = 40;
input int    InpLsChopMax = 3;
input double InpP1Wick = 0.55;
input double InpP2Body = 0.36;
input double InpE2NearPips = 3;
input bool   InpShowHistory = false;
input bool   InpNewsSimOff = true;
input bool   InpUseSessionFilter = true;
input double InpAthLow = 5278.0;
input double InpAthHigh = 5602.0;

double BufBuy[];
double BufSell[];
double BufConf[];

//+------------------------------------------------------------------+
bool BzIsDojiBar(const double o, const double h, const double l, const double c)
  {
   BzWick w;
   BzWickAt(o, h, l, c, w);
   return w.isDoji;
  }
//+------------------------------------------------------------------+
int OnInit()
  {
   SetIndexBuffer(0, BufBuy, INDICATOR_DATA);
   SetIndexBuffer(1, BufSell, INDICATOR_DATA);
   SetIndexBuffer(2, BufConf, INDICATOR_DATA);
   PlotIndexSetInteger(0, PLOT_ARROW, 233);
   PlotIndexSetInteger(1, PLOT_ARROW, 234);
   ArraySetAsSeries(BufBuy, true);
   ArraySetAsSeries(BufSell, true);
   ArraySetAsSeries(BufConf, true);
   IndicatorSetString(INDICATOR_SHORTNAME, "Bilshenz BZ");
   return INIT_SUCCEEDED;
  }
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0, "BZ_DASH_");
   ObjectsDeleteAll(0, "BZ_ZN_");
   ObjectsDeleteAll(0, "BZ_RR_");
  }
//+------------------------------------------------------------------+
void BzDashUpdate(const double conf, const bool anyB, const bool anyS,
                  const double immR, const double immS,
                  const double slBuy, const double tpBuy, const double slSell, const double tpSell)
  {
   const string p = "BZ_DASH_";
   const int y = 20;
   const int dy = 16;
   if(ObjectFind(0, p + "t0") < 0)
     {
      for(int i = 0; i < 12; i++)
        {
         const string nm = p + "t" + IntegerToString(i);
         if(!ObjectCreate(0, nm, OBJ_LABEL, 0, 0, 0))
            continue;
         ObjectSetInteger(0, nm, OBJPROP_CORNER, CORNER_LEFT_UPPER);
         ObjectSetInteger(0, nm, OBJPROP_XDISTANCE, 8);
         ObjectSetInteger(0, nm, OBJPROP_YDISTANCE, y + i * dy);
         ObjectSetInteger(0, nm, OBJPROP_COLOR, clrWhiteSmoke);
         ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, 9);
        }
     }
   const string L0 = "Bilshenz MT5 · Conf " + DoubleToString(conf, 1) + "%";
   string L1 = "SIGNAL: —";
   if(anyB)
      L1 = "SIGNAL: BUY";
   else if(anyS)
      L1 = "SIGNAL: SELL";
   const string L2 = (immR == EMPTY_VALUE) ? "Imm RES: —" : "Imm RES: " + DoubleToString(immR, _Digits);
   const string L3 = (immS == EMPTY_VALUE) ? "Imm SUP: —" : "Imm SUP: " + DoubleToString(immS, _Digits);
   string L4 = "RR: —";
   if(anyB)
      L4 = "RR BUY SL " + DoubleToString(slBuy, _Digits) + " TP " + DoubleToString(tpBuy, _Digits);
   else if(anyS)
      L4 = "RR SELL SL " + DoubleToString(slSell, _Digits) + " TP " + DoubleToString(tpSell, _Digits);
   ObjectSetString(0, p + "t0", OBJPROP_TEXT, L0);
   ObjectSetString(0, p + "t1", OBJPROP_TEXT, L1);
   ObjectSetString(0, p + "t2", OBJPROP_TEXT, L2);
   ObjectSetString(0, p + "t3", OBJPROP_TEXT, L3);
   ObjectSetString(0, p + "t4", OBJPROP_TEXT, L4);
   ChartRedraw(0);
  }
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
  {
   if(rates_total < 200)
      return 0;

   const int n = rates_total;
   double O[];
   double H[];
   double L[];
   double C[];
   ArrayResize(O, n);
   ArrayResize(H, n);
   ArrayResize(L, n);
   ArrayResize(C, n);

   for(int k = 0; k < n; k++)
     {
      const int si = n - 1 - k;
      O[k] = open[si];
      H[k] = high[si];
      L[k] = low[si];
      C[k] = close[si];
     }

   const double zone = InpZoneHalfPips * InpPipSize;
   const double e2Near = InpE2NearPips * InpPipSize;

   BzSrSnap sr[];
   BzReplaySrBarByBar(O, H, L, C, n, InpPivotL, InpPivotR, InpSrMax, zone, sr);

   if(prev_calculated == 0)
     {
      ArrayInitialize(BufBuy, EMPTY_VALUE);
      ArrayInitialize(BufSell, EMPTY_VALUE);
      ArrayInitialize(BufConf, EMPTY_VALUE);
     }

   const int minBar = InpPivotL + InpPivotR + 5;
   int start = MathMax(minBar, prev_calculated == 0 ? minBar : n - 3);
   if(start >= n)
      start = n - 1;

   for(int k = start; k < n; k++)
     {
      const int si = n - 1 - k;
      bool bullClean = false;
      bool bearClean = false;
      BzLeftSideScan(C, k, sr[k].immRes, sr[k].immSup, C[k], InpPipSize, InpLsBars, InpLsChopMax, InpMinRangePips, bullClean, bearClean);

      const bool hasStruct = (sr[k].immRes != EMPTY_VALUE || sr[k].immSup != EMPTY_VALUE);
      const bool structOk = hasStruct;
      const bool inSess = (!InpUseSessionFilter) || BzInFxSession(TimeHour(time[si]));
      const bool sessionGate = InpShowHistory || inSess;
      const bool spreadBl = false;
      const bool newsAct = (!InpNewsSimOff) && false;
      const bool nfp = false;
      const bool masterBlock = (!InpShowHistory) && (newsAct || nfp || spreadBl || !structOk);
      const bool liveGB = inSess && !masterBlock && structOk;
      const bool liveGS = inSess && !masterBlock && structOk;
      const bool histBull = InpShowHistory || bullClean;
      const bool histBear = InpShowHistory || bearClean;
      const bool pineGate =
         (InpShowHistory || inSess) && !spreadBl && !BzIsDojiBar(O[k], H[k], L[k], C[k]) && (bullClean || bearClean);

      const bool athBlock = (C[k] >= InpAthLow && C[k] <= InpAthHigh);

      BzSignals sig;
      BzComputeSignalsAt(O, H, L, C, k, sr[k], zone, e2Near, InpP1Wick, InpP2Body,
                         pineGate, sessionGate, masterBlock, liveGB, liveGS, histBull, histBear,
                         InpShowHistory, athBlock, sig);

      const double conf = BzConfidencePct(inSess || InpShowHistory, newsAct, nfp, spreadBl, structOk, false,
                                            false, athBlock, false, bullClean, bearClean, false, 0);

      BufBuy[si] = EMPTY_VALUE;
      BufSell[si] = EMPTY_VALUE;
      BufConf[si] = conf;

      if(sig.anyBuy)
         BufBuy[si] = low[si] - 15 * _Point;
      if(sig.anySell)
         BufSell[si] = high[si] + 15 * _Point;
     }

   const int si0 = 0;
   const int k0 = n - 1;
   bool bc = false;
   bool brc = false;
   BzLeftSideScan(C, k0, sr[k0].immRes, sr[k0].immSup, C[k0], InpPipSize, InpLsBars, InpLsChopMax, InpMinRangePips, bc, brc);
   const bool hasS2 = (sr[k0].immRes != EMPTY_VALUE || sr[k0].immSup != EMPTY_VALUE);
   const bool inS2 = (!InpUseSessionFilter) || BzInFxSession(TimeHour(time[si0]));
   const bool pine2 = (InpShowHistory || inS2) && (bc || brc);
   const bool athB2 = (C[k0] >= InpAthLow && C[k0] <= InpAthHigh);
   BzSignals sg2;
   BzComputeSignalsAt(O, H, L, C, k0, sr[k0], zone, e2Near, InpP1Wick, InpP2Body,
                      pine2, (InpShowHistory || inS2), false, inS2, inS2, (InpShowHistory || bc), (InpShowHistory || brc),
                      InpShowHistory, athB2, sg2);
   const double cf2 = BzConfidencePct(inS2 || InpShowHistory, false, false, false, hasS2, false, false, athB2, false, bc, brc, false, 0);
   const double slBuf = 2.0 * InpPipSize;
   const double slB = C[k0] - slBuf;
   const double tpB = sr[k0].immRes;
   const double slS = C[k0] + slBuf;
   const double tpS = sr[k0].immSup;
   BzDashUpdate(cf2, sg2.anyBuy, sg2.anySell, sr[k0].immRes, sr[k0].immSup, slB, tpB, slS, tpS);

   return rates_total;
  }
//+------------------------------------------------------------------+
