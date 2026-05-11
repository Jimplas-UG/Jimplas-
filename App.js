import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
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
import Svg, { Defs, LinearGradient, Polyline, Stop } from 'react-native-svg';
import { BlurView } from 'expo-blur';
import Slider from '@react-native-community/slider';
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import BilshenzHeader from './components/BilshenzHeader';

const C = {
  gold: '#D4B45A',
  goldL: '#F2E2B0',
  goldD: '#7A5C18',
  black: '#0A0806',
  appBg: '#100E0A',
  panel: '#15130C',
  panel2: '#1C1A12',
  border: '#322A18',
  text: '#E9E0C8',
  dim: '#7A6C45',
  dim2: '#524628',
  green: '#00E676',
  greenD: 'rgba(0,230,118,0.1)',
  red: '#FF3D57',
  redD: 'rgba(255,61,87,0.1)',
  amber: '#FFB300',
  blue: '#40C4FF',
  purple: '#CE93D8',
  teal: '#26C6DA',
};

const RESISTANCES = [4760.0, 4821.0, 4881.0, 4937.0];
const SUPPORTS = [4698.0, 4645.0, 4576.0, 4509.0, 4441.0];

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

function fmtUsd(n) {
  const neg = n < 0;
  const abs = Math.abs(Math.round(n));
  return (neg ? '-$' : '+$') + abs.toLocaleString('en-US');
}

function fmtNum(n, digits = 2) {
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function getImmRes(p) {
  return RESISTANCES.filter((v) => v > p).sort((a, b) => a - b)[0] ?? null;
}
function getImmSup(p) {
  return SUPPORTS.filter((v) => v < p).sort((a, b) => b - a)[0] ?? null;
}
function getPoiRes(p, immRes) {
  return RESISTANCES.filter((v) => v > p && v > (immRes ?? 0) + 5).sort((a, b) => a - b)[0] ?? null;
}
function getPoiSup(p, immSup) {
  return SUPPORTS.filter((v) => v < p && v < (immSup ?? 9999) - 5).sort((a, b) => b - a)[0] ?? null;
}

function calcChop(priceVal, target) {
  const range = Math.abs(target - priceVal);
  const rangePips = range / 0.1;
  if (rangePips < 15) return 8;
  if (rangePips < 20) return 5;
  if (rangePips < 25) return 4;
  if (rangePips < 30) return 3;
  if (rangePips < 40) return 2;
  return Math.floor(Math.random() * 3);
}

function Row({ children, style }) {
  return <View style={[styles.row, style]}>{children}</View>;
}

function BlinkDot({ color }) {
  return <View style={[styles.ldot, { backgroundColor: color, shadowColor: color }]} />;
}

function SessionBlock({ narrow, active, forceDead, sn, st, badge, badgeKind }) {
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
  return (
    <View style={styles.leftCol}>
      <Panel shell={{}} head={{ title: 'HTF Bias Engine', badge: 'EMA50 · HH/HL' }}>
        <View style={styles.biasHero}>
          <Text style={styles.biasTag}>OVERALL BIAS</Text>
          <Text style={[styles.biasWord, styles.biasBull]}>BULLISH</Text>
          <Text style={styles.biasSub}>Price &gt; EMA50 H4 · Daily HH/HL ✓</Text>
        </View>
        <TfRow l="MONTHLY" r="▲ HH/HL" rStyle={styles.tfBull} />
        <TfRow l="WEEKLY" r="▲ HH/HL" rStyle={styles.tfBull} />
        <TfRow l="DAILY" r="▲ HH/HL" rStyle={styles.tfBull} />
        <TfRow l="H4 EMA50" r="▲ ABOVE" rStyle={styles.tfBull} />
        <TfRow l="H1" r="⚠ RETEST" rStyle={styles.tfNeu} />
        <TfRow l="M30" r="▲ ALIGNED" rStyle={styles.tfBull} />
      </Panel>

      <Panel shell={styles.gmPanelShell} headTint={styles.gmHeaderTint} head={{ title: 'Geopolitical Filter', badge: 'NEW · v3', titleColor: C.red, badgeColor: C.gold }}>
        <View style={styles.geoDial}>
          <Text style={styles.geoRiskLbl}>RISK LEVEL</Text>
          <Text style={styles.geoLevel}>HIGH</Text>
          <Text style={styles.geoSub}>Iran Conflict · Strait of Hormuz</Text>
          <Row style={styles.geoBars}>
            <View style={[styles.geoBar, styles.geoBarG]} />
            <View style={[styles.geoBar, styles.geoBarG]} />
            <View style={[styles.geoBar, styles.geoBarA]} />
            <View style={[styles.geoBar, styles.geoBarA]} />
            <View style={[styles.geoBar, styles.geoBarR]} />
            <View style={[styles.geoBar, styles.geoBarR]} />
            <View style={[styles.geoBar, styles.geoBarR]} />
          </Row>
          <Text style={styles.geoRule}>
            ⚠ RISK=HIGH → MAX 0.25% SIZE{'\n'}Dynamic entries SUSPENDED{'\n'}TP1 reduced by 20%
          </Text>
        </View>
      </Panel>

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

      <Panel shell={styles.flipShell} headTint={styles.flipHeadTint} head={{ title: 'Flip Engine', badge: 'S→R / R→S · v3.2', titleColor: C.amber, badgeColor: C.gold }}>
        <Text style={styles.sectionLbl}>③ LEVEL FLIP STATUS</Text>
        <View style={styles.flipSupOuter}>
          <View style={styles.flipAccentGreen} />
          <View style={{ paddingLeft: 11 }}>
            <Text style={styles.flipGreenLbl}>PREV RESISTANCE → NOW SUPPORT</Text>
            <Text style={styles.flipSupLvl}>{sr.flipSup != null ? fmtNum(sr.flipSup) : fmtNum(4698.0)}</Text>
            <Text style={styles.imSmall}>Price closed above → flipped. E3 retest entry active.</Text>
            <Row style={{ marginTop: 6, gap: 6 }}>
              <Text style={styles.miniTagG}>BUY ON RETEST ✓</Text>
              <Text style={styles.miniTagG2}>ACTIVE</Text>
            </Row>
          </View>
        </View>
        <View style={styles.flipResOuter}>
          <View style={styles.flipAccentRed} />
          <View style={{ paddingLeft: 11 }}>
            <Text style={styles.flipDimLbl}>PREV SUPPORT → NOW RESISTANCE</Text>
            <Text style={[styles.flipResLvl, sr.flipRes == null && { opacity: 0.45 }]}>
              {sr.flipRes != null ? fmtNum(sr.flipRes) : '—'}
            </Text>
            <Text style={styles.imSmall}>No flip detected yet. Watching M30 closes.</Text>
            <Text style={[styles.miniTagWatch, { marginTop: 6 }]}>WATCHING</Text>
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
        <DxyRow l="DXY Level" v={dxy.toFixed(2)} vc={C.text} />
        <DxyRow l="Direction H1" v="▼ FALLING" vc={C.green} />
        <DxyRow l="Status" v="2-Month LOW" vc={C.green} />
        <DxyRow l="Gold Impact" v="✓ BUY SUPPORTED" vc={C.green} />
        <DxyRow l="Signal Filter" v="All signals active" vc={C.green} />
        <Text style={styles.dxyFoot}>✓ DXY FALLING → BUY ENTRIES CONFIRMED</Text>
      </Panel>

      <Panel shell={styles.gmPanelShell} headTint={styles.gmHeaderTint} head={{ title: 'Chop Detector', badge: 'NEW · v3', titleColor: C.amber, badgeColor: C.gold }}>
        <View style={styles.chopActive}>
          <Text style={[styles.chopWord, { color: C.amber }]}>CHOP ZONE</Text>
          <Text style={[styles.chopSub, { color: C.amber }]}>Range: $4,513–$4,660 · Wait-and-see</Text>
        </View>
        <DxyRow l="Last 3 H4 Candles" v="<40p each" vc={C.amber} />
        <DxyRow l="Breakout Entries" v="SUSPENDED" vc={C.red} />
        <DxyRow l="Flip Entries" v="SUSPENDED" vc={C.red} />
        <DxyRow l="Wick Entries" v="ACTIVE ONLY" vc={C.green} />
        <DxyRow l="Exit Chop When" v="Daily candle >60p" vc={C.text} />
      </Panel>

      <Panel shell={styles.gmPanelShell} headTint={styles.gmHeaderTint} head={{ title: 'ATH Wick Awareness', badge: 'NEW · v3', titleColor: C.red, badgeColor: C.gold }}>
        <View style={styles.athZone}>
          <Text style={styles.athTitle}>☠ PERMANENT NO-BUY ZONE</Text>
          <Text style={styles.athRange}>$5,278 – $5,602</Text>
          <Text style={styles.athSub}>ATH Wick · Jan 26, 2026 · Highest bearish vol ever</Text>
        </View>
        <DxyRow l="ATH" v="$5,602.00" vc={C.red} />
        <DxyRow l="Weekly Close" v="$4,895.00" vc={C.text} />
        <DxyRow l="Zone Rule" v="SELL BIAS ONLY" vc={C.red} />
        <DxyRow l="Invalidated By" v="Monthly close >$5,602" vc={C.text} />
        <DxyRow l="Current Price" v="$4,612 · SAFE ZONE" vc={C.green} />
      </Panel>
    </View>
  );
}

function Panel({ shell, headTint, head: { title, badge, titleColor, badgeColor }, children }) {
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
  return (
    <Row style={styles.tfRow}>
      <Text style={styles.tfl}>{l}</Text>
      <Text style={[styles.tfv, rStyle]}>{r}</Text>
    </Row>
  );
}

function DxyRow({ l, v, vc }) {
  return (
    <Row style={styles.dxyRow}>
      <Text style={styles.dxyL}>{l}</Text>
      <Text style={[styles.dxyV, { color: vc }]}>{v}</Text>
    </Row>
  );
}

function ScannerRows({ sr, bull }) {
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
  const chopTxt = chop + (chopOk ? ' bars — OK' : ' bars — CHOP');
  const wickTxt =
    chop <= 1 ? 'None — Clean' : chop <= 3 ? (bull ? '1 minor wick' : '1 minor wick') : 'Multiple wicks';
  const sideTxt = clean ? '✓ CLEAN' : pips >= 25 ? '⚠ CHOP DETECTED' : '✗ DIRTY';
  const rng = (bull ? '+' : '-') + pips.toFixed(1) + 'p';
  const rngColor =
    clean ? (bull ? C.green : C.red) : pips >= 25 ? C.amber : bull ? C.red : C.amber;

  return (
    <View style={styles.lsPanel}>
      {row(bull ? 'Entry → IMMED RES' : 'Entry → IMMED SUP', rng, { color: rngColor })}
      {row('≥ 25 pips?', qualTxt, qualOk ? styles.tfBull : styles.tfBear)}
      {row('Consolidation bars', chopTxt, chopOk ? styles.tfBull : styles.tfBear)}
      {row('Wick rejections in path', wickTxt, chop <= 1 ? styles.tfBull : chop <= 3 ? styles.tfNeu : styles.tfBear)}
      {row('Left side status', sideTxt, clean ? styles.tfBull : pips >= 25 ? styles.tfNeu : styles.tfBear)}
    </View>
  );
}

function VerdictBar({ ok, bull }) {
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
  variant = 'dashboard',
  compactSignal = false,
}) {
  const isDashboard = variant === 'dashboard';
  const fSpreadCol = spHigh ? C.red : C.green;
  const rangeCol = sr.bullClean ? C.green : C.amber;
  const modeCls =
    atrModePill.cls === 'std' ? styles.modeStd : atrModePill.cls === 'amb' ? styles.modeAmb : styles.modeRed;

  return (
    <View style={styles.centerCol}>
      <View style={[styles.sigCard, compactSignal && styles.sigCardCompact, sigMuted && { opacity: 0.25 }]}>
        <View style={styles.sigGlow} />
        <View style={styles.sigAccent} />
        {compactSignal ? (
          <View style={styles.sigInnerStack}>
            <Row style={styles.sigTopTrade}>
              <View style={styles.sigBuyBadge}>
                <Text style={[styles.sigAction, styles.sigBuy, styles.sigActionCompact]}>BUY</Text>
              </View>
              <View style={styles.sigInfoCompact}>
                <Text style={styles.sigPairCompact}>XAU / USD — SPOT GOLD</Text>
                <Text style={[styles.sigPill, pillStyle]}>{sigPill.text}</Text>
                <Text style={styles.sigConfCompact}>⬡ ALL 15 FILTERS PASSED · CONFIDENCE 91.2%</Text>
                <Text style={styles.sigStratCompact}>
                  Liquidity Sweep → M15 Rejection → Wick Fill · GEO RISK ADJ: 0.25% SIZE
                </Text>
              </View>
            </Row>
            <Text style={styles.sigSessCompact}>📍 {sessionBits.sessLabel}</Text>
            <Row style={styles.sigBtnRow}>
              <TouchableOpacity
                activeOpacity={0.85}
                style={[styles.execBtn, styles.execBtnCompact, execBusy && { opacity: 0.6 }]}
                onPress={onExecute}
                disabled={execBusy}>
                <Text style={styles.execBtnTxtCompact}>
                  {execBusy ? '⏳ PROCESSING...' : tradeCount >= 3 ? 'MAX TRADES' : '⚡ EXECUTE'}
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
              <Text style={[styles.sigAction, styles.sigBuy]}>BUY</Text>
              <View style={styles.sigInfo}>
                <Text style={styles.sigPair}>XAU / USD — SPOT GOLD</Text>
                <Text style={[styles.sigPill, pillStyle]}>{sigPill.text}</Text>
                <Text style={styles.sigConf}>⬡ ALL 15 FILTERS PASSED · CONFIDENCE 91.2%</Text>
                <Text style={styles.sigStrat}>Liquidity Sweep → M15 Rejection → Wick Fill · GEO RISK ADJ: 0.25% SIZE</Text>
              </View>
            </Row>
            <View style={styles.sigR}>
              <Text style={styles.sigSess}>📍 {sessionBits.sessLabel}</Text>
              <TouchableOpacity
                activeOpacity={0.85}
                style={[styles.execBtn, execBusy && { opacity: 0.6 }]}
                onPress={onExecute}
                disabled={execBusy}>
                <Text style={styles.execBtnTxt}>{execBusy ? '⏳ PROCESSING...' : tradeCount >= 3 ? 'MAX TRADES' : '⚡ EXECUTE'}</Text>
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
        <FilterCell lab="SPREAD" val={`${spread.toFixed(2)}p`} sub="✓ ≤3.5" box="ok" valColor={fSpreadCol} />
        <FilterCell lab="GEO RISK" val="HIGH" sub="⚠ 0.25%" box="warn" valColor={C.red} />
        <FilterCell lab="DXY" val="FALL" sub="✓ BUY OK" box="ok" valColor={C.green} />
        <FilterCell lab="CHOP" val="ACTIVE" sub="⚠ WICK ONLY" box="amb" valColor={C.amber} />
        <FilterCell lab="RANGE" val={`${sr.bullPips.toFixed(1)}p`} sub="✓ ≥25" box="ok" valColor={rangeCol} />
        <FilterCell lab="SESSION" val="NY" sub="✓ OPEN" box="ok" valColor={C.green} />
        <FilterCell lab="YIELD" val="4.42%" sub="⚠ TP2-30%" box="warn" valColor={C.purple} />
        <FilterCell lab="BLACKOUT" val="CLEAR" sub="✓ No NFP" box="ok" valColor={C.green} />
      </View>

      <Row style={styles.wickInd}>
        <Text style={styles.wiIcon}>🕯️</Text>
        <View style={{ flex: 1 }}>
          <Text style={styles.wiMain}>WICK CREATED ✓ — Candle filled. Entry confirmed by Raja Flip Rule.</Text>
          <Text style={styles.wiSub}>M30 started RED → bottom wick at $4,597 → closed GREEN above $4,608 · Wick: 22p · Body: 65%</Text>
        </View>
      </Row>

      <Panel shell={styles.gmPanelShell} headTint={styles.gmHeaderTint} head={{ title: 'ATR Volatility Sizing', badge: 'NEW · v3', titleColor: C.amber, badgeColor: C.gold }}>
        <Row style={styles.atrRow}>
          <Text style={styles.atrLabel}>ATR-14 (M30)</Text>
          <Text style={styles.atrVal}>{atr.toFixed(1)} pips</Text>
        </Row>
        <View style={styles.atrBarBg}>
          <View style={[styles.atrBarFill, { width: `${atrFillPct}%` }]} />
        </View>
        <Text style={[styles.modePill, modeCls]}>{atrModePill.text}</Text>
        <DxyRow l="ATR <50p" v="Standard 0.5%" vc={C.green} />
        <DxyRow l="ATR 50–100p" v="Reduced 0.35%" vc={C.amber} />
        <DxyRow l="ATR >100p" v="Crisis 0.25%" vc={C.red} />
        <DxyRow l="Current Risk" v="0.25% (GEO override)" vc={C.amber} />
      </Panel>

      <Panel shell={{}} head={{ title: 'Entry & Exit Engine', badge: 'ZONE-TO-ZONE TARGETS' }}>
        <View style={styles.eeGrid}>
          <EeCell lab="Entry Price" val={fmtNum(price)} sub="Wick fill · 0.25%" valStyle={styles.eeEntry} />
          <EeCell lab="BE @ +12p" val="4,624.50" sub="Move SL to entry" valStyle={styles.eeBe} />
          <EeCell lab="TP1 — Zone" val="4,629.00" sub="Next key zone" valStyle={styles.eeTp1} />
          <EeCell lab="TP2 — Zone" val="4,647.00" sub="-30% yield adj" valStyle={styles.eeTp2} />
        </View>
        <View style={styles.eeGrid}>
          <EeCell lab="Stop Loss" val="4,597.00" sub="Below M30 wick" valStyle={styles.eeSl} />
          <EeCell lab="Risk $" val="$125" sub="0.25% of $50k" valStyle={styles.eePlain} />
          <EeCell lab="R:R Ratio" val="1 : 1.8" sub="Geo adj" valStyle={styles.eeGold} />
          <EeCell lab="Lot Size" val="0.36" sub="ATR calc" valStyle={styles.eePlain} />
        </View>
        <Row style={styles.rrStrip}>
          <RrCell lab="REWARD $" val="$225" color={C.green} />
          <RrCell lab="DAY TRADES" val={`${tradeCount} / 3`} color={C.gold} />
          <RrCell lab="SIZE MODE" val="GEO 0.25%" color={C.amber} />
          <RrCell lab="TRAIL" val="H1 Lows" color={C.text} />
          <RrCell lab="DAY MODE" val={dayBits.modeRR} color={dayBits.rrColor} />
        </Row>
      </Panel>

      <Panel shell={{}} head={{ title: 'Price Action · Zone Map', badge: 'M30 · LEFT SIDE CLEAN' }}>
        <View style={styles.chartWrap}>
          <View style={styles.chartAth} />
          <Text style={styles.chartAthTxt}>☠ ATH ZONE $5,278-$5,602 — NO BUY</Text>
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
            <Text style={[styles.hLineLbl, { color: C.purple, left: 4 }]}>BE+12p</Text>
          </View>
          <View style={[styles.hLine, { top: '31%' }]}>
            <Text style={[styles.hLineLbl, { color: C.goldL, left: 4 }]}>TP1 ZONE 4629</Text>
          </View>
          <View style={[styles.hLine, { top: '18%' }]}>
            <Text style={[styles.hLineLbl, { color: C.gold, left: 4 }]}>TP2 ZONE 4647 (-30%yield)</Text>
          </View>
          <View style={[styles.hLine, { top: '93%' }]}>
            <Text style={[styles.hLineLbl, { color: C.red, left: 4 }]}>SL 4597</Text>
          </View>
          <View style={[styles.vLine, { left: '56%' }]}>
            <Text style={[styles.vLineLbl, { color: C.green }]}>ENTRY</Text>
          </View>
          <View style={styles.wickGrab} />
          <Text style={styles.wickGrabLbl}>WICK GRAB</Text>
        </View>
      </Panel>

      <Panel shell={{}} head={{ title: 'Signal History', badge: 'BILSHENZ v3 · TODAY' }}>
        <View style={styles.histTableWrap}>
          <HistHeader />
          {SIGNAL_HISTORY_SIM.map((row, i) => (
            <HistRow key={i} row={row} />
          ))}
        </View>
      </Panel>
    </View>
  );
}

function FilterCell({ lab, val, sub, box, valColor }) {
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
  return (
    <View style={styles.eeCell}>
      <Text style={styles.eeL}>{lab}</Text>
      <Text style={[styles.eeV, valStyle]}>{val}</Text>
      <Text style={styles.eeS}>{sub}</Text>
    </View>
  );
}

function RrCell({ lab, val, color }) {
  return (
    <View style={styles.rri}>
      <Text style={styles.rrl}>{lab}</Text>
      <Text style={[styles.rrv, { color }]}>{val}</Text>
    </View>
  );
}

function HistHeader() {
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
  const [utc, dir, typ, e1, e2, e3, e4, res, side, kind] = row;
  if (typ === 'BREAK') {
    return (
      <View style={styles.histRow}>
        <Text style={[styles.histTd, styles.histColUtc]}>{utc}</Text>
        <Text style={[styles.histTd, side === 'buy' ? styles.tBuy : styles.tSell, styles.histColDir]}>{dir}</Text>
        <View style={styles.histColType}>
          <Text style={[styles.eb, styles.ebW]}>BREAK</Text>
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
  const eb =
    typ === 'WICK' ? styles.ebW : typ === 'BREAK' ? styles.ebB : styles.ebF;
  const plStyle =
    kind === 'win' ? styles.tWin : kind === 'loss' ? styles.tLoss : kind === 'open' ? styles.tOpen : styles.histTd;
  return (
    <View style={styles.histRow}>
      <Text style={[styles.histTd, styles.histColUtc]}>{utc}</Text>
      <Text style={[styles.histTd, side === 'buy' ? styles.tBuy : styles.tSell, styles.histColDir]}>{dir}</Text>
      <View style={styles.histColType}>
        <Text style={[styles.eb, eb]}>{typ}</Text>
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

function RightColumn({ tradeCount, pnl, sessTag, spread, spreadOkColor, spHigh, dayBits }) {
  const pr = Math.round(pnl);
  const pnlColor = pr >= 0 ? C.green : C.red;
  return (
    <View style={styles.rightCol}>
      <Panel shell={{}} head={{ title: 'Live P&L', badge: sessTag }}>
        <View style={styles.pnlHero}>
          <Text style={styles.pnlTag}>UNREALIZED P&L (USD)</Text>
          <Text style={[styles.pnlNum, { color: pnlColor }]}>{fmtUsd(pr)}</Text>
          <Text style={styles.pnlPips}>{`${pr >= 0 ? '+' : ''}${(Math.abs(pr) / 10).toFixed(1)} pips · 1 active`}</Text>
        </View>
        <View style={styles.pnlMini}>
          <PmCell lab="Closed Today" val="+$1,335" c={C.green} />
          <PmCell lab="Win Rate" val="75.0%" />
          <PmCell lab="Trades/Max" val={`${tradeCount} / 3`} />
          <PmCell lab="Profit Factor" val="2.96" c={C.green} />
        </View>
      </Panel>

      <Panel shell={{}} head={{ title: 'Risk Engine', badge: 'GODMODE PROTOCOL' }}>
        <Row style={styles.rmHdr}>
          <Text style={styles.rmL}>PORTFOLIO RISK USED</Text>
          <Text style={styles.rmV}>0.5% / 2.0% MAX</Text>
        </Row>
        <View style={styles.rmBar}>
          <View style={[styles.rmFill, { width: '25%' }]} />
        </View>
        <DxyRow l="Balance" v="$50,000" vc={C.text} />
        <DxyRow l="Active Risk Mode" v="GEO HIGH → 0.25%" vc={C.red} />
        <DxyRow l="ATR Mode" v="Elevated → 0.35%" vc={C.amber} />
        <DxyRow l="Effective Risk" v="0.25% (lowest override)" vc={C.red} />
        <DxyRow l="BE Trigger" v="+12 pips" vc={C.green} />
        <DxyRow l="Trades Today" v={`${tradeCount} of 3 used`} vc={C.amber} />
        <DxyRow l="Dynamic Entries" v="SUSPENDED · GEO=HIGH" vc={C.red} />
      </Panel>

      <Panel shell={styles.gmPanelShell} headTint={styles.gmHeaderTint} head={{ title: 'Treasury Yield Filter', badge: 'NEW · v3', titleColor: C.purple, badgeColor: C.gold }}>
        <Row style={styles.atrRow}>
          <Text style={styles.atrLabel}>US 10Y Yield</Text>
          <Text style={styles.yieldPct}>4.42%</Text>
        </Row>
        <View style={styles.yieldBarBg}>
          <View style={[styles.yieldFill, { width: '74%' }]} />
        </View>
        <Row style={styles.yieldMarkers}>
          <Text style={styles.yieldMk}>3.0%</Text>
          <Text style={styles.yieldMk}>4.0%</Text>
          <Text style={styles.yieldMk}>4.4%</Text>
          <Text style={styles.yieldMk}>5.0%</Text>
        </Row>
        <DxyRow l="Yield <4.0%" v="Normal TPs" vc={C.green} />
        <DxyRow l="Yield 4.0–4.4%" v="TP2 -15%" vc={C.amber} />
        <DxyRow l="Yield >4.4%" v="TP2 -30% ACTIVE" vc={C.red} />
        <DxyRow l="Current Rule" v="TP2 reduced 30%" vc={C.red} />
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

      <Panel shell={{}} head={{ title: 'Spread Guard', badge: 'BLOCK >3.5 PIPS' }}>
        <Row style={[styles.spreadGuard, spHigh ? styles.sgWarn : styles.sgOk]}>
          <View>
            <Text style={styles.sgLabel}>LIVE SPREAD</Text>
            <Text style={[styles.sgSpread, { color: spreadOkColor }]}>{spread.toFixed(2)}</Text>
            <Text style={styles.sgTiny}>pips</Text>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Text style={[styles.sgStatus, { color: spreadOkColor }]}>{spHigh ? '✗ ENTRIES BLOCKED' : '✓ ENTRIES ALLOWED'}</Text>
            <Text style={styles.sgTiny2}>Limit: 3.5 pips</Text>
          </View>
        </Row>
      </Panel>

      <Panel shell={{}} head={{ title: 'News Filter', badge: '±15MIN · NFP BLACKOUT' }}>
        <Text style={styles.newsClear}>✓ CLEAR — NO ACTIVE BLOCK</Text>
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
  return (
    <View style={styles.pmC}>
      <Text style={styles.pmL}>{lab}</Text>
      <Text style={[styles.pmV, c ? { color: c } : null]}>{val}</Text>
    </View>
  );
}

function NewsRow({ t, n, impact, extra, ok, past }) {
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

function ProfileTab({ pad, width }) {
  const [profileId, setProfileId] = useState('p1');
  const [showSwitchModal, setShowSwitchModal] = useState(false);
  const [nameEdit, setNameEdit] = useState(false);
  const [riskMode, setRiskMode] = useState('GEO');
  const [maxTrades, setMaxTrades] = useState(3);
  const [defaultLot, setDefaultLot] = useState('0.25');
  const [atrManual, setAtrManual] = useState(false);
  const [notificationsOn, setNotificationsOn] = useState(true);

  const active = PROFILE_PRESETS.find((p) => p.id === profileId) ?? PROFILE_PRESETS[0];
  const [displayName, setDisplayName] = useState(active.name);

  useEffect(() => {
    const p = PROFILE_PRESETS.find((x) => x.id === profileId);
    if (p) setDisplayName(p.name);
    setNameEdit(false);
  }, [profileId]);

  const tierColor = active.tier === 'PRO' ? C.goldL : C.blue;
  const sparkW = Math.max(220, width - pad * 2 - 56);
  const sparkPts = '0,38 35,32 70,28 105,20 140,24 175,14 200,18';

  const resetDefaults = () => {
    setProfileId('p1');
    setRiskMode('GEO');
    setMaxTrades(3);
    setDefaultLot('0.25');
    setAtrManual(false);
    setNotificationsOn(true);
    setDisplayName(PROFILE_PRESETS[0].name);
    setNameEdit(false);
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
        <View style={styles.psAvatarRing}>
          <Text style={styles.psAvatarTxt}>{active.initials}</Text>
        </View>
        {nameEdit ? (
          <TextInput
            value={displayName}
            onChangeText={setDisplayName}
            onBlur={() => setNameEdit(false)}
            style={styles.psNameInput}
            placeholder="Trader name"
            placeholderTextColor={C.dim2}
            autoFocus
          />
        ) : (
          <Pressable onPress={() => setNameEdit(true)} style={({ pressed }) => [pressed && { opacity: 0.85 }]}>
            <Text style={styles.psName}>{displayName}</Text>
            <Text style={styles.psNameHint}>Tap to edit</Text>
          </Pressable>
        )}
        <View style={[styles.psTierBadge, { borderColor: tierColor }]}>
          <Text style={[styles.psTierTxt, { color: tierColor }]}>{active.tier}</Text>
        </View>
        <Row style={styles.psStatsRow}>
          <View style={styles.psStatGlass}>
            <Text style={styles.psStatLbl}>TOTAL P&L</Text>
            <Text style={[styles.psStatVal, { color: C.green }]}>+$12,450</Text>
          </View>
          <View style={styles.psStatGlass}>
            <Text style={styles.psStatLbl}>WIN RATE</Text>
            <Text style={[styles.psStatVal, { color: C.goldL }]}>75%</Text>
          </View>
          <View style={styles.psStatGlass}>
            <Text style={styles.psStatLbl}>TRADES</Text>
            <Text style={[styles.psStatVal, { color: C.text }]}>142</Text>
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
              onPress={() => setRiskMode(opt)}
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
          {[1, 2, 3].map((n) => (
            <Pressable
              key={n}
              onPress={() => setMaxTrades(n)}
              style={[styles.psSegChip, maxTrades === n && styles.psSegChipOn, { minHeight: 44, flex: 1 }]}>
              <Text style={[styles.psSegChipTxt, maxTrades === n && styles.psSegChipTxtOn]}>{n}</Text>
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
            <Text style={styles.psToggleLbl}>DARK THEME</Text>
            <Text style={styles.psToggleHint}>Always on</Text>
          </View>
          <Switch value={true} disabled trackColor={{ false: C.border, true: 'rgba(212,180,90,0.35)' }} thumbColor={C.goldL} />
        </Row>
      </View>

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
                  <Text style={styles.psModalAvatarTxt}>{p.initials}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.psModalName}>{p.name}</Text>
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
}) {
  const pnlRounded = Math.round(pnl);
  const pnlColor = pnlRounded >= 0 ? C.green : C.red;
  const sessShort = sessionBits.act
    ? sessionBits.s3
      ? 'NY PEAK'
      : sessionBits.s2
        ? 'LONDON'
        : 'PRE-LONDON'
    : 'STANDBY';
  const winRatePct = '75.0%';

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
              <Text style={[styles.ghMiniVal, { color: C.green }]}>{winRatePct}</Text>
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
          <Text style={styles.ghStatSub}>Unrealized · sim</Text>
        </View>
        <View style={styles.ghStatTile}>
          <Text style={styles.ghStatLbl}>TRADES</Text>
          <Text style={[styles.ghStatVal, { color: C.gold }]}>{tradeCount} / 3</Text>
          <Text style={styles.ghStatSub}>Daily cap</Text>
        </View>
      </View>

      <View style={[styles.ghVerdictCard, { marginHorizontal: pad }]}>
        <Text style={styles.ghVerdictLbl}>SCANNER VERDICT</Text>
        <Text style={[styles.ghVerdictMain, { color: sr.verdictValColor }]}>{sr.verdictVal}</Text>
        <Text style={styles.ghVerdictSub}>{sr.verdictSub}</Text>
      </View>

      <View style={[styles.ghHistWrap, { marginHorizontal: pad }]}>
        <Panel shell={{}} head={{ title: 'Signal History', badge: 'BILSHENZ v3 · TODAY' }}>
          <View style={styles.histTableWrap}>
            <HistHeader />
            {SIGNAL_HISTORY_SIM.map((row, i) => (
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

function MobileCompactStrip({ price, spread, pad, utcStr, est }) {
  const xauDiff = parseFloat((price - 4698.2).toFixed(2));
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
    </View>
  );
}

function MobileBottomNav({ tab, onChange, bottomInset }) {
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
        ) : null}
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

function AppContent() {
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
  const [tradeCount, setTradeCount] = useState(2);
  const [mobileTab, setMobileTab] = useState('home');

  const flipSupRef = useRef(null);
  const flipResRef = useRef(null);
  const prevPriceRef = useRef(4721.5);

  const est = useMemo(() => getEST(now), [now]);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const utcStr = now.toUTCString().split(' ')[4] ?? '--:--:--';

  const sessionBits = useMemo(() => {
    const mins = est.h * 60 + est.m;
    const s1 = mins >= 19 * 60 && mins < 23 * 60;
    const s2 = mins >= 2 * 60 && mins < 6 * 60;
    const s3 = mins >= 7 * 60 && mins < 12 * 60;
    const act = s1 || s2 || s3;
    let sessLabel =
      '☠ DEAD ZONE · ALL OTHER TIMES';
    if (s1) sessLabel = '① PRE-LONDON · 19:00–23:00';
    else if (s2) sessLabel = '② LONDON · 02:00–06:00 EST';
    else if (s3) sessLabel = '③ NEW YORK · 07:00–12:00 EST';
    return { s1, s2, s3, act, sessLabel };
  }, [est.h, est.m]);

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

  const sr = useMemo(() => {
    const p = price;
    const prev = prevPriceRef.current;
    RESISTANCES.forEach((v) => {
      if (prev <= v && p > v) flipSupRef.current = v;
    });
    SUPPORTS.forEach((v) => {
      if (prev >= v && p < v) flipResRef.current = v;
    });
    const flipSup = flipSupRef.current;
    const flipRes = flipResRef.current;

    const immRes = getImmRes(p);
    const immSup = getImmSup(p);
    const poiRes = getPoiRes(p, immRes);
    const poiSup = getPoiSup(p, immSup);

    const distRes = immRes ? ((immRes - p) / 0.1).toFixed(1) : '—';
    const distSup = immSup ? ((p - immSup) / 0.1).toFixed(1) : '—';
    const distPoiRes = poiRes ? ((poiRes - p) / 0.1).toFixed(1) : '—';
    const distPoiSup = poiSup ? ((p - poiSup) / 0.1).toFixed(1) : '—';

    const bullPips = immRes ? parseFloat(distRes) : 0;
    const bearPips = immSup ? parseFloat(distSup) : 0;

    const bullChop = immRes ? calcChop(p, immRes) : 99;
    const bearChop = immSup ? calcChop(p, immSup) : 99;

    const bullClean = bullPips >= 25 && bullChop <= 3;
    const bearClean = bearPips >= 25 && bearChop <= 3;

    let verdictLabelColor = C.dim;
    let verdictBg = 'transparent';
    let verdictBorder = C.border;
    let verdictVal = '⛔ NO TRADE';
    let verdictValColor = C.amber;
    let verdictSub = 'Neither path qualifies ≥25 pips';

    if (bullClean && bearClean) {
      verdictBorder = 'rgba(201,168,76,0.5)';
      verdictBg = 'rgba(201,168,76,0.05)';
      verdictLabelColor = C.gold;
      verdictValColor = C.goldL;
      verdictVal = '▲▼ BOTH SIDES TRADEABLE';
      verdictSub = 'Follow HTF bias for direction';
    } else if (bullClean) {
      verdictBorder = 'rgba(0,230,118,0.5)';
      verdictBg = 'rgba(0,230,118,0.05)';
      verdictLabelColor = C.green;
      verdictValColor = C.green;
      verdictVal = '▲ BUY ONLY';
      verdictSub = 'Bull path clean · Bear path blocked';
    } else if (bearClean) {
      verdictBorder = 'rgba(255,61,87,0.5)';
      verdictBg = 'rgba(255,61,87,0.05)';
      verdictLabelColor = C.red;
      verdictValColor = C.red;
      verdictVal = '▼ SELL ONLY';
      verdictSub = 'Bear path clean · Bull path blocked';
    }

    const pos =
      immRes && immSup ? 'Inside Range' : immRes ? 'Below All Resistance' : 'Above All Support';

    prevPriceRef.current = p;

    const flipNearFlipSup = flipSup != null && Math.abs(p - flipSup) < 30;

    return {
      currentPrice: p,
      immRes,
      immSup,
      poiRes,
      poiSup,
      distRes,
      distSup,
      distPoiRes,
      distPoiSup,
      bullPips,
      bearPips,
      bullChop,
      bearChop,
      bullClean,
      bearClean,
      verdictBg,
      verdictBorder,
      verdictLabelColor,
      verdictVal,
      verdictValColor,
      verdictSub,
      pos,
      flipSup,
      flipRes,
      flipNearFlipSup,
    };
  }, [price]);

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
    const atrNext = parseFloat((55 + Math.random() * 45).toFixed(1));
    setAtr(atrNext);
    setAtrFillPct(Math.min(100, ((atrNext - 30) / 120) * 100));
  }, []);

  useEffect(() => {
    const id = setInterval(tick, 1400);
    return () => clearInterval(id);
  }, [tick]);

  const spHigh = spread > 3.5;
  const spreadOkColor = spHigh ? C.red : C.green;

  const xauDiff = parseFloat((price - 4698.2).toFixed(2));
  const xauUp = xauDiff >= 0;

  const atrModePill =
    atr < 50
      ? { text: '✓ NORMAL MODE — RISK: 0.5%', cls: 'std' }
      : atr <= 100
        ? { text: '⚠ ELEVATED MODE — RISK: 0.35%', cls: 'amb' }
        : { text: '✗ CRISIS MODE — RISK: 0.25%', cls: 'red' };

  const chartPts = [
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

  const sigPill =
    sr.flipNearFlipSup && sr.flipSup != null
      ? { text: '🟡 FLIP RETEST — PRIORITY 3 · E3 ENTRY', variant: 'flip' }
      : { text: '🟥 WICK ENTRY — PRIORITY 1 · CHOP APPROVED', variant: 'wick' };

  const pillStyle =
    sigPill.variant === 'flip'
      ? styles.pillFlip
      : sigPill.variant === 'wick'
        ? styles.pillWick
        : styles.pillBreak;

  const onExecute = () => {
    if (tradeCount >= 3) return;
    setExecBusy(true);
    setTimeout(() => {
      setTradeCount((c) => c + 1);
      setExecBusy(false);
    }, 1200);
  };

  const onSkip = () => {
    setSigMuted(true);
    setTimeout(() => setSigMuted(false), 2500);
  };

  const sessTag = sessionBits.act
    ? sessionBits.sessLabel.replace(/[①②③☠]\s/, '')
    : 'OUT OF SESSION';

  const f4State = spHigh ? 'fail' : 'pass';
  const f3State = sessionBits.act ? 'pass' : 'fail';

  /** Bottom nav sits outside ScrollView — only a sliver so the footer line isn’t clipped */
  const scrollBottomPad = !isWide ? 6 : 10;
  const showDeskChrome = isWide || mobileTab === 'desk';
  const showFullHeader =
    isWide || mobileTab === 'desk' || mobileTab === 'home' || mobileTab === 'profile' || mobileTab === 'risk';

  const flowNodes = [
    { id: 'f1', state: 'pass', icon: '☢', sn: 'S01', ft: 'BLACKOUT\nCHECK', tag: 'NEW' },
    { id: 'f2', state: 'pass', icon: '📰', sn: 'S02', ft: 'NEWS\n±15MIN' },
    { id: 'f3', state: f3State, icon: '🕒', sn: 'S03', ft: 'SESSION\nACTIVE' },
    { id: 'f4', state: f4State, icon: '📏', sn: 'S04', ft: 'SPREAD\n≤3.5p' },
    { id: 'f5', state: 'warn', icon: '🌍', sn: 'S05', ft: 'GEO\nRISK', tag: 'NEW' },
    { id: 'f6', state: 'pass', icon: '💵', sn: 'S06', ft: 'DXY\nCONFIRM', tag: 'NEW' },
    { id: 'f7', state: 'pass', icon: '📊', sn: 'S07', ft: 'HTF\nBIAS' },
    { id: 'f8', state: 'warn', icon: '🌀', sn: 'S08', ft: 'CHOP\nDETECT', tag: 'NEW' },
    { id: 'f9', state: 'pass', icon: '🔭', sn: 'S09', ft: 'LEFT SIDE\nCLEAN' },
    { id: 'f10', state: 'pass', icon: '🗺', sn: 'S10', ft: 'ZONE\nMAP', tag: 'NEW' },
    { id: 'f11', state: 'pass', icon: '⚡', sn: 'S11', ft: 'SETUP\nP1-P3' },
    { id: 'f12', state: 'pass', icon: '🕯', sn: 'S12', ft: 'CANDLE\n40/60' },
    { id: 'f13', state: 'warn', icon: '📉', sn: 'S13', ft: 'ATR\nSIZE', tag: 'NEW' },
    { id: 'f14', state: 'warn', icon: '🏛', sn: 'S14', ft: 'YIELD\nCHECK', tag: 'NEW' },
    { id: 'f15', state: 'pass', icon: '🎯', sn: 'S15', ft: 'EXECUTE\n+BE@12p' },
  ];

  return (
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
                      <Text style={styles.xauPrice}>{fmtNum(price)}</Text>
                      <Text style={[styles.xauChg, { color: xauUp ? C.green : C.red }]}>
                        {(xauUp ? '▲ +' : '▼ ') + Math.abs(xauDiff).toFixed(2)}
                      </Text>
                    </Row>
                    <Text style={styles.xauSub}>
                      BID {fmtNum(price - 0.3)} · ASK {fmtNum(price + 0.3)} · SPREAD{' '}
                      <Text style={styles.xauSub}>{spread.toFixed(2)}</Text>p
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
                      <Text style={styles.livePillTxt}>LIVE SIM</Text>
                    </Row>
                    <View style={styles.clockBox}>
                      <Text style={styles.clockUtc}>{utcStr}</Text>
                      <Text style={styles.clockEst}>
                        {String(est.h).padStart(2, '0')}:{String(est.m).padStart(2, '0')} EST
                      </Text>
                    </View>
                  </Row>
                </Row>
              </View>
            ) : (
              <MobileCompactStrip price={price} spread={spread} pad={pad} utcStr={utcStr} est={est} />
            )}

            {showDeskChrome ? (
              <>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.bannerScroll}>
                  <View style={[styles.godBanner, { paddingHorizontal: pad }]}>
                    <Row style={styles.gmAlert}>
                      <BlinkDot color={C.red} />
                      <Text style={[styles.gmAlertTxt, { color: C.red }]}>GEOPOLITICAL: HIGH</Text>
                    </Row>
                    <View style={styles.gmDivider} />
                    <Row style={styles.gmAlert}>
                      <BlinkDot color={C.red} />
                      <Text style={[styles.gmAlertTxt, { color: C.red }]}>NFP BLACKOUT: MAY 8</Text>
                    </Row>
                    <View style={styles.gmDivider} />
                    <Row style={styles.gmAlert}>
                      <BlinkDot color={C.amber} />
                      <Text style={[styles.gmAlertTxt, { color: C.amber }]}>ATR MODE: ELEVATED 0.35%</Text>
                    </Row>
                    <View style={styles.gmDivider} />
                    <Row style={styles.gmAlert}>
                      <BlinkDot color={C.amber} />
                      <Text style={[styles.gmAlertTxt, { color: C.amber }]}>CHOP ZONE ACTIVE · WICK ONLY</Text>
                    </Row>
                    <View style={styles.gmDivider} />
                    <Row style={styles.gmAlert}>
                      <BlinkDot color={C.teal} />
                      <Text style={[styles.gmAlertTxt, { color: C.teal }]}>DXY: FALLING · BUY SUPPORTED</Text>
                    </Row>
                    <View style={styles.gmDivider} />
                    <Row style={styles.gmAlert}>
                      <BlinkDot color={C.purple} />
                      <Text style={[styles.gmAlertTxt, { color: C.purple }]}>YIELD: 4.4%+ · TP2 -30%</Text>
                    </Row>
                    <View style={styles.gmDivider} />
                    <Row style={styles.gmAlert}>
                      <BlinkDot color={C.red} />
                      <Text style={[styles.gmAlertTxt, { color: C.red }]}>ATH ZONE: $5,278–$5,602 · NO BUY</Text>
                    </Row>
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

            {isWide ? (
              <View style={[styles.grid, { paddingHorizontal: pad, flexDirection: 'row', alignItems: 'stretch' }]}>
                <View style={[styles.col, { width: 250 }]}>
                  <LeftColumn sr={sr} dxy={dxy} />
                </View>
                <View style={[styles.col, { flex: 1 }]}>
                  <CenterColumn
                    price={price}
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
                  />
                </View>
                <View style={[styles.col, { width: 250 }]}>
                  <RightColumn tradeCount={tradeCount} pnl={pnl} sessTag={sessTag} spread={spread} spreadOkColor={spreadOkColor} spHigh={spHigh} dayBits={dayBits} />
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
                />
              </View>
            ) : mobileTab === 'desk' ? (
              <View style={[styles.grid, { paddingHorizontal: pad, flexDirection: 'column', alignItems: 'stretch' }]}>
                <View style={[styles.col, { width: '100%' }]}>
                  <LeftColumn sr={sr} dxy={dxy} />
                </View>
                <View style={[styles.col, { width: '100%' }]}>
                  <CenterColumn
                    price={price}
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
                    compactSignal
                  />
                </View>
                <View style={[styles.col, { width: '100%' }]}>
                  <RightColumn tradeCount={tradeCount} pnl={pnl} sessTag={sessTag} spread={spread} spreadOkColor={spreadOkColor} spHigh={spHigh} dayBits={dayBits} />
                </View>
              </View>
            ) : mobileTab === 'trade' ? (
              <View style={[styles.mobileTabBody, { paddingHorizontal: pad }]}>
                <CenterColumn
                  price={price}
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
                  compactSignal
                />
              </View>
            ) : mobileTab === 'profile' ? (
              <View style={[styles.mobileTabBody, styles.psTabBody, { paddingHorizontal: 0 }]}>
                <ProfileTab pad={pad} width={width} />
              </View>
            ) : mobileTab === 'risk' ? (
              <View style={[styles.mobileTabBody, { paddingHorizontal: pad }]}>
                <RightColumn tradeCount={tradeCount} pnl={pnl} sessTag={sessTag} spread={spread} spreadOkColor={spreadOkColor} spHigh={spHigh} dayBits={dayBits} />
              </View>
            ) : null}

            {showDeskChrome ? (
              <View style={[styles.footer, { paddingHorizontal: pad }]}>
                <Text style={styles.footerTxt}>
                  BILSHENZ v3.2 GODMODE — <Text style={styles.footerGold}>Jimplas Capital Management</Text> · Billy William Onen · CEO
                </Text>
                <Text style={styles.footerTxt}>{utcStr} UTC</Text>
                <Text style={styles.footerTxt}>
                  <Text style={styles.footerGold}>S&R Engine · Flip Engine · Left Side Scanner · 8 Godmode Upgrades</Text> · Simulated · Not financial advice
                </Text>
              </View>
            ) : (
              <View style={[styles.footer, styles.footerMinimal, { paddingHorizontal: pad }]}>
                <Text style={styles.footerTxt}>
                  BILSHENZ v3.2 ·{' '}
                  <Text style={styles.footerGold}>
                    {mobileTab === 'desk' ? 'INTEL' : mobileTab === 'profile' ? 'PROFILE' : mobileTab.toUpperCase()}
                  </Text>{' '}
                  · Simulated · Not financial advice
                </Text>
              </View>
            )}
          </ScrollView>
          {!isWide ? <MobileBottomNav tab={mobileTab} onChange={setMobileTab} bottomInset={insets.bottom} /> : null}
        </View>
      </SafeAreaView>
  );
}

/** Corner radii for INTEL / desk panels (left, center, right columns) and nested blocks */
const DR = {
  panel: 14,
  block: 12,
  soft: 10,
  chip: 8,
  mini: 6,
};

const styles = StyleSheet.create({
  safeRoot: { flex: 1, backgroundColor: C.appBg },
  root: { flex: 1, backgroundColor: C.appBg },
  scrollContent: { paddingBottom: 0, backgroundColor: C.appBg },
  row: { flexDirection: 'row', alignItems: 'center' },
  header: {
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
    backgroundColor: 'rgba(16,14,10,0.98)',
  },
  headerTopRow: { justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 },
  stackCol: { flexDirection: 'column', alignItems: 'stretch' },
  headerStackGap: { gap: 6 },
  brandStack: { alignItems: 'flex-start' },
  hdrCenter: { alignItems: 'center', gap: 2 },
  xauRow: { alignItems: 'baseline', gap: 8 },
  xauPair: { fontSize: 8, color: C.dim, letterSpacing: 2, fontWeight: '600' },
  xauPrice: { fontSize: 28, fontWeight: '800', color: C.goldL },
  xauChg: { fontSize: 12, fontWeight: '700' },
  xauSub: { fontSize: 8, color: C.dim, letterSpacing: 1 },
  headerNotes: {
    marginTop: 5,
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 2,
    paddingHorizontal: 10,
    paddingVertical: Platform.OS === 'ios' ? 7 : 5,
    color: C.text,
    fontSize: 10,
    backgroundColor: 'rgba(14,12,10,0.28)',
  },
  hdrRight: { gap: 14 },
  livePill: {
    borderWidth: 1,
    borderColor: 'rgba(0,230,118,0.3)',
    backgroundColor: 'rgba(0,230,118,0.04)',
    paddingVertical: 5,
    paddingHorizontal: 11,
    borderRadius: 20,
    gap: 6,
  },
  livePillTxt: { fontSize: 8, color: C.green, letterSpacing: 2, fontWeight: '700' },
  ldot: { width: 6, height: 6, borderRadius: 3 },
  clockBox: { alignItems: 'flex-end' },
  clockUtc: { fontSize: 16, fontWeight: '800', color: C.gold },
  clockEst: { fontSize: 8, color: C.dim, letterSpacing: 1, marginTop: 1, fontWeight: '500' },

  bannerScroll: { maxHeight: 52, borderBottomWidth: 1, borderBottomColor: 'rgba(255,61,87,0.2)', backgroundColor: C.appBg },
  godBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    paddingVertical: 10,
    backgroundColor: 'rgba(255,61,87,0.04)',
  },
  gmAlert: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  gmAlertTxt: { fontSize: 9, letterSpacing: 1.5, fontWeight: '700' },
  gmDivider: { width: 1, height: 16, backgroundColor: C.border },

  sessBar: { flexDirection: 'row', flexWrap: 'wrap', borderBottomWidth: 1, borderBottomColor: C.border, backgroundColor: C.panel },
  sblk: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 9,
    paddingHorizontal: 16,
    borderRightWidth: 1,
    borderRightColor: C.border,
    borderTopWidth: 2,
    borderTopColor: 'transparent',
  },
  sblkActive: { borderTopColor: C.gold, backgroundColor: 'rgba(201,168,76,0.04)' },
  sblkDead: { borderTopColor: 'rgba(255,61,87,0.4)', backgroundColor: 'rgba(255,61,87,0.02)' },
  sn: { fontSize: 8, color: C.dim, letterSpacing: 1.5, marginBottom: 2, fontWeight: '600' },
  st: { fontSize: 9, color: C.text, fontWeight: '500' },
  sbadge: { fontSize: 7, letterSpacing: 1, paddingVertical: 3, paddingHorizontal: 8, borderRadius: 10, overflow: 'hidden', fontWeight: '700' },
  sbOpen: { color: C.green, borderWidth: 1, borderColor: 'rgba(0,230,118,0.3)', backgroundColor: C.greenD },
  sbWait: { color: C.amber, borderWidth: 1, borderColor: 'rgba(255,179,0,0.3)', backgroundColor: 'rgba(255,179,0,0.05)' },
  sbDead: { color: C.red, borderWidth: 1, borderColor: 'rgba(255,61,87,0.3)', backgroundColor: C.redD },

  flowScroll: { borderBottomWidth: 1, borderBottomColor: C.border, backgroundColor: 'rgba(16,14,10,0.94)', maxHeight: 92 },
  flowWrap: { flexDirection: 'row', alignItems: 'center', gap: 2, paddingVertical: 10 },
  fnode: {
    alignItems: 'center',
    gap: 2,
    paddingVertical: 6,
    paddingHorizontal: 8,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: C.panel2,
    minWidth: 68,
    borderRadius: DR.soft,
  },
  fnodePass: { borderColor: 'rgba(0,230,118,0.35)', backgroundColor: 'rgba(0,230,118,0.04)' },
  fnodeFail: { borderColor: 'rgba(255,61,87,0.35)', backgroundColor: 'rgba(255,61,87,0.04)' },
  fnodeWarn: { borderColor: 'rgba(255,179,0,0.35)', backgroundColor: 'rgba(255,179,0,0.04)' },
  fi: { fontSize: 11 },
  fn: { fontSize: 6, color: C.dim, fontWeight: '600' },
  ft: { fontSize: 7, color: C.text, letterSpacing: 0.3, textAlign: 'center', lineHeight: 11, fontWeight: '600' },
  fnewTag: {
    fontSize: 6,
    color: C.gold,
    backgroundColor: 'rgba(201,168,76,0.1)',
    borderWidth: 1,
    borderColor: 'rgba(201,168,76,0.2)',
    paddingHorizontal: 4,
    paddingVertical: 1,
    borderRadius: DR.mini,
    marginTop: 1,
    fontWeight: '700',
  },
  farr: { fontSize: 10, color: C.dim2, paddingHorizontal: 1 },

  grid: { gap: 12, paddingVertical: 12 },
  col: { gap: 10 },
  leftCol: { gap: 10 },
  centerCol: { gap: 10 },
  rightCol: { gap: 10 },

  footer: {
    paddingTop: 8,
    paddingBottom: 4,
    borderTopWidth: 1,
    borderTopColor: C.border,
    backgroundColor: C.panel,
    gap: 6,
  },
  footerTxt: { fontSize: 7, color: C.dim, letterSpacing: 1, fontWeight: '500' },
  footerGold: { color: C.goldD, fontWeight: '700' },
  footerMinimal: { paddingTop: 6, paddingBottom: 4 },

  mobileCompactHdr: { paddingVertical: 10 },
  mobileTabBody: { paddingTop: 12, paddingBottom: 0, gap: 10 },

  bottomNavOuter: {
    paddingHorizontal: 0,
    paddingTop: 0,
  },
  bottomNavBar: {
    position: 'relative',
    borderRadius: 0,
    overflow: 'hidden',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: 'rgba(212,180,90,0.18)',
    paddingTop: 4,
    paddingBottom: 2,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: -2 },
        shadowOpacity: 0.2,
        shadowRadius: 8,
      },
      android: { elevation: 6 },
      default: {},
    }),
  },
  bottomNavBarTint: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: Platform.OS === 'ios' ? 'rgba(18,16,12,0.78)' : 'rgba(18,16,12,0.96)',
  },
  bottomNavRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'stretch',
    paddingHorizontal: 2,
    paddingTop: 0,
    zIndex: 3,
  },
  bottomNavItem: {
    flex: 1,
    position: 'relative',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 6,
    minHeight: 50,
    borderRadius: 0,
    marginHorizontal: 0,
    minWidth: 0,
    backgroundColor: 'transparent',
  },
  bottomNavItemActive: {
    backgroundColor: 'rgba(212,180,90,0.07)',
  },
  bottomNavItemPressed: { opacity: 0.88 },
  bottomNavActiveCapWrap: {
    position: 'absolute',
    top: 2,
    left: 0,
    right: 0,
    alignItems: 'center',
    zIndex: 4,
  },
  bottomNavActiveCap: {
    width: 28,
    height: 2,
    borderRadius: 2,
    backgroundColor: C.goldL,
    opacity: 0.95,
  },
  bottomNavItemInner: { alignItems: 'center', justifyContent: 'center', gap: 2, paddingTop: 5 },
  bottomNavIcon: {
    fontSize: 28,
    color: 'rgba(233,224,200,0.45)',
    fontWeight: '600',
  },
  bottomNavIconActive: { color: C.goldL },
  bottomNavLbl: {
    fontSize: 8,
    fontWeight: '700',
    color: 'rgba(233,224,200,0.52)',
    letterSpacing: 0.9,
    textTransform: 'uppercase',
  },
  bottomNavLblActive: {
    color: C.goldL,
    fontWeight: '800',
    letterSpacing: 1,
  },

  psTabBody: { paddingTop: 8, paddingBottom: 0 },
  psScroll: { gap: 16, paddingTop: 4 },
  psProfileCard: {
    position: 'relative',
    borderRadius: 14,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: 'rgba(212,180,90,0.28)',
    paddingVertical: 20,
    paddingHorizontal: 16,
    alignItems: 'center',
  },
  psProfileTint: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(20,18,14,0.88)',
  },
  psProfileGlow: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 4,
    backgroundColor: C.gold,
    opacity: 0.55,
    borderTopLeftRadius: 14,
    borderBottomLeftRadius: 14,
  },
  psAvatarRing: {
    width: 68,
    height: 68,
    borderRadius: 34,
    borderWidth: 3,
    borderColor: C.goldL,
    backgroundColor: 'rgba(0,0,0,0.35)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 10,
    ...Platform.select({
      ios: {
        shadowColor: C.gold,
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.45,
        shadowRadius: 8,
      },
      android: { elevation: 10 },
      default: {},
    }),
  },
  psAvatarTxt: { fontSize: 22, fontWeight: '900', color: C.goldL, letterSpacing: 1 },
  psName: { fontSize: 20, fontWeight: '800', color: C.text, textAlign: 'center' },
  psNameHint: { fontSize: 8, color: C.dim, textAlign: 'center', marginTop: 4, letterSpacing: 1 },
  psNameInput: {
    marginTop: 4,
    marginBottom: 4,
    minWidth: 200,
    borderWidth: 1,
    borderColor: C.gold,
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 14,
    color: C.text,
    fontSize: 16,
    fontWeight: '700',
    textAlign: 'center',
    backgroundColor: 'rgba(0,0,0,0.25)',
  },
  psTierBadge: {
    marginTop: 10,
    paddingVertical: 5,
    paddingHorizontal: 14,
    borderRadius: 20,
    borderWidth: 1,
    backgroundColor: 'rgba(0,0,0,0.2)',
  },
  psTierTxt: { fontSize: 9, fontWeight: '900', letterSpacing: 2 },
  psStatsRow: { flexDirection: 'row', gap: 8, marginTop: 16, alignSelf: 'stretch' },
  psStatGlass: {
    flex: 1,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: 'rgba(212,180,90,0.2)',
    backgroundColor: 'rgba(255,255,255,0.04)',
    paddingVertical: 10,
    paddingHorizontal: 6,
    alignItems: 'center',
    minHeight: 64,
    justifyContent: 'center',
  },
  psStatLbl: { fontSize: 6, color: C.dim, letterSpacing: 1.2, fontWeight: '700', marginBottom: 4 },
  psStatVal: { fontSize: 13, fontWeight: '900' },
  psSparkWrap: { marginTop: 14, alignSelf: 'stretch', alignItems: 'center', opacity: 0.95 },
  psSwitchProfileBtn: {
    marginTop: 16,
    minHeight: 48,
    paddingVertical: 12,
    paddingHorizontal: 22,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: C.gold,
    backgroundColor: 'transparent',
    alignItems: 'center',
    justifyContent: 'center',
  },
  psSwitchProfileTxt: { fontSize: 10, fontWeight: '800', color: C.goldL, letterSpacing: 2 },
  psDivider: {
    height: 1,
    backgroundColor: C.border,
    marginVertical: 4,
    opacity: 0.9,
  },
  psSettingsTitle: {
    fontSize: 10,
    fontWeight: '900',
    color: C.gold,
    letterSpacing: 3,
    marginTop: 4,
    marginBottom: 8,
  },
  psSettingsCard: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: 'rgba(0,0,0,0.18)',
    paddingHorizontal: 14,
    paddingVertical: 12,
    gap: 0,
  },
  psRowLabel: { fontSize: 9, fontWeight: '800', color: C.dim, letterSpacing: 1.5, marginBottom: 8, marginTop: 4 },
  psSegRow: { flexDirection: 'row', gap: 6, marginBottom: 4 },
  psSegChip: {
    borderRadius: 8,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: 'rgba(255,255,255,0.03)',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
    paddingHorizontal: 4,
  },
  psSegChipOn: {
    borderColor: 'rgba(212,180,90,0.65)',
    backgroundColor: 'rgba(212,180,90,0.14)',
  },
  psSegChipTxt: { fontSize: 9, fontWeight: '700', color: C.dim, textAlign: 'center' },
  psSegChipTxtOn: { color: C.goldL, fontWeight: '900' },
  psRowDivider: { height: 1, backgroundColor: 'rgba(30,23,0,0.55)', marginVertical: 12 },
  psToggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: 48,
    paddingVertical: 6,
    gap: 12,
  },
  psToggleLbl: { fontSize: 11, fontWeight: '700', color: C.text, flex: 1 },
  psToggleHint: { fontSize: 9, color: C.dim, marginRight: 8, fontWeight: '600' },
  psResetBtn: {
    marginTop: 18,
    minHeight: 48,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: 'rgba(255,61,87,0.65)',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    backgroundColor: 'rgba(255,61,87,0.06)',
  },
  psResetTxt: { fontSize: 10, fontWeight: '800', color: C.red, letterSpacing: 1.5 },
  psModalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.72)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 22,
  },
  psModalCard: {
    width: '100%',
    maxWidth: 340,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(212,180,90,0.35)',
    backgroundColor: C.panel2,
    padding: 16,
    zIndex: 2,
  },
  psModalTitle: { fontSize: 11, fontWeight: '900', color: C.goldL, letterSpacing: 2, marginBottom: 12, textAlign: 'center' },
  psModalRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: C.border,
    marginBottom: 8,
    gap: 12,
    minHeight: 52,
  },
  psModalRowOn: { borderColor: C.gold, backgroundColor: 'rgba(212,180,90,0.1)' },
  psModalAvatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 2,
    borderColor: C.goldL,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.3)',
  },
  psModalAvatarTxt: { fontSize: 12, fontWeight: '900', color: C.goldL },
  psModalName: { fontSize: 14, fontWeight: '800', color: C.text },
  psModalTier: { fontSize: 9, color: C.dim, marginTop: 2, letterSpacing: 1 },
  psModalCheck: { fontSize: 16, color: C.green, fontWeight: '900' },
  psModalClose: { marginTop: 8, paddingVertical: 12, alignItems: 'center' },
  psModalCloseTxt: { fontSize: 10, fontWeight: '800', color: C.dim, letterSpacing: 2 },

  ghBody: { paddingVertical: 0 },
  ghWrap: { position: 'relative', paddingBottom: 0 },
  ghPriceCard: {
    borderRadius: 16,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: 'rgba(201,168,76,0.35)',
  },
  ghPriceInner: { padding: 16, position: 'relative', zIndex: 1 },
  ghPriceMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 4,
  },
  ghPriceStatBlock: { flex: 1, alignItems: 'center', paddingHorizontal: 6 },
  ghPriceStatDivider: { width: 1, height: 44, backgroundColor: 'rgba(30,23,0,0.85)' },
  ghMiniLbl: { fontSize: 6, color: C.dim, letterSpacing: 1, fontWeight: '600' },
  ghMiniVal: { fontSize: 18, fontWeight: '800', marginTop: 4 },
  ghPriceFoot: {
    marginTop: 14,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: 'rgba(30,23,0,0.6)',
    justifyContent: 'space-between',
  },
  ghFootUtc: { fontSize: 8, color: C.dim2, fontWeight: '500' },
  ghFootEdge: { fontSize: 8, color: C.amber, fontWeight: '700', letterSpacing: 1, flex: 1, textAlign: 'right' },
  ghChipScroll: { maxHeight: 44, marginTop: 14 },
  ghChipRow: { gap: 8, alignItems: 'center', paddingVertical: 4 },
  ghChip: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(201,168,76,0.25)',
    backgroundColor: 'rgba(15,13,6,0.95)',
  },
  ghChipTxt: { fontSize: 7, fontWeight: '800', color: C.gold, letterSpacing: 1.2 },
  ghGrid2: { flexDirection: 'row', gap: 10, marginTop: 16 },
  ghStatTile: {
    flex: 1,
    paddingVertical: 14,
    paddingHorizontal: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: C.panel2,
  },
  ghStatLbl: { fontSize: 7, color: C.dim, letterSpacing: 2, fontWeight: '700', marginBottom: 6 },
  ghStatVal: { fontSize: 20, fontWeight: '900' },
  ghStatSub: { fontSize: 7, color: C.dim2, marginTop: 4, fontWeight: '500' },
  ghVerdictCard: {
    marginTop: 14,
    padding: 16,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: C.border,
    borderLeftWidth: 4,
    borderLeftColor: C.gold,
    backgroundColor: 'rgba(201,168,76,0.04)',
  },
  ghVerdictLbl: { fontSize: 7, color: C.dim, letterSpacing: 2, fontWeight: '800', marginBottom: 6 },
  ghVerdictMain: { fontSize: 16, fontWeight: '900', letterSpacing: 0.5 },
  ghVerdictSub: { fontSize: 8, color: C.dim, marginTop: 6, lineHeight: 14, fontWeight: '500' },
  ghHistWrap: { marginTop: 14 },
  ghQuote: {
    marginTop: 22,
    padding: 18,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(201,168,76,0.15)',
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  ghQuoteMark: { fontSize: 28, color: 'rgba(201,168,76,0.2)', lineHeight: 28, marginBottom: -8, fontFamily: Platform.select({ ios: 'Georgia', android: 'serif', default: 'serif' }) },
  ghQuoteTxt: {
    fontSize: 11,
    color: C.text,
    lineHeight: 18,
    fontStyle: 'italic',
    fontWeight: '500',
    letterSpacing: 0.3,
  },
  ghQuoteSig: { marginTop: 12, fontSize: 8, color: C.goldD, fontWeight: '800', letterSpacing: 2 },

  pnl: { backgroundColor: C.panel, borderWidth: 1, borderColor: C.border, borderRadius: DR.panel, overflow: 'hidden' },
  gmPanelShell: { borderColor: 'rgba(201,168,76,0.25)' },
  gmHeaderTint: { backgroundColor: 'rgba(201,168,76,0.05)' },
  srPanelShell: { borderColor: 'rgba(255,61,87,0.3)' },
  srHeadTint: { backgroundColor: 'rgba(255,61,87,0.04)' },
  flipShell: { borderColor: 'rgba(255,179,0,0.3)' },
  flipHeadTint: { backgroundColor: 'rgba(255,179,0,0.04)' },
  scanShell: { borderColor: 'rgba(64,196,255,0.3)' },
  scanHeadTint: { backgroundColor: 'rgba(64,196,255,0.04)' },

  ph: {
    paddingVertical: 10,
    paddingHorizontal: 13,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
    justifyContent: 'space-between',
    backgroundColor: 'rgba(201,168,76,0.02)',
  },
  phT: { fontSize: 9, fontWeight: '800', color: C.gold, letterSpacing: 2, textTransform: 'uppercase' },
  phB: {
    fontSize: 6,
    color: C.dim,
    letterSpacing: 1,
    borderWidth: 1,
    borderColor: C.border,
    paddingVertical: 2,
    paddingHorizontal: 6,
    borderRadius: DR.chip,
    fontWeight: '600',
  },
  pb: { paddingHorizontal: 13, paddingVertical: 11 },

  biasHero: { alignItems: 'center', paddingVertical: 12 },
  biasTag: { fontSize: 7, color: C.dim, letterSpacing: 2, marginBottom: 4 },
  biasWord: { fontSize: 26, fontWeight: '800', letterSpacing: 4 },
  biasBull: { color: C.green },
  biasSub: { fontSize: 7, color: C.dim, marginTop: 2 },
  tfRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 5,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(30,23,0,0.5)',
  },
  tfl: { fontSize: 8, color: C.dim, fontWeight: '600' },
  tfv: { fontSize: 8, fontWeight: '700' },
  tfBull: { color: C.green },
  tfBear: { color: C.red },
  tfNeu: { color: C.amber },

  geoDial: { alignItems: 'center', paddingVertical: 12 },
  geoRiskLbl: { fontSize: 7, color: C.dim, letterSpacing: 2, marginBottom: 5 },
  geoLevel: { fontSize: 24, fontWeight: '900', letterSpacing: 3, color: C.red },
  geoSub: { fontSize: 7, color: C.dim, letterSpacing: 1, marginTop: 3 },
  geoBars: { gap: 4, marginVertical: 10 },
  geoBar: { height: 20, width: 18, borderRadius: DR.mini, borderWidth: 1, borderColor: C.border },
  geoBarG: { backgroundColor: C.green },
  geoBarA: { backgroundColor: C.amber },
  geoBarR: { backgroundColor: C.red },
  geoRule: { fontSize: 8, color: C.red, letterSpacing: 0.5, textAlign: 'center', lineHeight: 14 },

  sectionLbl: {
    fontSize: 7,
    fontWeight: '700',
    color: C.dim,
    letterSpacing: 2,
    textTransform: 'uppercase',
    marginBottom: 6,
  },
  twoCol: { flexDirection: 'row', gap: 6, marginBottom: 8 },
  immedResBox: {
    flex: 1,
    backgroundColor: 'rgba(255,61,87,0.07)',
    borderWidth: 2,
    borderColor: 'rgba(255,61,87,0.4)',
    borderRadius: DR.block,
    padding: 10,
  },
  immedSupBox: {
    flex: 1,
    backgroundColor: 'rgba(0,230,118,0.07)',
    borderWidth: 2,
    borderColor: 'rgba(0,230,118,0.4)',
    borderRadius: DR.block,
    padding: 10,
  },
  imLbl: { fontSize: 7, color: C.dim, fontWeight: '700', letterSpacing: 1, marginBottom: 3 },
  imResVal: { fontSize: 18, fontWeight: '800', color: C.red },
  imSupVal: { fontSize: 18, fontWeight: '800', color: C.green },
  imSmall: { fontSize: 7, color: C.dim, marginTop: 2 },
  imDistRes: { fontSize: 8, fontWeight: '700', color: C.red, marginTop: 3 },
  imDistSup: { fontSize: 8, fontWeight: '700', color: C.green, marginTop: 3 },
  currPriceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 6,
    paddingHorizontal: 10,
    backgroundColor: 'rgba(64,196,255,0.05)',
    borderWidth: 1,
    borderColor: 'rgba(64,196,255,0.2)',
    borderRadius: DR.block,
    marginBottom: 8,
    gap: 6,
  },
  currLbl: { fontSize: 8, fontWeight: '700', color: C.blue },
  currVal: { fontSize: 14, fontWeight: '800', color: C.goldL },
  currPos: { fontSize: 8, fontWeight: '600', color: C.blue },
  poiResBox: {
    flex: 1,
    backgroundColor: 'rgba(255,61,87,0.04)',
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: 'rgba(255,61,87,0.3)',
    borderRadius: DR.block,
    padding: 10,
  },
  poiSupBox: {
    flex: 1,
    backgroundColor: 'rgba(0,230,118,0.04)',
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: 'rgba(0,230,118,0.3)',
    borderRadius: DR.block,
    padding: 10,
  },
  poiResVal: { fontSize: 15, fontWeight: '800', color: 'rgba(255,61,87,0.7)' },
  poiSupVal: { fontSize: 15, fontWeight: '800', color: 'rgba(0,230,118,0.7)' },

  flipSupOuter: {
    marginBottom: 8,
    paddingVertical: 9,
    paddingHorizontal: 11,
    backgroundColor: 'rgba(0,230,118,0.06)',
    borderWidth: 1,
    borderColor: 'rgba(0,230,118,0.3)',
    borderRadius: DR.block,
    overflow: 'hidden',
    position: 'relative',
  },
  flipAccentGreen: { position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, backgroundColor: C.green },
  flipGreenLbl: { fontSize: 7, color: C.green, fontWeight: '700', letterSpacing: 1.5, marginBottom: 4 },
  flipSupLvl: { fontSize: 18, fontWeight: '800', color: C.green },
  miniTagG: {
    fontSize: 7,
    fontWeight: '700',
    paddingVertical: 2,
    paddingHorizontal: 7,
    borderRadius: DR.chip,
    backgroundColor: 'rgba(0,230,118,0.1)',
    borderWidth: 1,
    borderColor: 'rgba(0,230,118,0.3)',
    color: C.green,
  },
  miniTagG2: {
    fontSize: 7,
    fontWeight: '700',
    paddingVertical: 2,
    paddingHorizontal: 7,
    borderRadius: DR.chip,
    backgroundColor: 'rgba(0,230,118,0.08)',
    borderWidth: 1,
    borderColor: 'rgba(0,230,118,0.2)',
    color: C.green,
  },
  flipResOuter: {
    marginBottom: 8,
    paddingVertical: 9,
    paddingHorizontal: 11,
    backgroundColor: 'rgba(255,61,87,0.04)',
    borderWidth: 1,
    borderColor: 'rgba(255,61,87,0.2)',
    borderRadius: DR.block,
    overflow: 'hidden',
    position: 'relative',
  },
  flipAccentRed: { position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, backgroundColor: 'rgba(255,61,87,0.3)' },
  flipDimLbl: { fontSize: 7, color: C.dim, fontWeight: '700', letterSpacing: 1.5, marginBottom: 4 },
  flipResLvl: { fontSize: 18, fontWeight: '800', color: 'rgba(255,61,87,0.5)' },
  miniTagWatch: {
    alignSelf: 'flex-start',
    fontSize: 7,
    fontWeight: '700',
    paddingVertical: 2,
    paddingHorizontal: 7,
    borderRadius: DR.chip,
    backgroundColor: 'rgba(255,61,87,0.06)',
    borderWidth: 1,
    borderColor: 'rgba(255,61,87,0.15)',
    color: C.dim,
  },
  flipRuleBox: {
    paddingVertical: 7,
    paddingHorizontal: 10,
    backgroundColor: 'rgba(255,179,0,0.05)',
    borderWidth: 1,
    borderColor: 'rgba(255,179,0,0.2)',
    borderRadius: DR.block,
  },
  flipRuleTxt: { fontSize: 7, color: C.amber, lineHeight: 14, fontWeight: '600' },

  pathLblG: { fontSize: 7, fontWeight: '700', color: C.green, letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 5 },
  pathLblR: { fontSize: 7, fontWeight: '700', color: C.red, letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 5 },
  lsPanel: {
    backgroundColor: 'rgba(0,0,0,0.2)',
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: DR.block,
    overflow: 'hidden',
  },
  lsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
  },
  lsRowL: { fontSize: 8, fontWeight: '600', color: C.dim },
  lsRowR: { fontSize: 8, fontWeight: '800' },
  pathVerdict: { marginTop: 4, paddingVertical: 6, paddingHorizontal: 8, borderRadius: DR.block, borderWidth: 1 },
  lsVerdictBox: { paddingVertical: 10, paddingHorizontal: 12, borderRadius: DR.block, borderWidth: 1, alignItems: 'center', marginTop: 8 },
  lsVerdictLbl: { fontSize: 7, fontWeight: '700', letterSpacing: 2, marginBottom: 3 },
  lsVerdictVal: { fontSize: 14, fontWeight: '800' },
  lsVerdictSub: { fontSize: 7, color: C.dim, marginTop: 3 },

  dxyRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(30,23,0,0.4)',
  },
  dxyL: { fontSize: 8, color: C.dim, fontWeight: '500' },
  dxyV: { fontSize: 8, fontWeight: '600' },
  dxyFoot: {
    marginTop: 8,
    paddingVertical: 6,
    paddingHorizontal: 8,
    backgroundColor: C.greenD,
    borderWidth: 1,
    borderColor: 'rgba(0,230,118,0.15)',
    borderRadius: DR.block,
    fontSize: 7,
    color: C.green,
    letterSpacing: 0.5,
  },

  chopActive: {
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: DR.block,
    alignItems: 'center',
    marginBottom: 10,
    backgroundColor: 'rgba(255,179,0,0.06)',
    borderWidth: 1,
    borderColor: 'rgba(255,179,0,0.25)',
  },
  chopWord: { fontSize: 16, fontWeight: '800', letterSpacing: 2 },
  chopSub: { fontSize: 7, marginTop: 3, letterSpacing: 1 },

  athZone: {
    backgroundColor: 'rgba(255,61,87,0.04)',
    borderWidth: 1,
    borderColor: 'rgba(255,61,87,0.2)',
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: DR.block,
    marginBottom: 8,
  },
  athTitle: { fontSize: 8, color: C.red, letterSpacing: 1.5, marginBottom: 6, fontWeight: '700' },
  athRange: { fontSize: 15, fontWeight: '800', color: C.red },
  athSub: { fontSize: 7, color: C.dim, marginTop: 2 },

  sigCard: {
    borderWidth: 1,
    borderColor: C.goldD,
    backgroundColor: '#16130E',
    paddingVertical: 16,
    paddingHorizontal: 16,
    borderRadius: DR.block,
    overflow: 'hidden',
    position: 'relative',
  },
  sigCardCompact: {
    paddingVertical: 14,
    paddingHorizontal: 14,
    borderRadius: DR.block,
  },
  sigInnerStack: { gap: 14 },
  sigTopTrade: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  sigBuyBadge: {
    width: 72,
    minHeight: 88,
    borderRadius: DR.chip,
    borderWidth: 1,
    borderColor: 'rgba(0,230,118,0.35)',
    backgroundColor: 'rgba(0,230,118,0.06)',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
  },
  sigActionCompact: { fontSize: 26, lineHeight: 30, letterSpacing: 1 },
  sigInfoCompact: { flex: 1, minWidth: 0, gap: 6 },
  sigPairCompact: { fontSize: 9, color: C.dim, letterSpacing: 1.5, fontWeight: '700' },
  sigConfCompact: { fontSize: 10, color: C.gold, fontWeight: '700', lineHeight: 15 },
  sigStratCompact: { fontSize: 8, color: C.dim, letterSpacing: 0.3, lineHeight: 14, fontWeight: '500' },
  sigSessCompact: {
    fontSize: 8,
    color: C.dim,
    letterSpacing: 0.8,
    textAlign: 'center',
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: DR.chip,
    backgroundColor: 'rgba(0,0,0,0.25)',
    borderWidth: 1,
    borderColor: C.border,
    overflow: 'hidden',
  },
  sigBtnRow: { flexDirection: 'row', alignItems: 'stretch', gap: 10 },
  execBtnCompact: {
    flex: 1,
    paddingVertical: 14,
    paddingHorizontal: 10,
    borderRadius: DR.soft,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 50,
  },
  execBtnTxtCompact: { color: '#000', fontSize: 11, fontWeight: '800', letterSpacing: 1.5 },
  skipBtnCompact: {
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: DR.soft,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 50,
    minWidth: 100,
  },
  skipBtnTxtCompact: { color: C.red, fontSize: 10, fontWeight: '700', letterSpacing: 1 },
  sigWatermarkCompact: { opacity: 0.06, top: '36%' },
  sigGlow: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'transparent',
    opacity: 1,
  },
  sigAccent: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 4,
    backgroundColor: C.green,
    borderTopLeftRadius: DR.block,
    borderBottomLeftRadius: DR.block,
  },
  sigInner: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'stretch',
    gap: 12,
    flexWrap: 'nowrap',
  },
  sigL: { flex: 1, minWidth: 0, gap: 14, alignItems: 'center', flexDirection: 'row' },
  sigAction: { fontSize: 36, fontWeight: '800', lineHeight: 40 },
  sigBuy: { color: C.green },
  sigInfo: { flex: 1, minWidth: 0, gap: 4 },
  sigPair: { fontSize: 8, color: C.dim, letterSpacing: 2, fontWeight: '600' },
  pillWick: {
    alignSelf: 'flex-start',
    fontSize: 8,
    paddingVertical: 3,
    paddingHorizontal: 10,
    borderRadius: DR.chip,
    letterSpacing: 1,
    marginBottom: 2,
    fontWeight: '700',
    color: C.red,
    borderWidth: 1,
    borderColor: 'rgba(255,61,87,0.4)',
    backgroundColor: 'rgba(255,61,87,0.06)',
  },
  pillBreak: {
    alignSelf: 'flex-start',
    fontSize: 8,
    paddingVertical: 3,
    paddingHorizontal: 10,
    borderRadius: DR.chip,
    color: C.blue,
    borderWidth: 1,
    borderColor: 'rgba(64,196,255,0.4)',
    backgroundColor: 'rgba(64,196,255,0.06)',
    fontWeight: '700',
  },
  pillFlip: {
    alignSelf: 'flex-start',
    fontSize: 8,
    paddingVertical: 3,
    paddingHorizontal: 10,
    borderRadius: DR.chip,
    color: C.amber,
    borderWidth: 1,
    borderColor: 'rgba(255,179,0,0.4)',
    backgroundColor: 'rgba(255,179,0,0.06)',
    fontWeight: '700',
  },
  sigConf: { fontSize: 10, color: C.gold, fontWeight: '700' },
  sigStrat: { fontSize: 7, color: C.dim, letterSpacing: 0.5 },
  sigR: { flexShrink: 0, alignItems: 'flex-end', justifyContent: 'center', gap: 6 },
  sigSess: { fontSize: 7, color: C.dim, letterSpacing: 1, textAlign: 'right' },
  execBtn: {
    backgroundColor: C.gold,
    paddingVertical: 10,
    paddingHorizontal: 22,
    borderRadius: DR.soft,
  },
  execBtnTxt: { color: '#000', fontSize: 9, fontWeight: '800', letterSpacing: 2 },
  skipBtn: {
    borderWidth: 1,
    borderColor: 'rgba(255,61,87,0.3)',
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: DR.soft,
    backgroundColor: 'transparent',
  },
  skipBtnTxt: { color: C.red, fontSize: 8, fontWeight: '600', letterSpacing: 1 },
  sigWatermark: {
    position: 'absolute',
    right: -18,
    top: '42%',
    fontSize: 7,
    color: 'rgba(201,168,76,0.12)',
    letterSpacing: 4,
    transform: [{ rotate: '90deg' }],
    fontWeight: '700',
  },

  filterGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 8 },
  filt: { flexGrow: 1, flexBasis: '22%', paddingVertical: 8, paddingHorizontal: 10, borderRadius: DR.soft, gap: 3, minWidth: '22%' },
  filtOk: { backgroundColor: C.greenD, borderWidth: 1, borderColor: 'rgba(0,230,118,0.2)' },
  filtWarn: { backgroundColor: C.redD, borderWidth: 1, borderColor: 'rgba(255,61,87,0.2)' },
  filtAmb: { backgroundColor: 'rgba(255,179,0,0.06)', borderWidth: 1, borderColor: 'rgba(255,179,0,0.2)' },
  filtL: { fontSize: 7, color: C.dim, letterSpacing: 1, fontWeight: '600' },
  filtV: { fontSize: 13, fontWeight: '800' },
  filtS: { fontSize: 7, letterSpacing: 0.5, fontWeight: '600' },

  wickInd: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 8,
    paddingHorizontal: 11,
    borderRadius: DR.block,
    marginBottom: 8,
    backgroundColor: C.greenD,
    borderWidth: 1,
    borderColor: 'rgba(0,230,118,0.2)',
  },
  wiIcon: { fontSize: 16 },
  wiMain: { fontSize: 8, color: C.text, letterSpacing: 0.5, marginBottom: 1, fontWeight: '600' },
  wiSub: { fontSize: 7, color: C.dim },

  atrRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  atrLabel: { fontSize: 8, color: C.dim, fontWeight: '600' },
  atrVal: { fontSize: 14, fontWeight: '800', color: C.amber },
  atrBarBg: { height: 5, backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: DR.mini, overflow: 'hidden', marginBottom: 10 },
  atrBarFill: { height: '100%', borderRadius: DR.mini, backgroundColor: C.amber },
  modePill: {
    alignSelf: 'flex-start',
    fontSize: 8,
    paddingVertical: 3,
    paddingHorizontal: 10,
    borderRadius: DR.chip,
    letterSpacing: 1,
    marginBottom: 10,
    fontWeight: '700',
  },
  modeStd: { color: C.green, borderWidth: 1, borderColor: 'rgba(0,230,118,0.3)', backgroundColor: C.greenD },
  modeAmb: { color: C.amber, borderWidth: 1, borderColor: 'rgba(255,179,0,0.3)', backgroundColor: 'rgba(255,179,0,0.06)' },
  modeRed: { color: C.red, borderWidth: 1, borderColor: 'rgba(255,61,87,0.3)', backgroundColor: C.redD },

  eeGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 7, marginBottom: 8 },
  eeCell: {
    flexGrow: 1,
    flexBasis: '22%',
    backgroundColor: 'rgba(0,0,0,0.3)',
    borderWidth: 1,
    borderColor: C.border,
    padding: 10,
    borderRadius: DR.block,
    minWidth: '45%',
  },
  eeL: { fontSize: 6, color: C.dim, letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 4, fontWeight: '700' },
  eeV: { fontSize: 15, fontWeight: '800' },
  eeS: { fontSize: 7, color: C.dim, marginTop: 2 },
  eeEntry: { color: C.green },
  eeBe: { color: C.purple },
  eeTp1: { color: C.goldL },
  eeTp2: { color: C.gold },
  eeSl: { color: C.red },
  eePlain: { color: C.text },
  eeGold: { color: C.gold },

  rrStrip: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    gap: 8,
    backgroundColor: 'rgba(201,168,76,0.04)',
    borderWidth: 1,
    borderColor: C.border,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: DR.block,
  },
  rri: { alignItems: 'center', minWidth: '18%' },
  rrl: { fontSize: 6, color: C.dim, letterSpacing: 1, fontWeight: '600' },
  rrv: { fontSize: 13, fontWeight: '800', color: C.gold },

  chartWrap: {
    height: 120,
    backgroundColor: 'rgba(0,0,0,0.2)',
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: DR.block,
    overflow: 'hidden',
    position: 'relative',
  },
  chartAth: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: 0,
    height: 10,
    backgroundColor: 'rgba(255,61,87,0.06)',
    borderTopLeftRadius: DR.block,
    borderTopRightRadius: DR.block,
  },
  chartAthTxt: {
    position: 'absolute',
    left: 4,
    top: 1,
    fontSize: 6,
    color: 'rgba(255,61,87,0.6)',
  },
  chartDot: {
    position: 'absolute',
    width: 3,
    height: 3,
    borderRadius: 1.5,
    backgroundColor: C.gold,
    marginLeft: -1.5,
    marginTop: -1.5,
  },
  hLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    borderTopWidth: 1,
    borderStyle: 'dashed',
    borderColor: 'rgba(216,200,144,0.35)',
  },
  hLineLbl: { position: 'absolute', top: -10, fontSize: 6 },
  vLine: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    borderLeftWidth: 1,
    borderStyle: 'dashed',
    borderColor: 'rgba(0,230,118,0.45)',
  },
  vLineLbl: { position: 'absolute', left: 4, top: 4, fontSize: 6 },
  wickGrab: {
    position: 'absolute',
    left: '49%',
    top: '52%',
    width: '8%',
    height: '24%',
    backgroundColor: 'rgba(255,61,87,0.07)',
    borderWidth: 1,
    borderColor: 'rgba(255,61,87,0.35)',
    borderRadius: DR.chip,
  },
  wickGrabLbl: { position: 'absolute', left: '48%', bottom: 4, fontSize: 7, color: C.red },

  histTableWrap: {
    borderRadius: DR.block,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: 'rgba(30,23,0,0.45)',
    backgroundColor: 'rgba(0,0,0,0.2)',
  },
  histHead: {
    flexDirection: 'row',
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: C.border,
    gap: 4,
    alignItems: 'flex-start',
  },
  histTh: { fontSize: 6, color: C.dim, letterSpacing: 1, fontWeight: '700', textTransform: 'uppercase' },
  histColUtc: { flex: 0.7, minWidth: 0 },
  histColDir: { flex: 0.4, minWidth: 0 },
  histColType: {
    flex: 0.9,
    minWidth: 0,
    alignItems: 'center',
    justifyContent: 'flex-start',
    paddingTop: 1,
  },
  histColEntry: { flex: 1, minWidth: 0, flexShrink: 1, paddingRight: 2 },
  histColSl: { flex: 0.8, minWidth: 0 },
  histColBe: { flex: 0.8, minWidth: 0 },
  histColPl: { flex: 0.9, minWidth: 0 },
  histColRes: { flex: 0.7, minWidth: 0 },
  histBreakMsg: { color: C.red, fontSize: 7, lineHeight: 11, fontWeight: '600' },
  histDashCell: { color: C.dim2, fontSize: 7, textAlign: 'center' },
  histRow: {
    flexDirection: 'row',
    paddingHorizontal: 8,
    paddingVertical: 7,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(30,23,0,0.4)',
    alignItems: 'flex-start',
    gap: 4,
  },
  histTd: { fontSize: 8, fontWeight: '500', color: C.text },
  tBuy: { color: C.green, fontWeight: '800' },
  tSell: { color: C.red, fontWeight: '800' },
  tWin: { color: C.green, fontWeight: '600' },
  tLoss: { color: C.red, fontWeight: '600' },
  tOpen: { color: C.gold, fontWeight: '600' },
  eb: { fontSize: 6, paddingVertical: 1, paddingHorizontal: 5, borderRadius: DR.mini, fontWeight: '700', overflow: 'hidden' },
  ebW: { backgroundColor: 'rgba(255,61,87,0.1)', color: C.red },
  ebB: { backgroundColor: 'rgba(64,196,255,0.1)', color: C.blue },
  ebF: { backgroundColor: 'rgba(255,179,0,0.1)', color: C.amber },

  pnlHero: { alignItems: 'center', paddingVertical: 14 },
  pnlTag: { fontSize: 7, color: C.dim, letterSpacing: 2, marginBottom: 5, fontWeight: '600' },
  pnlNum: { fontSize: 32, fontWeight: '800' },
  pnlPips: { fontSize: 8, color: C.dim, marginTop: 3 },
  pnlMini: { flexDirection: 'row', flexWrap: 'wrap', gap: 7 },
  pmC: {
    flexGrow: 1,
    flexBasis: '45%',
    backgroundColor: 'rgba(0,0,0,0.3)',
    borderWidth: 1,
    borderColor: C.border,
    padding: 8,
    borderRadius: DR.block,
    alignItems: 'center',
  },
  pmL: { fontSize: 7, color: C.dim, letterSpacing: 1, marginBottom: 3, fontWeight: '600' },
  pmV: { fontSize: 15, fontWeight: '800', color: C.gold },

  rmHdr: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 },
  rmL: { fontSize: 7, color: C.dim, fontWeight: '600' },
  rmV: { fontSize: 7, color: C.green, fontWeight: '600' },
  rmBar: { height: 4, backgroundColor: 'rgba(255,255,255,0.04)', borderRadius: DR.mini, overflow: 'hidden', marginBottom: 10 },
  rmFill: { height: '100%', borderRadius: DR.mini, backgroundColor: C.gold },

  yieldPct: { fontSize: 14, fontWeight: '900', color: C.purple },
  yieldBarBg: { height: 6, backgroundColor: 'rgba(255,255,255,0.04)', borderRadius: DR.mini, overflow: 'hidden', marginBottom: 6 },
  yieldFill: { height: '100%', borderRadius: DR.mini, backgroundColor: C.purple },
  yieldMarkers: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8 },
  yieldMk: { fontSize: 7, color: C.dim, fontWeight: '500' },

  dayCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    padding: 10,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: 'rgba(0,0,0,0.2)',
    borderRadius: DR.block,
    marginBottom: 8,
  },
  dayIcon: { fontSize: 20 },
  dayName: { fontSize: 13, fontWeight: '800', color: C.gold },
  dayMode: { fontSize: 7, color: C.dim, letterSpacing: 1, marginTop: 2 },
  dayRule: { fontSize: 8, color: C.green, marginTop: 3, fontWeight: '600' },

  spreadGuard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 8,
    paddingHorizontal: 11,
    borderRadius: DR.block,
    marginBottom: 8,
  },
  sgOk: { backgroundColor: C.greenD, borderWidth: 1, borderColor: 'rgba(0,230,118,0.2)' },
  sgWarn: { backgroundColor: C.redD, borderWidth: 1, borderColor: 'rgba(255,61,87,0.25)' },
  sgLabel: { fontSize: 7, color: C.dim, letterSpacing: 1, marginBottom: 2, fontWeight: '600' },
  sgSpread: { fontSize: 20, fontWeight: '800' },
  sgTiny: { fontSize: 7, color: C.dim },
  sgTiny2: { fontSize: 7, color: C.dim, marginTop: 2 },
  sgStatus: { fontSize: 8, letterSpacing: 1 },

  newsClear: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    backgroundColor: C.greenD,
    borderWidth: 1,
    borderColor: 'rgba(0,230,118,0.2)',
    borderRadius: DR.block,
    fontSize: 7,
    color: C.green,
    letterSpacing: 1,
    marginBottom: 7,
    textAlign: 'center',
    fontWeight: '700',
  },
  ni: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 5,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(30,23,0,0.4)',
    gap: 6,
  },
  niTime: { fontSize: 8, color: C.dim, fontWeight: '500', minWidth: 36 },
  niName: { flex: 1, fontSize: 8, color: C.text, fontWeight: '500' },
  niImpact: { fontSize: 6, paddingVertical: 2, paddingHorizontal: 6, borderRadius: DR.mini, letterSpacing: 1, fontWeight: '700' },
  niH: { color: C.red, borderWidth: 1, borderColor: 'rgba(255,61,87,0.3)', backgroundColor: 'rgba(255,61,87,0.05)' },
  niM: { color: C.amber, borderWidth: 1, borderColor: 'rgba(255,179,0,0.3)', backgroundColor: 'rgba(255,179,0,0.05)' },
  niOk: { fontSize: 6, color: C.green, fontWeight: '700' },
  niPast: { fontSize: 6, color: C.dim, fontWeight: '500' },
  niBlock: { fontSize: 6, color: C.red, letterSpacing: 1, fontWeight: '700' },
  newsFoot: {
    marginTop: 7,
    paddingTop: 7,
    borderTopWidth: 1,
    borderTopColor: C.border,
    fontSize: 7,
    color: C.dim,
    lineHeight: 14,
  },
});

export default function App() {
  return (
    <SafeAreaProvider>
      <AppContent />
    </SafeAreaProvider>
  );
}
