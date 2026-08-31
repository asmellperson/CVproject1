// 文件说明：实现`StatisticsSection` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Activity, AlertTriangle, Calendar, Camera, Clock, TrendingUp } from 'lucide-react'
import { getStatistics, type AlarmEvent } from '@/lib/api'
import { useAuth } from '@/auth/useAuth'
import { getAccessibleAlarmEventTypes } from '@/auth/permissions'

type TypeBucket = {
  event_type: string
  name: string
  value: number
  color: string
}

type CameraBucket = {
  camera_no: string
  name: string
  value: number
}

type TrendRow = {
  day?: string
  time?: string
  total: number
  blocks?: number
  detect_door?: number
  detect_phone?: number
  detect_human?: number
  detect_human_haoda?: number
  detect_face?: number
  detect_logistics_single_person?: number
  detect_logistics_single_person_electronics_electrician?: number
  detect_logistics_single_person_electrical_components?: number
  detect_logistics_single_person_precious_metal_recycling?: number
  guard_absent?: number
  guard_phone_use?: number
  guard_prone_sleep?: number
  security_vlm_non_compliant?: number
  security_vlm_error?: number
}

type AiVisionStatistics = {
  summary: {
    total: number
    today: number
    week: number
    avg_per_day: number
    active_cameras: number
    peak_hour: string
  }
  by_type: TypeBucket[]
  by_camera: CameraBucket[]
  daily: TrendRow[]
  hourly: TrendRow[]
  recent: AlarmEvent[]
}

const EMPTY: AiVisionStatistics = {
  summary: { total: 0, today: 0, week: 0, avg_per_day: 0, active_cameras: 0, peak_hour: '-' },
  by_type: [],
  by_camera: [],
  daily: [],
  hourly: [],
  recent: [],
}

const TYPE_META: TypeBucket[] = [
  { event_type: 'blocks', name: '区域入侵', value: 0, color: '#ef4444' },
  { event_type: 'detect_door', name: '大门开关', value: 0, color: '#f59e0b' },
  { event_type: 'detect_face', name: '人脸检测', value: 0, color: '#8b5cf6' },
  { event_type: 'detect_phone', name: '手机检测', value: 0, color: '#f97316' },
  { event_type: 'detect_human', name: '人员违规逗留检测', value: 0, color: '#2563eb' },
  { event_type: 'detect_human_haoda', name: '人员违规逗留检测（皓达公司）', value: 0, color: '#1d4ed8' },
  { event_type: 'detect_logistics_single_person', name: '物流通道单人', value: 0, color: '#0f766e' },
  { event_type: 'detect_logistics_single_person_electronics_electrician', name: '物流通道单人（电子电工）', value: 0, color: '#0f766e' },
  { event_type: 'detect_logistics_single_person_electrical_components', name: '物流通道单人（电气部件）', value: 0, color: '#0f766e' },
  { event_type: 'detect_logistics_single_person_precious_metal_recycling', name: '物流通道单人（伟达公司）', value: 0, color: '#0f766e' },
  { event_type: 'guard_absent', name: '保安离岗', value: 0, color: '#dc2626' },
  { event_type: 'guard_phone_use', name: '保安玩手机', value: 0, color: '#ea580c' },
  { event_type: 'guard_prone_sleep', name: '保安趴睡', value: 0, color: '#ca8a04' },
  { event_type: 'security_vlm_non_compliant', name: '安检流程不规范', value: 0, color: '#0891b2' },
  { event_type: 'security_vlm_error', name: '安检判定错误', value: 0, color: '#d97706' },
]

/**
 * 功能：转换或规范化 `toRecord` 对应的`StatisticsSection` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 * 返回：Record<string, unknown> | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/StatisticsSection.tsx` 的 `normalizeTrendRow`
 *         调用本符号；`unified_frontend/src/sections/StatisticsSection.tsx` 的 `normalizeStatistics` 调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function toRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object') return null
  return value as Record<string, unknown>
}

/**
 * 功能：转换或规范化 `toNumber` 对应的`StatisticsSection` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 * 返回：number；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Number`、`isFinite`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function toNumber(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

/**
 * 功能：转换或规范化 `toString` 对应的`StatisticsSection` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 *   - `fallback`（未显式标注）：`fallback` 对应的业务输入值；声明包含默认值 `''`
 * 返回：string；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/StatisticsSection.tsx` 的 `normalizeTrendRow`
 *         调用本符号；`unified_frontend/src/sections/StatisticsSection.tsx` 的 `normalizeStatistics`
 *         调用本符号；`unified_frontend/tests/feature-monitor-dashboards.test.mjs` 的 `importTypeScript`
 *         调用本符号；`unified_frontend/tests/home-camera-counts.test.mjs` 的 `importTypeScript` 调用本符号；另有 6 处静态调用
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function toString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

/**
 * 功能：转换或规范化 `normalizeTrendRow` 对应的`StatisticsSection` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 *   - `labelKey`（'day' | 'time'）：`labelKey` 对应的业务输入值
 * 返回：TrendRow；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/StatisticsSection.tsx` 的 `normalizeStatistics` 调用本符号
 *   - 内部调用：`toRecord`、`toString`、`toNumber`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function normalizeTrendRow(value: unknown, labelKey: 'day' | 'time'): TrendRow {
  const row = toRecord(value)
  return {
    [labelKey]: toString(row?.[labelKey]),
    total: toNumber(row?.total),
    blocks: toNumber(row?.blocks),
    detect_door: toNumber(row?.detect_door),
    detect_face: toNumber(row?.detect_face),
    detect_phone: toNumber(row?.detect_phone),
    detect_human: toNumber(row?.detect_human),
    detect_human_haoda: toNumber(row?.detect_human_haoda),
    detect_logistics_single_person: toNumber(row?.detect_logistics_single_person),
    detect_logistics_single_person_electronics_electrician: toNumber(row?.detect_logistics_single_person_electronics_electrician),
    detect_logistics_single_person_electrical_components: toNumber(row?.detect_logistics_single_person_electrical_components),
    detect_logistics_single_person_precious_metal_recycling: toNumber(row?.detect_logistics_single_person_precious_metal_recycling),
    guard_absent: toNumber(row?.guard_absent),
    guard_phone_use: toNumber(row?.guard_phone_use),
    guard_prone_sleep: toNumber(row?.guard_prone_sleep),
    security_vlm_non_compliant: toNumber(row?.security_vlm_non_compliant),
    security_vlm_error: toNumber(row?.security_vlm_error),
  }
}

/**
 * 功能：转换或规范化 `normalizeStatistics` 对应的`StatisticsSection` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `data`（unknown）：待处理的数据
 * 返回：AiVisionStatistics；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/StatisticsSection.tsx` 的 `StatisticsSection` 调用本符号
 *   - 内部调用：`toRecord`、`isArray`、`toNumber`、`toString`、`map`、`normalizeTrendRow`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function normalizeStatistics(data: unknown): AiVisionStatistics {
  const root = toRecord(data)
  const summary = toRecord(root?.summary)
  const byType = Array.isArray(root?.by_type) ? root.by_type : []
  const byCamera = Array.isArray(root?.by_camera) ? root.by_camera : []
  const daily = Array.isArray(root?.daily) ? root.daily : []
  const hourly = Array.isArray(root?.hourly) ? root.hourly : []
  const recent = Array.isArray(root?.recent) ? root.recent : []

  return {
    summary: {
      total: toNumber(summary?.total),
      today: toNumber(summary?.today),
      week: toNumber(summary?.week),
      avg_per_day: toNumber(summary?.avg_per_day),
      active_cameras: toNumber(summary?.active_cameras),
      peak_hour: toString(summary?.peak_hour, '-'),
    },
    by_type: byType.map((item) => {
      const row = toRecord(item)
      return {
        event_type: toString(row?.event_type),
        name: toString(row?.name, '未知报警'),
        value: toNumber(row?.value),
        color: toString(row?.color, '#64748b'),
      }
    }),
    by_camera: byCamera.map((item) => {
      const row = toRecord(item)
      return {
        camera_no: toString(row?.camera_no),
        name: toString(row?.name, '未知摄像头'),
        value: toNumber(row?.value),
      }
    }),
    daily: daily.map((item) => normalizeTrendRow(item, 'day')),
    hourly: hourly.map((item) => normalizeTrendRow(item, 'time')),
    recent: recent as AlarmEvent[],
  }
}

/**
 * 功能：转换或规范化 `formatTime` 对应的`StatisticsSection` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `timestamp?`（string）：事件或帧对应的时间戳
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/StatisticsSection.tsx` 的 `StatisticsSection`
 *         调用本符号；`unified_frontend/src/sections/AlarmsSection.tsx` 的 `AlarmsSection` 调用本符号
 *   - 内部调用：`Date`、`toLocaleString`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function formatTime(timestamp?: string) {
  return timestamp ? new Date(timestamp).toLocaleString('zh-CN') : '-'
}

/**
 * 功能：渲染 `StatisticsSection` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：无。
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useAuth`、`useState`、`useMemo`、`getAccessibleAlarmEventTypes`、`Set`、`useEffect`、`async`、`getStatistics`、`setStats`、`normalizeStatistics`
 *          等共 49 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
export function StatisticsSection() {
  const { user } = useAuth()
  const [stats, setStats] = useState<AiVisionStatistics>(EMPTY)
  const accessibleAlarmEventTypes = useMemo(() => getAccessibleAlarmEventTypes(user), [user])
  const allowedAlarmTypes = useMemo(
    () => (accessibleAlarmEventTypes ? new Set(accessibleAlarmEventTypes) : null),
    [accessibleAlarmEventTypes],
  )

  useEffect(() => {
    let mounted = true

    const load = async () => {
      const next = await getStatistics(accessibleAlarmEventTypes)
      if (mounted) setStats(normalizeStatistics(next))
    }

    load().catch((err) => {
      console.error('加载统计失败:', err)
    })

    const timer = window.setInterval(() => {
      load().catch((err) => {
        console.error('轮询统计失败:', err)
      })
    }, 30000)

    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [accessibleAlarmEventTypes])

  const typeMetaRows = useMemo(
    () => TYPE_META.filter((item) => !allowedAlarmTypes || allowedAlarmTypes.has(item.event_type)),
    [allowedAlarmTypes],
  )

  const typeRows = useMemo(() => {
    const live = new Map(stats.by_type.map((item) => [item.event_type, item]))
    return typeMetaRows.map((item) => live.get(item.event_type) || item)
  }, [stats.by_type, typeMetaRows])

  const topType = typeRows.reduce(
    (best, item) => (item.value > best.value ? item : best),
    typeMetaRows[0] || { event_type: 'none', name: '-', value: 0, color: '#64748b' },
  )

  return (
    <div className="space-y-6 text-slate-950 dark:text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100">统计聚合</h2>
          <p className="text-slate-500">报警趋势、类型分布与摄像头排行</p>
        </div>
        <Badge variant="outline" className="gap-2">
          <Calendar className="h-4 w-4" />
          最近7天
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
        <SummaryCard title="今日报警" value={stats.summary.today} sub="自然日" icon={<Clock className="h-6 w-6 text-blue-600" />} />
        <SummaryCard title="周期总数" value={stats.summary.total} sub="最近7天" icon={<AlertTriangle className="h-6 w-6 text-red-600" />} />
        <SummaryCard title="日均报警" value={stats.summary.avg_per_day} sub="次/天" icon={<TrendingUp className="h-6 w-6 text-emerald-600" />} />
        <SummaryCard title="活跃摄像头" value={stats.summary.active_cameras} sub="有报警" icon={<Camera className="h-6 w-6 text-violet-600" />} />
        <SummaryCard title="峰值时段" value={stats.summary.peak_hour} sub={topType.name} icon={<Activity className="h-6 w-6 text-orange-600" />} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle className="text-lg">报警趋势</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={330}>
              <AreaChart data={stats.daily}>
                <defs>
                  {typeMetaRows.map((item) => (
                    <linearGradient key={item.event_type} id={`fill-${item.event_type}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={item.color} stopOpacity={0.32} />
                      <stop offset="95%" stopColor={item.color} stopOpacity={0.04} />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="day" stroke="#64748b" />
                <YAxis stroke="#64748b" allowDecimals={false} />
                <Tooltip />
                {typeMetaRows.map((item) => (
                  <Area
                    key={item.event_type}
                    type="monotone"
                    dataKey={item.event_type}
                    name={item.name}
                    stackId="1"
                    stroke={item.color}
                    fill={`url(#fill-${item.event_type})`}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg">报警类型分布</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={330}>
              <PieChart>
                <Pie data={typeRows} cx="50%" cy="50%" innerRadius={72} outerRadius={118} dataKey="value" paddingAngle={4}>
                  {typeRows.map((entry) => (
                    <Cell key={entry.event_type} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div className="grid grid-cols-2 gap-3">
              {typeRows.map((item) => (
                <div key={item.event_type} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
                  <span className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                    {item.name}
                  </span>
                  <span className="font-semibold">{item.value}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle className="text-lg">24小时热度</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={290}>
              <BarChart data={stats.hourly}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="time" stroke="#64748b" interval={2} />
                <YAxis stroke="#64748b" allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="total" name="报警数" fill="#0f172a" radius={[5, 5, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg">摄像头排行</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {stats.by_camera.length === 0 ? (
              <div className="rounded-md border border-dashed p-6 text-center text-sm text-slate-500">暂无报警摄像头</div>
            ) : (
              stats.by_camera.map((camera, index) => {
                const max = Math.max(...stats.by_camera.map((item) => item.value), 1)
                return (
                  <div key={camera.camera_no || camera.name} className="space-y-2">
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="truncate font-medium text-slate-800 dark:text-slate-200">
                        {index + 1}. {camera.name}
                      </span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100">{camera.value}</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-100">
                      <div className="h-2 rounded-full bg-slate-900 dark:bg-blue-500" style={{ width: `${(camera.value / max) * 100}%` }} />
                    </div>
                  </div>
                )
              })
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">最近报警</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {stats.recent.length === 0 ? (
              <div className="col-span-full rounded-md border border-dashed p-6 text-center text-sm text-slate-500">暂无报警记录</div>
            ) : (
              stats.recent.map((alarm) => (
                <div key={alarm.id} className="rounded-md border bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <Badge variant="outline">{alarm.event_label || alarm.event_type}</Badge>
                    <span className="text-xs text-slate-400">#{alarm.id}</span>
                  </div>
                  <div className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{alarm.camera_name || alarm.camera_no || '-'}</div>
                  <div className="mt-1 text-xs text-slate-500">{formatTime(alarm.created_at)}</div>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * 功能：渲染 `SummaryCard` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 title, value, sub, icon, title, string, value, number
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`Card`、`CardContent`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
function SummaryCard({
  title,
  value,
  sub,
  icon,
}: {
  title: string
  value: number | string
  sub: string
  icon: React.ReactNode
}) {
  return (
    <Card className="dark:border-slate-800 dark:bg-slate-900">
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm text-slate-500">{title}</p>
            <div className="mt-1 flex items-baseline gap-2">
              <p className="truncate text-2xl font-bold text-slate-950 dark:text-slate-100">{value}</p>
              <span className="text-xs text-slate-400">{sub}</span>
            </div>
          </div>
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-slate-100">{icon}</div>
        </div>
      </CardContent>
    </Card>
  )
}

export default StatisticsSection
