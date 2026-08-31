// 文件说明：实现监控展示的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  AlertTriangle,
  BellRing,
  Camera,
  Clock3,
  Info,
  RefreshCw,
  Timer,
  Users,
  Video,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { getAiVisionCameraKey, type AiVisionCamera, type AiVisionHumanDwellStatus } from '@/lib/aivision'
import type { OverlayPoint } from '../AiVisionMonitor.overlay'
import type { HumanDwellMonitorEvent } from './monitorState'

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
 * 功能：转换或规范化 `formatClock` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（string | null）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Date`、`isNaN`、`getTime`、`toLocaleTimeString`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function formatClock(value: string | null) {
  if (!value) return '--'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '--' : parsed.toLocaleTimeString('zh-CN', { hour12: false })
}

export type HumanDwellMonitorViewProps = {
  cameras: AiVisionCamera[]
  selectedCamera: string
  selectedCameraInfo?: AiVisionCamera
  loading: boolean
  message: string
  frameConnected: boolean
  frameContent: ReactNode
  featureValue: Record<string, unknown> | null
  status: AiVisionHumanDwellStatus | null
  events: HumanDwellMonitorEvent[]
  todayAlarmCount: number
  latestAlarmAt: string | null
  roiPolygons: OverlayPoint[][]
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
 * 功能：渲染 `HumanDwellMonitorView` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（HumanDwellMonitorViewProps）：React 组件属性对象；解构字段包括 cameras, selectedCamera, selectedCameraInfo, loading, message,
 *     frameConnected, frameContent, featureValue
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`String`、`Boolean`、`round`、`Number`、`isFinite`、`getAiVisionCameraKey`、`Date`、`getFullYear`、`getMonth`、`padStart` 等共 44
 *          个调用。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function HumanDwellMonitorView({
  cameras,
  selectedCamera,
  selectedCameraInfo,
  loading,
  message,
  frameConnected,
  frameContent,
  featureValue,
  status,
  events,
  todayAlarmCount,
  latestAlarmAt,
  roiPolygons,
  imageSize,
  onSelectCamera,
  onRefreshCameras,
}: HumanDwellMonitorViewProps) {
  const count = status?.count ?? null
  const countText = count === null ? '--' : String(count)
  const alarm = Boolean(status?.alarm)
  const runtimeThreshold = status?.threshold_seconds ?? null
  const runtimeThresholdText = runtimeThreshold === null ? '--' : String(Math.round(runtimeThreshold))
  const configuredThreshold = Number(featureValue?.MAX_TIME ?? 10)
  const configuredThresholdText = Number.isFinite(configuredThreshold) ? Math.round(configuredThreshold) : 10
  const cameraKey = selectedCameraInfo ? getAiVisionCameraKey(selectedCameraInfo) : selectedCamera
  const cameraName = selectedCameraInfo?.name || '未选择摄像头'
  const fps = selectedCameraInfo?.fps
  const now = new Date()
  const timestamp = `${now.getFullYear()}年${String(now.getMonth() + 1).padStart(2, '0')}月${String(now.getDate()).padStart(2, '0')}日 ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`

  return (
    <div className="space-y-5">
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="摄像头状态" value={frameConnected ? '在线' : '离线'} detail={frameConnected ? `${cameraKey || 'cam'} · 实时画面已连接` : '等待实时画面'} icon={Video} tone={frameConnected ? 'emerald' : 'rose'} ping={frameConnected} />
        <StatCard label="区域当前人数" value={`${countText} 人`} detail="蓝色区域内实时统计" icon={Users} tone={alarm ? 'rose' : count !== null && count > 0 ? 'indigo' : 'slate'} />
        <StatCard label="逗留阈值" value={runtimeThreshold === null ? '--' : `${runtimeThresholdText} 秒`} detail="超时自动触发告警" icon={Timer} tone="amber" />
        <StatCard label="今日逗留告警次数" value={`${todayAlarmCount} 次`} detail={todayAlarmCount ? `最近一次 ${formatClock(latestAlarmAt)}` : '今日暂无逗留告警'} icon={BellRing} tone={todayAlarmCount ? 'rose' : 'emerald'} />
      </section>

      <ResizableMonitorLayout id="human-dwell">
        <div className="space-y-5">
          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300"><Camera className="h-4 w-4" /></span>监控对象</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-5 pb-5">
              <div className="space-y-2">
                <Label htmlFor="human-dwell-monitor-camera" className="text-xs text-slate-500">摄像头</Label>
                <Select value={selectedCamera} onValueChange={onSelectCamera} disabled={loading || cameras.length === 0}>
                  <SelectTrigger id="human-dwell-monitor-camera" className="w-full rounded-xl border-slate-200 bg-slate-50/60 px-3.5 py-2.5 focus:border-[#1B3FA0] focus:ring-2 focus:ring-[#1B3FA0]/15 dark:border-slate-700 dark:bg-slate-950/60 dark:text-slate-200"><SelectValue placeholder={loading ? '正在读取摄像头' : '选择摄像头'} /></SelectTrigger>
                  <SelectContent>{cameras.map((camera) => { const key = getAiVisionCameraKey(camera); return <SelectItem key={key} value={key}>{camera.name}</SelectItem> })}</SelectContent>
                </Select>
              </div>
              <Button type="button" variant="outline" className="w-full gap-2 rounded-xl border-slate-200 text-slate-600 active:[&>svg]:animate-spin dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300" onClick={onRefreshCameras} disabled={loading}><RefreshCw className="h-4 w-4" />{loading ? '读取中' : '刷新状态'}</Button>
            </CardContent>
          </Card>

          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300"><Info className="h-4 w-4" /></span>判定说明</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-5 pb-5 text-sm">
              <div className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">监测区域</span><span className="text-slate-700">蓝色区域（loitering_roi）</span></div>
              <div className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">判定规则</span><span className="text-slate-700">人员进入区域并停留超过 {configuredThresholdText} 秒</span></div>
              <div className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">告警方式</span><span className="text-slate-700">平台实时推送 + 报警记录入库</span></div>
            </CardContent>
          </Card>

          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center justify-between text-base font-bold text-slate-950 dark:text-slate-100"><span>实时事件</span><Activity className="h-4 w-4 text-slate-300 dark:text-slate-600" /></CardTitle></CardHeader>
            <CardContent className="px-5 pb-5">
              {events.length ? <div className="relative space-y-4 pl-5 before:absolute before:bottom-1 before:left-[5px] before:top-1 before:w-px before:bg-slate-200">{events.map((event) => <div key={event.id} className="relative"><span className={cn('absolute -left-5 top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white', event.tone === 'danger' ? 'bg-rose-500' : 'bg-slate-300')} /><p className={cn('text-sm font-medium', event.tone === 'danger' ? 'text-rose-600' : 'text-slate-600')}>{event.label}</p><p className="mt-1 font-mono text-[11px] text-slate-400">{formatClock(event.occurredAt)}</p></div>)}</div> : <p className="text-sm text-slate-400">等待区域逗留事件</p>}
            </CardContent>
          </Card>
        </div>

        <Card className={cn(CARD_CLASS, 'overflow-hidden lg:col-span-2')}>
          <CardHeader className="border-b border-slate-100 p-4 dark:border-slate-800 sm:px-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#132C72] text-white dark:bg-blue-700"><Video className="h-5 w-5" /></span><div className="min-w-0"><CardTitle className="truncate text-base font-bold text-slate-950 dark:text-slate-100">人员违规逗留检测监控</CardTitle><p className="mt-0.5 truncate text-xs text-slate-400">{cameraKey || 'cam'} · {cameraName}</p></div></div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={cn('rounded-full border-0 px-2.5 py-1 shadow-none', alarm ? 'bg-rose-50 text-rose-600' : count !== null && count > 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-500')}>区域 {countText} 人</Badge>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 font-mono text-xs text-slate-500">FPS {fps?.toFixed(1) ?? '--'}</span>
                <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold', frameConnected ? 'bg-rose-50 text-rose-600' : 'bg-slate-100 text-slate-500')}>{frameConnected && <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-70" /><span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" /></span>}{frameConnected ? 'LIVE' : '离线'}</span>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="relative overflow-hidden bg-slate-950">
              <div className="relative aspect-video w-full saturate-[.85]">{frameContent}</div>
              {frameConnected && roiPolygons.length > 0 && <svg viewBox={`0 0 ${imageSize.width} ${imageSize.height}`} preserveAspectRatio="xMidYMid meet" className="pointer-events-none absolute inset-0 h-full w-full">{roiPolygons.map((polygon, index) => { const anchor = polygon[0]; return <g key={`loitering-roi-${index}`}><polygon points={polygon.map((point) => `${point.x},${point.y}`).join(' ')} fill="rgba(34,211,238,0.10)" stroke="#22D3EE" strokeWidth="4" />{anchor && <><rect x={anchor.x} y={Math.max(0, anchor.y - 24)} width="92" height="22" rx="5" fill="rgba(34,211,238,0.90)" /><text x={anchor.x + 7} y={Math.max(15, anchor.y - 9)} fill="#020617" fontSize="12" fontWeight="700">loitering_roi</text></>}</g> })}</svg>}
              <div className="pointer-events-none absolute left-3 right-3 top-3 flex flex-wrap gap-2"><GlassPill><span className="relative flex h-1.5 w-1.5"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" /><span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" /></span>实时检测</GlassPill><GlassPill danger={!frameConnected}><span className={cn('h-1.5 w-1.5 rounded-full', frameConnected ? 'bg-emerald-400' : 'bg-rose-300')} />{cameraKey || 'cam'} · {frameConnected ? '在线' : '离线'}</GlassPill><GlassPill danger={alarm}>区域人数 {countText}</GlassPill>{alarm && <GlassPill danger><AlertTriangle className="h-3.5 w-3.5" />逗留超时告警</GlassPill>}</div>
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/30 via-transparent to-black/15" />
              <div className="pointer-events-none absolute bottom-3 left-4 font-mono font-semibold text-white/95 [text-shadow:0_1px_4px_rgba(0,0,0,0.85)]"><Clock3 className="mr-1.5 inline h-4 w-4" />{timestamp}</div>
              <span className="pointer-events-none absolute bottom-3 right-4 rounded-full bg-black/45 px-2 py-1 font-mono text-[10px] text-white backdrop-blur-sm">实时画面</span>
            </div>
            <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-400 dark:border-slate-800">{message}</div>
          </CardContent>
        </Card>
      </ResizableMonitorLayout>
    </div>
  )
}
