import { useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Search, Filter, Download, Eye, Smartphone, Coffee, XCircle, AlertTriangle } from 'lucide-react'
import { alarmImageUrl, getAlarms, type AlarmEvent } from '@/lib/api'
import { alarmVideoUrl } from '@/lib/api'

export function AlarmsSection() {
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [selectedAlarm, setSelectedAlarm] = useState<AlarmEvent | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [alarms, setAlarms] = useState<AlarmEvent[]>([])
  const itemsPerPage = 10

  useEffect(() => {
    let mounted = true

    const load = async () => {
      const data = await getAlarms(200)
      if (mounted) setAlarms(data)
    }

    load().catch((err) => {
      console.error('加载报警记录失败:', err)
    })

    const timer = window.setInterval(() => {
      load().catch((err) => {
        console.error('轮询报警记录失败:', err)
      })
    }, 5000)

    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [])

  const filteredAlarms = useMemo(
    () =>
      alarms.filter((alarm) => {
        const matchesSearch =
          (alarm.reason || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
          (alarm.id || '').toLowerCase().includes(searchQuery.toLowerCase())
        const matchesType = typeFilter === 'all' || alarm.event_type === typeFilter
        return matchesSearch && matchesType
      }),
    [alarms, searchQuery, typeFilter],
  )

  const paginatedAlarms = filteredAlarms.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
  const totalPages = Math.max(1, Math.ceil(filteredAlarms.length / itemsPerPage))

  const counts = {
    total: alarms.length,
    absent: alarms.filter((item) => item.event_type === 'absent').length,
    phone_use: alarms.filter((item) => item.event_type === 'phone_use').length,
    prone_sleep: alarms.filter((item) => item.event_type === 'prone_sleep').length,
  }

  const getAlarmBadge = (type: string) => {
    switch (type) {
      case 'absent':
        return <Badge variant="destructive">离岗</Badge>
      case 'phone_use':
        return <Badge className="bg-orange-500">玩手机</Badge>
      case 'prone_sleep':
        return <Badge className="bg-yellow-500">趴睡</Badge>
      default:
        return <Badge variant="secondary">未知</Badge>
    }
  }

  const formatTime = (timestamp?: string) => (timestamp ? new Date(timestamp).toLocaleString('zh-CN') : '-')

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(filteredAlarms, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'alarm-events.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">报警记录</h2>
          <p className="text-slate-500">查看和管理所有报警事件</p>
        </div>
        <Button variant="outline" className="gap-2" onClick={exportJson}>
          <Download className="w-4 h-4" />
          导出
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <StatCard title="总报警数" value={counts.total} icon={<AlertTriangle className="w-6 h-6 text-slate-600" />} />
        <StatCard
          title="离岗报警"
          value={counts.absent}
          icon={<XCircle className="w-6 h-6 text-red-600" />}
          valueClassName="text-red-600"
        />
        <StatCard
          title="玩手机"
          value={counts.phone_use}
          icon={<Smartphone className="w-6 h-6 text-orange-600" />}
          valueClassName="text-orange-600"
        />
        <StatCard
          title="趴睡"
          value={counts.prone_sleep}
          icon={<Coffee className="w-6 h-6 text-yellow-600" />}
          valueClassName="text-yellow-600"
        />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col gap-4 md:flex-row">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                placeholder="搜索报警原因或ID..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value)
                  setCurrentPage(1)
                }}
                className="pl-10"
              />
            </div>

            <Select
              value={typeFilter}
              onValueChange={(value) => {
                setTypeFilter(value)
                setCurrentPage(1)
              }}
            >
              <SelectTrigger className="w-40">
                <Filter className="mr-2 h-4 w-4" />
                <SelectValue placeholder="报警类型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部类型</SelectItem>
                <SelectItem value="absent">离岗</SelectItem>
                <SelectItem value="phone_use">玩手机</SelectItem>
                <SelectItem value="prone_sleep">趴睡</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">报警列表</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>原因</TableHead>
                <TableHead>置信度</TableHead>
                <TableHead>时间</TableHead>
                <TableHead>帧号</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedAlarms.map((alarm) => (
                <TableRow key={alarm.id}>
                  <TableCell className="font-mono text-sm">#{alarm.id}</TableCell>
                  <TableCell>{getAlarmBadge(alarm.event_type)}</TableCell>
                  <TableCell className="max-w-xs truncate">{alarm.reason || '-'}</TableCell>
                  <TableCell>{Math.round((alarm.confidence || 0) * 100)}%</TableCell>
                  <TableCell className="text-sm text-slate-500">{formatTime(alarm.created_at)}</TableCell>
                  <TableCell className="font-mono text-sm">{alarm.frame_index ?? '-'}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="sm" onClick={() => setSelectedAlarm(alarm)}>
                      <Eye className="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
            <span>
              显示 {(currentPage - 1) * itemsPerPage + 1} - {Math.min(currentPage * itemsPerPage, filteredAlarms.length)} 条，共{' '}
              {filteredAlarms.length} 条
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={currentPage <= 1}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </Button>
              <span>
                {currentPage}/{totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={currentPage >= totalPages}
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              >
                下一页
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Dialog open={!!selectedAlarm} onOpenChange={(open) => !open && setSelectedAlarm(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>报警详情</DialogTitle>
          </DialogHeader>

          {selectedAlarm && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-slate-500">类型：</span>
                  {getAlarmBadge(selectedAlarm.event_type)}
                </div>
                <div>
                  <span className="text-slate-500">时间：</span>
                  {formatTime(selectedAlarm.created_at)}
                </div>
                <div>
                  <span className="text-slate-500">帧号：</span>
                  {selectedAlarm.frame_index ?? '-'}
                </div>
                <div>
                  <span className="text-slate-500">置信度：</span>
                  {Math.round((selectedAlarm.confidence || 0) * 100)}%
                </div>
              </div>

              <div className="rounded-lg border bg-slate-50 p-3 text-sm">{selectedAlarm.reason || '-'}</div>

              <div className="space-y-3">
                <div>
                  <div className="text-sm text-slate-500 mb-1">报警截图</div>
                  <img
                    src={alarmImageUrl(selectedAlarm.id)}
                    alt="报警截图"
                    className="w-full rounded-lg border"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none'
                    }}
                  />
                </div>
                
                {selectedAlarm.video_status === 'ready' && (
                  <div>
                    <div className="text-sm text-slate-500 mb-1">报警视频</div>
                    <video
                      src={alarmVideoUrl(selectedAlarm.id)}
                      controls
                      className="w-full rounded-lg border bg-black"
                    />
                  </div>
                )}
                
                {selectedAlarm.video_status === 'pending' && (
                  <div className="text-sm text-slate-500">视频录制中...</div>
                )}
                
                {selectedAlarm.video_status === 'failed' && (
                  <div className="text-sm text-red-500">视频录制或上传失败</div>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

function StatCard({
  title,
  value,
  icon,
  valueClassName,
}: {
  title: string
  value: number
  icon: React.ReactNode
  valueClassName?: string
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-slate-500">{title}</p>
            <p className={`text-2xl font-bold ${valueClassName || ''}`}>{value}</p>
          </div>
          <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-slate-100">
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default AlarmsSection