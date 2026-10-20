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
import { Activity, AlertTriangle, Calendar, Clock, MapPin, TrendingUp } from 'lucide-react'
import { getStatistics, type AlarmEvent } from '@/lib/api'
import { useAuth } from '@/auth/useAuth'
import { getAccessibleAlarmEventTypes } from '@/auth/permissions'

type TypeBucket = {
  event_type: string
  name: string
  value: number
  color: string
}

type SubjectBucket = {
  subject_type: string
  subject_id: string
  subject_name: string
  value: number
}

type TrendRow = {
  day?: string
  time?: string
  total: number
  blocks?: number
  tailgating?: number
  detect_door?: number
  detect_phone?: number
  detect_human?: number
  detect_face?: number
  detect_logistics_single_person?: number
  guard_absent?: number
  guard_phone_use?: number
  guard_prone_sleep?: number
  guard_vehicle_inspection_missing?: number
  security_inspection?: number
}

type AiVisionStatistics = {
  summary: {
    total: number
    today: number
    avg_per_day: number
    active_subjects: number
    peak_hour: string
  }
  by_type: TypeBucket[]
  by_subject: SubjectBucket[]
  daily: TrendRow[]
  hourly: TrendRow[]
  recent: AlarmEvent[]
}

const EMPTY: AiVisionStatistics = {
  summary: { total: 0, today: 0, avg_per_day: 0, active_subjects: 0, peak_hour: '-' },
  by_type: [],
  by_subject: [],
  daily: [],
  hourly: [],
  recent: [],
}

const TYPE_META: TypeBucket[] = [
  { event_type: 'tailgating', name: '非法闯闸（尾随）', value: 0, color: '#dc2626' },
  { event_type: 'blocks', name: '区域入侵', value: 0, color: '#ef4444' },
  { event_type: 'detect_door', name: '大门开关', value: 0, color: '#f59e0b' },
  { event_type: 'detect_face', name: '人脸逗留检测', value: 0, color: '#8b5cf6' },
  { event_type: 'detect_phone', name: '手机检测', value: 0, color: '#f97316' },
  { event_type: 'detect_human', name: '人员违规逗留检测', value: 0, color: '#2563eb' },
  { event_type: 'detect_logistics_single_person', name: '物流通道单人', value: 0, color: '#0f766e' },
  { event_type: 'guard_absent', name: '保安离岗', value: 0, color: '#dc2626' },
  { event_type: 'guard_phone_use', name: '保安玩手机', value: 0, color: '#ea580c' },
  { event_type: 'guard_prone_sleep', name: '保安趴睡', value: 0, color: '#ca8a04' },
  { event_type: 'guard_vehicle_inspection_missing', name: '车辆出厂检查异常', value: 0, color: '#be123c' },
  { event_type: 'security_inspection', name: '安检流程不规范', value: 0, color: '#0891b2' },
]

function toRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object') return null
  return value as Record<string, unknown>
}

function toNumber(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function toString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function normalizeTrendRow(value: unknown, labelKey: 'day' | 'time'): TrendRow {
  const row = toRecord(value)
  return {
    [labelKey]: toString(row?.[labelKey]),
    total: toNumber(row?.total),
    blocks: toNumber(row?.blocks),
    tailgating: toNumber(row?.tailgating),
    detect_door: toNumber(row?.detect_door),
    detect_face: toNumber(row?.detect_face),
    detect_phone: toNumber(row?.detect_phone),
    detect_human: toNumber(row?.detect_human),
    detect_logistics_single_person: toNumber(row?.detect_logistics_single_person),
    guard_absent: toNumber(row?.guard_absent),
    guard_phone_use: toNumber(row?.guard_phone_use),
    guard_prone_sleep: toNumber(row?.guard_prone_sleep),
    guard_vehicle_inspection_missing: toNumber(row?.guard_vehicle_inspection_missing),
    security_inspection: toNumber(row?.security_inspection),
  }
}

function normalizeStatistics(data: unknown): AiVisionStatistics {
  const root = toRecord(data)
  const summary = toRecord(root?.summary)
  const byType = Array.isArray(root?.by_type) ? root.by_type : []
  const bySubject = Array.isArray(root?.by_subject) ? root.by_subject : []
  const daily = Array.isArray(root?.daily) ? root.daily : []
  const hourly = Array.isArray(root?.hourly) ? root.hourly : []
  const recent = Array.isArray(root?.recent) ? root.recent : []

  return {
    summary: {
      total: toNumber(summary?.total),
      today: toNumber(summary?.today),
      avg_per_day: toNumber(summary?.avg_per_day),
      active_subjects: toNumber(summary?.active_subjects),
      peak_hour: toString(summary?.peak_hour, '-'),
    },
    by_type: byType.map((item) => {
      const row = toRecord(item)
      const eventType = toString(row?.event_type)
      const presentation = TYPE_META.find((meta) => meta.event_type === eventType)
      return {
        event_type: eventType,
        name: toString(row?.name, '未知报警'),
        value: toNumber(row?.value),
        color: presentation?.color ?? '#64748b',
      }
    }),
    by_subject: bySubject.map((item) => {
      const row = toRecord(item)
      return {
        subject_type: toString(row?.subject_type, 'unknown'),
        subject_id: toString(row?.subject_id, 'unknown'),
        subject_name: toString(row?.subject_name, '未知主体'),
        value: toNumber(row?.value),
      }
    }),
    daily: daily.map((item) => normalizeTrendRow(item, 'day')),
    hourly: hourly.map((item) => normalizeTrendRow(item, 'time')),
    recent: recent as AlarmEvent[],
  }
}

function formatTime(timestamp?: string) {
  return timestamp ? new Date(timestamp).toLocaleString('zh-CN') : '-'
}

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
          <p className="text-slate-500">报警趋势、类型分布与主体排行</p>
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
        <SummaryCard title="活跃主体" value={stats.summary.active_subjects} sub="有报警" icon={<MapPin className="h-6 w-6 text-violet-600" />} />
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
            <CardTitle className="text-lg">告警主体排行</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {stats.by_subject.length === 0 ? (
              <div className="rounded-md border border-dashed p-6 text-center text-sm text-slate-500">暂无告警主体</div>
            ) : (
              stats.by_subject.map((subject, index) => {
                const max = Math.max(...stats.by_subject.map((item) => item.value), 1)
                return (
                  <div key={`${subject.subject_type}:${subject.subject_id}`} className="space-y-2">
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="truncate font-medium text-slate-800 dark:text-slate-200">
                        {index + 1}. {subject.subject_name}
                      </span>
                      <span className="font-semibold text-slate-900 dark:text-slate-100">{subject.value}</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-100">
                      <div className="h-2 rounded-full bg-slate-900 dark:bg-blue-500" style={{ width: `${(subject.value / max) * 100}%` }} />
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
                  <div className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{alarm.subject_name || alarm.channel_name || alarm.camera_name || alarm.camera_no || '-'}</div>
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
