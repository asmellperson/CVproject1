import { useId } from 'react'
import { regionDirection, type PreviewRegion } from './previewRegions'

export function CameraRegionsOverlay({ regions, width, height }: { regions: PreviewRegion[]; width: number; height: number }) {
  const marker = useId().replaceAll(':', '')
  if (!width || !height || !regions.length) return null
  return <svg aria-label="检测区域" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet"
    className="pointer-events-none absolute inset-0 h-full w-full overflow-hidden">
    <defs><marker id={marker} markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="none" stroke="#fbbf24" strokeWidth="1.4" /></marker></defs>
    {regions.map((region) => <g key={region.label}>
      {region.line
        ? <polyline points={region.points.map(([x, y]) => `${x * width},${y * height}`).join(' ')} fill="none" stroke="#22d3ee" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        : <polygon points={region.points.map(([x, y]) => `${x * width},${y * height}`).join(' ')} fill="#22d3ee" fillOpacity="0.04" stroke="#22d3ee" strokeWidth="2" vectorEffect="non-scaling-stroke" />}
      {region.directions?.map((direction) => {
        const arrow = regionDirection(region.points, width, height, direction)
        return arrow && <line key={direction} {...arrow} stroke="#fbbf24" strokeWidth="2" vectorEffect="non-scaling-stroke" markerEnd={`url(#${marker})`} />
      })}
      <text x={Math.max(4, Math.min(...region.points.map(([x]) => x * width)) + 5)}
        y={Math.max(20, Math.min(...region.points.map(([, y]) => y * height)) - 7)}
        fontSize={Math.max(14, width / 75)} fill="#67e8f9" stroke="#0f172a" strokeWidth="3" paintOrder="stroke">{region.label}</text>
    </g>)}
  </svg>
}
