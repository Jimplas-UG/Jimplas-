import React from 'react';
import Svg, { Circle, Defs, G, Line, LinearGradient, Polygon, Stop, Text as SvgText } from 'react-native-svg';
import { CX, CY, DIAMONDS, INNER_HEX, MAIN_HEX, VB } from './hexLogoGeometry';

const COLORS = {
  gold: '#D4B45A',
  goldBright: '#F2E2B0',
  goldPale: '#FFF4D0',
  amber: '#C98A2E',
  bronze: '#7A5C18',
};

/** App icon / splash — same geometry as CinematicSplash (solid). */
export default function StaticHexLogo({ size = 120 }) {
  return (
    <Svg width={size} height={size} viewBox={`0 0 ${VB} ${VB}`}>
      <Defs>
        <LinearGradient id="metalFill" x1="0%" y1="0%" x2="100%" y2="100%">
          <Stop offset="0%" stopColor="#3A3020" />
          <Stop offset="35%" stopColor="#1A160E" />
          <Stop offset="70%" stopColor="#0A0806" />
          <Stop offset="100%" stopColor="#000000" />
        </LinearGradient>
        <LinearGradient id="goldLine" x1="0%" y1="0%" x2="100%" y2="100%">
          <Stop offset="0%" stopColor={COLORS.goldPale} />
          <Stop offset="45%" stopColor={COLORS.gold} />
          <Stop offset="100%" stopColor={COLORS.bronze} />
        </LinearGradient>
        <LinearGradient id="gradB" x1="0%" y1="0%" x2="100%" y2="100%">
          <Stop offset="0%" stopColor={COLORS.goldBright} />
          <Stop offset="100%" stopColor={COLORS.amber} />
        </LinearGradient>
        <LinearGradient id="gradS" x1="100%" y1="0%" x2="0%" y2="100%">
          <Stop offset="0%" stopColor={COLORS.goldBright} />
          <Stop offset="100%" stopColor={COLORS.bronze} />
        </LinearGradient>
      </Defs>
      <G>
        <Circle cx={CX} cy={CY} r={35} fill="none" stroke={COLORS.gold} strokeWidth={0.4} strokeOpacity={0.55} strokeDasharray="2,4" />
        <Line x1={40} y1={5} x2={40} y2={9} stroke="url(#goldLine)" strokeWidth={1} strokeOpacity={0.92} />
        <Line x1={40} y1={71} x2={40} y2={75} stroke="url(#goldLine)" strokeWidth={1} strokeOpacity={0.92} />
        <Line x1={71} y1={40} x2={75} y2={40} stroke="url(#goldLine)" strokeWidth={1} strokeOpacity={0.92} />
        <Line x1={5} y1={40} x2={9} y2={40} stroke="url(#goldLine)" strokeWidth={1} strokeOpacity={0.92} />
        <Polygon points={MAIN_HEX} fill="url(#metalFill)" stroke="url(#goldLine)" strokeWidth={1.2} />
        <Polygon points={INNER_HEX} fill="none" stroke={COLORS.gold} strokeWidth={0.58} strokeOpacity={0.72} strokeDasharray="2,2" />
        {DIAMONDS.map((pts, i) => (
          <Polygon
            key={i}
            points={pts}
            fill={i < 4 ? COLORS.goldBright : COLORS.gold}
            fillOpacity={i < 4 ? 0.92 : 0.62}
          />
        ))}
        <Circle cx={CX} cy={CY} r={28} fill="none" stroke={COLORS.gold} strokeWidth={0.34} strokeDasharray="1,5" strokeOpacity={0.48} />
        <Line x1={40} y1={40} x2={40} y2={11} stroke={COLORS.goldBright} strokeWidth={1} strokeOpacity={0.7} strokeLinecap="round" />
        <Circle cx={40} cy={11} r={1.6} fill={COLORS.goldBright} fillOpacity={0.95} />
        <Circle cx={CX} cy={CY} r={2.6} fill={COLORS.goldBright} />
        <SvgText x={27} y={45} fontSize={16} fontWeight="bold" fontFamily="Georgia" fill="url(#gradB)" stroke="url(#goldLine)" strokeWidth={0.32}>
          B
        </SvgText>
        <SvgText x={39} y={45} fontSize={16} fontWeight="bold" fontFamily="Georgia" fill="url(#gradS)" stroke="url(#goldLine)" strokeWidth={0.32}>
          S
        </SvgText>
      </G>
    </Svg>
  );
}
