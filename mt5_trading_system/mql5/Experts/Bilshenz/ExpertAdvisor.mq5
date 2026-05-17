//+------------------------------------------------------------------+
//| ExpertAdvisor.mq5 — Bilshenz auto-exec (TS logic via core)        |
//| Deploy: <MT5 Data Folder>/MQL5/Experts/Bilshenz/ExpertAdvisor.mq5 |
//| Requires: MQL5/Include/Bilshenz/BilshenzCore.mqh (see install.md) |
//| No WebRequest / no DLL — only standard library + Trade.mqh       |
//+------------------------------------------------------------------+
#property copyright "Bilshenz / Jimplas"
#property link      "https://github.com/Jimplas-UG"
#property version   "1.01"
#property description "Bilshenz EA: S/R + P1–P3 signals. Enable Algo Trading (green) on MT5."

#include <Trade/Trade.mqh>
#include <Bilshenz/BilshenzCore.mqh>

CTrade trade;

input ulong  InpMagic = 77002002;
input double InpLots = 0.01;
input int    InpSlPips = 20;          // stop distance in “pips” × InpPipSize
input int    InpTpOffsetPips = 0;     // TP beyond S/R (0 = use imm level)
input int    InpSlippagePt = 80;
input int    InpTf = PERIOD_M30;
input int    InpPivotL = 3;
input int    InpPivotR = 3;
input int    InpSrMax = 8;
input double InpPipSize = 0.1;
input double InpZoneHalfPips = 3;
input double InpMinRangePips = 25;
input double InpSpreadPips = 1.5;
input int    InpMaxDailyTrades = 3;
input bool   InpShowHistory = false;
input bool   InpEnableP3 = false;
input int    InpTpMinPips = 10;
input int    InpTpMaxPips = 28;
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
input int    InpStatusTimerSec = 2;   // OnTimer interval for chart status refresh

static datetime s_lastBarTime = 0;
static bool     s_initSucceeded = false;
static datetime s_lastStatusPrintUtc = 0;

//+------------------------------------------------------------------+
bool BzSetTradeFillingForSymbol(const string sym, CTrade &t, string &detail)
  {
   long fm = SymbolInfoInteger(sym, SYMBOL_FILLING_MODE);
   detail = StringFormat("SYMBOL_FILLING_MODE=0x%X", (uint)fm);
   if((fm & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
     {
      t.SetTypeFilling(ORDER_FILLING_IOC);
      detail += " → IOC";
      return true;
     }
   if((fm & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
     {
      t.SetTypeFilling(ORDER_FILLING_FOK);
      detail += " → FOK";
      return true;
     }
   t.SetTypeFilling(ORDER_FILLING_RETURN);
   detail += " → RETURN";
   return true;
  }
//+------------------------------------------------------------------+
string BzTfName(const int tf)
  {
   switch(tf)
     {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      default:         return StringFormat("TF=%d", tf);
     }
  }
//+------------------------------------------------------------------+
void BzPushStatus(const string title, const string msg)
  {
   Print("[BilshenzEA] ", title, " | ", msg);
  }
//+------------------------------------------------------------------+
void BzUpdateChartStatus()
  {
   const bool termConn = (TerminalInfoInteger(TERMINAL_CONNECTED) != 0);
   const bool termTrade = (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) != 0);
   const bool mqlTrade = (MQLInfoInteger(MQL_TRADE_ALLOWED) != 0);
   const bool acctTrade = (AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) != 0);
   const bool acctExpert = (AccountInfoInteger(ACCOUNT_TRADE_EXPERT) != 0);

   const long tradeMode = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE);
   const bool symOk = (tradeMode != SYMBOL_TRADE_MODE_DISABLED);

   string mt5Line = termConn ? "MT5 Connected" : "MT5 NOT connected (check login / server)";
   string botLine = s_initSucceeded ? "Bot Connected" : "Initialization Failed";
   string tradeLine = (termTrade && mqlTrade && acctTrade && acctExpert && symOk)
                      ? "Trading Enabled"
                      : "Trading NOT enabled (see Experts log)";

   string block = "";
   block += "=== Bilshenz EA ===\n";
   block += botLine + "\n";
   block += mt5Line + "\n";
   block += tradeLine + "\n";
   block += "-------------------\n";
   block += StringFormat("Symbol: %s  Chart: %s  Engine TF: %s\n",
                         _Symbol, BzTfName((int)Period()), BzTfName(InpTf));
   block += StringFormat("Account: %s  Server: %s\n",
                         (string)(long)AccountInfoInteger(ACCOUNT_LOGIN),
                         AccountInfoString(ACCOUNT_SERVER));
   block += StringFormat("TERMINAL_CONNECTED=%s  TERMINAL_TRADE_ALLOWED=%s\n",
                         termConn ? "yes" : "NO",
                         termTrade ? "yes" : "NO");
   block += StringFormat("MQL_TRADE_ALLOWED=%s  ACCOUNT_TRADE_ALLOWED=%s  ACCOUNT_TRADE_EXPERT=%s\n",
                         mqlTrade ? "yes" : "NO",
                         acctTrade ? "yes" : "NO",
                         acctExpert ? "yes" : "NO");
   block += "SYMBOL_TRADE_MODE=" + (string)tradeMode + " (disabled=" + (!symOk ? "YES" : "no") + ")\n";
   block += "-------------------\n";
   block += "Algo Trading: green toolbar button must be ON.\n";
   block += "Tools → Options → Expert Advisors: allow live trading.\n";
   block += "No WebRequest/DLL required for this EA.\n";

   Comment(block);

   datetime now = TimeGMT();
   if(s_lastStatusPrintUtc == 0 || (now - s_lastStatusPrintUtc) >= 30)
     {
      s_lastStatusPrintUtc = now;
      BzPushStatus(botLine, mt5Line + " | " + tradeLine);
     }
  }
//+------------------------------------------------------------------+
bool BzIsDoji(double o,double h,double l,double c)
  {
   BzWick w;
   BzWickAt(o,h,l,c,w);
   return w.isDoji;
  }
//+------------------------------------------------------------------+
int OnInit()
  {
   s_initSucceeded = false;
   s_lastBarTime = 0;

   string fillDetail = "";
   if(!BzSetTradeFillingForSymbol(_Symbol, trade, fillDetail))
     {
      BzPushStatus("Initialization Failed", "Could not set order filling mode");
      Comment("Initialization Failed\nCould not set order filling.\nCheck Experts log.");
      return INIT_FAILED;
     }
   BzPushStatus("Filling mode", fillDetail);

   trade.SetExpertMagicNumber((int)InpMagic);
   trade.SetDeviationInPoints(InpSlippagePt);

   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      BzPushStatus("Initialization Failed", "Terminal not connected to broker server");
      BzUpdateChartStatus();
      return INIT_FAILED;
     }

   if(SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE) == SYMBOL_TRADE_MODE_DISABLED)
     {
      BzPushStatus("Initialization Failed", "Symbol trading is disabled for " + _Symbol);
      BzUpdateChartStatus();
      return INIT_FAILED;
     }

   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
      BzPushStatus("Warning", "ACCOUNT_TRADE_ALLOWED is false — no manual or EA orders until the broker enables trading");

   if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
      BzPushStatus("Warning", "ACCOUNT_TRADE_EXPERT is false — enable Expert Advisors for this account (broker profile / MT5 settings)");

   s_initSucceeded = true;
   int sec = InpStatusTimerSec;
   if(sec < 1) sec = 1;
   if(sec > 60) sec = 60;
   EventSetTimer(sec);

   BzPushStatus("Bot Connected", "OnInit OK — " + _Symbol + " magic=" + (string)InpMagic);
   BzUpdateChartStatus();
   return INIT_SUCCEEDED;
  }
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
   BzPushStatus("OnDeinit", StringFormat("reason=%d", reason));
  }
//+------------------------------------------------------------------+
void OnTimer()
  {
   BzUpdateChartStatus();
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

   BzSrSnap sr[];
   BzReplaySrBarByBar(O, H, L, C, n, InpPivotL, InpPivotR, InpSrMax, zone, sr);

   bool bullClean = false, bearClean = false, bullRangeOk = false, bearRangeOk = false;
   BzLeftSideScan(O, H, L, C, last, sr[last].nearestRes, sr[last].nearestSup, C[last], InpPipSize, InpMinRangePips,
                  bullClean, bearClean, bullRangeOk, bearRangeOk);

   bool hasStruct = !(sr[last].r1 == EMPTY_VALUE && sr[last].r2 == EMPTY_VALUE && sr[last].r3 == EMPTY_VALUE &&
                      sr[last].s1 == EMPTY_VALUE && sr[last].s2 == EMPTY_VALUE && sr[last].s3 == EMPTY_VALUE);
   bool structOk = hasStruct;
   datetime barUtc = t[1];
   bool inSess = !InpUseSessionFilter || BzInPineSessionNY(barUtc);
   bool sessionGate = InpShowHistory || inSess;
   bool spreadBl = (InpSpreadPips > 3.5);
   bool newsAct = false;
   bool nfp = false;
   bool masterBlock = (!InpShowHistory) && (newsAct || nfp || spreadBl || !structOk);
   bool liveGB = inSess && structOk && !spreadBl && !newsAct && !nfp;
   bool liveGS = inSess && structOk && !spreadBl && !newsAct && !nfp;
   bool histBull = InpShowHistory || bullClean;
   bool histBear = InpShowHistory || bearClean;
   bool athB = (C[last] >= InpAthLow);

   MqlRates h4[];
   bool chopZone = false;
   if(CopyRates(_Symbol, PERIOD_H4, 0, 4, h4) >= 3)
     {
      ArraySetAsSeries(h4, true);
      double r0 = (h4[0].high - h4[0].low) / InpPipSize;
      double r1 = (h4[1].high - h4[1].low) / InpPipSize;
      double r2 = (h4[2].high - h4[2].low) / InpPipSize;
      chopZone = (r0 < 40 && r1 < 40 && r2 < 40);
     }

   bool isBullish = false, isBearish = false;
   MqlRates d1[];
   if(CopyRates(_Symbol, PERIOD_D1, 0, 3, d1) >= 2)
     {
      ArraySetAsSeries(d1, true);
      bool bullStruct = (d1[0].high > d1[1].high && d1[0].low > d1[1].low);
      bool bearStruct = (d1[0].high < d1[1].high && d1[0].low < d1[1].low);
      double h4c[];
      if(CopyClose(_Symbol, PERIOD_H4, 0, 55, h4c) >= 50)
        {
         ArraySetAsSeries(h4c, true);
         double ema = h4c[49];
         double k = 2.0 / 51.0;
         for(int i = 48; i >= 0; i--)
            ema = h4c[i] * k + ema * (1.0 - k);
         isBullish = (C[last] > ema && bullStruct);
         isBearish = (C[last] < ema && bearStruct);
        }
     }

   BzSignals sig;
   BzComputeSignalsAt(O, H, L, C, last, sr[last], inSess, sessionGate, masterBlock, liveGB, liveGS,
                      histBull, histBear, InpShowHistory, chopZone, bullRangeOk, bearRangeOk,
                      isBullish, isBearish, athB, spreadBl, false, false, false, newsAct, nfp,
                      InpEnableP3, sig);

   if(InpOnePosition && HasMyPosition()) return;

   if(!MQLInfoInteger(MQL_TRADE_ALLOWED) || !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double slDist = InpSlPips * InpPipSize;

   if(sig.anyBuy && sr[last].nearestRes != EMPTY_VALUE)
     {
      double sl = L[last] - 2.0 * InpPipSize;
      double tp = BzClampTp1(true, ask, sl, sr[last].nearestRes + InpTpOffsetPips * InpPipSize,
                           InpPipSize, InpTpMinPips, InpTpMaxPips);
      if(tp == EMPTY_VALUE || tp <= ask) return;
      if(!trade.Buy(InpLots, _Symbol, ask, sl, tp, "BZEA"))
         Print("Buy fail err=", GetLastError(), " retcode=", trade.ResultRetcodeDescription());
     }
   else if(sig.anySell && sr[last].nearestSup != EMPTY_VALUE)
     {
      double sl = H[last] + 2.0 * InpPipSize;
      double tp = BzClampTp1(false, bid, sl, sr[last].nearestSup - InpTpOffsetPips * InpPipSize,
                            InpPipSize, InpTpMinPips, InpTpMaxPips);
      if(tp == EMPTY_VALUE || tp >= bid) return;
      if(!trade.Sell(InpLots, _Symbol, bid, sl, tp, "BZEA"))
         Print("Sell fail err=", GetLastError(), " retcode=", trade.ResultRetcodeDescription());
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
