import React, { useEffect, useState } from 'react';
import { Platform, StyleSheet, Text, View } from 'react-native';
import Svg, {
  Circle,
  Defs,
  G,
  Line,
  LinearGradient,
  Polygon,
  RadialGradient,
  Stop,
  Text as SvgText,
} from 'react-native-svg';

const VB = 80;
const CX = 40;
const CY = 40;

const MAIN_HEX = '40,10 64,23.5 64,56.5 40,70 16,56.5 16,23.5';
const INNER_HEX = '40,18 58,28.5 58,51.5 40,62 22,51.5 22,28.5';

const DIAMONDS = [
  '40,12.5 41.2,13.7 40,14.9 38.8,13.7',
  '40,65.1 41.2,66.3 40,67.5 38.8,66.3',
  '12.5,40 13.7,41.2 14.9,40 13.7,38.8',
  '65.1,40 66.3,41.2 67.5,40 66.3,38.8',
  '20.5,20.5 21.7,21.7 20.5,22.9 19.3,21.7',
  '59.5,59.5 60.7,60.7 59.5,61.9 58.3,60.7',
];

/** Plain Svg + rAF (Animated.createAnimatedComponent often breaks on Expo Go). */
function AnimatedSvgLogo() {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let id;
    const loop = () => {
      setTick(Date.now());
      id = requestAnimationFrame(loop);
    };
    id = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(id);
  }, []);

  const ms = tick || Date.now();

  const pOuter = (ms % 3000) / 3000;
  const outerR = 37 + ((Math.sin(pOuter * Math.PI * 2) + 1) / 2) * 2;
  const outerOp = 0.05 + ((Math.cos(pOuter * Math.PI * 2) + 1) / 2) * (0.2 - 0.05);

  const outerDeg = ((ms % 30000) / 30000) * 360;
  const innerDeg = -((ms % 20000) / 20000) * 360;
  const dashOff = ((ms % 8000) / 8000) * 100;
  const radarDeg = ((ms % 4000) / 4000) * 360;

  const pCenter = (ms % 1500) / 1500;
  const centerR = 2 + ((Math.sin(pCenter * Math.PI * 2) + 1) / 2) * 1.5;
  const centerOp = 0.4 + ((Math.sin(pCenter * Math.PI * 2 + Math.PI / 2) + 1) / 2) * 0.6;

  const serifSvg = Platform.select({ ios: 'Georgia', android: 'serif', default: 'serif' });

  return (
    <View style={logoStyles.shadowWrap}>
      <Svg width={VB} height={VB} viewBox={`0 0 ${VB} ${VB}`}>
        <Defs>
          <RadialGradient id="hexFill" cx={CX} cy={CY} r={28} gradientUnits="userSpaceOnUse">
            <Stop offset="0%" stopColor="#2C1E00" />
            <Stop offset="100%" stopColor="#0A0700" />
          </RadialGradient>
          <LinearGradient id="goldLine" x1="0%" y1="0%" x2="100%" y2="100%">
            <Stop offset="0%" stopColor="#F0D080" />
            <Stop offset="50%" stopColor="#C9A84C" />
            <Stop offset="100%" stopColor="#8B6914" />
          </LinearGradient>
          <LinearGradient id="goldLine2" x1="100%" y1="0%" x2="0%" y2="100%">
            <Stop offset="0%" stopColor="#F0D080" />
            <Stop offset="100%" stopColor="#6A4E10" />
          </LinearGradient>
          <LinearGradient id="gradB" x1="0%" y1="0%" x2="100%" y2="100%">
            <Stop offset="0%" stopColor="#F0D080" />
            <Stop offset="100%" stopColor="#8B6914" />
          </LinearGradient>
          <LinearGradient id="gradS" x1="100%" y1="0%" x2="0%" y2="100%">
            <Stop offset="0%" stopColor="#F0D080" />
            <Stop offset="100%" stopColor="#6A4E10" />
          </LinearGradient>
        </Defs>

        <Circle
          cx={CX}
          cy={CY}
          r={outerR}
          fill="none"
          stroke="#C9A84C"
          strokeWidth={0.5}
          strokeOpacity={outerOp}
        />

        <G rotation={outerDeg} originX={CX} originY={CY}>
          <Circle
            cx={CX}
            cy={CY}
            r={35}
            fill="none"
            stroke="#C9A84C"
            strokeWidth={0.4}
            strokeDasharray="2, 4"
            strokeOpacity={0.4}
          />
          <Line x1={40} y1={5} x2={40} y2={9} stroke="#C9A84C" strokeWidth={1} strokeOpacity={0.8} />
          <Line x1={40} y1={71} x2={40} y2={75} stroke="#C9A84C" strokeWidth={1} strokeOpacity={0.8} />
          <Line x1={71} y1={40} x2={75} y2={40} stroke="#C9A84C" strokeWidth={1} strokeOpacity={0.8} />
          <Line x1={5} y1={40} x2={9} y2={40} stroke="#C9A84C" strokeWidth={1} strokeOpacity={0.8} />
          <Line x1={14.4} y1={14.4} x2={17.2} y2={17.2} stroke="#C9A84C" strokeWidth={0.8} strokeOpacity={0.5} />
          <Line x1={62.8} y1={62.8} x2={65.6} y2={65.6} stroke="#C9A84C" strokeWidth={0.8} strokeOpacity={0.5} />
          <Line x1={65.6} y1={14.4} x2={62.8} y2={17.2} stroke="#C9A84C" strokeWidth={0.8} strokeOpacity={0.5} />
          <Line x1={17.2} y1={62.8} x2={14.4} y2={65.6} stroke="#C9A84C" strokeWidth={0.8} strokeOpacity={0.5} />
        </G>

        <G rotation={innerDeg} originX={CX} originY={CY}>
          <Circle
            cx={CX}
            cy={CY}
            r={28}
            fill="none"
            stroke="#C9A84C"
            strokeWidth={0.3}
            strokeDasharray="1, 6"
            strokeOpacity={0.3}
          />
          {DIAMONDS.map((pts, i) => (
            <Polygon key={i} points={pts} fill="#C9A84C" fillOpacity={i < 4 ? 0.7 : 0.5} />
          ))}
        </G>

        <Polygon points={MAIN_HEX} fill="url(#hexFill)" stroke="url(#goldLine)" strokeWidth={1.2} />

        <Polygon
          points={INNER_HEX}
          fill="none"
          stroke="#C9A84C"
          strokeWidth={0.5}
          strokeOpacity={0.4}
          strokeDasharray="3, 3"
          strokeDashoffset={dashOff}
        />

        <G rotation={radarDeg} originX={CX} originY={CY}>
          <Line
            x1={40}
            y1={40}
            x2={40}
            y2={11}
            stroke="#F0D080"
            strokeWidth={1}
            strokeOpacity={0.5}
            strokeLinecap="round"
          />
          <Circle cx={40} cy={11} r={1.5} fill="#F0D080" fillOpacity={0.8} />
        </G>

        <Circle cx={CX} cy={CY} r={centerR} fill="#F0D080" fillOpacity={centerOp} />

        <SvgText
          x={27}
          y={45}
          fontSize={16}
          fontWeight="bold"
          fontFamily={serifSvg}
          fill="url(#gradB)"
          stroke="url(#goldLine)"
          strokeWidth={0.3}>
          B
        </SvgText>
        <SvgText x={39} y={45} fontSize={16} fontWeight="bold" fontFamily={serifSvg} fill="url(#gradS)">
          S
        </SvgText>
      </Svg>
    </View>
  );
}

const serifHeading = Platform.select({
  ios: 'Georgia',
  android: 'serif',
  default: 'serif',
});

export default function BilshenzHeader() {
  return (
    <View style={styles.headerRow} testID="bilshenz-header">
      <AnimatedSvgLogo />
      <View style={styles.textStack}>
        <Text style={[styles.h1, { fontFamily: serifHeading }]}>BILSHENZ</Text>
        <Text style={styles.sub}>Jimplas Capital Management · XAUUSD Spot Intelligence</Text>
        <Text style={styles.vtag}>v3.2 GODMODE · WICKS DON'T LIE · S&R ENGINE</Text>
      </View>
    </View>
  );
}

const logoStyles = StyleSheet.create({
  shadowWrap: {
    width: VB,
    height: VB,
    shadowColor: '#C9A84C',
    shadowOpacity: 0.35,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 0 },
    elevation: 8,
  },
});

const styles = StyleSheet.create({
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    flexShrink: 1,
  },
  textStack: {
    flexDirection: 'column',
    gap: 2,
    flexShrink: 1,
    minWidth: 0,
  },
  h1: {
    fontSize: 22,
    fontWeight: '900',
    color: '#F0D080',
    letterSpacing: 6,
  },
  sub: {
    fontSize: 8,
    fontWeight: '500',
    color: '#5A4A20',
    letterSpacing: 3,
    textTransform: 'uppercase',
  },
  vtag: {
    fontSize: 7,
    fontWeight: '600',
    color: '#6A4E10',
    letterSpacing: 2,
  },
});
