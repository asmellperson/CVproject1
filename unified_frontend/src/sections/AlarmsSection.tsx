import { useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Search, Filter, Download, Eye, Smartphone, UserRound, AlertTriangle, Radar, DoorOpen, ScanFace, ShieldCheck } from 'lucide-react'
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
          (alarm.id || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
          (alarm.camera_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
          (alarm.camera_no || '').toLowerCase().includes(searchQuery.toLowerCase())
        const matchesType = typeFilter === 'all' || alarm.event_type === typeFilter
        return matchesSearch && matchesType
      }),
    [alarms, searchQuery, typeFilter],
  )

  const paginatedAlarms = filteredAlarms.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
  const totalPages = Math.max(1, Math.ceil(filteredAlarms.length / itemsPerPage))

  const counts = useMemo(() => {
    const byType = alarms.reduce<Record<string, number>>((acc, alarm) => {
      acc[alarm.event_type] = (acc[alarm.event_type] || 0) + 1
      return acc
    }, {})
    return { total: alarms.length, byType }
  }, [alarms])

  const getAlarmBadge = (type: string) => {
    switch (type) {
      case 'blocks':
        return <Badge variant="destructive">区域入侵</Badge>
      case 'detect_door':
        return <Badge className="bg-amber-500">大门开关</Badge>
      case 'detect_phone':
        return <Badge className="bg-orange-500">手机检测</Badge>
      case 'detect_face':
        return <Badge className="bg-violet-600">人脸检测</Badge>
      case 'detect_human':
        return <Badge className="bg-blue-600">人体逗留</Badge>
      case 'guard_absent':
        return <Badge className="bg-red-700">保安离岗</Badge>
      case 'guard_phone_use':
        return <Badge className="bg-orange-700">保安玩手机</Badge>
      case 'guard_prone_sleep':
        return <Badge className="bg-yellow-600">保安趴睡</Badge>
      default:
        return <Badge variant="secondary">未知报警</Badge>
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold text-slate-900">报警记录</h2>
          <p className="text-slate-500">查看报警事件、截图与处置线索</p>
        </div>
        <Button variant="outline" className="gap-2" onClick={exportJson}>
          <Download className="w-4 h-4" />
          导出
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-6">
        <StatCard title="总报警数" value={counts.total} icon={<AlertTriangle className="w-6 h-6 text-slate-600" />} />
        <StatCard
          title="区域入侵"
          value={counts.byType.blocks || 0}
          icon={<Radar className="w-6 h-6 text-red-600" />}
          valueClassName="text-red-600"
        />
        <StatCard
          title="大门开关"
          value={counts.byType.detect_door || 0}
          icon={<DoorOpen className="w-6 h-6 text-amber-600" />}
          valueClassName="text-amber-600"
        />
        <StatCard
          title="人脸检测"
          value={counts.byType.detect_face || 0}
          icon={<ScanFace className="w-6 h-6 text-violet-600" />}
          valueClassName="text-violet-600"
        />
        <StatCard
          title="手机检测"
          value={counts.byType.detect_phone || 0}
          icon={<Smartphone className="w-6 h-6 text-orange-600" />}
          valueClassName="text-orange-600"
        />
        <StatCard
          title="人体逗留"
          value={counts.byType.detect_human || 0}
          icon={<UserRound className="w-6 h-6 text-blue-600" />}
          valueClassName="text-blue-600"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard
          title="保安离岗"
          value={counts.byType.guard_absent || 0}
          icon={<ShieldCheck className="w-6 h-6 text-red-700" />}
          valueClassName="text-red-700"
        />
        <StatCard
          title="保安玩手机"
          value={counts.byType.guard_phone_use || 0}
          icon={<Smartphone className="w-6 h-6 text-orange-700" />}
          valueClassName="text-orange-700"
        />
        <StatCard
          title="保安趴睡"
          value={counts.byType.guard_prone_sleep || 0}
          icon={<UserRound className="w-6 h-6 text-yellow-600" />}
          valueClassName="text-yellow-600"
        />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col gap-4 md:flex-row">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                placeholder="搜索报警、摄像头或ID..."
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
              <SelectTrigger className="w-full md:w-40">
                <Filter className="mr-2 h-4 w-4" />
                <SelectValue placeholder="报警类型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部类型</SelectItem>
                <SelectItem value="blocks">区域入侵</SelectItem>
                <SelectItem value="detect_door">大门开关</SelectItem>
                <SelectItem value="detect_face">人脸检测</SelectItem>
                <SelectItem value="detect_phone">手机检测</SelectItem>
                <SelectItem value="detect_human">人体逗留</SelectItem>
                <SelectItem value="guard_absent">保安离岗</SelectItem>
                <SelectItem value="guard_phone_use">保安玩手机</SelectItem>
                <SelectItem value="guard_prone_sleep">保安趴睡</SelectItem>
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
                <TableHead>摄像头</TableHead>
                <TableHead>说明</TableHead>
                <TableHead>时间</TableHead>
                <TableHead>截图</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedAlarms.map((alarm) => (
                <TableRow key={alarm.id}>
                  <TableCell className="font-mono text-sm">#{alarm.id}</TableCell>
                  <TableCell>{getAlarmBadge(alarm.event_type)}</TableCell>
                  <TableCell className="max-w-[12rem] truncate">{alarm.camera_name || alarm.camera_no || '-'}</TableCell>
                  <TableCell className="max-w-xs truncate">{alarm.reason || '-'}</TableCell>
                  <TableCell className="text-sm text-slate-500">{formatTime(alarm.created_at)}</TableCell>
                  <TableCell>{alarm.image_path || alarm.image_url ? <Badge variant="outline">可查看</Badge> : <Badge variant="secondary">无</Badge>}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="sm" onClick={() => setSelectedAlarm(alarm)}>
                      <Eye className="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <div className="mt-4 flex flex-col gap-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
            <span>
              显示 {(currentPage - 1) * itemsPerPage + 1} - {Math.min(currentPage * itemsPerPage, filteredAlarms.length)} 条，共{' '}
              {filteredAlarms.length} 条
            </span>
            <div className="flex items-center justify-between gap-2 sm:justify-start">
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
        <DialogContent className="max-h-[92dvh] max-w-[calc(100vw-1.5rem)] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>报警详情</DialogTitle>
          </DialogHeader>

          {selectedAlarm && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
                <div>
                  <span className="text-slate-500">类型：</span>
                  {getAlarmBadge(selectedAlarm.event_type)}
                </div>
                <div>
                  <span className="text-slate-500">时间：</span>
                  {formatTime(selectedAlarm.created_at)}
                </div>
                <div>
                  <span className="text-slate-500">摄像头：</span>
                  {selectedAlarm.camera_name || selectedAlarm.camera_no || '-'}
                </div>
                <div>
                  <span className="text-slate-500">摄像头标识：</span>
                  {selectedAlarm.camera_no || '-'}
                </div>
              </div>

              <div className="rounded-lg border bg-slate-50 p-3 text-sm">{selectedAlarm.reason || '-'}</div>

              <div className="space-y-3">
                <div>
                  <div className="text-sm text-slate-500 mb-1">报警截图</div>
                  <img
                    src={selectedAlarm.image_url || alarmImageUrl(selectedAlarm.source_id || selectedAlarm.id)}
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
                      src={selectedAlarm.video_url || alarmVideoUrl(selectedAlarm.source_id || selectedAlarm.id)}
                      controls
                      className="w-full rounded-lg border bg-black"
                    />
                  </div>
                )}

                {!selectedAlarm.video_status && (
                  <div className="text-sm text-slate-500">当前 AiVision 报警记录已保存截图；未配置录屏文件。</div>
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
