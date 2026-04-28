import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Area,
  AreaChart,
} from 'recharts'
import { TrendingUp, Calendar, Clock, AlertTriangle } from 'lucide-react'
import { getStatistics } from '@/lib/api'

type StatisticsResponse = {
  summary: {
    total: number
    absent: number
    phone_use: number
    prone_sleep: number
    today: number
    week: number
  }
  hourly: Array<{
    time: string
    absent: number
    phone: number
    prone_sleep: number
  }>
  weekly: Array<{
    day: string
    absent: number
    phone: number
    prone_sleep: number
  }>
  pie: Array<{
    name: string
    value: number
    color: string
  }>
}

const EMPTY: StatisticsResponse = {
  summary: { total: 0, absent: 0, phone_use: 0, prone_sleep: 0, today: 0, week: 0 },
  hourly: [],
  weekly: [],
  pie: [],
}

function normalizeStatistics(data: any): StatisticsResponse {
  return {
    summary: {
      total: Number(data?.summary?.total || 0),
      absent: Number(data?.summary?.absent || 0),
      phone_use: Number(data?.summary?.phone_use || 0),
      prone_sleep: Number(data?.summary?.prone_sleep ?? data?.summary?.drowsy ?? 0),
      today: Number(data?.summary?.today || 0),
      week: Number(data?.summary?.week || 0),
    },
    hourly: Array.isArray(data?.hourly)
      ? data.hourly.map((item: any) => ({
          time: item?.time || '',
          absent: Number(item?.absent || 0),
          phone: Number(item?.phone || 0),
          prone_sleep: Number(item?.prone_sleep ?? item?.drowsy ?? 0),
        }))
      : [],
    weekly: Array.isArray(data?.weekly)
      ? data.weekly.map((item: any) => ({
          day: item?.day || '',
          absent: Number(item?.absent || 0),
          phone: Number(item?.phone || 0),
          prone_sleep: Number(item?.prone_sleep ?? item?.drowsy ?? 0),
        }))
      : [],
    pie: Array.isArray(data?.pie)
      ? data.pie.map((item: any) => ({
          name: item?.name || '',
          value: Number(item?.value || 0),
          color: item?.color || '#94a3b8',
        }))
      : [],
  }
}

export function StatisticsSection() {
  const [stats, setStats] = useState<StatisticsResponse>(EMPTY)

  useEffect(() => {
    let mounted = true

    const load = async () => {
      const next = await getStatistics()
      if (mounted) {
        setStats(normalizeStatistics(next))
      }
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
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">统计分析</h2>
          <p className="text-slate-500">报警数据统计与趋势分析</p>
        </div>
        <Badge variant="outline" className="gap-2">
          <Calendar className="w-4 h-4" />
          最近7天
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <SummaryCard
          title="今日报警"
          value={stats.summary.today}
          sub="按自然日统计"
          icon={<Clock className="w-6 h-6 text-blue-600" />}
        />
        <SummaryCard
          title="本周报警"
          value={stats.summary.week}
          sub="最近7天"
          icon={<Calendar className="w-6 h-6 text-purple-600" />}
        />
        <SummaryCard
          title="总报警数"
          value={stats.summary.total}
          sub="累计"
          icon={<AlertTriangle className="w-6 h-6 text-slate-600" />}
        />
        <SummaryCard
          title="平均每日"
          value={Number((stats.summary.week / 7).toFixed(1))}
          sub="次/天"
          icon={<TrendingUp className="w-6 h-6 text-green-600" />}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg">周报警趋势</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={stats.weekly}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="day" stroke="#64748b" />
                <YAxis stroke="#64748b" />
                <Tooltip />
                <Legend />
                <Bar dataKey="absent" name="离岗" fill="#ef4444" radius={[4, 4, 0, 0]} />
                <Bar dataKey="phone" name="玩手机" fill="#f97316" radius={[4, 4, 0, 0]} />
                <Bar dataKey="prone_sleep" name="趴睡" fill="#eab308" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">报警分布</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={stats.pie}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  dataKey="value"
                  label
                >
                  {stats.pie.map((entry, index) => (
                    <Cell key={index} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">24小时报警趋势</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={stats.hourly}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="time" stroke="#64748b" />
              <YAxis stroke="#64748b" />
              <Tooltip />
              <Legend />
              <Area
                type="monotone"
                dataKey="absent"
                name="离岗"
                stroke="#ef4444"
                fill="#ef4444"
                fillOpacity={0.25}
              />
              <Area
                type="monotone"
                dataKey="phone"
                name="玩手机"
                stroke="#f97316"
                fill="#f97316"
                fillOpacity={0.25}
              />
              <Area
                type="monotone"
                dataKey="prone_sleep"
                name="趴睡"
                stroke="#eab308"
                fill="#eab308"
                fillOpacity={0.25}
              />
            </AreaChart>
          </ResponsiveContainer>
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
  value: number
  sub: string
  icon: React.ReactNode
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-slate-500">{title}</p>
            <div className="flex items-baseline gap-2">
              <p className="text-2xl font-bold">{value}</p>
              <span className="text-xs text-slate-400">{sub}</span>
            </div>
          </div>
          <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-slate-100">
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default StatisticsSection