//+------------------------------------------------------------------+
//| PollBridgeEA.mq5 — poll bridge-server /poll, place market orders |
//| 1) Tools → Options → Expert Advisors → Allow WebRequest for URL  |
//| 2) Attach EA to chart. Enable Algo Trading (toolbar).            |
//| 3) QueueUrl must match bridge, e.g.                              |
//|    http://127.0.0.1:8788/poll?key=YOUR_MT5_BRIDGE_SECRET         |
//+------------------------------------------------------------------+
#property copyright "Bilshenz template"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

CTrade trade;

input string QueueUrl   = "http://127.0.0.1:8788/poll?key=CHANGE_ME";
input int    PollSec    = 2;
input double Lots       = 0.01;
input long   MagicIn    = 77001001;
input int    SlippagePt = 80;

string lastJobId = "";

int OnInit()
  {
   trade.SetExpertMagicNumber((int)MagicIn);
   trade.SetDeviationInPoints(SlippagePt);
   EventSetTimer(PollSec);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

bool ParseTradeLine(const string body,string &side,string &sym,double &e,double &sl,double &tp,string &jid)
  {
   if(StringFind(body,"NONE")==0 && StringLen(StringTrimLeft(StringTrimRight(body)))<=4)
      return(false);
   string p[];
   int n=StringSplit(body,' ',p);
   if(n<7)
      return(false);
   if(p[0]!="TRADE")
      return(false);
   side = p[1];
   sym  = p[2];
   e    = StringToDouble(p[3]);
   sl   = StringToDouble(p[4]);
   tp   = StringToDouble(p[5]);
   jid  = p[6];
   return(true);
  }

void OnTimer()
  {
   uchar post[];
   uchar result[];
   string hdr;
   ResetLastError();
   int st = WebRequest("GET",QueueUrl,"",5000,post,0,result,hdr);
   if(st==-1)
     {
      Print("PollBridgeEA WebRequest failed, err=",GetLastError()," — add URL in Tools→Options→Expert Advisors");
      return;
     }
   string body = CharArrayToString(result);
   StringTrimLeft(body);
   StringTrimRight(body);
   if(StringLen(body)<6)
      return;

   string side,sym,jid;
   double e,sl,tp;
   if(!ParseTradeLine(body,side,sym,e,sl,tp,jid))
      return;
   if(jid==lastJobId)
      return;

   if(side!="BUY" && side!="SELL")
      return;

   bool ok=false;
   if(side=="BUY")
      ok = trade.Buy(Lots,sym,0,sl,tp,"BilshenzPoll");
   else
      ok = trade.Sell(Lots,sym,0,sl,tp,"BilshenzPoll");

   if(!ok)
     {
      Print("CTrade failed: ",trade.ResultRetcodeDescription());
      return;
     }

   lastJobId = jid;
   Print("Order sent, retcode=",trade.ResultRetcode()," deal=",trade.ResultDeal());
  }
