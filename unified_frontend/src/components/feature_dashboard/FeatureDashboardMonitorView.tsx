// 文件说明：实现监控展示的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  BellRing,
  Camera,
  Clock3,
  Info,
  RefreshCw,
  Settings2,
  Video,
} from 'lucide-react'
import type { ReactNode } from 'react'
import type { AlarmEvent } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { getAiVisionCameraKey, type AiVisionCamera } from '@/lib/aivision'
import type { OverlayPoint } from '../AiVisionMonitor.overlay'
import {
  FEATURE_DASHBOARD_PROFILES,
  isFeatureOverlayConfigured,
  type FeatureDashboardKey,
} from './monitorState'

const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'

/**
 * 功能：渲染 `StatCard` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 label, value, detail, icon, Icon, tone, ping, false
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`Icon`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function StatCard({
  label,
  value,
  detail,
  icon: Icon,
  tone,
  ping = false,
}: {
  label: string
  value: string
  detail: string
  icon: LucideIcon
  tone: 'emerald' | 'indigo' | 'amber' | 'rose' | 'slate'
  ping?: boolean
}) {
  const tones = {
    emerald: 'bg-emerald-50 text-emerald-600',
    indigo: 'bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300',
    amber: 'bg-amber-50 text-amber-600',
    rose: 'bg-rose-50 text-rose-600',
    slate: 'bg-slate-100 text-slate-500',
  }

  return (
    <article className={cn(CARD_CLASS, 'relative p-4')}>
      <span className={cn('flex h-9 w-9 items-center justify-center rounded-xl', tones[tone])}>
        <Icon className="h-[18px] w-[18px]" />
      </span>
      {ping && (
        <span className="absolute right-4 top-4 flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
        </span>
      )}
      <p className="mt-4 text-xs font-medium text-slate-400">{label}</p>
      <p className="mt-1 text-[22px] font-bold leading-tight text-slate-950 dark:text-slate-100">{value}</p>
      <p className="mt-1.5 truncate text-xs text-slate-400" title={detail}>{detail}</p>
    </article>
  )
}

/**
 * 功能：渲染 `GlassPill` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 children, danger, false, children, ReactNode, danger, boolean
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function GlassPill({ children, danger = false }: { children: ReactNode; danger?: boolean }) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 rounded-full bg-black/45 px-2.5 py-1 text-xs font-medium text-white backdrop-blur-sm',
      danger && 'bg-rose-500/90',
    )}>
      {children}
    </span>
  )
}

/**
 * 功能：转换或规范化 `formatBusinessMetric` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（FeatureDashboardKey）：`feature` 对应的业务输入值
 *   - `value`（Record<string, unknown> | null）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/feature_dashboard/FeatureDashboardMonitorView.tsx` 的 `ruleRows`
 *         调用本符号；`unified_frontend/src/components/feature_dashboard/FeatureDashboardMonitorView.tsx` 的 `FeatureDashboardMonitorView`
 *         调用本符号
 *   - 内部调用：`Number`、`isFinite`、`toFixed`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function formatBusinessMetric(feature: FeatureDashboardKey, value: Record<string, unknown> | null) {
  if (feature === 'blocks') {
    const side = Number(value?.alarm_side)
    return side === 1 ? '线左侧' : side === -1 ? '线右侧' : '--'
  }
  if (feature === 'detect_face') {
    const threshold = Number(value?.FACE_SCORE_THR)
    return Number.isFinite(threshold) ? threshold.toFixed(2) : '--'
  }
  if (feature === 'detect_phone') {
    const seconds = Number(value?.MIN_CONFIRM_SECONDS)
    return Number.isFinite(seconds) ? `${seconds} 秒` : '--'
  }
  const seconds = Number(value?.first_alarm)
  return Number.isFinite(seconds) ? `${seconds} 秒` : '--'
}

/**
 * 功能：转换或规范化 `formatValue` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 *   - `suffix`（未显式标注）：`suffix` 对应的业务输入值；声明包含默认值 `''`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/feature_dashboard/FeatureDashboardMonitorView.tsx` 的 `ruleRows` 调用本符号
 *   - 内部调用：`isArray`、`stringify`、`String`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function formatValue(value: unknown, suffix = '') {
  if (typeof value === 'boolean') return value ? '已启用' : '未启用'
  if (value === null || value === undefined || value === '') return '--'
  if (Array.isArray(value)) return JSON.stringify(value)
  return `${String(value)}${suffix}`
}

/**
 * 功能：实现 `ruleRows` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（FeatureDashboardKey）：`feature` 对应的业务输入值
 *   - `value`（Record<string, unknown> | null）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/feature_dashboard/FeatureDashboardMonitorView.tsx` 的 `FeatureDashboardMonitorView` 调用本符号
 *   - 内部调用：`formatBusinessMetric`、`formatValue`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function ruleRows(feature: FeatureDashboardKey, value: Record<string, unknown> | null) {
  if (feature === 'blocks') {
    return [
      ['监测区域', '红色警戒线（alarm_line）'],
      ['判定规则', `目标跨越警戒线进入${formatBusinessMetric(feature, value)}`],
      ['检测阈值', formatValue(value?.threshold)],
    ]
  }
  if (feature === 'detect_face') {
    return [
      ['监测区域', '青色区域（face_roi）'],
      ['置信阈值', formatValue(value?.FACE_SCORE_THR)],
      ['角度阈值', formatValue(value?.YAW_THRESHOLD)],
    ]
  }
  if (feature === 'detect_phone') {
    return [
      ['监测区域', '青色区域（phone_roi）'],
      ['手机置信度', formatValue(value?.CONF_THRESHOLD)],
      ['人体关联', formatValue(value?.REQUIRE_PERSON_ASSOCIATION)],
    ]
  }
  return [
    ['监测区域', '青色区域（door_roi）'],
    ['变化阈值', formatValue(value?.threshold)],
    ['首次告警', formatValue(value?.first_alarm, ' 秒')],
  ]
}

/**
 * 功能：转换或规范化 `formatClock` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（string | undefined）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Date`、`isNaN`、`getTime`、`toLocaleTimeString`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function formatClock(value: string | undefined) {
  if (!value) return '--'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '--' : parsed.toLocaleTimeString('zh-CN', { hour12: false })
}

/**
 * 功能：实现 `browserTimestamp` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/feature_dashboard/FeatureDashboardMonitorView.tsx` 的 `FeatureDashboardMonitorView` 调用本符号
 *   - 内部调用：`Date`、`getFullYear`、`String`、`getMonth`、`padStart`、`getDate`、`getHours`、`getMinutes`、`getSeconds`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function browserTimestamp() {
  const now = new Date()
  return `${now.getFullYear()}年${String(now.getMonth() + 1).padStart(2, '0')}月${String(now.getDate()).padStart(2, '0')}日 ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`
}

export type FeatureDashboardMonitorViewProps = {
  feature: FeatureDashboardKey
  cameras: AiVisionCamera[]
  selectedCamera: string
  selectedCameraInfo?: AiVisionCamera
  loading: boolean
  message: string
  frameConnected: boolean
  frameContent: ReactNode
  featureValue: Record<string, unknown> | null
  alarms: AlarmEvent[]
  todayAlarmCount: number
  roiPolygons: OverlayPoint[][]
  alarmLines: [OverlayPoint, OverlayPoint][]
  imageSize: { width: number; height: number }
  /**
   * 功能：处理 `onSelectCamera` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onSelectCamera: (cameraKey: string) => void
  /**
   * 功能：处理 `onRefreshCameras` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onRefreshCameras: () => void
}

/**
 * 功能：渲染 `FeatureDashboardMonitorView` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（FeatureDashboardMonitorViewProps）：React 组件属性对象；解构字段包括 feature, cameras, selectedCamera, selectedCameraInfo, loading,
 *     message, frameConnected, frameContent
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`getAiVisionCameraKey`、`ruleRows`、`isFeatureOverlayConfigured`、`return`、`formatBusinessMetric`、`formatClock`、`map`、`cn`、`toFixed`、`join`
 *          等共 35 个调用。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function FeatureDashboardMonitorView({
  feature,
  cameras,
  selectedCamera,
  selectedCameraInfo,
  loading,
  message,
  frameConnected,
  frameContent,
  featureValue,
  alarms,
  todayAlarmCount,
  roiPolygons,
  alarmLines,
  imageSize,
  onSelectCamera,
  onRefreshCameras,
}: FeatureDashboardMonitorViewProps) {
  const profile = FEATURE_DASHBOARD_PROFILES[feature]
  const cameraKey = selectedCameraInfo ? getAiVisionCameraKey(selectedCameraInfo) : selectedCamera
  const cameraName = selectedCameraInfo?.name || '未选择摄像头'
  const fps = selectedCameraInfo?.fps
  const rows = ruleRows(feature, featureValue)
  const overlayConfigured = isFeatureOverlayConfigured(feature, roiPolygons.length, alarmLines.length)

  return (
    <div className="space-y-5">
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="摄像头状态" value={frameConnected ? '在线' : '离线'} detail={frameConnected ? `${cameraKey || 'cam'} · 实时画面已连接` : '等待实时画面'} icon={Video} tone={frameConnected ? 'emerald' : 'rose'} ping={frameConnected} />
        <StatCard label="启用摄像头" value={`${cameras.length} 路`} detail={`已启用${profile.videoTitle}`} icon={Camera} tone="indigo" />
        <StatCard label={profile.metricLabel} value={formatBusinessMetric(feature, featureValue)} detail="读取当前摄像头现有配置" icon={Settings2} tone="amber" />
        <StatCard label={`今日${profile.eventLabel}`} value={`${todayAlarmCount} 次`} detail={todayAlarmCount ? `最近一次 ${formatClock(alarms[0]?.created_at)}` : '今日暂无报警'} icon={BellRing} tone={todayAlarmCount ? 'rose' : 'emerald'} />
      </section>

      <ResizableMonitorLayout id={`feature-dashboard-${feature}`}>
        <div className="space-y-5">
          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300"><Camera className="h-4 w-4" /></span>监控对象</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-5 pb-5">
              <div className="space-y-2">
                <Label htmlFor={`${feature}-dashboard-camera`} className="text-xs text-slate-500">摄像头</Label>
                <Select value={selectedCamera} onValueChange={onSelectCamera} disabled={loading || cameras.length === 0}>
                  <SelectTrigger id={`${feature}-dashboard-camera`} className="w-full rounded-xl border-slate-200 bg-slate-50/60 px-3.5 py-2.5 focus:border-[#1B3FA0] focus:ring-2 focus:ring-[#1B3FA0]/15 dark:border-slate-700 dark:bg-slate-950/60 dark:text-slate-200"><SelectValue placeholder={loading ? '正在读取摄像头' : '选择摄像头'} /></SelectTrigger>
                  <SelectContent>{cameras.map((camera) => { const key = getAiVisionCameraKey(camera); return <SelectItem key={key} value={key}>{camera.name}</SelectItem> })}</SelectContent>
                </Select>
              </div>
              <Button type="button" variant="outline" className="w-full gap-2 rounded-xl border-slate-200 text-slate-600 active:[&>svg]:animate-spin dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300" onClick={onRefreshCameras} disabled={loading}><RefreshCw className="h-4 w-4" />{loading ? '读取中' : '刷新状态'}</Button>
            </CardContent>
          </Card>

          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300"><Info className="h-4 w-4" /></span>判定说明</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-5 pb-5 text-sm">{rows.map(([label, value]) => <div key={label} className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">{label}</span><span className="break-words text-slate-700 dark:text-slate-300">{value}</span></div>)}</CardContent>
          </Card>

          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center justify-between text-base font-bold text-slate-950 dark:text-slate-100"><span>最近报警</span><Activity className="h-4 w-4 text-slate-300 dark:text-slate-600" /></CardTitle></CardHeader>
            <CardContent className="px-5 pb-5">
              {alarms.length ? <div className="relative space-y-4 pl-5 before:absolute before:bottom-1 before:left-[5px] before:top-1 before:w-px before:bg-slate-200">{alarms.map((alarm) => <div key={alarm.id} className="relative"><span className="absolute -left-5 top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-rose-500" /><p className="text-sm font-medium text-rose-600">{alarm.event_label || profile.eventLabel}</p><p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{alarm.reason || cameraName}</p><p className="mt-1 font-mono text-[11px] text-slate-400">{formatClock(alarm.created_at)}</p></div>)}</div> : <p className="text-sm text-slate-400">当前摄像头今日暂无报警</p>}
            </CardContent>
          </Card>
        </div>

        <Card className={cn(CARD_CLASS, 'overflow-hidden lg:col-span-2')}>
          <CardHeader className="border-b border-slate-100 p-4 dark:border-slate-800 sm:px-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#132C72] text-white dark:bg-blue-700"><Video className="h-5 w-5" /></span><div className="min-w-0"><CardTitle className="truncate text-base font-bold text-slate-950 dark:text-slate-100">{profile.videoTitle}</CardTitle><p className="mt-0.5 truncate text-xs text-slate-400">{cameraKey || 'cam'} · {cameraName}</p></div></div>
              <div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-slate-100 px-2.5 py-1 font-mono text-xs text-slate-500">FPS {fps?.toFixed(1) ?? '--'}</span><Badge className={cn('rounded-full border-0 px-2.5 py-1 shadow-none', frameConnected ? 'bg-rose-50 text-rose-600' : 'bg-slate-100 text-slate-500')}>{frameConnected && <span className="relative mr-1.5 flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-70" /><span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" /></span>}{frameConnected ? 'LIVE' : '离线'}</Badge></div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="relative overflow-hidden bg-slate-950">
              <div className="relative aspect-video w-full saturate-[.85]">{frameContent}</div>
              {frameConnected && (roiPolygons.length > 0 || alarmLines.length > 0) && <svg viewBox={`0 0 ${imageSize.width} ${imageSize.height}`} preserveAspectRatio="xMidYMid meet" className="pointer-events-none absolute inset-0 h-full w-full">
                {roiPolygons.map((polygon, index) => { const anchor = polygon[0]; return <g key={`feature-roi-${index}`}><polygon points={polygon.map((point) => `${point.x},${point.y}`).join(' ')} fill="rgba(34,211,238,0.10)" stroke="#22D3EE" strokeWidth="4" />{anchor && <><rect x={anchor.x} y={Math.max(0, anchor.y - 24)} width="82" height="22" rx="5" fill="rgba(34,211,238,0.90)" /><text x={anchor.x + 7} y={Math.max(15, anchor.y - 9)} fill="#020617" fontSize="12" fontWeight="700">{profile.overlayLabel}</text></>}</g> })}
                {alarmLines.map(([start, end], index) => <g key={`feature-line-${index}`}><line x1={start.x} y1={start.y} x2={end.x} y2={end.y} stroke="rgb(239, 68, 68)" strokeWidth="5" strokeLinecap="round" /><rect x={start.x} y={Math.max(0, start.y - 24)} width="78" height="22" rx="5" fill="rgba(244,63,94,0.90)" /><text x={start.x + 7} y={Math.max(15, start.y - 9)} fill="white" fontSize="12" fontWeight="700">alarm_line</text></g>)}
              </svg>}
              <div className="pointer-events-none absolute left-3 right-3 top-3 flex flex-wrap gap-2"><GlassPill danger={!frameConnected}><span className="relative flex h-1.5 w-1.5"><span className={cn('absolute inline-flex h-full w-full animate-ping rounded-full opacity-70', frameConnected ? 'bg-emerald-400' : 'bg-rose-300')} /><span className={cn('relative inline-flex h-1.5 w-1.5 rounded-full', frameConnected ? 'bg-emerald-400' : 'bg-rose-300')} /></span>{frameConnected ? '实时检测' : '检测离线'}</GlassPill><GlassPill danger={!frameConnected}><span className={cn('h-1.5 w-1.5 rounded-full', frameConnected ? 'bg-emerald-400' : 'bg-rose-300')} />{cameraKey || 'cam'} · {frameConnected ? '在线' : '离线'}</GlassPill><GlassPill danger={!overlayConfigured}>{profile.statusSubject}{overlayConfigured ? '已配置' : '未配置'}</GlassPill></div>
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/30 via-transparent to-black/15" />
              <div className="pointer-events-none absolute bottom-3 left-4 font-mono font-semibold text-white/95 [text-shadow:0_1px_4px_rgba(0,0,0,0.85)]"><Clock3 className="mr-1.5 inline h-4 w-4" />{browserTimestamp()}</div>
              <span className="pointer-events-none absolute bottom-3 right-4 rounded-full bg-black/45 px-2 py-1 font-mono text-[10px] text-white backdrop-blur-sm">实时画面</span>
            </div>
            <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-400 dark:border-slate-800">{message}</div>
          </CardContent>
        </Card>
      </ResizableMonitorLayout>
    </div>
  )
}
