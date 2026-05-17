import React, { Suspense, lazy, useCallback, useContext, useEffect, useMemo, useRef, useState, createContext } from 'react';
import * as SplashScreen from 'expo-splash-screen';
import CinematicSplash from './components/CinematicSplash';
import {
  Alert,
  Image,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import Svg, { Defs, LinearGradient, Polyline, Stop } from 'react-native-svg';
import { BlurView } from 'expo-blur';
import Slider from '@react-native-community/slider';
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import BilshenzHeader from './components/BilshenzHeader';
import GeoPoliticalTicker from './components/GeoPoliticalTicker';

const Mt5BridgePanelLazy = lazy(() => import('./components/Mt5BridgePanel'));
import { buildBrokerOrderIntent, canExecuteTrade, executeBrokerRoutes } from './broker';
import { Mt5BridgeProvider, useMt5Bridge } from './contexts/Mt5BridgeContext';
import { ThemeProvider, useBilshenzTheme } from './contexts/ThemeContext';
import { defaultBilshenzConfig, mapJournalToHistRows, mapSessionBitsFromEngine, mapSrFromEngine } from './engine';
import { useBilshenzMarketEngine } from './hooks/useBilshenzMarketEngine';
import { useMt5LiveFeed } from './hooks/useMt5LiveFeed';
import {
  clearProfilePhoto,
  loadAllProfilePhotos,
  saveProfilePhoto,
} from './utils/profilePhoto';
import {
  clearProfileName,
  initialsFromName,
  loadAllProfileNames,
  saveProfileName,
} from './utils/profileName';
import {
  journalClosedUsd,
  lotSizeSubtitle,
  lotsForTrade,
  pctOfBalanceLabel,
  resolveAccountEquity,
  SIM_DESK_EQUITY,
  sizingForTrade,
} from './utils/riskSizing';

const STORAGE_BROKER_HOOK_URL = '@bilshenz_v1/brokerHookUrl';
const STORAGE_AUTO_EXEC = '@bilshenz_v1/autoExecSignals';

const BilshenzEngineCtx = createContext(null);

/** Profile risk preset → engine `geoRisk` (macro tier). */
function profileRiskModeToGeo(mode) {
  if (mode === 'GEO') return 'HIGH';
  if (mode === 'AGGRESSIVE') return 'MEDIUM';
  return 'LOW';
}

const SIGNAL_HISTORY_SIM = [
  ['14:32', '▲', 'WICK', '4612.50', '4597.00', 'Pending', 'OPEN', '⏳', 'buy', 'open'],
  ['12:15', '▲', 'WICK', '4598.20', '4582.00', '✓ +12p', '+$840', 'WIN', 'buy', 'win'],
  ['09:03', '▼', 'WICK', '4641.10', '4657.00', '✓ +12p', '+$620', 'WIN', 'sell', 'win'],
  ['07:48', '▲', 'BREAK', '✗ BLOCKED — CHOP ZONE · No breakout entries', '', '', '', 'buy', 'blocked'],
  ['03:22', '▼', 'WICK', '4649.80', '4662.00', '✗ No BE', '-$125', 'SL HIT', 'sell', 'loss'],
];

function getEST(now = new Date()) {
  let h = now.getUTCHours() - 5;
  if (h < 0) h += 24;
  return { h, m: now.getUTCMinutes(), dow: now.getUTCDay() };
}

/** Risk / macro strip rows (shared by dashboard stack + geopolitical ticker tape). */
function buildGmAlertRows(r, nfpBlackout, newsActive, C) {
  if (!r) return [];
  const rows = [];
  rows.push({
    color: r.geoHigh ? C.red : r.geoMedium ? C.amber : C.teal,
    text: r.geoHigh ? 'GEOPOLITICAL: HIGH' : r.geoMedium ? 'GEOPOLITICAL: MEDIUM' : 'GEOPOLITICAL: LOW',
  });
  rows.push({
    color: nfpBlackout ? C.red : C.green,
    text: nfpBlackout ? 'NFP BLACKOUT: SIM ON' : 'NFP BLACKOUT: CLEAR',
  });
  if (r.atrPips != null) {
    const c = r.atrPips >= 100 ? C.red : r.atrPips >= 50 ? C.amber : C.teal;
    const atrLbl = typeof r.atrMode === 'string' ? r.atrMode.split('—')[0].trim() : 'ATR';
    rows.push({ color: c, text: `ATR: ${atrLbl} (${r.atrPips.toFixed(0)}p)` });
  }
  rows.push({
    color: r.chopZone ? C.amber : C.green,
    text: r.chopZone ? 'CHOP ZONE ACTIVE · WICK ONLY' : 'CHOP: NORMAL',
  });
  rows.push({
    color: r.dxyBlocksBuy ? C.red : C.teal,
    text: r.dxyRising ? 'DXY: RISING · BUYS GATED' : 'DXY: FALLING / FLAT · BUY PATH',
  });
  rows.push({
    color: r.yieldHigh ? C.red : C.purple,
    text: r.yieldHigh ? 'YIELD: HIGH · TP2 HAIRCUT' : 'YIELD: WITHIN BAND',
  });
  rows.push({
    color: r.athZoneBlocked ? C.red : C.green,
    text: r.athZoneBlocked ? 'ATH ZONE: NO BUY' : 'ATH ZONE: CLEAR',
  });
  if (newsActive) {
    rows.push({ color: C.amber, text: 'NEWS WINDOW: TREATED AS ACTIVE (sim)' });
  }
  return rows;
}

function fmtUsd(n) {
  const neg = n < 0;
  const abs = Math.abs(Math.round(n));
  return (neg ? '-$' : '+$') + abs.toLocaleString('en-US');
}

function fmtNum(n, digits = 2) {
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Next zone beyond TP1 (Pine TP2: next POI, then ladder / structure). */
function pickTp2FromSnapshot(trade, sr, lv) {
  const side = trade?.side;
  const tp1 = trade?.tp1;
  if (!side || tp1 == null || !Number.isFinite(tp1) || !sr || !lv) return null;
  if (side === 'BUY') {
    const cands = [sr.poiRes, sr.r2, sr.r3, lv.pdh, lv.wh].filter((x) => x != null && Number.isFinite(x) && x > tp1);
    return cands.length ? Math.min(...cands) : null;
  }
  if (side === 'SELL') {
    const cands = [sr.poiSup, sr.s2, sr.s3, lv.pdl, lv.wl].filter((x) => x != null && Number.isFinite(x) && x < tp1);
    return cands.length ? Math.max(...cands) : null;
  }
  return null;
}

/** Stacked ATR + geo tier sizing (matches {@link BilshenzEngineConfig} riskPct* fields). */
function effectiveRiskPctFromEngine(geoRisk, atrPips, cfg) {
  const d = cfg ?? defaultBilshenzConfig;
  let pct = d.riskPctAtrNormal;
  if (atrPips != null && Number.isFinite(atrPips)) {
    if (atrPips >= 100) pct = d.riskPctAtrCrisis;
    else if (atrPips >= 50) pct = d.riskPctAtrElevated;
  }
  if (geoRisk === 'HIGH') pct = Math.min(pct, d.riskPctGeoHighCap);
  return pct;
}

/** Active Jimplas setup labels for UI (matches jimplasFluiditySignalEngine). */
function jimplasSetupLive(signals) {
  if (!signals) return { p1: 'SCAN', p2: 'SCAN', p3: 'SCAN' };
  return {
    p1: signals.p1Buy || signals.p1Sell ? 'LIVE' : 'SCAN',
    p2: signals.p2Buy || signals.p2Sell ? 'LIVE' : 'SCAN',
    p3: signals.p3Buy || signals.p3Sell ? 'LIVE' : 'SCAN',
  };
}

function jimplasStrategyModeLine(cfg) {
  if (!cfg) return 'Jimplas Fluidity';
  const tp =
    cfg.useLegacyTpClampOnly && cfg.tp1MinRewardPips != null
      ? `TP ${cfg.tp1MinRewardPips}–${cfg.tp1MaxRewardPips}p`
      : 'Structure TP';
  const p2 = cfg.p2UseStrictFilters ? 'P2 strict' : 'P2 loose';
  const sz = cfg.journalSizingSlPips > 0 ? `${cfg.journalSizingSlPips}p risk lots` : 'SL-sized lots';
  return `Jimplas Fluidity · ${tp} · ${p2} · ${sz}`;
}

function activeSetupGrabLbl(signals) {
  if (signals?.p1Buy || signals?.p1Sell) return 'P1 BREAKOUT ✓';
  if (signals?.p2Buy || signals?.p2Sell) return 'P2 WICK FILL ✓';
  if (signals?.p3Buy || signals?.p3Sell) return 'P3 SESSION ✓';
  return 'JIMPLAS SCAN';
}

function wickStoryLines(wick, pipSize) {
  const pip = pipSize > 0 ? pipSize : 0.1;
  const rngP = (wick.candleRange / pip).toFixed(0);
  const bodyPct = (wick.bodyRatio * 100).toFixed(0);
  const lwP = (wick.lowerWick / pip).toFixed(0);
  const uwP = (wick.upperWick / pip).toFixed(0);
  let main = 'M30 wick scan — awaiting Jimplas flip / rejection stack';
  if (wick.jimplasFlipBuy) main = 'WICK CREATED ✓ — Jimplas flip BUY (prev bear → bull + lower wick)';
  else if (wick.jimplasFlipSell) main = 'WICK CREATED ✓ — Jimplas flip SELL (prev bull → bear + upper wick)';
  else if (wick.isValidRejection) main = 'WICK REJECTION ✓ — Dominant wick (Pine wick path)';
  const sub = `M30 · range ${rngP}p · body ${bodyPct}% · lower ${lwP}p · upper ${uwP}p`;
  return { main, sub };
}

/** Closed journal rows: net pips + profit factor on price distances (TP vs SL). */
function journalClosedStats(rows, pipSize) {
  const pip = pipSize > 0 ? pipSize : 0.1;
  let grossWin = 0;
  let grossLoss = 0;
  let winP = 0;
  let lossP = 0;
  for (const r of rows) {
    if (r.out === 'WIN' && r.tp1 != null && Number.isFinite(r.tp1) && Number.isFinite(r.entry)) {
      const d = Math.abs(r.tp1 - r.entry);
      grossWin += d;
      winP += d / pip;
    }
    if (r.out === 'LOSS' && Number.isFinite(r.entry) && Number.isFinite(r.sl)) {
      const d = Math.abs(r.entry - r.sl);
      grossLoss += d;
      lossP += d / pip;
    }
  }
  const pfStr = grossLoss > 1e-9 ? (grossWin / grossLoss).toFixed(2) : grossWin > 0 ? '∞' : '—';
  return { winP, lossP, netP: winP - lossP, pfStr };
}

function Row({ children, style }) {
  const { colors: C, styles } = useBilshenzTheme();
  return <View style={[styles.row, style]}>{children}</View>;
}

function BlinkDot({ color }) {
  const { colors: C, styles } = useBilshenzTheme();
  return <View style={[styles.ldot, { backgroundColor: color, shadowColor: color }]} />;
}

function SessionBlock({ narrow, active, forceDead, sn, st, badge, badgeKind }) {
  const { colors: C, styles } = useBilshenzTheme();
  const w = narrow ? '50%' : '25%';
  const blk = [styles.sblk, { width: w }];
  if (active) blk.push(styles.sblkActive);
  if (forceDead) blk.push(styles.sblkDead);
  const bd =
    badgeKind === 'open'
      ? styles.sbOpen
      : badgeKind === 'dead'
        ? styles.sbDead
        : styles.sbWait;
  return (
    <View style={blk}>
      <View style={{ flex: 1, paddingRight: 8 }}>
        <Text style={styles.sn}>{sn}</Text>
        <Text style={styles.st}>{st}</Text>
      </View>
      <Text style={[styles.sbadge, bd]}>{badge}</Text>
    </View>
  );
}

function LeftColumn({ sr, dxy }) {
  const { colors: C, styles } = useBilshenzTheme();
  const eng = useContext(BilshenzEngineCtx);
  const snap = eng?.snapshot;
  const useRealMt5 = !!eng?.useRealMt5;
  const dxyLive = snap?.dxyClose ?? (useRealMt5 ? null : dxy);
  const cfg = eng?.cfg;
  const bias = snap?.bias;
  const risk = snap?.risk;
  const esr = snap?.sr;
  const jLive = jimplasSetupLive(snap?.signals);
  const cfgJ = eng?.cfg;
  const athLo = cfg?.athZoneLow ?? 5278;
  const athHi = cfg?.athZoneHigh ?? 5602;

  const biasWord = bias?.isBullish ? 'BULLISH' : bias?.isBearish ? 'BEARISH' : 'NEUTRAL';
  const biasWordStyle = bias?.isBullish ? styles.biasBull : bias?.isBearish ? styles.biasBear : styles.biasNeu;
  const biasSub = !bias
    ? 'Engine loading…'
    : bias.isBullish
      ? 'Price > M30 EMA50 · M30 HH/HL (piv 5) ✓'
      : bias.isBearish
        ? 'Price < M30 EMA50 · M30 LH/LL (piv 5) ✓'
        : 'M30 EMA50 / pivot structure neutral';

  const dStr = bias?.bullStructure ? '▲ HH/HL' : bias?.bearStructure ? '▼ LH/LL' : '— NEUTRAL';
  const dSty = bias?.bullStructure ? styles.tfBull : bias?.bearStructure ? styles.tfBear : styles.tfNeu;
  const ema50Row =
    bias?.ema50H4 != null && sr.currentPrice != null
      ? sr.currentPrice > bias.ema50H4
        ? '▲ ABOVE'
        : '▼ BELOW'
      : '—';
  const ema50Sty =
    bias?.ema50H4 != null && sr.currentPrice != null
      ? sr.currentPrice > bias.ema50H4
        ? styles.tfBull
        : styles.tfBear
      : styles.tfNeu;

  const h1Row =
    bias?.ema21M30 != null && sr.currentPrice != null
      ? sr.currentPrice > bias.ema21M30
        ? '▲ ABOVE EMA21'
        : '▼ BELOW EMA21'
      : '—';
  const h1Sty =
    bias?.ema21M30 != null && sr.currentPrice != null
      ? sr.currentPrice > bias.ema21M30
        ? styles.tfBull
        : styles.tfBear
      : styles.tfNeu;

  const geoLbl = risk?.geoHigh ? 'HIGH' : risk?.geoMedium ? 'MEDIUM' : 'LOW';
  const geoCap = cfg?.riskPctGeoHighCap ?? defaultBilshenzConfig.riskPctGeoHighCap;
  const geoRule =
    risk?.geoHigh
      ? `⚠ RISK=HIGH → MAX ${geoCap}% SIZE\nDynamic entries SUSPENDED\nTP1 reduced by 20%`
      : risk?.geoMedium
        ? '⚠ MEDIUM GEO — monitor headlines\nSize capped per protocol'
        : 'GEO filter clear — full protocol sizing';

  const liveBadge = useRealMt5 ? 'MT5 LIVE' : 'SIM';

  return (
    <View style={styles.leftCol}>
      <Panel shell={{}} head={{ title: 'HTF Bias · Jimplas', badge: useRealMt5 ? 'MT5 · H4/D1' : 'H4 EMA50' }}>
        <View style={styles.biasHero}>
          <Text style={styles.biasTag}>OVERALL BIAS</Text>
          <Text style={[styles.biasWord, biasWordStyle]}>{biasWord}</Text>
          <Text style={styles.biasSub}>{biasSub}</Text>
        </View>
        <TfRow l="M30 · EMA50" r={ema50Row} rStyle={ema50Sty} />
        <TfRow l="M30 · pivots" r={dStr} rStyle={dSty} />
        <TfRow l="H1 (M30·21)" r={h1Row} rStyle={h1Sty} />
        <TfRow l="M30 S&R" r={snap?.gates?.structureOk ? '▲ ALIGNED' : '⏳ WAIT'} rStyle={snap?.gates?.structureOk ? styles.tfBull : styles.tfNeu} />
      </Panel>

      <Panel
        shell={styles.gmPanelShell}
        headTint={styles.gmHeaderTint}
        head={{ title: 'Jimplas Setups', badge: 'P1 · P2 · P3', titleColor: C.goldL, badgeColor: C.gold }}
      >
        <DxyRow l="P1 Breakout + retest" v={jLive.p1} vc={jLive.p1 === 'LIVE' ? C.green : C.dim} />
        <DxyRow l="P2 Wick fill" v={jLive.p2} vc={jLive.p2 === 'LIVE' ? C.teal : C.dim} />
        <DxyRow l="P3 Session impulse" v={jLive.p3} vc={jLive.p3 === 'LIVE' ? C.amber : C.dim} />
        <Text style={styles.geoSub}>{jimplasStrategyModeLine(cfgJ)}</Text>
      </Panel>

      <Panel
        shell={styles.gmPanelShell}
        headTint={styles.gmHeaderTint}
        head={{
          title: 'Geopolitical Filter',
          badge: useRealMt5 ? 'MT5 · v3' : 'NEW · v3',
          titleColor: C.red,
          badgeColor: C.gold,
        }}
      >
        <View style={styles.geoDial}>
          <Text style={styles.geoRiskLbl}>RISK LEVEL</Text>
          <Text style={styles.geoLevel}>{geoLbl}</Text>
          <Text style={styles.geoSub}>Pine macro: geo_risk → hard_block on HIGH</Text>
          <Row style={styles.geoBars}>
            <View style={[styles.geoBar, styles.geoBarG]} />
            <View style={[styles.geoBar, styles.geoBarG]} />
            <View style={[styles.geoBar, styles.geoBarA]} />
            <View style={[styles.geoBar, styles.geoBarA]} />
            <View style={[styles.geoBar, styles.geoBarR]} />
            <View style={[styles.geoBar, styles.geoBarR]} />
            <View style={[styles.geoBar, styles.geoBarR]} />
          </Row>
          <Text style={styles.geoRule}>{geoRule}</Text>
        </View>
      </Panel>

      <Panel
        shell={styles.srPanelShell}
        headTint={styles.srHeadTint}
        head={{ title: 'S&R Engine', badge: `${liveBadge} · M30`, titleColor: C.red, badgeColor: C.gold }}
      >
        <Text style={styles.sectionLbl}>① IMMEDIATE S&R ZONES</Text>
        <View style={styles.twoCol}>
          <View style={styles.immedResBox}>
            <Text style={styles.imLbl}>IMMED RESISTANCE</Text>
            <Text style={styles.imResVal}>{sr.immRes ? fmtNum(sr.immRes) : '—'}</Text>
            <Text style={styles.imSmall}>M30 Swing High · Resistance</Text>
            <Text style={styles.imDistRes}>+{sr.distRes}p away</Text>
          </View>
          <View style={styles.immedSupBox}>
            <Text style={styles.imLbl}>IMMED SUPPORT</Text>
            <Text style={styles.imSupVal}>{sr.immSup ? fmtNum(sr.immSup) : '—'}</Text>
            <Text style={styles.imSmall}>M30 Swing Low · Support</Text>
            <Text style={styles.imDistSup}>-{sr.distSup}p away</Text>
          </View>
        </View>
        <Row style={styles.currPriceRow}>
          <Text style={styles.currLbl}>CURRENT PRICE</Text>
            <Text style={styles.currVal}>{fmtNum(sr.currentPrice)}</Text>
          <Text style={styles.currPos}>{sr.pos}</Text>
        </Row>
        <Text style={styles.sectionLbl}>② NEXT POINT OF INTEREST (POI)</Text>
        <View style={styles.twoCol}>
          <View style={styles.poiResBox}>
            <Text style={styles.imLbl}>NEXT POI RES</Text>
            <Text style={styles.poiResVal}>{sr.poiRes ? fmtNum(sr.poiRes) : '—'}</Text>
            <Text style={styles.imSmall}>+{sr.distPoiRes}p from entry</Text>
          </View>
          <View style={styles.poiSupBox}>
            <Text style={styles.imLbl}>NEXT POI SUP</Text>
            <Text style={styles.poiSupVal}>{sr.poiSup ? fmtNum(sr.poiSup) : '—'}</Text>
            <Text style={styles.imSmall}>-{sr.distPoiSup}p from entry</Text>
          </View>
        </View>
      </Panel>

      <Panel
        shell={styles.flipShell}
        headTint={styles.flipHeadTint}
        head={{ title: 'Flip Engine', badge: `${liveBadge} · S/R`, titleColor: C.amber, badgeColor: C.gold }}
      >
        <Text style={styles.sectionLbl}>③ LEVEL FLIP STATUS (M30 pivots)</Text>
        <View style={styles.flipSupOuter}>
          <View style={styles.flipAccentGreen} />
          <View style={{ paddingLeft: 11 }}>
            <Text style={styles.flipGreenLbl}>RESISTANCE → SUPPORT (R flipped)</Text>
            <Text style={styles.flipSupLvl}>
              {esr?.r1Flipped
                ? 'PREV RES → NOW SUPPORT · M30 R1'
                : esr?.r1 != null
                  ? 'Watching R1 ' + fmtNum(esr.r1)
                  : '—'}
            </Text>
            <Text style={styles.imSmall}>Pine: close &gt; R + zone → teal zone (engine replay).</Text>
            <Row style={{ marginTop: 6, gap: 6 }}>
              <Text style={styles.miniTagG}>{esr?.r1Flipped ? 'FLIPPED ✓' : 'SCAN'}</Text>
            </Row>
          </View>
        </View>
        <View style={styles.flipResOuter}>
          <View style={styles.flipAccentRed} />
          <View style={{ paddingLeft: 11 }}>
            <Text style={styles.flipDimLbl}>SUPPORT → RESISTANCE (S flipped)</Text>
            <Text style={[styles.flipResLvl, !esr?.s1Flipped && { opacity: 0.75 }]}>
              {esr?.s1Flipped
                ? 'PREV SUP → NOW RESISTANCE · M30 S1'
                : esr?.s1 != null
                  ? 'Watching S1 ' + fmtNum(esr.s1)
                  : '—'}
            </Text>
            <Text style={styles.imSmall}>Pine: close &lt; S − zone → orange zone.</Text>
            <Text style={[styles.miniTagWatch, { marginTop: 6 }]}>{esr?.s1Flipped ? 'FLIPPED' : 'WATCHING'}</Text>
          </View>
        </View>
        <View style={styles.flipRuleBox}>
          <Text style={styles.flipRuleTxt}>
            FLIP RULE: M30 candle closes ABOVE resistance → that level becomes new Support → E3 RETEST entry on next return to the zone.
            {'\n'}Reverse applies for support breaking below.
          </Text>
        </View>
      </Panel>

      <Panel shell={styles.scanShell} headTint={styles.scanHeadTint} head={{ title: 'Left Side Scanner', badge: 'BOTH SIDES · v3.2', titleColor: C.blue, badgeColor: C.gold }}>
        <Text style={styles.sectionLbl}>④ LEFT SIDE CLEAN CHECK — FROM ENTRY</Text>
        <Text style={styles.pathLblG}>▲ BULL PATH — ENTRY → RESISTANCE</Text>
        <ScannerRows sr={sr} bull />
        <VerdictBar ok={sr.bullClean} bull />
        <Text style={[styles.pathLblR, { marginTop: 10 }]}>▼ BEAR PATH — ENTRY → SUPPORT</Text>
        <ScannerRows sr={sr} bull={false} />
        <VerdictBar ok={sr.bearClean} bull={false} />
        <View style={[styles.lsVerdictBox, { borderColor: sr.verdictBorder, backgroundColor: sr.verdictBg }]}>
          <Text style={[styles.lsVerdictLbl, { color: sr.verdictLabelColor }]}>TRADEABLE DIRECTION</Text>
          <Text style={[styles.lsVerdictVal, { color: sr.verdictValColor }]}>{sr.verdictVal}</Text>
          <Text style={styles.lsVerdictSub}>{sr.verdictSub}</Text>
        </View>
      </Panel>

      <Panel shell={styles.gmPanelShell} headTint={styles.gmHeaderTint} head={{ title: 'DXY Confirmation', badge: 'NEW · v3', titleColor: C.teal, badgeColor: C.gold }}>
        <DxyRow l="DXY Level" v={dxyLive != null ? dxyLive.toFixed(2) : '—'} vc={C.text} />
        <DxyRow
          l="Direction (3-bar)"
          v={risk?.dxyRising ? '▲ RISING' : '▼ FALLING / FLAT'}
          vc={risk?.dxyRising ? C.red : C.green}
        />
        <DxyRow l="Buy filter" v={risk?.dxyBlocksBuy ? 'BLOCKED (rising DXY)' : 'OK'} vc={risk?.dxyBlocksBuy ? C.red : C.green} />
        <DxyRow l="Gold Impact" v={risk?.dxyBlocksBuy ? 'Buys gated' : 'Buys allowed'} vc={risk?.dxyBlocksBuy ? C.red : C.green} />
        <Text style={styles.dxyFoot}>{risk?.dxyBlocksBuy ? '⛔ DXY RISING → PINE BLOCKS BUYS' : '✓ DXY FILTER CLEAR FOR BUYS'}</Text>
      </Panel>

      <Panel shell={styles.gmPanelShell} headTint={styles.gmHeaderTint} head={{ title: 'Chop Detector', badge: 'NEW · v3', titleColor: C.amber, badgeColor: C.gold }}>
        <View style={styles.chopActive}>
          <Text style={[styles.chopWord, { color: risk?.chopZone ? C.amber : C.green }]}>
            {risk?.chopZone ? 'CHOP ZONE' : 'NORMAL'}
          </Text>
          <Text style={[styles.chopSub, { color: risk?.chopZone ? C.amber : C.dim }]}>
            Last 3 H4 ranges &lt; 40p — {risk?.chopZone ? 'compression advisory' : 'normal volatility'}
          </Text>
        </View>
        <DxyRow l="P2 wick path" v={risk?.chopZone ? 'ADVISORY' : 'ACTIVE'} vc={risk?.chopZone ? C.amber : C.green} />
        <DxyRow l="P1 breakout" v={jLive.p1} vc={jLive.p1 === 'LIVE' ? C.green : C.dim} />
      </Panel>

      <Panel shell={styles.gmPanelShell} headTint={styles.gmHeaderTint} head={{ title: 'ATH Wick Awareness', badge: 'NEW · v3', titleColor: C.red, badgeColor: C.gold }}>
        <View style={styles.athZone}>
          <Text style={styles.athTitle}>☠ ATH NO-BUY ZONE (Pine)</Text>
          <Text style={styles.athRange}>{`$${fmtNum(athLo, 0)} – $${fmtNum(athHi, 0)}`}</Text>
          <Text style={styles.athSub}>{`close ≥ ${fmtNum(athLo, 0)} → ath_zone_blocked → hard_block_buy`}</Text>
        </View>
        <DxyRow l="Zone status" v={risk?.athZoneBlocked ? 'INSIDE / TOUCHING' : 'CLEAR'} vc={risk?.athZoneBlocked ? C.red : C.green} />
        <DxyRow l="Buys" v={risk?.athZoneBlocked ? 'BLOCKED' : 'OK'} vc={risk?.athZoneBlocked ? C.red : C.green} />
      </Panel>
    </View>
  );
}

function Panel({ shell, headTint, head: { title, badge, titleColor, badgeColor }, children }) {
  const { colors: C, styles } = useBilshenzTheme();
  return (
    <View style={[styles.pnl, shell]}>
      <Row style={[styles.ph, headTint]}>
        <Text style={[styles.phT, titleColor ? { color: titleColor } : null]}>{title}</Text>
        <Text style={[styles.phB, badgeColor ? { color: badgeColor } : null]}>{badge}</Text>
      </Row>
      <View style={styles.pb}>{children}</View>
    </View>
  );
}

function TfRow({ l, r, rStyle }) {
  const { colors: C, styles } = useBilshenzTheme();
  return (
    <Row style={styles.tfRow}>
      <Text style={styles.tfl}>{l}</Text>
      <Text style={[styles.tfv, rStyle]}>{r}</Text>
    </Row>
  );
}

function DxyRow({ l, v, vc }) {
  const { colors: C, styles } = useBilshenzTheme();
  return (
    <Row style={styles.dxyRow}>
      <Text style={styles.dxyL}>{l}</Text>
      <Text style={[styles.dxyV, { color: vc }]}>{v}</Text>
    </Row>
  );
}

function ScannerRows({ sr, bull }) {
  const { colors: C, styles } = useBilshenzTheme();
  const pips = bull ? sr.bullPips : sr.bearPips;
  const chop = bull ? sr.bullChop : sr.bearChop;
  const clean = bull ? sr.bullClean : sr.bearClean;
  const qualOk = pips >= 25;
  const chopOk = chop <= 3;
  const row = (a, b, bc) => (
    <Row style={styles.lsRow}>
      <Text style={styles.lsRowL}>{a}</Text>
      <Text style={[styles.lsRowR, bc]}>{b}</Text>
    </Row>
  );
  const qualTxt = qualOk ? '✓ QUALIFIES ≥25p' : '✗ BELOW 25p';
  const chopTxt = chop + (chopOk ? ' — OK (≤3)' : ' — BLOCKED');
  const sideTxt = clean ? '✓ CLEAN' : pips >= 25 ? '⚠ CHOP DETECTED' : '✗ DIRTY';
  const rng = (bull ? '+' : '-') + pips.toFixed(1) + 'p';
  const rngColor =
    clean ? (bull ? C.green : C.red) : pips >= 25 ? C.amber : bull ? C.red : C.amber;

  /** Pine-style zone strip: green = clean path, amber = chop/dirty but ≥25p, red-tint = blocked */
  const zoneH = Math.min(112, Math.max(52, 40 + Math.round(pips * 0.85)));
  const zoneBg = clean
    ? bull
      ? 'rgba(0,230,118,0.16)'
      : 'rgba(255,61,87,0.14)'
    : pips >= 25
      ? 'rgba(255,179,0,0.14)'
      : bull
        ? 'rgba(255,61,87,0.09)'
        : 'rgba(255,179,0,0.1)';
  const zoneBorder = clean
    ? bull
      ? 'rgba(0,230,118,0.55)'
      : 'rgba(255,61,87,0.5)'
    : 'rgba(255,179,0,0.55)';

  return (
    <View style={styles.lsPanel}>
      <View
        style={[
          styles.lsZoneBox,
          {
            minHeight: zoneH,
            backgroundColor: zoneBg,
            borderColor: zoneBorder,
            borderStyle: clean ? 'solid' : 'dashed',
          },
        ]}>
        <Text style={styles.lsZonePath}>{bull ? 'ENTRY → IMMED RES' : 'ENTRY → IMMED SUP'}</Text>
        <Text style={[styles.lsZonePips, { color: rngColor }]}>{rng}</Text>
        <Text style={styles.lsZoneChop}>
          Chop {chop} / 3 max · {qualOk ? '≥25p range' : '<25p range'}
        </Text>
        <Text style={[styles.lsZoneStatus, { color: clean ? C.green : pips >= 25 ? C.amber : C.red }]}>{sideTxt}</Text>
      </View>
      {row('≥ 25 pips?', qualTxt, qualOk ? styles.tfBull : styles.tfBear)}
      {row('Chop closes (Pine LS)', chopTxt, chopOk ? styles.tfBull : styles.tfBear)}
      {row('Left side status', sideTxt, clean ? styles.tfBull : pips >= 25 ? styles.tfNeu : styles.tfBear)}
    </View>
  );
}

function VerdictBar({ ok, bull }) {
  const { colors: C, styles } = useBilshenzTheme();
  const txt = ok ? (bull ? '✅ BULL PATH — TRADEABLE' : '✅ BEAR PATH — TRADEABLE') : bull ? '❌ BULL PATH — NO TRADE' : '❌ BEAR PATH — NO TRADE';
  return (
    <View
      style={[
        styles.pathVerdict,
        { borderColor: ok ? 'rgba(0,230,118,0.25)' : 'rgba(255,61,87,0.25)', backgroundColor: ok ? 'rgba(0,230,118,0.08)' : 'rgba(255,61,87,0.08)' },
      ]}>
      <Text style={{ fontSize: 8, fontWeight: '800', textAlign: 'center', color: ok ? C.green : C.red }}>{txt}</Text>
    </View>
  );
}

function ScannerTabPanels({ sr }) {
  const { colors: C, styles } = useBilshenzTheme();
  return (
    <View style={styles.leftCol}>
      <Panel shell={styles.srPanelShell} headTint={styles.srHeadTint} head={{ title: 'S&R Engine', badge: 'M30 ZONES · v3.2', titleColor: C.red, badgeColor: C.gold }}>
        <Text style={styles.sectionLbl}>① IMMEDIATE S&R ZONES</Text>
        <View style={styles.twoCol}>
          <View style={styles.immedResBox}>
            <Text style={styles.imLbl}>IMMED RESISTANCE</Text>
            <Text style={styles.imResVal}>{sr.immRes ? fmtNum(sr.immRes) : '—'}</Text>
            <Text style={styles.imSmall}>M30 Swing High · Resistance</Text>
            <Text style={styles.imDistRes}>+{sr.distRes}p away</Text>
          </View>
          <View style={styles.immedSupBox}>
            <Text style={styles.imLbl}>IMMED SUPPORT</Text>
            <Text style={styles.imSupVal}>{sr.immSup ? fmtNum(sr.immSup) : '—'}</Text>
            <Text style={styles.imSmall}>M30 Swing Low · Support</Text>
            <Text style={styles.imDistSup}>-{sr.distSup}p away</Text>
          </View>
        </View>
        <Row style={styles.currPriceRow}>
          <Text style={styles.currLbl}>CURRENT PRICE</Text>
          <Text style={styles.currVal}>{fmtNum(sr.currentPrice)}</Text>
          <Text style={styles.currPos}>{sr.pos}</Text>
        </Row>
        <Text style={styles.sectionLbl}>② NEXT POINT OF INTEREST (POI)</Text>
        <View style={styles.twoCol}>
          <View style={styles.poiResBox}>
            <Text style={styles.imLbl}>NEXT POI RES</Text>
            <Text style={styles.poiResVal}>{sr.poiRes ? fmtNum(sr.poiRes) : '—'}</Text>
            <Text style={styles.imSmall}>+{sr.distPoiRes}p from entry</Text>
          </View>
          <View style={styles.poiSupBox}>
            <Text style={styles.imLbl}>NEXT POI SUP</Text>
            <Text style={styles.poiSupVal}>{sr.poiSup ? fmtNum(sr.poiSup) : '—'}</Text>
            <Text style={styles.imSmall}>-{sr.distPoiSup}p from entry</Text>
          </View>
        </View>
      </Panel>

      <Panel shell={styles.scanShell} headTint={styles.scanHeadTint} head={{ title: 'Left Side Scanner', badge: 'BOTH SIDES · v3.2', titleColor: C.blue, badgeColor: C.gold }}>
        <Text style={styles.sectionLbl}>④ LEFT SIDE CLEAN CHECK — FROM ENTRY</Text>
        <Text style={styles.pathLblG}>▲ BULL PATH — ENTRY → RESISTANCE</Text>
        <ScannerRows sr={sr} bull />
        <VerdictBar ok={sr.bullClean} bull />
        <Text style={[styles.pathLblR, { marginTop: 10 }]}>▼ BEAR PATH — ENTRY → SUPPORT</Text>
        <ScannerRows sr={sr} bull={false} />
        <VerdictBar ok={sr.bearClean} bull={false} />
        <View style={[styles.lsVerdictBox, { borderColor: sr.verdictBorder, backgroundColor: sr.verdictBg }]}>
          <Text style={[styles.lsVerdictLbl, { color: sr.verdictLabelColor }]}>TRADEABLE DIRECTION</Text>
          <Text style={[styles.lsVerdictVal, { color: sr.verdictValColor }]}>{sr.verdictVal}</Text>
          <Text style={styles.lsVerdictSub}>{sr.verdictSub}</Text>
        </View>
      </Panel>
    </View>
  );
}

function CenterColumn({
  price,
  sr,
  spread,
  spreadOkColor,
  spHigh,
  sessionBits,
  dayBits,
  sigMuted,
  sigPill,
  pillStyle,
  chartPts,
  execBusy,
  tradeCount,
  onExecute,
  onSkip,
  atr,
  atrFillPct,
  atrModePill,
  engineTrade,
  histRows,
  accountEquity,
  mt5LiveAccount,
  mt5Account,
  variant = 'dashboard',
  compactSignal = false,
}) {
  const { colors: C, styles } = useBilshenzTheme();
  const engCtx = useContext(BilshenzEngineCtx);
  const snap = engCtx?.snapshot;
  const cfg = engCtx?.cfg;
  const engineReady = engCtx?.hydrated === true;
  const pip = cfg?.pipSize ?? 0.1;
  const er = snap?.risk;
  const eg = snap?.gates;
  const tradeCap = cfg?.maxDailyTrades ?? 5;
  const tradeCountDisp = engineReady ? tradeCount : '—';
  const trade = engineTrade;
  const wickM = snap?.wick;
  const jLive = jimplasSetupLive(snap?.signals);
  const lv = snap?.structureLevels;
  const srE = snap?.sr;
  const geoRg = cfg?.geoRisk ?? 'LOW';
  const effRiskPct = effectiveRiskPctFromEngine(geoRg, er?.atrPips ?? null, cfg);
  const wickLines = wickM ? wickStoryLines(wickM, pip) : { main: 'M30 wick scan — engine idle', sub: '—' };
  const sideLbl = trade?.side === 'SELL' ? 'SELL' : trade?.side === 'BUY' ? 'BUY' : 'SCAN';
  const isSell = trade?.side === 'SELL';
  const accentDyn = [styles.sigAccent, isSell ? { backgroundColor: C.red } : null];
  const badgeDyn = [
    styles.sigBuyBadge,
    isSell ? { borderColor: 'rgba(255,61,87,0.35)', backgroundColor: 'rgba(255,61,87,0.06)' } : null,
  ];
  const sideColor = isSell ? C.red : trade?.side === 'BUY' ? C.green : C.dim;
  const entPx = trade?.entry != null && Number.isFinite(trade.entry) ? trade.entry : price;
  const slPx = trade?.sl;
  const tp1Px = trade?.tp1;
  const tp2Px = pickTp2FromSnapshot(trade, srE, lv);
  const beOff = cfg?.beOffset ?? 1.2;
  const bePips = Math.max(1, Math.round(beOff / pip));
  const bePx = trade?.side === 'SELL' ? entPx - beOff : trade?.side === 'BUY' ? entPx + beOff : entPx + beOff;
  const simUsd = cfg?.simUsdPerEnginePip ?? defaultBilshenzConfig.simUsdPerEnginePip;
  const tradeSizing = sizingForTrade(
    { side: trade?.side, entry: entPx, sl: slPx, tp1: tp1Px },
    cfg,
    accountEquity,
    effRiskPct
  );
  const slPipsE = tradeSizing.structuralSlPips;
  const sizingSlPips = tradeSizing.sizingSlPips;
  const riskUsd = Math.round(tradeSizing.riskUsd);
  const lotStr = tradeSizing.lots > 0 ? tradeSizing.lots.toFixed(2) : '—';
  const rrDisp =
    sizingSlPips > 0 && tp1Px != null && Number.isFinite(tp1Px)
      ? `1 : ${(Math.abs(tp1Px - entPx) / pip / sizingSlPips).toFixed(1)}`
      : trade?.rr != null && Number.isFinite(trade.rr)
        ? `1 : ${trade.rr.toFixed(1)}`
        : '—';
  const rewardUsd =
    tradeSizing.rewardUsd > 0
      ? Math.round(tradeSizing.rewardUsd)
      : trade?.rr != null && Number.isFinite(trade.rr)
        ? Math.round(riskUsd * trade.rr)
        : Math.round(riskUsd * 1.8);
  const fmtPx = (x) => (x != null && Number.isFinite(x) ? fmtNum(x) : '—');
  const athLo = cfg?.athZoneLow ?? 5278;
  const athHi = cfg?.athZoneHigh ?? 5602;
  const maxSpr = cfg?.maxSpreadPips ?? 3.5;
  const minRp = cfg?.minRangePips ?? 25;
  const equityLbl = mt5LiveAccount
    ? `$${Math.round(accountEquity).toLocaleString('en-US')} MT5`
    : `$${Math.round(SIM_DESK_EQUITY / 1000)}k sim`;
  const riskAtPct = Math.round(accountEquity * (effRiskPct / 100));
  const normPct = cfg?.riskPctAtrNormal ?? 1;
  const elevPct = cfg?.riskPctAtrElevated ?? 0.7;
  const crisisPct = cfg?.riskPctAtrCrisis ?? 0.5;
  const currentRiskLbl = `${effRiskPct.toFixed(2)}% · ${fmtUsd(riskAtPct)} at risk`;
  const sizeModeLbl = er?.geoHigh ? `GEO cap ${effRiskPct.toFixed(2)}%` : `${effRiskPct.toFixed(2)}% of balance`;
  const tp2Sub = er?.yieldHigh ? 'TP2 −30% (yield rule)' : 'Next ladder zone';
  const tp1Sub =
    cfg?.useLegacyTpClampOnly && cfg?.tp1MinRewardPips != null
      ? `Clamp ${cfg.tp1MinRewardPips}–${cfg.tp1MaxRewardPips} pips`
      : 'Structure target';
  const slSub =
    trade?.side && (cfg?.journalSizingSlPips ?? 0) > 0 && slPipsE > sizingSlPips + 0.05
      ? `Chart SL · lots on ${sizingSlPips}p risk`
      : trade?.side === 'SELL'
        ? 'Above entry + buffer'
        : trade?.side === 'BUY'
          ? 'Below entry − buffer'
          : 'Structure + buffer';
  const grabLbl = activeSetupGrabLbl(snap?.signals);
  const stratModeLbl = jimplasStrategyModeLine(cfg);
  const fSpreadCol = spHigh ? C.red : C.green;
  const rangeCol = sr.bullClean ? C.green : C.amber;
  const modeCls =
    atrModePill.cls === 'std' ? styles.modeStd : atrModePill.cls === 'amb' ? styles.modeAmb : styles.modeRed;

  return (
    <View style={styles.centerCol}>
      <View style={[styles.sigCard, compactSignal && styles.sigCardCompact, sigMuted && { opacity: 0.25 }]}>
        <View style={styles.sigGlow} />
        <View style={accentDyn} />
        {compactSignal ? (
          <View style={styles.sigInnerStack}>
            <Row style={styles.sigTopTrade}>
              <View style={badgeDyn}>
                <Text style={[styles.sigAction, styles.sigActionCompact, { color: sideColor }]}>{sideLbl}</Text>
              </View>
              <View style={styles.sigInfoCompact}>
                <Text style={styles.sigPairCompact}>XAU / USD — SPOT GOLD</Text>
                <Text style={[styles.sigPill, pillStyle]}>{sigPill.text}</Text>
                <Text style={styles.sigConfCompact}>
                  ⬡ ENGINE GATES · CONFIDENCE {engineTrade?.confidencePct?.toFixed(1) ?? '—'}%
                </Text>
                <Text style={styles.sigStratCompact} numberOfLines={3}>
                  {engineTrade?.reason ?? 'Awaiting Jimplas Fluidity setup (P1/P2/P3)…'}
                </Text>
                {engineTrade?.m15EarlyExit ? (
                  <Text style={styles.sigStratCompact} numberOfLines={2}>
                    ⚠ {engineTrade.m15EarlyExit.message} · exit ≈ {engineTrade.m15EarlyExit.exitPrice.toFixed(2)}
                  </Text>
                ) : null}
              </View>
            </Row>
            <Text style={styles.sigSessCompact}>📍 {sessionBits.sessLabel}</Text>
            <Row style={styles.sigBtnRow}>
              <TouchableOpacity
                activeOpacity={0.85}
                style={[styles.execBtn, styles.execBtnCompact, execBusy && { opacity: 0.6 }]}
                onPress={onExecute}
                disabled={execBusy || !engineReady || tradeCount >= tradeCap}>
                <Text style={styles.execBtnTxtCompact}>
                  {!engineReady
                    ? '⏳ SYNC…'
                    : execBusy
                      ? '⏳ PROCESSING...'
                      : tradeCount >= tradeCap
                        ? 'MAX TRADES'
                        : '⚡ EXECUTE'}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity activeOpacity={0.85} style={[styles.skipBtn, styles.skipBtnCompact]} onPress={onSkip}>
                <Text style={styles.skipBtnTxtCompact}>✕ SKIP</Text>
              </TouchableOpacity>
            </Row>
          </View>
        ) : (
          <Row style={styles.sigInner}>
            <Row style={styles.sigL}>
              <Text style={[styles.sigAction, { color: sideColor }]}>{sideLbl}</Text>
              <View style={styles.sigInfo}>
                <Text style={styles.sigPair}>XAU / USD — SPOT GOLD</Text>
                <Text style={[styles.sigPill, pillStyle]}>{sigPill.text}</Text>
                <Text style={styles.sigConf}>
                  ⬡ ENGINE GATES · CONFIDENCE {engineTrade?.confidencePct?.toFixed(1) ?? '—'}%
                </Text>
                <Text style={styles.sigStrat} numberOfLines={3}>
                  {engineTrade?.reason ?? 'Awaiting Jimplas Fluidity setup (P1/P2/P3)…'}
                </Text>
                {engineTrade?.m15EarlyExit ? (
                  <Text style={styles.sigStrat} numberOfLines={2}>
                    ⚠ {engineTrade.m15EarlyExit.message} · exit ≈ {engineTrade.m15EarlyExit.exitPrice.toFixed(2)}
                  </Text>
                ) : null}
              </View>
            </Row>
            <View style={styles.sigR}>
              <Text style={styles.sigSess}>📍 {sessionBits.sessLabel}</Text>
              <TouchableOpacity
                activeOpacity={0.85}
                style={[styles.execBtn, execBusy && { opacity: 0.6 }]}
                onPress={onExecute}
                disabled={execBusy || !engineReady || tradeCount >= tradeCap}>
                <Text style={styles.execBtnTxt}>
                  {!engineReady
                    ? '⏳ SYNC…'
                    : execBusy
                      ? '⏳ PROCESSING...'
                      : tradeCount >= tradeCap
                        ? 'MAX TRADES'
                        : '⚡ EXECUTE'}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity activeOpacity={0.85} style={styles.skipBtn} onPress={onSkip}>
                <Text style={styles.skipBtnTxt}>✕ SKIP</Text>
              </TouchableOpacity>
            </View>
          </Row>
        )}
        <Text style={[styles.sigWatermark, compactSignal && styles.sigWatermarkCompact]}>BILSHENZ V3</Text>
      </View>

      <View style={styles.filterGrid}>
        <FilterCell lab="SPREAD" val={`${spread.toFixed(2)}p`} sub={`✓ ≤${maxSpr}`} box="ok" valColor={fSpreadCol} />
        <FilterCell
          lab="GEO RISK"
          val={er?.geoHigh ? 'HIGH' : er?.geoMedium ? 'MED' : 'LOW'}
          sub={er?.geoHigh ? '⚠ Hard gates' : er?.geoMedium ? '⚠ Monitor' : '✓ Clear'}
          box={er?.geoHigh ? 'warn' : er?.geoMedium ? 'amb' : 'ok'}
          valColor={er?.geoHigh ? C.red : er?.geoMedium ? C.amber : C.green}
        />
        <FilterCell
          lab="DXY"
          val={er?.dxyRising ? 'RISE' : 'FALL'}
          sub={er?.dxyBlocksBuy ? '✗ Buys gated' : '✓ Buys OK'}
          box={er?.dxyBlocksBuy ? 'warn' : 'ok'}
          valColor={er?.dxyBlocksBuy ? C.red : C.green}
        />
        <FilterCell
          lab="CHOP"
          val={er?.chopZone ? 'ACTIVE' : 'CLEAR'}
          sub={er?.chopZone ? '⚠ Wick path' : '✓ All paths'}
          box={er?.chopZone ? 'amb' : 'ok'}
          valColor={er?.chopZone ? C.amber : C.green}
        />
        <FilterCell lab="RANGE" val={`${sr.bullPips.toFixed(1)}p`} sub={`✓ ≥${minRp}`} box="ok" valColor={rangeCol} />
        <FilterCell
          lab="SESSION"
          val={sessionBits.s3 ? 'NY' : sessionBits.s2 ? 'LDN' : sessionBits.s1 ? 'PRE' : '—'}
          sub={sessionBits.act ? '✓ OPEN' : '✗ Standby'}
          box={sessionBits.act ? 'ok' : 'warn'}
          valColor={sessionBits.act ? C.green : C.amber}
        />
        <FilterCell
          lab="YIELD"
          val={engCtx?.snapshot?.us10yClose != null ? `${engCtx.snapshot.us10yClose.toFixed(2)}%` : '—'}
          sub={er?.yieldHigh ? '⚠ TP2 -30%' : '✓ Band OK'}
          box={er?.yieldHigh ? 'warn' : 'ok'}
          valColor={er?.yieldHigh ? C.red : C.green}
        />
        <FilterCell
          lab="BLACKOUT"
          val={eg?.masterBlock ? 'BLOCK' : 'CLEAR'}
          sub={eg?.masterBlock ? '⚠ Gates' : '✓ Flow'}
          box={eg?.masterBlock ? 'warn' : 'ok'}
          valColor={eg?.masterBlock ? C.amber : C.green}
        />
      </View>

      <Row style={styles.wickInd}>
        <Text style={styles.wiIcon}>🕯️</Text>
        <View style={{ flex: 1 }}>
          <Text style={styles.wiMain}>{wickLines.main}</Text>
          <Text style={styles.wiSub}>{wickLines.sub}</Text>
        </View>
      </Row>

      <Panel
        shell={styles.gmPanelShell}
        headTint={styles.gmHeaderTint}
        head={{ title: 'Strategy Mode', badge: 'JIMPLAS', titleColor: C.goldL, badgeColor: C.gold }}
      >
        <Text style={styles.wiMain}>{stratModeLbl}</Text>
        <Text style={[styles.wiSub, { marginTop: 6 }]}>
          {trade?.setup
            ? `Active: ${trade.setup} · ${trade.side ?? '—'}`
            : 'Priority: P1 → P2 → P3 · max ' + (cfg?.maxDailyTrades ?? 3) + ' trades/NY day'}
        </Text>
        <Row style={{ marginTop: 8, gap: 8, flexWrap: 'wrap' }}>
          <Text style={[styles.miniTagG, jLive.p1 === 'LIVE' && { opacity: 1 }]}>P1 {jLive.p1}</Text>
          <Text style={[styles.miniTagG, jLive.p2 === 'LIVE' && { opacity: 1 }]}>P2 {jLive.p2}</Text>
          <Text style={[styles.miniTagWatch, jLive.p3 === 'LIVE' && { color: C.amber }]}>P3 {jLive.p3}</Text>
        </Row>
      </Panel>

      <Panel shell={styles.gmPanelShell} headTint={styles.gmHeaderTint} head={{ title: 'ATR Volatility Sizing', badge: 'NEW · v3', titleColor: C.amber, badgeColor: C.gold }}>
        <Row style={styles.atrRow}>
          <Text style={styles.atrLabel}>ATR-14 (M30)</Text>
          <Text style={styles.atrVal}>{atr.toFixed(1)} pips</Text>
        </Row>
        <View style={styles.atrBarBg}>
          <View style={[styles.atrBarFill, { width: `${atrFillPct}%` }]} />
        </View>
        <Text style={[styles.modePill, modeCls]}>{atrModePill.text}</Text>
        <DxyRow l="ATR <50p" v={pctOfBalanceLabel(normPct, accountEquity, mt5LiveAccount)} vc={C.green} />
        <DxyRow l="ATR 50–100p" v={pctOfBalanceLabel(elevPct, accountEquity, mt5LiveAccount)} vc={C.amber} />
        <DxyRow l="ATR >100p" v={pctOfBalanceLabel(crisisPct, accountEquity, mt5LiveAccount)} vc={C.red} />
        <DxyRow l="Current Risk" v={currentRiskLbl} vc={C.amber} />
        {mt5LiveAccount && mt5Account ? (
          <DxyRow
            l="MT5 Equity"
            v={`$${Math.round(mt5Account.equity ?? accountEquity).toLocaleString('en-US')}`}
            vc={C.text}
          />
        ) : null}
      </Panel>

      <Panel shell={{}} head={{ title: 'Entry & Exit Engine', badge: 'JIMPLAS FLUIDITY' }}>
        <View style={styles.eeGrid}>
          <EeCell lab="Entry Price" val={fmtPx(entPx)} sub={`${effRiskPct.toFixed(2)}% risk tier`} valStyle={styles.eeEntry} />
          <EeCell lab={`BE @ +${bePips}p`} val={fmtPx(bePx)} sub="Move SL to entry" valStyle={styles.eeBe} />
          <EeCell lab="TP1 — Target" val={fmtPx(tp1Px)} sub={tp1Sub} valStyle={styles.eeTp1} />
          <EeCell lab="TP2 — Zone" val={fmtPx(tp2Px)} sub={tp2Sub} valStyle={styles.eeTp2} />
        </View>
        <View style={styles.eeGrid}>
          <EeCell lab="Stop Loss" val={fmtPx(slPx)} sub={slSub} valStyle={styles.eeSl} />
          <EeCell
            lab="Risk $"
            val={`$${riskUsd.toLocaleString('en-US')}`}
            sub={`${effRiskPct.toFixed(2)}% of ${equityLbl}`}
            valStyle={styles.eePlain}
          />
          <EeCell lab="R:R Ratio" val={rrDisp} sub="On journal risk pips" valStyle={styles.eeGold} />
          <EeCell
            lab="Lot Size"
            val={lotStr}
            sub={lotSizeSubtitle(riskUsd, slPipsE, sizingSlPips, simUsd, cfg)}
            valStyle={styles.eePlain}
          />
        </View>
        <Row style={styles.rrStrip}>
          <RrCell lab="REWARD $" val={`$${rewardUsd.toLocaleString('en-US')}`} color={C.green} />
          <RrCell lab="DAY TRADES" val={`${tradeCountDisp} / ${tradeCap}`} color={C.gold} />
          <RrCell lab="SIZE MODE" val={sizeModeLbl} color={C.amber} />
          <RrCell lab="TRAIL" val="H1 Lows" color={C.text} />
          <RrCell lab="DAY MODE" val={dayBits.modeRR} color={dayBits.rrColor} />
        </Row>
      </Panel>

      <Panel shell={{}} head={{ title: 'Price Action · Zone Map', badge: 'M30 · LEFT SIDE CLEAN' }}>
        <View style={styles.chartWrap}>
          <View style={styles.chartAth} />
          <Text style={styles.chartAthTxt}>{`☠ ATH ${fmtNum(athLo, 0)}–${fmtNum(athHi, 0)} — NO BUY`}</Text>
          {chartPts.map(([x, y], i) => (
            <View
              key={i}
              style={[
                styles.chartDot,
                {
                  left: `${(x / 900) * 100}%`,
                  top: `${(y / 120) * 100}%`,
                },
              ]}
            />
          ))}
          <View style={[styles.hLine, { top: '43%' }]}>
            <Text style={[styles.hLineLbl, { color: C.purple, left: 4 }]}>{`BE+${bePips}p`}</Text>
          </View>
          <View style={[styles.hLine, { top: '31%' }]}>
            <Text style={[styles.hLineLbl, { color: C.goldL, left: 4 }]}>
              {tp1Px != null ? `TP1 ${fmtPx(tp1Px)}` : 'TP1 —'}
            </Text>
          </View>
          <View style={[styles.hLine, { top: '18%' }]}>
            <Text style={[styles.hLineLbl, { color: C.gold, left: 4 }]}>
              {tp2Px != null ? `TP2 ${fmtPx(tp2Px)}${er?.yieldHigh ? ' (−30%y)' : ''}` : 'TP2 —'}
            </Text>
          </View>
          <View style={[styles.hLine, { top: '93%' }]}>
            <Text style={[styles.hLineLbl, { color: C.red, left: 4 }]}>{slPx != null ? `SL ${fmtPx(slPx)}` : 'SL —'}</Text>
          </View>
          <View style={[styles.vLine, { left: '56%' }]}>
            <Text style={[styles.vLineLbl, { color: C.green }]}>ENTRY</Text>
          </View>
          <View style={styles.wickGrab} />
          <Text style={styles.wickGrabLbl}>{grabLbl}</Text>
        </View>
      </Panel>

      <Panel shell={{}} head={{ title: 'Signal History', badge: 'JIMPLAS · TODAY' }}>
        <View style={styles.histTableWrap}>
          <HistHeader />
          {(histRows ?? SIGNAL_HISTORY_SIM).map((row, i) => (
            <HistRow key={i} row={row} />
          ))}
        </View>
      </Panel>
    </View>
  );
}

function FilterCell({ lab, val, sub, box, valColor }) {
  const { colors: C, styles } = useBilshenzTheme();
  const bx =
    box === 'ok' ? styles.filtOk : box === 'warn' ? styles.filtWarn : styles.filtAmb;
  return (
    <View style={[styles.filt, bx]}>
      <Text style={styles.filtL}>{lab}</Text>
      <Text style={[styles.filtV, { color: valColor }]}>{val}</Text>
      <Text style={[styles.filtS, { color: valColor }]}>{sub}</Text>
    </View>
  );
}

function EeCell({ lab, val, sub, valStyle }) {
  const { colors: C, styles } = useBilshenzTheme();
  return (
    <View style={styles.eeCell}>
      <Text style={styles.eeL}>{lab}</Text>
      <Text style={[styles.eeV, valStyle]}>{val}</Text>
      <Text style={styles.eeS}>{sub}</Text>
    </View>
  );
}

function RrCell({ lab, val, color }) {
  const { colors: C, styles } = useBilshenzTheme();
  return (
    <View style={styles.rri}>
      <Text style={styles.rrl}>{lab}</Text>
      <Text style={[styles.rrv, { color }]}>{val}</Text>
    </View>
  );
}

function HistHeader() {
  const { colors: C, styles } = useBilshenzTheme();
  return (
    <Row style={styles.histHead}>
      <Text style={[styles.histTh, styles.histColUtc]}>UTC</Text>
      <Text style={[styles.histTh, styles.histColDir]}>DIR</Text>
      <View style={styles.histColType}>
        <Text style={styles.histTh}>TYPE</Text>
      </View>
      <Text style={[styles.histTh, styles.histColEntry]}>ENTRY</Text>
      <Text style={[styles.histTh, styles.histColSl]}>SL</Text>
      <Text style={[styles.histTh, styles.histColBe]}>BE</Text>
      <Text style={[styles.histTh, styles.histColPl]}>P&L</Text>
      <Text style={[styles.histTh, styles.histColRes]}>RES</Text>
    </Row>
  );
}

function HistRow({ row }) {
  const { colors: C, styles } = useBilshenzTheme();
  const [utc, dir, typ, e1, e2, e3, e4, res, side, kind] = row;
  if (typ === 'BREAK') {
    return (
      <View style={styles.histRow}>
        <Text style={[styles.histTd, styles.histColUtc]}>{utc}</Text>
        <Text style={[styles.histTd, side === 'buy' ? styles.tBuy : styles.tSell, styles.histColDir]}>{dir}</Text>
        <View style={styles.histColType}>
          <Text style={[styles.eb, styles.ebB]}>P1</Text>
        </View>
        <Text
          style={[styles.histTd, styles.histColEntry, styles.histBreakMsg]}
          numberOfLines={2}
          ellipsizeMode="tail">
          {e1}
        </Text>
        <Text style={[styles.histTd, styles.histColSl, styles.histDashCell]}>—</Text>
        <Text style={[styles.histTd, styles.histColBe, styles.histDashCell]}>—</Text>
        <Text style={[styles.histTd, styles.histColPl, styles.histDashCell]}>—</Text>
        <Text style={[styles.histTd, styles.histColRes, styles.histDashCell]}>—</Text>
      </View>
    );
  }
  const typLbl = typ === 'WICK' ? 'P2' : typ === 'FLIP' ? 'P3' : typ;
  const eb =
    typLbl === 'P2'
      ? styles.ebW
      : typLbl === 'P1'
        ? styles.ebB
        : typLbl === 'P3'
          ? styles.ebF
          : styles.ebF;
  const plStyle =
    kind === 'win' ? styles.tWin : kind === 'loss' ? styles.tLoss : kind === 'open' ? styles.tOpen : styles.histTd;
  return (
    <View style={styles.histRow}>
      <Text style={[styles.histTd, styles.histColUtc]}>{utc}</Text>
      <Text style={[styles.histTd, side === 'buy' ? styles.tBuy : styles.tSell, styles.histColDir]}>{dir}</Text>
      <View style={styles.histColType}>
        <Text style={[styles.eb, eb]}>{typLbl}</Text>
      </View>
      <Text style={[styles.histTd, styles.histColEntry]} numberOfLines={2} ellipsizeMode="tail">
        {e1}
      </Text>
      <Text style={[styles.histTd, styles.histColSl]} numberOfLines={1} ellipsizeMode="tail">
        {e2}
      </Text>
      <Text
        style={[styles.histTd, styles.histColBe, kind === 'win' ? styles.tWin : kind === 'open' ? styles.tOpen : null]}
        numberOfLines={1}
        ellipsizeMode="tail">
        {e3}
      </Text>
      <Text style={[styles.histTd, plStyle, styles.histColPl]} numberOfLines={1} ellipsizeMode="tail">
        {e4}
      </Text>
      <Text style={[styles.histTd, plStyle, styles.histColRes]} numberOfLines={1} ellipsizeMode="tail">
        {res}
      </Text>
    </View>
  );
}

function RightColumn({
  tradeCount,
  pnl,
  sessTag,
  spread,
  spreadOkColor,
  spHigh,
  dayBits,
  accountEquity,
  mt5LiveAccount,
  mt5Account,
}) {
  const { colors: C, styles } = useBilshenzTheme();
  const pr = Math.round(pnl);
  const pnlColor = pr >= 0 ? C.green : C.red;
  const eng = useContext(BilshenzEngineCtx);
  const snap = eng?.snapshot;
  const wr = snap?.winRate;
  const g = snap?.gates;
  const r = snap?.risk;
  const yClose = snap?.us10yClose;
  const winRateStr = wr && wr.totalWins + wr.totalLosses > 0 ? `${wr.winRatePct.toFixed(1)}%` : '—';
  const closedN = wr ? wr.totalWins + wr.totalLosses : 0;
  const yieldPctStr = yClose != null ? `${yClose.toFixed(2)}%` : '—';
  const yieldRule = r?.yieldHigh ? 'TP2 -30% ACTIVE' : yClose != null && yClose > 4.0 ? 'TP2 -15% band' : 'Normal TPs';
  const tradeCap = eng?.cfg?.maxDailyTrades ?? 5;
  const tradeCountDisp = eng?.hydrated === true ? tradeCount : '—';
  const cfg = eng?.cfg;
  const geoTier = cfg?.geoRisk ?? 'LOW';
  const pipRm = cfg?.pipSize ?? 0.1;
  const effPct = effectiveRiskPctFromEngine(geoTier, r?.atrPips ?? null, cfg);
  const bePipsRm = Math.max(1, Math.round((cfg?.beOffset ?? 1.2) / pipRm));
  const atrShort = r?.atrMode?.split('—')[0]?.trim() ?? '—';
  const activeRiskStr = `${geoTier} → ${effPct.toFixed(2)}%`;
  const effRiskStr = `${effPct.toFixed(2)}% (${atrShort})`;
  const dynEntStr = r?.geoHigh ? 'SUSPENDED · GEO=HIGH' : r?.chopZone ? 'ACTIVE · H4 CHOP ADVISORY' : 'ACTIVE';
  const maxNorm = cfg?.riskPctAtrNormal ?? 1;
  const elevPct = cfg?.riskPctAtrElevated ?? 0.7;
  const crisisPct = cfg?.riskPctAtrCrisis ?? 0.5;
  const riskUsdNow = Math.round(accountEquity * (effPct / 100));
  const riskUsdMax = Math.round(accountEquity * (maxNorm / 100));
  const rmPctWidth = `${Math.min(100, maxNorm > 0 ? (effPct / maxNorm) * 100 : 0)}%`;
  const yFillW =
    yClose != null ? `${Math.min(100, Math.max(0, ((yClose - 3) / 2) * 100))}%` : '74%';
  const geoVc = geoTier === 'HIGH' ? C.red : geoTier === 'MEDIUM' ? C.amber : C.green;
  const maxSpr = cfg?.maxSpreadPips ?? 3.5;
  const simUsd = cfg?.simUsdPerEnginePip ?? defaultBilshenzConfig.simUsdPerEnginePip;
  const journalRows = eng?.journalRows ?? [];
  const jStat = journalClosedStats(journalRows, pipRm);
  const closedUsd = mt5LiveAccount
    ? Math.round(journalClosedUsd(journalRows, cfg, accountEquity, effPct))
    : Math.round(jStat.netP * simUsd);
  const closedTodayVal = fmtUsd(closedUsd);
  const closedTodayCol = closedUsd >= 0 ? C.green : C.red;
  const openTrade = snap?.trade;
  const openSizing = sizingForTrade(openTrade, cfg, accountEquity, effPct);
  const openLotsStr = openSizing.lots > 0 ? openSizing.lots.toFixed(2) : '—';
  const openSlPips = openSizing.structuralSlPips;
  const openSizingSlPips = openSizing.sizingSlPips;
  const pfVal = jStat.pfStr;
  const pfNum = parseFloat(jStat.pfStr);
  const pfCol =
    jStat.pfStr === '—' ? C.dim : jStat.pfStr === '∞' || (!Number.isNaN(pfNum) && pfNum >= 1) ? C.green : C.amber;
  const newsOn = !!cfg?.newsActive;
  const nfpOn = !!cfg?.nfpBlackout;
  const newsHead =
    g?.masterBlock && (newsOn || nfpOn)
      ? '⚠ GATES — NEWS / BLACKOUT'
      : newsOn
        ? '⚠ NEWS WINDOW (SIM ±15m)'
        : nfpOn
          ? '⚠ NFP BLACKOUT SIM ON'
          : '✓ CLEAR — NO ACTIVE BLOCK';

  return (
    <View style={styles.rightCol}>
      <Panel shell={{}} head={{ title: 'Live P&L', badge: mt5LiveAccount ? 'MT5' : sessTag }}>
        <View style={styles.pnlHero}>
          <Text style={styles.pnlTag}>{mt5LiveAccount ? 'FLOATING P&L (MT5)' : 'UNREALIZED P&L (USD)'}</Text>
          <Text style={[styles.pnlNum, { color: pnlColor }]}>{fmtUsd(pr)}</Text>
          <Text style={styles.pnlPips}>
            {mt5LiveAccount
              ? `Account profit · risk ${effPct.toFixed(2)}% = ${fmtUsd(riskUsdNow)}`
              : `${pr >= 0 ? '+' : ''}${(Math.abs(pr) / 10).toFixed(1)} pips · sim`}
          </Text>
        </View>
        <View style={styles.pnlMini}>
          <PmCell lab="Closed Today" val={closedTodayVal} c={closedTodayCol} />
          <PmCell lab="Win Rate" val={winRateStr} />
          <PmCell lab="Trades/Max" val={`${tradeCountDisp} / ${tradeCap}`} />
          <PmCell lab="Closed (engine)" val={String(closedN)} />
          <PmCell lab="Profit Factor" val={pfVal} c={pfCol} />
        </View>
      </Panel>

      {g && r ? (
        <Panel
          shell={styles.gmPanelShell}
          headTint={styles.gmHeaderTint}
          head={{ title: 'Engine gates', badge: mt5LiveAccount ? 'MT5 LIVE' : 'LIVE', titleColor: C.teal, badgeColor: C.gold }}
        >
          <DxyRow l="Session gate" v={g.sessionGate ? 'OPEN' : 'CLOSED'} vc={g.sessionGate ? C.green : C.amber} />
          <DxyRow l="M30 structure" v={g.structureOk ? 'OK' : 'WAIT'} vc={g.structureOk ? C.green : C.amber} />
          <DxyRow l="Live gate (B/S)" v={`${g.liveGateBuy ? 'B' : '·'}/${g.liveGateSell ? 'S' : '·'}`} vc={g.liveGateBuy || g.liveGateSell ? C.green : C.dim} />
          <DxyRow l="Hard block buy" v={g.hardBlockBuy ? 'ON' : 'OFF'} vc={g.hardBlockBuy ? C.red : C.green} />
          <DxyRow l="Hard block sell" v={g.hardBlockSell ? 'ON' : 'OFF'} vc={g.hardBlockSell ? C.red : C.green} />
          <DxyRow l="Max trades" v={g.maxTradesReached ? 'CAP' : 'OK'} vc={g.maxTradesReached ? C.red : C.green} />
          <DxyRow l="Master block" v={g.masterBlock ? 'ON' : 'OFF'} vc={g.masterBlock ? C.red : C.green} />
          <DxyRow
            l="Spread / chop"
            v={
              [r.brokerSpreadBlocked && 'Broker', r.barRangeBlocked && 'Wide M30', r.chopZone && 'Chop']
                .filter(Boolean)
                .join(' · ') || 'Clear'
            }
            vc={r.spreadBlocked || r.chopZone ? C.amber : C.green}
          />
        </Panel>
      ) : null}

      <Panel
        shell={{}}
        head={{
          title: 'Risk Engine',
          badge: mt5LiveAccount ? (mt5Account ? 'MT5 BALANCE' : 'MT5…') : 'SIM $50K',
        }}
      >
        <Row style={styles.rmHdr}>
          <Text style={styles.rmL}>RISK AT STAKE</Text>
          <Text style={styles.rmV}>{`${fmtUsd(riskUsdNow)} / ${fmtUsd(riskUsdMax)} cap`}</Text>
        </Row>
        <View style={styles.rmBar}>
          <View style={[styles.rmFill, { width: rmPctWidth }]} />
        </View>
        <DxyRow
          l="Balance"
          v={
            mt5LiveAccount
              ? mt5Account?.balance != null
                ? `$${Math.round(mt5Account.balance).toLocaleString('en-US')}`
                : 'Loading…'
              : `$${SIM_DESK_EQUITY.toLocaleString('en-US')} (sim)`
          }
          vc={C.text}
        />
        {mt5LiveAccount ? (
          <DxyRow
            l="Equity"
            v={
              mt5Account?.equity != null
                ? `$${Math.round(mt5Account.equity).toLocaleString('en-US')}`
                : 'Loading…'
            }
            vc={C.text}
          />
        ) : null}
        {mt5LiveAccount && mt5Account?.margin_free != null ? (
          <DxyRow
            l="Free margin"
            v={`$${Math.round(mt5Account.margin_free).toLocaleString('en-US')}`}
            vc={C.dim}
          />
        ) : null}
        <DxyRow l="Risk % (now)" v={`${effPct.toFixed(2)}% = ${fmtUsd(riskUsdNow)}`} vc={C.amber} />
        <DxyRow l="Normal tier" v={`${maxNorm.toFixed(2)}% = ${fmtUsd(Math.round(accountEquity * (maxNorm / 100)))}`} vc={C.green} />
        <DxyRow l="Elevated tier" v={`${elevPct.toFixed(2)}% = ${fmtUsd(Math.round(accountEquity * (elevPct / 100)))}`} vc={C.amber} />
        <DxyRow l="Crisis tier" v={`${crisisPct.toFixed(2)}% = ${fmtUsd(Math.round(accountEquity * (crisisPct / 100)))}`} vc={C.red} />
        <DxyRow l="Active Risk Mode" v={activeRiskStr} vc={geoVc} />
        <DxyRow l="ATR Mode" v={atrShort} vc={C.amber} />
        <DxyRow l="Effective Risk" v={`${effRiskStr} · ${fmtUsd(riskUsdNow)}`} vc={geoVc} />
        <DxyRow
          l="Next trade lots"
          v={openTrade?.side ? openLotsStr : '—'}
          vc={openTrade?.side ? C.goldL : C.dim}
        />
        <DxyRow
          l="Risk sizing"
          v={
            openTrade?.side
              ? (cfg?.journalSizingSlPips ?? 0) > 0
                ? `${openSizingSlPips}p risk · ${openSlPips.toFixed(1)}p chart SL`
                : `${openSlPips.toFixed(1)}p SL`
              : '—'
          }
          vc={openTrade?.side ? C.amber : C.dim}
        />
        <DxyRow
          l="Max loss @ risk"
          v={openTrade?.side ? fmtUsd(riskUsdNow) : '—'}
          vc={openTrade?.side ? C.red : C.dim}
        />
        <DxyRow l="BE Trigger" v={`+${bePipsRm} pips`} vc={C.green} />
        <DxyRow l="Trades Today" v={`${tradeCountDisp} of ${tradeCap} (executes)`} vc={C.amber} />
        <DxyRow l="Dynamic Entries" v={dynEntStr} vc={r?.geoHigh || r?.chopZone ? C.amber : C.green} />
      </Panel>

      <Panel shell={styles.gmPanelShell} headTint={styles.gmHeaderTint} head={{ title: 'Treasury Yield Filter', badge: 'NEW · v3', titleColor: C.purple, badgeColor: C.gold }}>
        <Row style={styles.atrRow}>
          <Text style={styles.atrLabel}>US 10Y Yield</Text>
          <Text style={styles.yieldPct}>{yieldPctStr}</Text>
        </Row>
        <View style={styles.yieldBarBg}>
          <View style={[styles.yieldFill, { width: yFillW }]} />
        </View>
        <Row style={styles.yieldMarkers}>
          <Text style={styles.yieldMk}>3.0%</Text>
          <Text style={styles.yieldMk}>4.0%</Text>
          <Text style={styles.yieldMk}>4.4%</Text>
          <Text style={styles.yieldMk}>5.0%</Text>
        </Row>
        <DxyRow l="Yield <4.0%" v="Normal TPs" vc={C.green} />
        <DxyRow l="Yield 4.0–4.4%" v="TP2 -15%" vc={C.amber} />
        <DxyRow l="Yield >4.4%" v={r?.yieldHigh ? 'TP2 -30% ACTIVE' : 'OFF'} vc={r?.yieldHigh ? C.red : C.green} />
        <DxyRow l="Current Rule" v={yieldRule} vc={r?.yieldHigh ? C.red : C.amber} />
      </Panel>

      <Panel shell={{}} head={{ title: 'Weekday Personality', badge: dayBits.day }}>
        <Row style={styles.dayCard}>
          <Text style={styles.dayIcon}>{dayBits.icon}</Text>
          <View style={{ flex: 1 }}>
            <Text style={styles.dayName}>{dayBits.day}</Text>
            <Text style={styles.dayMode}>{dayBits.mode}</Text>
            <Text style={styles.dayRule}>{dayBits.rule}</Text>
          </View>
        </Row>
        <DxyRow l="Mon–Tue" v="Scalp · Partial @ 1:1 RR" vc={C.amber} />
        <DxyRow l="Wed–Fri" v="Trend · 50% @ 1.5R" vc={C.green} />
        <DxyRow l="Trail Behind" v="H1 Candle Lows" vc={C.text} />
        <DxyRow l="Today" v={dayBits.todayM} vc={dayBits.modeRR === 'N/A' ? C.dim : dayBits.modeRR === 'TREND' ? C.green : C.amber} />
      </Panel>

      <Panel shell={{}} head={{ title: 'Spread Guard', badge: `BLOCK >${maxSpr} PIPS` }}>
        <Row style={[styles.spreadGuard, spHigh ? styles.sgWarn : styles.sgOk]}>
          <View>
            <Text style={styles.sgLabel}>LIVE SPREAD</Text>
            <Text style={[styles.sgSpread, { color: spreadOkColor }]}>{spread.toFixed(2)}</Text>
            <Text style={styles.sgTiny}>pips</Text>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Text style={[styles.sgStatus, { color: spreadOkColor }]}>{spHigh ? '✗ ENTRIES BLOCKED' : '✓ ENTRIES ALLOWED'}</Text>
            <Text style={styles.sgTiny2}>{`Limit: ${maxSpr} pips`}</Text>
          </View>
        </Row>
      </Panel>

      <Panel shell={{}} head={{ title: 'News Filter', badge: '±15MIN · NFP BLACKOUT' }}>
        <Text style={styles.newsClear}>{newsHead}</Text>
        <NewsRow t="May 8" n="NFP + Unemployment" impact="HIGH" extra="BLACKOUT 24HR" />
        <NewsRow t="May 12" n="CPI April" impact="HIGH" extra="BLACKOUT 24HR" />
        <NewsRow t="16:30" n="USD CPI Data" impact="HIGH" ok />
        <NewsRow t="18:00" n="Fed Chair Speech" impact="HIGH" ok />
        <NewsRow t="13:30" n="US PPI m/m" impact="MED" past />
        <Text style={styles.newsFoot}>
          NFP/CPI: Full 24hr blackout · Others: ±15 min block · Spread spike: auto-block
        </Text>
      </Panel>
    </View>
  );
}

function PmCell({ lab, val, c }) {
  const { colors: C, styles } = useBilshenzTheme();
  return (
    <View style={styles.pmC}>
      <Text style={styles.pmL}>{lab}</Text>
      <Text style={[styles.pmV, c ? { color: c } : null]}>{val}</Text>
    </View>
  );
}

function NewsRow({ t, n, impact, extra, ok, past }) {
  const { colors: C, styles } = useBilshenzTheme();
  return (
    <Row style={styles.ni}>
      <Text style={styles.niTime}>{t}</Text>
      <Text style={styles.niName}>{n}</Text>
      <Text style={[styles.niImpact, impact === 'HIGH' ? styles.niH : styles.niM]}>{impact}</Text>
      {ok ? <Text style={styles.niOk}>SAFE ✓</Text> : past ? <Text style={styles.niPast}>PAST</Text> : <Text style={styles.niBlock}>{extra}</Text>}
    </Row>
  );
}

const PROFILE_PRESETS = [
  { id: 'p1', initials: 'JD', name: 'John Doe', tier: 'PRO' },
  { id: 'p2', initials: 'TA', name: 'Trader Alpha', tier: 'STANDARD' },
];

function ProfileTab({
  pad,
  width,
  riskMode,
  onRiskModeChange,
  newsActive,
  onNewsActiveChange,
  nfpBlackout,
  onNfpBlackoutChange,
  onResetEngineTuning,
  engineWinRatePct,
  engineClosedTrades,
  maxDailyTrades,
  onMaxDailyTradesChange,
  engineHydrated,
  runMode,
  onRunModeChange,
  brokerHookEnabled,
  onBrokerHookEnabledChange,
  brokerWebhookUrl,
  onBrokerWebhookUrlChange,
  lastBrokerMsg,
  autoExecuteSignals,
  onAutoExecuteSignalsChange,
  mt5Connected,
}) {
  const { colors: C, styles } = useBilshenzTheme();
  const [profileId, setProfileId] = useState('p1');
  const [showSwitchModal, setShowSwitchModal] = useState(false);
  const [nameEdit, setNameEdit] = useState(false);
  const [defaultLot, setDefaultLot] = useState('0.25');
  const [atrManual, setAtrManual] = useState(false);
  const [notificationsOn, setNotificationsOn] = useState(true);
  const [photoByProfile, setPhotoByProfile] = useState({});
  const [nameByProfile, setNameByProfile] = useState({});
  const nameSaveTimer = useRef(null);

  const active = PROFILE_PRESETS.find((p) => p.id === profileId) ?? PROFILE_PRESETS[0];
  const profilePhotoUri = photoByProfile[profileId] ?? null;
  const savedName = nameByProfile[profileId];
  const [displayName, setDisplayName] = useState(savedName || active.name);
  const avatarInitials = initialsFromName(displayName || active.name);

  useEffect(() => {
    const p = PROFILE_PRESETS.find((x) => x.id === profileId) ?? PROFILE_PRESETS[0];
    setDisplayName(nameByProfile[profileId]?.trim() || p.name);
    setNameEdit(false);
  }, [profileId, nameByProfile]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const ids = PROFILE_PRESETS.map((p) => p.id);
      const [photos, names] = await Promise.all([loadAllProfilePhotos(ids), loadAllProfileNames(ids)]);
      if (!cancelled) {
        setPhotoByProfile(photos);
        setNameByProfile(names);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(
    () => () => {
      if (nameSaveTimer.current) clearTimeout(nameSaveTimer.current);
    },
    []
  );

  const persistDisplayName = useCallback(
    async (name) => {
      const trimmed = name.trim() || active.name;
      await saveProfileName(profileId, trimmed);
      setNameByProfile((prev) => ({ ...prev, [profileId]: trimmed }));
      setDisplayName(trimmed);
    },
    [profileId, active.name]
  );

  const scheduleNameSave = useCallback(
    (name) => {
      if (nameSaveTimer.current) clearTimeout(nameSaveTimer.current);
      nameSaveTimer.current = setTimeout(() => {
        void persistDisplayName(name);
      }, 400);
    },
    [persistDisplayName]
  );

  const pickProfilePhoto = useCallback(async () => {
    try {
      const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (status !== 'granted') {
        Alert.alert('Photos', 'Allow photo library access to set a profile picture.');
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsEditing: true,
        aspect: [1, 1],
        quality: 0.85,
      });
      if (result.canceled || !result.assets?.[0]?.uri) return;
      const uri = result.assets[0].uri;
      await saveProfilePhoto(profileId, uri);
      setPhotoByProfile((prev) => ({ ...prev, [profileId]: uri }));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      Alert.alert('Profile photo', msg || 'Could not open photo library.');
    }
  }, [profileId]);

  const removeProfilePhoto = useCallback(() => {
    Alert.alert('Remove photo', 'Use initials again for this profile?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Remove',
        style: 'destructive',
        onPress: async () => {
          await clearProfilePhoto(profileId);
          setPhotoByProfile((prev) => {
            const next = { ...prev };
            delete next[profileId];
            return next;
          });
        },
      },
    ]);
  }, [profileId]);

  const tierColor = active.tier === 'PRO' ? C.goldL : C.blue;
  const engPr = useContext(BilshenzEngineCtx);
  const useRealMt5Pr = !!engPr?.useRealMt5;
  const jStatPr = journalClosedStats(engPr?.journalRows ?? [], engPr?.cfg?.pipSize ?? 0.1);
  const effPctPr = effectiveRiskPctFromEngine(
    engPr?.cfg?.geoRisk ?? 'LOW',
    engPr?.snapshot?.risk?.atrPips ?? null,
    engPr?.cfg
  );
  const eqPr = engPr?.accountEquity ?? SIM_DESK_EQUITY;
  const totalPlUsd = useRealMt5Pr
    ? Math.round(journalClosedUsd(engPr?.journalRows ?? [], engPr?.cfg, eqPr, effPctPr))
    : Math.round(jStatPr.netP * (engPr?.cfg?.simUsdPerEnginePip ?? defaultBilshenzConfig.simUsdPerEnginePip));
  const totalPlStr = fmtUsd(totalPlUsd);
  const totalPlCol = totalPlUsd >= 0 ? C.green : C.red;
  const sparkW = Math.max(220, width - pad * 2 - 56);
  const sparkPts = '0,38 35,32 70,28 105,20 140,24 175,14 200,18';

  const resetDefaults = () => {
    setProfileId('p1');
    onRiskModeChange('GEO');
    onResetEngineTuning?.();
    onMaxDailyTradesChange(5);
    onRunModeChange?.('live');
    onBrokerHookEnabledChange?.(false);
    onBrokerWebhookUrlChange?.('');
    onAutoExecuteSignalsChange(false);
    setDefaultLot('0.25');
    setAtrManual(false);
    setNotificationsOn(true);
    setNameEdit(false);
    void (async () => {
      await Promise.all(
        PROFILE_PRESETS.map(async (p) => {
          await clearProfilePhoto(p.id);
          await clearProfileName(p.id);
        })
      );
      setPhotoByProfile({});
      setNameByProfile({});
      setDisplayName(PROFILE_PRESETS[0].name);
    })();
  };

  return (
    <ScrollView
      style={{ flex: 1 }}
      contentContainerStyle={[styles.psScroll, { paddingHorizontal: pad, paddingBottom: 8 }]}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}>
      <View style={styles.psProfileCard}>
        {Platform.OS === 'ios' ? (
          <BlurView intensity={22} tint="dark" style={[StyleSheet.absoluteFillObject, { borderRadius: 14 }]} />
        ) : null}
        <View style={styles.psProfileTint} />
        <View style={styles.psProfileGlow} />
        <Pressable
          onPress={pickProfilePhoto}
          onLongPress={profilePhotoUri ? removeProfilePhoto : undefined}
          accessibilityRole="button"
          accessibilityLabel="Profile photo. Tap to choose from library. Long press to remove."
          style={({ pressed }) => [styles.psAvatarRing, pressed && { opacity: 0.88 }]}>
          {profilePhotoUri ? (
            <Image source={{ uri: profilePhotoUri }} style={styles.psAvatarImage} resizeMode="cover" />
          ) : (
            <Text style={styles.psAvatarTxt}>{avatarInitials}</Text>
          )}
        </Pressable>
        <Text style={styles.psAvatarHint}>
          {profilePhotoUri ? 'Tap to change · hold to remove' : 'Tap to add photo'}
        </Text>
        {nameEdit ? (
          <TextInput
            value={displayName}
            onChangeText={(t) => {
              setDisplayName(t);
              scheduleNameSave(t);
            }}
            onBlur={() => {
              if (nameSaveTimer.current) {
                clearTimeout(nameSaveTimer.current);
                nameSaveTimer.current = null;
              }
              void persistDisplayName(displayName);
              setNameEdit(false);
            }}
            style={styles.psNameInput}
            placeholder="Trader name"
            placeholderTextColor={C.dim2}
            autoFocus
          />
        ) : (
          <Pressable onPress={() => setNameEdit(true)} style={({ pressed }) => [pressed && { opacity: 0.85 }]}>
            <Text style={styles.psName}>{displayName}</Text>
            <Text style={styles.psNameHint}>Tap to edit · saved automatically</Text>
          </Pressable>
        )}
        <View style={[styles.psTierBadge, { borderColor: tierColor }]}>
          <Text style={[styles.psTierTxt, { color: tierColor }]}>{active.tier}</Text>
        </View>
        <Row style={styles.psStatsRow}>
          <View style={styles.psStatGlass}>
            <Text style={styles.psStatLbl}>TOTAL P&L</Text>
            <Text style={[styles.psStatVal, { color: totalPlCol }]}>{totalPlStr}</Text>
          </View>
          <View style={styles.psStatGlass}>
            <Text style={styles.psStatLbl}>WIN RATE</Text>
            <Text style={[styles.psStatVal, { color: C.goldL }]}>{engineWinRatePct}</Text>
          </View>
          <View style={styles.psStatGlass}>
            <Text style={styles.psStatLbl}>TRADES</Text>
            <Text style={[styles.psStatVal, { color: C.text }]}>{engineClosedTrades}</Text>
          </View>
        </Row>
        <View style={styles.psSparkWrap}>
          <Svg width={sparkW} height={44} viewBox="0 0 200 44">
            <Defs>
              <LinearGradient id="psSparkStroke" x1="0" y1="0" x2="200" y2="0">
                <Stop offset="0%" stopColor={C.green} />
                <Stop offset="55%" stopColor={C.green} />
                <Stop offset="100%" stopColor={C.goldL} />
              </LinearGradient>
            </Defs>
            <Polyline
              points={sparkPts}
              fill="none"
              stroke="url(#psSparkStroke)"
              strokeWidth="2.6"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          </Svg>
        </View>
        <Pressable
          onPress={() => setShowSwitchModal(true)}
          style={({ pressed }) => [styles.psSwitchProfileBtn, pressed && { opacity: 0.88 }]}>
          <Text style={styles.psSwitchProfileTxt}>SWITCH PROFILE</Text>
        </Pressable>
      </View>

      <View style={styles.psDivider} />

      <Text style={styles.psSettingsTitle}>APP SETTINGS</Text>

      <View style={styles.psSettingsCard}>
        <Text style={styles.psRowLabel}>RISK MODE</Text>
        <Row style={styles.psSegRow}>
          {['GEO', 'NORMAL', 'AGGRESSIVE'].map((opt) => (
            <Pressable
              key={opt}
              onPress={() => onRiskModeChange(opt)}
              style={[styles.psSegChip, riskMode === opt && styles.psSegChipOn, { minHeight: 44, flex: 1 }]}>
              <Text style={[styles.psSegChipTxt, riskMode === opt && styles.psSegChipTxtOn]} numberOfLines={1}>
                {opt}
              </Text>
            </Pressable>
          ))}
        </Row>

        <View style={styles.psRowDivider} />
        <Text style={styles.psRowLabel}>MAX TRADES / DAY</Text>
        <Row style={styles.psSegRow}>
          {[3, 5, 8].map((n) => (
            <Pressable
              key={n}
              onPress={() => onMaxDailyTradesChange(n)}
              style={[styles.psSegChip, maxDailyTrades === n && styles.psSegChipOn, { minHeight: 44, flex: 1 }]}>
              <Text style={[styles.psSegChipTxt, maxDailyTrades === n && styles.psSegChipTxtOn]}>{n}</Text>
            </Pressable>
          ))}
        </Row>

        <View style={styles.psRowDivider} />
        <Text style={styles.psRowLabel}>DEFAULT LOT</Text>
        <Row style={styles.psSegRow}>
          {['0.10', '0.25', '0.50', '1.00'].map((lot) => (
            <Pressable
              key={lot}
              onPress={() => setDefaultLot(lot)}
              style={[styles.psSegChip, defaultLot === lot && styles.psSegChipOn, { minHeight: 44, flex: 1, paddingHorizontal: 2 }]}>
              <Text style={[styles.psSegChipTxt, defaultLot === lot && styles.psSegChipTxtOn]} numberOfLines={1} adjustsFontSizeToFit>
                {lot}
              </Text>
            </Pressable>
          ))}
        </Row>

        <View style={styles.psRowDivider} />
        <Row style={styles.psToggleRow}>
          <Text style={styles.psToggleLbl}>ATR MODE</Text>
          <Text style={styles.psToggleHint}>{atrManual ? 'Manual' : 'Auto'}</Text>
          <Switch
            value={atrManual}
            onValueChange={setAtrManual}
            trackColor={{ false: C.border, true: 'rgba(212,180,90,0.45)' }}
            thumbColor={atrManual ? C.goldL : C.dim2}
            style={{ transform: [{ scaleX: 1.05 }, { scaleY: 1.05 }] }}
          />
        </Row>

        <View style={styles.psRowDivider} />
        <Row style={styles.psToggleRow}>
          <Text style={styles.psToggleLbl}>NOTIFICATIONS</Text>
          <Text style={styles.psToggleHint}>{notificationsOn ? 'On' : 'Off'}</Text>
          <Switch
            value={notificationsOn}
            onValueChange={setNotificationsOn}
            trackColor={{ false: C.border, true: 'rgba(212,180,90,0.45)' }}
            thumbColor={notificationsOn ? C.goldL : C.dim2}
            style={{ transform: [{ scaleX: 1.05 }, { scaleY: 1.05 }] }}
          />
        </Row>

        <View style={styles.psRowDivider} />
        <Row style={styles.psToggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.psToggleLbl}>NEWS WINDOW (±15m)</Text>
            <Text style={styles.psToggleHint}>{newsActive ? 'Treat as hot' : 'Off'}</Text>
          </View>
          <Switch
            value={newsActive}
            onValueChange={onNewsActiveChange}
            trackColor={{ false: C.border, true: 'rgba(212,180,90,0.45)' }}
            thumbColor={newsActive ? C.goldL : C.dim2}
            style={{ transform: [{ scaleX: 1.05 }, { scaleY: 1.05 }] }}
          />
        </Row>

        <View style={styles.psRowDivider} />
        <Row style={styles.psToggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.psToggleLbl}>NFP BLACKOUT</Text>
            <Text style={styles.psToggleHint}>{nfpBlackout ? 'Simulated on' : 'Clear'}</Text>
          </View>
          <Switch
            value={nfpBlackout}
            onValueChange={onNfpBlackoutChange}
            trackColor={{ false: C.border, true: 'rgba(255,61,87,0.35)' }}
            thumbColor={nfpBlackout ? C.red : C.dim2}
            style={{ transform: [{ scaleX: 1.05 }, { scaleY: 1.05 }] }}
          />
        </Row>

        <View style={styles.psRowDivider} />
        <Row style={styles.psToggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.psToggleLbl}>DARK THEME</Text>
            <Text style={styles.psToggleHint}>Always on</Text>
          </View>
          <Switch value={true} disabled trackColor={{ false: C.border, true: 'rgba(212,180,90,0.35)' }} thumbColor={C.goldL} />
        </Row>
      </View>

      <Text style={styles.psSettingsTitle}>BOT · BACKTEST · BROKER</Text>
      <View style={styles.psSettingsCard}>
        <Text style={styles.psRowLabel}>RUN MODE</Text>
        <Row style={styles.psSegRow}>
          {[
            { id: 'live', lab: 'LIVE SIM' },
            { id: 'backtest', lab: 'BACKTEST' },
          ].map((m) => (
            <Pressable
              key={m.id}
              disabled={m.id === 'backtest' && !engineHydrated}
              onPress={() => onRunModeChange?.(m.id)}
              style={[
                styles.psSegChip,
                runMode === m.id && styles.psSegChipOn,
                { minHeight: 44, flex: 1 },
                m.id === 'backtest' && !engineHydrated ? { opacity: 0.45 } : null,
              ]}>
              <Text style={[styles.psSegChipTxt, runMode === m.id && styles.psSegChipTxtOn]} numberOfLines={1}>
                {m.lab}
              </Text>
            </Pressable>
          ))}
        </Row>
        {engineHydrated ? null : (
          <Text style={[styles.psToggleHint, { marginTop: 6 }]}>Wait for engine sync before backtest.</Text>
        )}
        <Text style={[styles.psToggleHint, { marginTop: 8, lineHeight: 16 }]}>
          Backtest replays synthetic M30 history: desk shows a scrub bar. Live journal is frozen while in backtest and restored when you return to LIVE SIM.
        </Text>

        <View style={styles.psRowDivider} />
        <Row style={styles.psToggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.psToggleLbl}>POST EXEC TO BROKER HOOK</Text>
            <Text style={styles.psToggleHint}>HTTPS JSON webhook</Text>
          </View>
          <Switch
            value={brokerHookEnabled}
            onValueChange={onBrokerHookEnabledChange}
            trackColor={{ false: C.border, true: 'rgba(212,180,90,0.45)' }}
            thumbColor={brokerHookEnabled ? C.goldL : C.dim2}
            style={{ transform: [{ scaleX: 1.05 }, { scaleY: 1.05 }] }}
          />
        </Row>

        <View style={styles.psRowDivider} />
        <Row style={styles.psToggleRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.psToggleLbl}>AUTO-EXECUTE SIGNALS</Text>
            <Text style={styles.psToggleHint}>
              {autoExecuteSignals
                ? 'ON — auto-sends allowed signals to MT5 when connected.'
                : mt5Connected
                  ? 'OFF — manual EXEC only. Turn on to resume auto orders.'
                  : 'Turns ON automatically when you connect MT5.'}
              {!mt5Connected && !brokerWebhookUrl.trim() ? ' Connect MT5 in Profile first.' : ''}
            </Text>
          </View>
          <Switch
            value={autoExecuteSignals}
            onValueChange={onAutoExecuteSignalsChange}
            disabled={(!brokerWebhookUrl.trim() && !mt5Connected) || !engineHydrated || runMode !== 'live'}
            trackColor={{ false: C.border, true: 'rgba(255,61,87,0.45)' }}
            thumbColor={autoExecuteSignals ? C.red : C.dim2}
            style={{ transform: [{ scaleX: 1.05 }, { scaleY: 1.05 }] }}
          />
        </Row>

        <View style={styles.psRowDivider} />
        <Text style={styles.psRowLabel}>BROKER WEBHOOK URL</Text>
        <TextInput
          value={brokerWebhookUrl}
          onChangeText={onBrokerWebhookUrlChange}
          placeholder="https://your-bridge.example/order"
          placeholderTextColor={C.dim2}
          autoCapitalize="none"
          autoCorrect={false}
          style={styles.psBrokerInput}
        />
        <Text style={[styles.psToggleHint, { marginTop: 6, lineHeight: 15 }]}>
          Auto/manual EXEC sends webhook (if URL set) and Python MT5 order (if CONNECT MT5). Webhook bridge:
          myapp/mt5/bridge-server.mjs + PollBridgeEA.mq5 — see myapp/mt5/README.txt.
        </Text>
        {lastBrokerMsg ? (
          <Text style={[styles.psToggleHint, { marginTop: 8, color: C.amber }]} numberOfLines={3}>
            Last: {lastBrokerMsg}
          </Text>
        ) : null}
      </View>

      <Suspense
        fallback={
          <View style={{ paddingVertical: 12, paddingHorizontal: pad }}>
            <Text style={{ color: C.dim, fontSize: 11 }}>Loading MT5 panel…</Text>
          </View>
        }>
        <Mt5BridgePanelLazy />
      </Suspense>

      <Pressable onPress={resetDefaults} style={({ pressed }) => [styles.psResetBtn, pressed && { opacity: 0.88 }]}>
        <Text style={styles.psResetTxt}>RESET TO DEFAULTS</Text>
      </Pressable>

      <Modal visible={showSwitchModal} transparent animationType="fade" onRequestClose={() => setShowSwitchModal(false)}>
        <View style={styles.psModalBackdrop}>
          <Pressable style={StyleSheet.absoluteFillObject} onPress={() => setShowSwitchModal(false)} />
          <View style={styles.psModalCard}>
            <Text style={styles.psModalTitle}>SWITCH PROFILE</Text>
            {PROFILE_PRESETS.map((p) => (
              <Pressable
                key={p.id}
                onPress={() => {
                  setProfileId(p.id);
                  setShowSwitchModal(false);
                }}
                style={({ pressed }) => [
                  styles.psModalRow,
                  profileId === p.id && styles.psModalRowOn,
                  pressed && { opacity: 0.9 },
                ]}>
                <View style={styles.psModalAvatar}>
                  {photoByProfile[p.id] ? (
                    <Image
                      source={{ uri: photoByProfile[p.id] }}
                      style={styles.psModalAvatarImg}
                      resizeMode="cover"
                    />
                  ) : (
                    <Text style={styles.psModalAvatarTxt}>{p.initials}</Text>
                  )}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.psModalName}>{nameByProfile[p.id]?.trim() || p.name}</Text>
                  <Text style={styles.psModalTier}>{p.tier}</Text>
                </View>
                {profileId === p.id ? <Text style={styles.psModalCheck}>✓</Text> : null}
              </Pressable>
            ))}
            <Pressable onPress={() => setShowSwitchModal(false)} style={styles.psModalClose}>
              <Text style={styles.psModalCloseTxt}>CLOSE</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

function GodmodeHome({
  pad,
  pnl,
  tradeCount,
  sessionBits,
  sr,
  utcStr,
  histRows,
  winRatePct,
}) {
  const { colors: C, styles } = useBilshenzTheme();
  const eng = useContext(BilshenzEngineCtx);
  const useRealMt5 = !!eng?.useRealMt5;
  const mt5Account = eng?.mt5Account;
  const tradeCap = eng?.cfg?.maxDailyTrades ?? 5;
  const tradeCountDisp = eng?.hydrated === true ? tradeCount : '—';
  const livePnl = useRealMt5 && mt5Account?.profit != null ? mt5Account.profit : pnl;
  const pnlRounded = Math.round(livePnl);
  const pnlColor = pnlRounded >= 0 ? C.green : C.red;
  const sessShort = sessionBits.act
    ? sessionBits.s3
      ? 'NY PEAK'
      : sessionBits.s2
        ? 'LONDON'
        : 'PRE-LONDON'
    : 'STANDBY';
  const wr = winRatePct ?? '75.0%';

  const chips = ['15 FILTERS', 'S&R v3.2', 'FLIP ENGINE', 'LEFT SCAN', 'GEO', 'CHOP', 'ATH SHIELD', 'YIELD'];

  return (
    <View style={styles.ghWrap}>
      <View style={[styles.ghPriceCard, { marginHorizontal: pad, marginTop: 4 }]}>
        {Platform.OS === 'ios' ? (
          <BlurView intensity={28} tint="dark" style={StyleSheet.absoluteFill} />
        ) : (
          <View style={[StyleSheet.absoluteFill, { backgroundColor: 'rgba(10,9,0,0.92)' }]} />
        )}
        <View style={styles.ghPriceInner}>
          <Row style={styles.ghPriceMetaRow}>
            <View style={styles.ghPriceStatBlock}>
              <Text style={styles.ghMiniLbl}>WIN RATE</Text>
              <Text style={[styles.ghMiniVal, { color: C.green }]}>{wr}</Text>
            </View>
            <View style={styles.ghPriceStatDivider} />
            <View style={styles.ghPriceStatBlock}>
              <Text style={styles.ghMiniLbl}>SESSION</Text>
              <Text style={[styles.ghMiniVal, { color: sessionBits.act ? C.green : C.amber }]}>{sessShort}</Text>
            </View>
          </Row>
          <Row style={styles.ghPriceFoot}>
            <Text style={styles.ghFootUtc}>{utcStr} UTC</Text>
            <Text style={styles.ghFootEdge}>EDGE: {sr.verdictVal}</Text>
          </Row>
        </View>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.ghChipScroll}
        contentContainerStyle={[styles.ghChipRow, { paddingHorizontal: pad }]}>
        {chips.map((c) => (
          <View key={c} style={styles.ghChip}>
            <Text style={styles.ghChipTxt}>{c}</Text>
          </View>
        ))}
      </ScrollView>

      <View style={[styles.ghGrid2, { paddingHorizontal: pad }]}>
        <View style={styles.ghStatTile}>
          <Text style={styles.ghStatLbl}>DAY P&L</Text>
          <Text style={[styles.ghStatVal, { color: pnlColor }]}>{fmtUsd(pnlRounded)}</Text>
          <Text style={styles.ghStatSub}>{useRealMt5 ? 'Floating P&L · MT5' : 'Unrealized · sim'}</Text>
        </View>
        <View style={styles.ghStatTile}>
          <Text style={styles.ghStatLbl}>TRADES</Text>
          <Text style={[styles.ghStatVal, { color: C.gold }]}>
            {tradeCountDisp} / {tradeCap}
          </Text>
          <Text style={styles.ghStatSub}>Daily cap</Text>
        </View>
      </View>

      <View style={[styles.ghVerdictCard, { marginHorizontal: pad }]}>
        <Text style={styles.ghVerdictLbl}>SCANNER VERDICT</Text>
        <Text style={[styles.ghVerdictMain, { color: sr.verdictValColor }]}>{sr.verdictVal}</Text>
        <Text style={styles.ghVerdictSub}>{sr.verdictSub}</Text>
      </View>

      <View style={[styles.ghHistWrap, { marginHorizontal: pad }]}>
        <Panel shell={{}} head={{ title: 'Signal History', badge: 'JIMPLAS · TODAY' }}>
          <View style={styles.histTableWrap}>
            <HistHeader />
            {(histRows ?? SIGNAL_HISTORY_SIM).map((row, i) => (
              <HistRow key={i} row={row} />
            ))}
          </View>
        </Panel>
      </View>

      <View style={[styles.ghQuote, { marginHorizontal: pad }]}>
        <Text style={styles.ghQuoteMark}>&ldquo;</Text>
        <Text style={styles.ghQuoteTxt}>One protocol. Fifteen gates. Execute only when the desk agrees.</Text>
        <Text style={styles.ghQuoteSig}>— BILSHENZ v3.2</Text>
      </View>
    </View>
  );
}

function MobileCompactStrip({ price, spread, pad, utcStr, est, tickerItems, tapeTheme, dayOpen }) {
  const { colors: C, styles } = useBilshenzTheme();
  const ref = dayOpen != null && Number.isFinite(dayOpen) ? dayOpen : 4698.2;
  const xauDiff = parseFloat((price - ref).toFixed(2));
  const xauUp = xauDiff >= 0;
  return (
    <View style={[styles.header, styles.mobileCompactHdr, { paddingHorizontal: pad }]}>
      <Row style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <Row style={styles.xauRow}>
          <Text style={styles.xauPair}>XAU/USD</Text>
          <Text style={styles.xauPrice}>{fmtNum(price)}</Text>
          <Text style={[styles.xauChg, { color: xauUp ? C.green : C.red }]}>
            {(xauUp ? '▲ +' : '▼ ') + Math.abs(xauDiff).toFixed(2)}
          </Text>
        </Row>
        <View style={{ alignItems: 'flex-end' }}>
          <Text style={styles.clockUtc}>{utcStr}</Text>
          <Text style={styles.clockEst}>
            {String(est.h).padStart(2, '0')}:{String(est.m).padStart(2, '0')} EST · {spread.toFixed(2)}p
          </Text>
        </View>
      </Row>
      <GeoPoliticalTicker
        style={{ marginTop: 8, marginHorizontal: -pad }}
        items={tickerItems}
        tapeTheme={tapeTheme}
      />
    </View>
  );
}

function MobileBottomNav({ tab, onChange, bottomInset }) {
  const { colors: C, styles } = useBilshenzTheme();
  const items = [
    { id: 'home', icon: '⌂', label: 'HOME' },
    { id: 'desk', icon: '◈', label: 'INTEL' },
    { id: 'trade', icon: '⚡', label: 'TRADE' },
    { id: 'profile', icon: '👤', label: 'PROFILE' },
    { id: 'risk', icon: '◎', label: 'RISK' },
  ];
  return (
    <View style={[styles.bottomNavOuter, { paddingBottom: Math.max(bottomInset, 4) }]}>
      <View style={styles.bottomNavBar}>
        {Platform.OS === 'ios' ? (
          <BlurView intensity={28} tint="dark" style={StyleSheet.absoluteFillObject} />
        ) : (
          <View style={[StyleSheet.absoluteFillObject, { backgroundColor: 'rgba(10,9,0,0.96)' }]} />
        )}
        <View style={styles.bottomNavBarTint} />
        <Row style={styles.bottomNavRow}>
          {items.map((it) => {
            const active = tab === it.id;
            return (
              <Pressable
                key={it.id}
                accessibilityRole="tab"
                accessibilityState={{ selected: active }}
                onPress={() => onChange(it.id)}
                style={({ pressed }) => [
                  styles.bottomNavItem,
                  active && styles.bottomNavItemActive,
                  pressed && styles.bottomNavItemPressed,
                ]}>
                {active ? (
                  <View style={styles.bottomNavActiveCapWrap} pointerEvents="none">
                    <View style={styles.bottomNavActiveCap} />
                  </View>
                ) : null}
                <View style={styles.bottomNavItemInner}>
                  <Text style={[styles.bottomNavIcon, active && styles.bottomNavIconActive]}>{it.icon}</Text>
                  <Text
                    numberOfLines={1}
                    adjustsFontSizeToFit
                    minimumFontScale={0.8}
                    style={[styles.bottomNavLbl, active && styles.bottomNavLblActive]}>
                    {it.label}
                  </Text>
                </View>
              </Pressable>
            );
          })}
        </Row>
      </View>
    </View>
  );
}

function AppContent({ onEngineReady }) {
  const { colors: C, styles } = useBilshenzTheme();
  const { baseUrl: mt5BaseUrl, connected: mt5Connected } = useMt5Bridge();
  const { width } = useWindowDimensions();
  const isWide = width >= 880;
  const pad = Math.max(12, Math.min(24, width * 0.06));
  const insets = useSafeAreaInsets();

  const [now, setNow] = useState(() => new Date());
  const [price, setPrice] = useState(4721.5);
  const [pnl, setPnl] = useState(840);
  const [spread, setSpread] = useState(0.6);
  const [dxy, setDxy] = useState(99.42);
  const [atr, setAtr] = useState(72.4);
  const [atrFillPct, setAtrFillPct] = useState(65);
  const [execBusy, setExecBusy] = useState(false);
  const [sigMuted, setSigMuted] = useState(false);
  const [mobileTab, setMobileTab] = useState('home');
  const [us10y, setUs10y] = useState(4.35);
  const [profileRiskMode, setProfileRiskMode] = useState('GEO');
  const [newsActive, setNewsActive] = useState(false);
  const [nfpBlackout, setNfpBlackout] = useState(false);
  const [profileMaxDailyTrades, setProfileMaxDailyTrades] = useState(5);
  const [runMode, setRunMode] = useState('live');
  const [backtestEndIndex, setBacktestEndIndex] = useState(220);
  const [backtestPlaying, setBacktestPlaying] = useState(false);
  const [brokerHookEnabled, setBrokerHookEnabled] = useState(false);
  const [brokerWebhookUrl, setBrokerWebhookUrl] = useState('');
  const [lastBrokerMsg, setLastBrokerMsg] = useState('');
  const [autoExecuteSignals, setAutoExecuteSignals] = useState(false);
  const prevMt5ConnectedRef = useRef(false);
  const userDisabledAutoExecRef = useRef(false);

  const onAutoExecuteSignalsChange = useCallback((enabled) => {
    if (!enabled) userDisabledAutoExecRef.current = true;
    setAutoExecuteSignals(!!enabled);
  }, []);

  const mt5Live = useMt5LiveFeed({
    baseUrl: mt5BaseUrl,
    connected: mt5Connected,
    enabled: runMode === 'live',
  });

  const useRealMt5 = mt5Connected && runMode === 'live';

  const accountEquity = useMemo(() => {
    if (!useRealMt5) return SIM_DESK_EQUITY;
    if (mt5Live.account) return resolveAccountEquity(mt5Live.account, SIM_DESK_EQUITY);
    return null;
  }, [useRealMt5, mt5Live.account?.balance, mt5Live.account?.equity]);

  const sizingEquity = accountEquity ?? SIM_DESK_EQUITY;

  const est = useMemo(() => getEST(now), [now]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [[, urlVal]] = await AsyncStorage.multiGet([STORAGE_BROKER_HOOK_URL]);
        if (cancelled) return;
        if (urlVal) setBrokerWebhookUrl(urlVal);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** Turn auto-execute ON when MT5 connects (user can still switch OFF in Profile). */
  useEffect(() => {
    if (runMode !== 'live') return;
    const wasConnected = prevMt5ConnectedRef.current;
    if (mt5Connected && !wasConnected) {
      userDisabledAutoExecRef.current = false;
      setAutoExecuteSignals(true);
    }
    prevMt5ConnectedRef.current = mt5Connected;
  }, [mt5Connected, runMode]);

  useEffect(() => {
    AsyncStorage.setItem(STORAGE_BROKER_HOOK_URL, brokerWebhookUrl).catch(() => {});
  }, [brokerWebhookUrl]);

  useEffect(() => {
    AsyncStorage.setItem(STORAGE_AUTO_EXEC, autoExecuteSignals ? '1' : '0').catch(() => {});
  }, [autoExecuteSignals]);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const utcStr = now.toUTCString().split(' ')[4] ?? '--:--:--';

  const geoRisk = useMemo(() => profileRiskModeToGeo(profileRiskMode), [profileRiskMode]);

  const bilshenzEngine = useBilshenzMarketEngine({
    price,
    spread,
    dxy,
    us10y,
    now,
    geoRisk,
    newsActive,
    nfpBlackout,
    maxDailyTrades: profileMaxDailyTrades,
    initialTradeCount: 0,
    runMode,
    backtestEndIndex,
    mt5MarketBundle: useRealMt5 ? mt5Live.marketBundle : null,
    useMt5Data: useRealMt5,
    mt5Connected: useRealMt5,
    countSignalTowardCap: !autoExecuteSignals,
  });

  const engineCtxValue = useMemo(
    () => ({
      ...bilshenzEngine,
      useRealMt5,
      mt5Connected,
      mt5Account: useRealMt5 ? mt5Live.account : null,
      accountEquity: sizingEquity,
    }),
    [bilshenzEngine, useRealMt5, mt5Connected, mt5Live.account, sizingEquity]
  );
  const bzSnapshot = bilshenzEngine.snapshot;
  const tradeCount = bilshenzEngine.tradeCount;
  const engineHydrated = bilshenzEngine.hydrated;
  const bundleReady = bilshenzEngine.bundleReady;

  useEffect(() => {
    if (bundleReady && onEngineReady) onEngineReady();
  }, [bundleReady, onEngineReady]);

  const incrementExecuteTrade = bilshenzEngine.incrementExecuteTrade;
  const bumpAutoTradeCount = bilshenzEngine.bumpAutoTradeCount;
  const dailyTradeCap = bilshenzEngine.cfg.maxDailyTrades;

  const chartPrice = useMemo(() => {
    if (runMode === 'backtest' && bilshenzEngine.bundle?.m30?.length) {
      const c = bilshenzEngine.bundle.m30[bilshenzEngine.bundle.m30.length - 1].c;
      return Number.isFinite(c) ? c : price;
    }
    return price;
  }, [runMode, bilshenzEngine.bundle, price]);

  const bzRef = useRef(bzSnapshot);
  const engineRef = useRef(bilshenzEngine);
  const runModeRef = useRef(runMode);
  bzRef.current = bzSnapshot;
  engineRef.current = bilshenzEngine;
  runModeRef.current = runMode;

  const autoHookInFlight = useRef(false);
  const autoHookDoneBarRef = useRef(null);

  const execLotsForTrade = useCallback(
    (tradeSnap) => {
      const cfg = bilshenzEngine.cfg ?? defaultBilshenzConfig;
      const riskPct = effectiveRiskPctFromEngine(cfg.geoRisk, bzSnapshot.risk?.atrPips ?? null, cfg);
      return lotsForTrade(tradeSnap, cfg, sizingEquity, riskPct);
    },
    [sizingEquity, bilshenzEngine.cfg, bzSnapshot.risk?.atrPips]
  );

  useEffect(() => {
    if (!autoExecuteSignals || !engineHydrated) return;
    if (runMode !== 'live') return;
    const hookUrl = brokerWebhookUrl.trim();
    if (!hookUrl && !mt5Connected) return;

    const lastSig = bilshenzEngine.lastBarSig;
    const m30 = bilshenzEngine.bundle?.m30;
    if (!m30?.length) return;
    const bar = m30[m30.length - 1];
    const sig = bzSnapshot.signals.anyBuy || bzSnapshot.signals.anySell;
    if (!sig || lastSig !== bar.t) return;
    if (autoHookDoneBarRef.current === bar.t) return;
    if (autoHookInFlight.current) return;
    if (tradeCount >= dailyTradeCap) {
      setLastBrokerMsg('Auto: skipped (daily cap)');
      autoHookDoneBarRef.current = bar.t;
      return;
    }
    const trade = bzSnapshot.trade;
    const gate = canExecuteTrade(bzSnapshot, trade);
    if (!gate.ok) {
      setLastBrokerMsg(`Auto: skipped (${gate.reason})`);
      autoHookDoneBarRef.current = bar.t;
      return;
    }

    const intent = buildBrokerOrderIntent(trade, {
      barTimeMs: bar.t,
      runMode: 'live',
      trigger: 'auto',
      symbol: mt5Live.resolvedSymbol || 'XAUUSD',
    });
    if (!intent) {
      autoHookDoneBarRef.current = bar.t;
      return;
    }

    autoHookInFlight.current = true;
    void (async () => {
      try {
        const lots = execLotsForTrade(bzSnapshot.trade);
        const r = await executeBrokerRoutes({
          intent,
          webhookUrl: hookUrl,
          useWebhook: !!hookUrl && !mt5Connected,
          mt5BaseUrl,
          useMt5: mt5Connected,
          mt5Volume: lots,
          symbol: mt5Live.resolvedSymbol,
        });
        if (r.anyOk) {
          bumpAutoTradeCount();
          autoHookDoneBarRef.current = bar.t;
        }
        setLastBrokerMsg(r.anyOk ? `Auto: ${r.summary}` : `Auto: ${r.summary}`);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setLastBrokerMsg(`Auto error: ${msg}`);
      } finally {
        autoHookInFlight.current = false;
      }
    })();
  }, [
    autoExecuteSignals,
    engineHydrated,
    runMode,
    brokerWebhookUrl,
    bilshenzEngine.lastBarSig,
    bilshenzEngine.bundle?.m30?.length
      ? bilshenzEngine.bundle.m30[bilshenzEngine.bundle.m30.length - 1].t
      : null,
    bzSnapshot.signals.anyBuy,
    bzSnapshot.signals.anySell,
    bzSnapshot.trade,
    tradeCount,
    dailyTradeCap,
    bumpAutoTradeCount,
    mt5BaseUrl,
    mt5Connected,
    mt5Live.resolvedSymbol,
    execLotsForTrade,
    bzSnapshot.trade,
  ]);

  useEffect(() => {
    if (mt5Connected && mt5Live.feedReady) {
      setLastBrokerMsg((prev) =>
        prev.startsWith('Auto:') || prev.startsWith('MT5') ? prev : 'MT5 live feed · M30 bars from terminal'
      );
    }
    if (mt5Live.feedError) setLastBrokerMsg(`MT5 feed: ${mt5Live.feedError}`);
  }, [mt5Connected, mt5Live.feedReady, mt5Live.feedError]);

  useEffect(() => {
    if (!autoExecuteSignals) autoHookDoneBarRef.current = null;
  }, [autoExecuteSignals]);

  useEffect(() => {
    if (runMode !== 'live') autoHookDoneBarRef.current = null;
  }, [runMode]);

  const histRows = useMemo(() => {
    const mapped = mapJournalToHistRows(bilshenzEngine.journalRows);
    if (mapped.length) return mapped;
    if (useRealMt5) return [];
    return SIGNAL_HISTORY_SIM;
  }, [bilshenzEngine.journalRows, useRealMt5]);

  const engineWinRatePctStr =
    bzSnapshot.winRate.totalWins + bzSnapshot.winRate.totalLosses > 0
      ? `${bzSnapshot.winRate.winRatePct.toFixed(1)}%`
      : '—';
  const engineClosedTradesStr = String(bzSnapshot.winRate.totalWins + bzSnapshot.winRate.totalLosses);

  const sessionBits = useMemo(() => mapSessionBitsFromEngine(bzSnapshot.session), [bzSnapshot.session]);

  const sr = useMemo(() => mapSrFromEngine(bzSnapshot, chartPrice, C), [bzSnapshot, chartPrice]);

  const dayBits = useMemo(() => {
    const days = ['SUNDAY', 'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY'];
    const day = days[est.dow];
    const isMonTue = est.dow === 1 || est.dow === 2;
    const isWedFri = est.dow >= 3 && est.dow <= 5;
    let mode = 'PRE-WEEK STANDBY';
    let rule = 'Markets open Monday';
    let icon = '📅';
    let todayM = 'N/A';
    let modeRR = 'N/A';
    let rrColor = C.dim;
    if (isMonTue) {
      mode = 'SCALP MENTALITY';
      rule = 'Partial @ 1:1 RR → BE';
      icon = '⚡';
      todayM = 'Partial @ 1R';
      modeRR = 'SCALP';
      rrColor = C.amber;
    } else if (isWedFri) {
      mode = 'TREND MENTALITY';
      rule = '50% @ 1.5R · Trail H1 lows';
      icon = '🚀';
      todayM = 'Trail H1 lows';
      modeRR = 'TREND';
      rrColor = C.green;
    } else {
      rrColor = C.dim;
    }
    return { day, mode, rule, icon, todayM, modeRR, rrColor };
  }, [est.dow]);

  const tick = useCallback(() => {
    setPrice((p0) => {
      let p = p0 + (Math.random() - 0.47) * 0.9;
      p = parseFloat(p.toFixed(2));
      return p;
    });
    setSpread(parseFloat((0.35 + Math.random() * 1.2).toFixed(2)));
    setPnl((p0) => {
      const pr = Math.round(p0 + (Math.random() - 0.44) * 10);
      return pr;
    });
    setDxy(parseFloat((98.8 + Math.random() * 1.8).toFixed(2)));
    setUs10y(parseFloat((4.15 + Math.random() * 0.35).toFixed(2)));
    const atrNext = parseFloat((55 + Math.random() * 45).toFixed(1));
    setAtr(atrNext);
    setAtrFillPct(Math.min(100, ((atrNext - 30) / 120) * 100));
  }, []);

  useEffect(() => {
    if (!useRealMt5) return;
    if (mt5Live.price != null) setPrice(mt5Live.price);
    if (mt5Live.spreadPips != null) setSpread(mt5Live.spreadPips);
    if (mt5Live.account?.profit != null) setPnl(mt5Live.account.profit);
    if (mt5Live.dxy != null) setDxy(mt5Live.dxy);
    if (mt5Live.us10y != null) setUs10y(mt5Live.us10y);
  }, [
    useRealMt5,
    mt5Live.price,
    mt5Live.spreadPips,
    mt5Live.account?.profit,
    mt5Live.dxy,
    mt5Live.us10y,
  ]);

  useEffect(() => {
    if (!useRealMt5) return;
    const ap = bzSnapshot.risk.atrPips;
    if (ap == null || !Number.isFinite(ap)) return;
    setAtr(ap);
    setAtrFillPct(Math.min(100, ((ap - 30) / 120) * 100));
  }, [useRealMt5, bzSnapshot.risk.atrPips]);

  useEffect(() => {
    if (runMode !== 'live' || useRealMt5) return undefined;
    const id = setInterval(tick, 1400);
    return () => clearInterval(id);
  }, [tick, runMode, useRealMt5]);

  const spHigh = spread > (bilshenzEngine.cfg?.maxSpreadPips ?? 3.5);
  const spreadOkColor = spHigh ? C.red : C.green;

  const xauDayOpen = useMemo(() => {
    const m30 = bilshenzEngine.bundle?.m30;
    if (m30?.length) {
      const ref = m30[Math.max(0, m30.length - 48)];
      return ref?.o ?? ref?.c ?? chartPrice;
    }
    return useRealMt5 ? chartPrice : 4698.2;
  }, [useRealMt5, bilshenzEngine.bundle?.m30, chartPrice]);

  const xauDiff = parseFloat((chartPrice - xauDayOpen).toFixed(2));
  const xauUp = xauDiff >= 0;

  const pipSz = defaultBilshenzConfig.pipSize;
  const displayBid = useRealMt5 && mt5Live.bid != null ? mt5Live.bid : price - spread * pipSz;
  const displayAsk = useRealMt5 && mt5Live.ask != null ? mt5Live.ask : price + spread * pipSz;

  const btMaxIdx = Math.max(0, bilshenzEngine.m30BaseLength - 1);
  const btMinIdx = Math.min(80, btMaxIdx);

  useEffect(() => {
    if (runMode !== 'backtest' || !backtestPlaying) return undefined;
    const id = setInterval(() => {
      setBacktestEndIndex((idx) => Math.min(btMaxIdx, idx + 1));
    }, 420);
    return () => clearInterval(id);
  }, [runMode, backtestPlaying, btMaxIdx]);

  useEffect(() => {
    if (runMode === 'backtest' && backtestPlaying && backtestEndIndex >= btMaxIdx) {
      setBacktestPlaying(false);
    }
  }, [runMode, backtestPlaying, backtestEndIndex, btMaxIdx]);

  const atrModePill = useMemo(() => {
    const cfg = bilshenzEngine.cfg;
    const ap = bzSnapshot.risk.atrPips;
    const rn = cfg?.riskPctAtrNormal ?? 1;
    const re = cfg?.riskPctAtrElevated ?? 0.7;
    const rc = cfg?.riskPctAtrCrisis ?? 0.5;
    if (ap == null) return { text: '— ATR MODE', cls: 'std' };
    if (ap < 50) return { text: `✓ NORMAL MODE — RISK: ${rn}%`, cls: 'std' };
    if (ap < 100) return { text: `⚠ ELEVATED MODE — RISK: ${re}%`, cls: 'amb' };
    return { text: `✗ CRISIS MODE — RISK: ${rc}%`, cls: 'red' };
  }, [bzSnapshot.risk.atrPips, bilshenzEngine.cfg]);

  const chartPts = useMemo(() => {
    const m30 = bilshenzEngine.bundle?.m30;
    if (m30?.length && (useRealMt5 || runMode === 'backtest')) {
      const slice = m30.slice(-16);
      const w = 900;
      const lows = slice.map((b) => b.l);
      const highs = slice.map((b) => b.h);
      const min = Math.min(...lows);
      const max = Math.max(...highs);
      const range = max - min || 1;
      return slice.map((b, i) => {
        const x = (i / Math.max(slice.length - 1, 1)) * w;
        const y = 8 + (1 - (b.c - min) / range) * 92;
        return [x, y];
      });
    }
    if (useRealMt5) return [];
    return [
      [0, 105],
      [80, 100],
      [160, 94],
      [240, 90],
      [320, 84],
      [400, 76],
      [460, 82],
      [480, 68],
      [530, 62],
      [580, 56],
      [640, 48],
      [700, 38],
      [760, 26],
      [820, 16],
      [900, 10],
    ];
  }, [useRealMt5, bilshenzEngine.bundle?.m30]);

  const sigPill = useMemo(() => {
    const t = bzSnapshot.trade;
    if (t.setup === 'P1') return { text: '🟩 P1 — S/R BREAKOUT & RETEST', variant: 'break' };
    if (t.setup === 'P2') return { text: '🟦 P2 — WICK FILL (FLUIDITY)', variant: 'wick' };
    if (t.setup === 'P3') return { text: '🟡 P3 — SESSION IMPULSE', variant: 'flip' };
    if (bzSnapshot.risk.chopZone) return { text: '⚠ H4 CHOP — advisory', variant: 'wick' };
    return { text: '⬡ SCANNING — NO PRIORITY SETUP', variant: 'wick' };
  }, [bzSnapshot.trade, bzSnapshot.risk.chopZone]);

  const pillStyle =
    sigPill.variant === 'flip'
      ? styles.pillFlip
      : sigPill.variant === 'wick'
        ? styles.pillWick
        : styles.pillBreak;

  const onExecute = useCallback(() => {
    if (!engineHydrated) return;
    if (tradeCount >= dailyTradeCap) return;
    setExecBusy(true);
    setTimeout(async () => {
      const snap = bzRef.current;
      const tradeSnap = snap.trade;
      const en = engineRef.current;
      const barT = en.bundle?.m30?.length ? en.bundle.m30[en.bundle.m30.length - 1].t : null;
      const gate = canExecuteTrade(snap, tradeSnap);
      if (!gate.ok) {
        setLastBrokerMsg(`EXEC blocked: ${gate.reason}`);
        setExecBusy(false);
        return;
      }
      incrementExecuteTrade();
      const hookUrl = brokerWebhookUrl.trim();
      const intent = buildBrokerOrderIntent(tradeSnap, {
        barTimeMs: barT,
        runMode: runModeRef.current,
        trigger: 'manual',
        symbol: mt5Live.resolvedSymbol || 'XAUUSD',
      });
      if (intent && ((brokerHookEnabled && hookUrl) || mt5Connected)) {
        const lots = execLotsForTrade(tradeSnap);
        const r = await executeBrokerRoutes({
          intent,
          webhookUrl: hookUrl,
          useWebhook: !!(brokerHookEnabled && hookUrl && !mt5Connected),
          mt5BaseUrl,
          useMt5: mt5Connected,
          mt5Volume: lots,
          symbol: mt5Live.resolvedSymbol,
        });
        setLastBrokerMsg(r.summary ? `${r.summary} · ${lots.toFixed(2)} lot` : r.summary);
      } else if (!intent) {
        setLastBrokerMsg('EXEC skipped (no side)');
      } else {
        setLastBrokerMsg('');
      }
      setExecBusy(false);
    }, 1200);
  }, [
    engineHydrated,
    tradeCount,
    dailyTradeCap,
    incrementExecuteTrade,
    brokerHookEnabled,
    brokerWebhookUrl,
    mt5BaseUrl,
    mt5Connected,
    mt5Live.resolvedSymbol,
    execLotsForTrade,
  ]);

  const onSkip = () => {
    setSigMuted(true);
    setTimeout(() => setSigMuted(false), 2500);
  };

  const sessTag = sessionBits.act
    ? sessionBits.sessLabel.replace(/[①②③☠]\s/, '')
    : 'OUT OF SESSION';

  /** Bottom nav sits outside ScrollView — only a sliver so the footer line isn’t clipped */
  const scrollBottomPad = !isWide ? 6 : 10;
  const showDeskChrome = isWide || mobileTab === 'desk';
  const showFullHeader =
    isWide || mobileTab === 'desk' || mobileTab === 'home' || mobileTab === 'profile' || mobileTab === 'risk';

  const gmAlerts = useMemo(
    () => buildGmAlertRows(bzSnapshot.risk, nfpBlackout, newsActive, C),
    [bzSnapshot.risk, nfpBlackout, newsActive, C]
  );
  const tickerStrings = useMemo(() => gmAlerts.map((a) => a.text), [gmAlerts]);
  const tapeTheme = useMemo(
    () => ({
      barBg: C.panel2,
      barBorder: C.border,
      text: C.text,
      textMuted: C.dim,
      glow: 'rgba(212, 180, 90, 0.42)',
    }),
    [C]
  );

  const flowNodes = useMemo(() => {
    const ec = bilshenzEngine.cfg;
    const maxSp = ec?.maxSpreadPips ?? 3.5;
    const beOff = ec?.beOffset ?? 12;
    const r = bzSnapshot.risk;
    const g = bzSnapshot.gates;
    const f1State = nfpBlackout || g.masterBlock ? 'fail' : 'pass';
    const f2State = newsActive ? 'warn' : 'pass';
    const f3State = sessionBits.act ? 'pass' : 'fail';
    const f4State = spHigh ? 'fail' : 'pass';
    const f5State = r.geoHigh ? 'fail' : r.geoMedium ? 'warn' : 'pass';
    const f6State = r.dxyBlocksBuy ? 'warn' : 'pass';
    const f7State = bzSnapshot.bias?.isBullish || bzSnapshot.bias?.isBearish ? 'pass' : 'warn';
    const f8State = r.chopZone ? 'warn' : 'pass';
    const f9State = sr.bullClean || sr.bearClean ? 'pass' : 'warn';
    const f10State = r.athZoneBlocked ? 'warn' : 'pass';
    const setup = bzSnapshot.trade?.setup;
    const f11State = setup ? 'pass' : 'warn';
    const f11Ft = setup ? `SETUP\n${setup}` : 'SETUP\nP1-P3';
    const f12State = 'pass';
    const f13State = r.atrPips != null && r.atrPips >= 50 ? 'warn' : 'pass';
    const f14State = r.yieldHigh ? 'warn' : 'pass';
    const f15State = g.maxTradesReached ? 'fail' : 'pass';

    return [
      { id: 'f1', state: f1State, icon: '☢', sn: 'S01', ft: 'BLACKOUT\nCHECK', tag: 'NEW' },
      { id: 'f2', state: f2State, icon: '📰', sn: 'S02', ft: 'NEWS\n±15MIN' },
      { id: 'f3', state: f3State, icon: '🕒', sn: 'S03', ft: 'SESSION\nACTIVE' },
      { id: 'f4', state: f4State, icon: '📏', sn: 'S04', ft: `SPREAD\n≤${maxSp}p` },
      { id: 'f5', state: f5State, icon: '🌍', sn: 'S05', ft: 'GEO\nRISK', tag: 'NEW' },
      { id: 'f6', state: f6State, icon: '💵', sn: 'S06', ft: 'DXY\nCONFIRM', tag: 'NEW' },
      { id: 'f7', state: f7State, icon: '📊', sn: 'S07', ft: 'HTF\nBIAS' },
      { id: 'f8', state: f8State, icon: '🌀', sn: 'S08', ft: 'CHOP\nDETECT', tag: 'NEW' },
      { id: 'f9', state: f9State, icon: '🔭', sn: 'S09', ft: 'LEFT SIDE\nCLEAN' },
      { id: 'f10', state: f10State, icon: '🗺', sn: 'S10', ft: 'ZONE\nMAP', tag: 'NEW' },
      { id: 'f11', state: f11State, icon: '⚡', sn: 'S11', ft: f11Ft },
      { id: 'f12', state: f12State, icon: '🕯', sn: 'S12', ft: 'CANDLE\n40/60' },
      { id: 'f13', state: f13State, icon: '📉', sn: 'S13', ft: 'ATR\nSIZE', tag: 'NEW' },
      { id: 'f14', state: f14State, icon: '🏛', sn: 'S14', ft: 'YIELD\nCHECK', tag: 'NEW' },
      { id: 'f15', state: f15State, icon: '🎯', sn: 'S15', ft: `EXECUTE\n+BE@${beOff}p` },
    ];
  }, [
    bilshenzEngine.cfg,
    bzSnapshot.risk,
    bzSnapshot.gates,
    bzSnapshot.bias,
    bzSnapshot.trade,
    sessionBits.act,
    spHigh,
    sr.bullClean,
    sr.bearClean,
    nfpBlackout,
    newsActive,
  ]);

  if (!bundleReady || (useRealMt5 && !mt5Live.feedReady)) {
    return (
      <View style={[styles.safeRoot, { alignItems: 'center', justifyContent: 'center', padding: 24 }]}>
        <Text style={{ color: C.dim, fontSize: 12, textAlign: 'center' }}>
          {useRealMt5
            ? mt5Live.feedError || 'Connecting to MT5…'
            : 'Loading market engine…'}
        </Text>
      </View>
    );
  }

  return (
    <BilshenzEngineCtx.Provider value={engineCtxValue}>
      <SafeAreaView style={styles.safeRoot} edges={['top']}>
        <View style={styles.root}>
          <ScrollView
            style={{ flex: 1 }}
            stickyHeaderIndices={showFullHeader ? [0] : []}
            contentContainerStyle={[styles.scrollContent, { paddingHorizontal: 0, paddingBottom: scrollBottomPad }]}
            keyboardShouldPersistTaps="handled">
            {showFullHeader ? (
              <View style={[styles.header, { paddingHorizontal: pad }]}>
                <Row style={[styles.headerTopRow, !isWide && styles.stackCol, !isWide && styles.headerStackGap]}>
                  <View style={!isWide ? styles.brandStack : undefined}>
                    <BilshenzHeader />
                  </View>

                  <View style={[styles.hdrCenter, !isWide && { alignItems: 'flex-start', marginTop: 8 }]}>
                    <Row style={styles.xauRow}>
                      <Text style={styles.xauPair}>XAU/USD</Text>
                      <Text style={styles.xauPrice}>{fmtNum(chartPrice)}</Text>
                      <Text style={[styles.xauChg, { color: xauUp ? C.green : C.red }]}>
                        {(xauUp ? '▲ +' : '▼ ') + Math.abs(xauDiff).toFixed(2)}
                      </Text>
                    </Row>
                    <Text style={styles.xauSub}>
                      BID {fmtNum(displayBid)} · ASK {fmtNum(displayAsk)} · SPREAD{' '}
                      <Text style={styles.xauSub}>{spread.toFixed(2)}</Text>p
                      {useRealMt5 ? ' · MT5' : ''}
                    </Text>
                    <TextInput
                      placeholder="Notes / tag (optional)"
                      placeholderTextColor={C.dim2}
                      style={[styles.headerNotes, { width: isWide ? 220 : width - pad * 2 }]}
                    />
                  </View>

                  <Row style={[styles.hdrRight, !isWide && { marginTop: 2, alignSelf: 'stretch', justifyContent: 'space-between' }]}>
                    <Row style={styles.livePill}>
                      <BlinkDot color={C.green} />
                      <Text style={styles.livePillTxt}>
                        {runMode === 'backtest' ? 'BACKTEST' : useRealMt5 ? 'MT5 LIVE' : 'LIVE SIM'}
                      </Text>
                    </Row>
                    <View style={styles.clockBox}>
                      <Text style={styles.clockUtc}>{utcStr}</Text>
                      <Text style={styles.clockEst}>
                        {String(est.h).padStart(2, '0')}:{String(est.m).padStart(2, '0')} EST
                      </Text>
                    </View>
                  </Row>
                </Row>
                <GeoPoliticalTicker
                  style={{ marginTop: 10, marginHorizontal: -pad }}
                  items={tickerStrings}
                  tapeTheme={tapeTheme}
                />
              </View>
            ) : (
              <MobileCompactStrip
                price={chartPrice}
                spread={spread}
                pad={pad}
                utcStr={utcStr}
                est={est}
                tickerItems={tickerStrings}
                tapeTheme={tapeTheme}
                dayOpen={xauDayOpen}
              />
            )}

            {showDeskChrome ? (
              <>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.bannerScroll}>
                  <View style={[styles.godBanner, { paddingHorizontal: pad }]}>
                    {gmAlerts.map((a, i) => (
                      <React.Fragment key={`ga-${i}`}>
                        {i > 0 ? <View style={styles.gmDivider} /> : null}
                        <Row style={styles.gmAlert}>
                          <BlinkDot color={a.color} />
                          <Text style={[styles.gmAlertTxt, { color: a.color }]}>{a.text}</Text>
                        </Row>
                      </React.Fragment>
                    ))}
                  </View>
                </ScrollView>

                <View style={[styles.sessBar, { flexDirection: 'row', flexWrap: 'wrap' }]}>
                  <SessionBlock
                    narrow={!isWide}
                    active={sessionBits.s1}
                    forceDead={false}
                    sn="① PRE-LONDON"
                    st="19:00–23:00 EST"
                    badge={sessionBits.s1 ? 'OPEN' : 'WAITING'}
                    badgeKind={sessionBits.s1 ? 'open' : 'wait'}
                  />
                  <SessionBlock
                    narrow={!isWide}
                    active={sessionBits.s2}
                    forceDead={false}
                    sn="② LONDON OPEN"
                    st="02:00–06:00 EST"
                    badge={sessionBits.s2 ? 'OPEN' : 'WAITING'}
                    badgeKind={sessionBits.s2 ? 'open' : 'wait'}
                  />
                  <SessionBlock
                    narrow={!isWide}
                    active={sessionBits.s3}
                    forceDead={false}
                    sn="③ NEW YORK OPEN · PEAK"
                    st="07:00–12:00 EST"
                    badge={sessionBits.s3 ? 'OPEN' : 'WAITING'}
                    badgeKind={sessionBits.s3 ? 'open' : 'wait'}
                  />
                  <SessionBlock
                    narrow={!isWide}
                    active={false}
                    forceDead
                    sn="☠ DEAD ZONE"
                    st="ALL OTHER TIMES"
                    badge={sessionBits.act ? 'OVERRIDE' : 'HIBERNATE'}
                    badgeKind={sessionBits.act ? 'open' : 'dead'}
                  />
                </View>

                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.flowScroll}>
                  <View style={[styles.flowWrap, { paddingHorizontal: pad }]}>
                    {flowNodes.map((n, i) => (
                      <React.Fragment key={n.id}>
                        <View style={[styles.fnode, n.state === 'pass' ? styles.fnodePass : n.state === 'fail' ? styles.fnodeFail : styles.fnodeWarn]}>
                          <Text style={styles.fi}>{n.icon}</Text>
                          <Text style={styles.fn}>{n.sn}</Text>
                          <Text style={styles.ft}>{n.ft}</Text>
                          {n.tag ? <Text style={styles.fnewTag}>{n.tag}</Text> : null}
                        </View>
                        {i < flowNodes.length - 1 ? <Text style={styles.farr}>→</Text> : null}
                      </React.Fragment>
                    ))}
                  </View>
                </ScrollView>
              </>
            ) : null}

            {showDeskChrome && runMode === 'backtest' ? (
              <View style={[styles.btBar, { paddingHorizontal: pad }]}>
                <Text style={styles.btBarTitle}>BACKTEST REPLAY · M30 cursor · session time follows bar</Text>
                <Row style={styles.btBarRow}>
                  <TouchableOpacity
                    style={styles.btMiniBtn}
                    onPress={() => setBacktestEndIndex((i) => Math.max(btMinIdx, i - 1))}
                    activeOpacity={0.85}>
                    <Text style={styles.btMiniBtnTxt}>◀</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.btMiniBtn}
                    onPress={() => setBacktestEndIndex((i) => Math.min(btMaxIdx, i + 1))}
                    activeOpacity={0.85}>
                    <Text style={styles.btMiniBtnTxt}>▶</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.btMiniBtn, backtestPlaying && { borderColor: C.gold }]}
                    onPress={() => setBacktestPlaying((p) => !p)}
                    activeOpacity={0.85}>
                    <Text style={styles.btMiniBtnTxt}>{backtestPlaying ? '❚❚' : '▶'}</Text>
                  </TouchableOpacity>
                  <Text style={styles.btBarMeta}>
                    Bar {bilshenzEngine.backtestEndClamped + 1}/{bilshenzEngine.m30BaseLength} · BT journal (not persisted)
                  </Text>
                </Row>
                <Slider
                  style={styles.btSlider}
                  minimumValue={btMinIdx}
                  maximumValue={btMaxIdx}
                  step={1}
                  value={backtestEndIndex}
                  onValueChange={setBacktestEndIndex}
                  minimumTrackTintColor={C.gold}
                  maximumTrackTintColor={C.border}
                  thumbTintColor={C.goldL}
                />
              </View>
            ) : null}

            {isWide ? (
              <View style={[styles.grid, { paddingHorizontal: pad, flexDirection: 'row', alignItems: 'stretch' }]}>
                <View style={[styles.col, { width: 250 }]}>
                  <LeftColumn sr={sr} dxy={dxy} />
                </View>
                <View style={[styles.col, { flex: 1 }]}>
                  <CenterColumn
                    price={chartPrice}
                    sr={sr}
                    spread={spread}
                    spreadOkColor={spreadOkColor}
                    spHigh={spHigh}
                    sessionBits={sessionBits}
                    dayBits={dayBits}
                    sigMuted={sigMuted}
                    sigPill={sigPill}
                    pillStyle={pillStyle}
                    chartPts={chartPts}
                    execBusy={execBusy}
                    tradeCount={tradeCount}
                    onExecute={onExecute}
                    onSkip={onSkip}
                    atr={atr}
                    atrFillPct={atrFillPct}
                    atrModePill={atrModePill}
                    engineTrade={bzSnapshot.trade}
                    histRows={histRows}
                    accountEquity={sizingEquity}
                    mt5LiveAccount={useRealMt5}
                    mt5Account={useRealMt5 ? mt5Live.account : null}
                  />
                </View>
                <View style={[styles.col, { width: 250 }]}>
                  <RightColumn
                    tradeCount={tradeCount}
                    pnl={pnl}
                    sessTag={sessTag}
                    spread={spread}
                    spreadOkColor={spreadOkColor}
                    spHigh={spHigh}
                    dayBits={dayBits}
                    accountEquity={sizingEquity}
                    mt5LiveAccount={useRealMt5}
                    mt5Account={useRealMt5 ? mt5Live.account : null}
                  />
                </View>
              </View>
            ) : mobileTab === 'home' ? (
              <View style={[styles.mobileTabBody, styles.ghBody, { paddingHorizontal: 0 }]}>
                <GodmodeHome
                  pad={pad}
                  pnl={pnl}
                  tradeCount={tradeCount}
                  sessionBits={sessionBits}
                  sr={sr}
                  utcStr={utcStr}
                  histRows={histRows}
                  winRatePct={engineWinRatePctStr}
                />
              </View>
            ) : mobileTab === 'desk' ? (
              <View style={[styles.grid, { paddingHorizontal: pad, flexDirection: 'column', alignItems: 'stretch' }]}>
                <View style={[styles.col, { width: '100%' }]}>
                  <LeftColumn sr={sr} dxy={dxy} />
                </View>
                <View style={[styles.col, { width: '100%' }]}>
                  <CenterColumn
                    price={chartPrice}
                    sr={sr}
                    spread={spread}
                    spreadOkColor={spreadOkColor}
                    spHigh={spHigh}
                    sessionBits={sessionBits}
                    dayBits={dayBits}
                    sigMuted={sigMuted}
                    sigPill={sigPill}
                    pillStyle={pillStyle}
                    chartPts={chartPts}
                    execBusy={execBusy}
                    tradeCount={tradeCount}
                    onExecute={onExecute}
                    onSkip={onSkip}
                    atr={atr}
                    atrFillPct={atrFillPct}
                    atrModePill={atrModePill}
                    engineTrade={bzSnapshot.trade}
                    histRows={histRows}
                    accountEquity={sizingEquity}
                    mt5LiveAccount={useRealMt5}
                    mt5Account={useRealMt5 ? mt5Live.account : null}
                    compactSignal
                  />
                </View>
                <View style={[styles.col, { width: '100%' }]}>
                  <RightColumn
                    tradeCount={tradeCount}
                    pnl={pnl}
                    sessTag={sessTag}
                    spread={spread}
                    spreadOkColor={spreadOkColor}
                    spHigh={spHigh}
                    dayBits={dayBits}
                    accountEquity={sizingEquity}
                    mt5LiveAccount={useRealMt5}
                    mt5Account={useRealMt5 ? mt5Live.account : null}
                  />
                </View>
              </View>
            ) : mobileTab === 'trade' ? (
              <View style={[styles.mobileTabBody, { paddingHorizontal: pad }]}>
                <CenterColumn
                  price={chartPrice}
                  sr={sr}
                  spread={spread}
                  spreadOkColor={spreadOkColor}
                  spHigh={spHigh}
                  sessionBits={sessionBits}
                  dayBits={dayBits}
                  sigMuted={sigMuted}
                  sigPill={sigPill}
                  pillStyle={pillStyle}
                  chartPts={chartPts}
                  execBusy={execBusy}
                  tradeCount={tradeCount}
                  onExecute={onExecute}
                  onSkip={onSkip}
                  atr={atr}
                  atrFillPct={atrFillPct}
                  atrModePill={atrModePill}
                  engineTrade={bzSnapshot.trade}
                  histRows={histRows}
                  accountEquity={sizingEquity}
                  mt5LiveAccount={useRealMt5}
                  mt5Account={useRealMt5 ? mt5Live.account : null}
                  compactSignal
                />
              </View>
            ) : mobileTab === 'profile' ? (
              <View style={[styles.mobileTabBody, styles.psTabBody, { paddingHorizontal: 0 }]}>
                <ProfileTab
                  pad={pad}
                  width={width}
                  riskMode={profileRiskMode}
                  onRiskModeChange={setProfileRiskMode}
                  newsActive={newsActive}
                  onNewsActiveChange={setNewsActive}
                  nfpBlackout={nfpBlackout}
                  onNfpBlackoutChange={setNfpBlackout}
                  onResetEngineTuning={() => {
                    setNewsActive(false);
                    setNfpBlackout(false);
                  }}
                  engineWinRatePct={engineWinRatePctStr}
                  engineClosedTrades={engineClosedTradesStr}
                  maxDailyTrades={profileMaxDailyTrades}
                  onMaxDailyTradesChange={setProfileMaxDailyTrades}
                  engineHydrated={engineHydrated}
                  runMode={runMode}
                  onRunModeChange={(m) => {
                    setBacktestPlaying(false);
                    setRunMode(m);
                  }}
                  brokerHookEnabled={brokerHookEnabled}
                  onBrokerHookEnabledChange={setBrokerHookEnabled}
                  brokerWebhookUrl={brokerWebhookUrl}
                  onBrokerWebhookUrlChange={setBrokerWebhookUrl}
                  lastBrokerMsg={lastBrokerMsg}
                  autoExecuteSignals={autoExecuteSignals}
                  onAutoExecuteSignalsChange={onAutoExecuteSignalsChange}
                  mt5Connected={mt5Connected}
                />
              </View>
            ) : mobileTab === 'risk' ? (
              <View style={[styles.mobileTabBody, { paddingHorizontal: pad }]}>
                <RightColumn
                  tradeCount={tradeCount}
                  pnl={useRealMt5 && mt5Live.account?.profit != null ? mt5Live.account.profit : pnl}
                  sessTag={sessTag}
                  spread={spread}
                  spreadOkColor={spreadOkColor}
                  spHigh={spHigh}
                  dayBits={dayBits}
                  accountEquity={sizingEquity}
                  mt5LiveAccount={useRealMt5}
                  mt5Account={useRealMt5 ? mt5Live.account : null}
                />
              </View>
            ) : null}

            {showDeskChrome ? (
              <View style={[styles.footer, { paddingHorizontal: pad }]}>
                <Text style={styles.footerTxt}>
                  BILSHENZ v3.2 GODMODE — <Text style={styles.footerGold}>Jimplas Capital Management</Text> · Billy William Onen · CEO
                </Text>
                <Text style={styles.footerTxt}>{utcStr} UTC</Text>
                <Text style={styles.footerTxt}>
                  <Text style={styles.footerGold}>Jimplas Fluidity P1/P2/P3 · S&R · Left Side Scanner · MT5 Bridge</Text>
                  {useRealMt5 ? ' · MT5 live data' : ' · Simulated'} · Not financial advice
                </Text>
              </View>
            ) : (
              <View style={[styles.footer, styles.footerMinimal, { paddingHorizontal: pad }]}>
                <Text style={styles.footerTxt}>
                  BILSHENZ v3.2 ·{' '}
                  <Text style={styles.footerGold}>
                    {mobileTab === 'desk' ? 'INTEL' : mobileTab === 'profile' ? 'PROFILE' : mobileTab.toUpperCase()}
                  </Text>{' '}
                  · {useRealMt5 ? 'MT5 live data' : 'Simulated'} · Not financial advice
                </Text>
              </View>
            )}
          </ScrollView>
          {!isWide ? <MobileBottomNav tab={mobileTab} onChange={setMobileTab} bottomInset={insets.bottom} /> : null}
        </View>
      </SafeAreaView>
    </BilshenzEngineCtx.Provider>
  );
}


SplashScreen.preventAutoHideAsync().catch(() => {});

function AppRoot() {
  const { styles } = useBilshenzTheme();
  const [splashDone, setSplashDone] = useState(false);
  const [engineReady, setEngineReady] = useState(false);

  return (
    <View style={styles.appShell}>
      <View style={styles.appUnderlay} pointerEvents={splashDone ? 'auto' : 'none'}>
        <AppContent onEngineReady={() => setEngineReady(true)} />
      </View>
      {!splashDone ? (
        <View style={styles.splashOverlay}>
          <CinematicSplash appReady={engineReady} onComplete={() => setSplashDone(true)} />
        </View>
      ) : null}
    </View>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <Mt5BridgeProvider>
          <AppRoot />
        </Mt5BridgeProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
