import { useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Search,
  Filter,
  Download,
  Eye,
  Smartphone,
  UserRound,
  AlertTriangle,
  Radar,
  DoorOpen,
  ScanFace,
  ShieldAlert,
  ShieldCheck,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  UsersRound,
  XCircle,
} from 'lucide-react'
import {
  alarmImageUrl,
  getAlarms,
  updateAlarmDisposition,
  type AlarmDisposition,
  type AlarmDispositionStatus,
  type AlarmEvent,
} from '@/lib/api'
import { alarmVideoUrl } from '@/lib/api'
import { useAuth } from '@/auth/useAuth'
import { getAccessibleAlarmEventTypes } from '@/auth/permissions'

export function AlarmsSection() {
  const { user } = useAuth()
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('open')
  const [selectedAlarm, setSelectedAlarm] = useState<AlarmEvent | null>(null)
  const [dispositionNote, setDispositionNote] = useState('')
  const [dispositionError, setDispositionError] = useState('')
  const [dispositionBusy, setDispositionBusy] = useState<AlarmDispositionStatus | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [alarms, setAlarms] = useState<AlarmEvent[]>([])
  const itemsPerPage = 10
  const accessibleAlarmEventTypes = useMemo(() => getAccessibleAlarmEventTypes(user), [user])
  const allowedAlarmTypes = useMemo(
    () => (accessibleAlarmEventTypes ? new Set(accessibleAlarmEventTypes) : null),
    [accessibleAlarmEventTypes],
  )

  useEffect(() => {
    let mounted = true

    const load = async () => {
      const data = await getAlarms(200, accessibleAlarmEventTypes)
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
  }, [accessibleAlarmEventTypes])

  useEffect(() => {
    setDispositionNote(selectedAlarm?.disposition_note || '')
    setDispositionError('')
    setDispositionBusy(null)
  }, [selectedAlarm?.id, selectedAlarm?.disposition_note])

  const effectiveTypeFilter =
    typeFilter !== 'all' && allowedAlarmTypes && !allowedAlarmTypes.has(typeFilter) ? 'all' : typeFilter

  const filteredAlarms = useMemo(
    () =>
      alarms.filter((alarm) => {
        const matchesSearch =
          (alarm.reason || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
          (alarm.id || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
          (alarm.camera_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
          (alarm.camera_no || '').toLowerCase().includes(searchQuery.toLowerCase())
        const matchesType = effectiveTypeFilter === 'all' || alarm.event_type === effectiveTypeFilter
        const status = alarm.disposition_status || 'pending'
        const matchesStatus =
          statusFilter === 'all' ||
          (statusFilter === 'open' ? status === 'pending' || status === 'acknowledged' : status === statusFilter)
        return matchesSearch && matchesType && matchesStatus
      }),
    [alarms, searchQuery, effectiveTypeFilter, statusFilter],
  )

  const totalPages = Math.max(1, Math.ceil(filteredAlarms.length / itemsPerPage))
  const safeCurrentPage = Math.min(currentPage, totalPages)
  const pageStart = filteredAlarms.length === 0 ? 0 : (safeCurrentPage - 1) * itemsPerPage + 1
  const pageEnd = Math.min(safeCurrentPage * itemsPerPage, filteredAlarms.length)
  const paginatedAlarms = filteredAlarms.slice((safeCurrentPage - 1) * itemsPerPage, safeCurrentPage * itemsPerPage)

  const counts = useMemo(() => {
    const byType = alarms.reduce<Record<string, number>>((acc, alarm) => {
      acc[alarm.event_type] = (acc[alarm.event_type] || 0) + 1
      return acc
    }, {})
    const byStatus = alarms.reduce<Record<AlarmDispositionStatus, number>>(
      (acc, alarm) => {
        const status = alarm.disposition_status || 'pending'
        acc[status] = (acc[status] || 0) + 1
        return acc
      },
      { pending: 0, acknowledged: 0, resolved: 0, false_positive: 0 },
    )
    return { total: alarms.length, byType, byStatus }
  }, [alarms])

  const alarmTypeOptions = useMemo(
    () =>
      [
        { eventType: 'blocks', label: '区域入侵', icon: <Radar className="w-6 h-6 text-red-600" />, valueClassName: 'text-red-600' },
        { eventType: 'detect_door', label: '大门开关', icon: <DoorOpen className="w-6 h-6 text-amber-600" />, valueClassName: 'text-amber-600' },
        { eventType: 'detect_face', label: '人脸检测', icon: <ScanFace className="w-6 h-6 text-violet-600" />, valueClassName: 'text-violet-600' },
        { eventType: 'detect_phone', label: '手机检测', icon: <Smartphone className="w-6 h-6 text-orange-600" />, valueClassName: 'text-orange-600' },
        { eventType: 'detect_human', label: '人体逗留', icon: <UserRound className="w-6 h-6 text-blue-600" />, valueClassName: 'text-blue-600' },
        { eventType: 'detect_logistics_single_person', label: '物流通道单人', icon: <UsersRound className="w-6 h-6 text-teal-700" />, valueClassName: 'text-teal-700' },
        { eventType: 'guard_absent', label: '保安离岗', icon: <ShieldCheck className="w-6 h-6 text-red-700" />, valueClassName: 'text-red-700' },
        { eventType: 'guard_phone_use', label: '保安玩手机', icon: <Smartphone className="w-6 h-6 text-orange-700" />, valueClassName: 'text-orange-700' },
        { eventType: 'guard_prone_sleep', label: '保安趴睡', icon: <UserRound className="w-6 h-6 text-yellow-600" />, valueClassName: 'text-yellow-600' },
        { eventType: 'security_vlm_non_compliant', label: '安检不规范', icon: <ShieldAlert className="w-6 h-6 text-cyan-700" />, valueClassName: 'text-cyan-700' },
        { eventType: 'security_vlm_error', label: '安检判定错误', icon: <AlertTriangle className="w-6 h-6 text-amber-600" />, valueClassName: 'text-amber-600' },
      ].filter((item) => !allowedAlarmTypes || allowedAlarmTypes.has(item.eventType)),
    [allowedAlarmTypes],
  )

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
      case 'detect_logistics_single_person':
        return <Badge className="bg-teal-700">物流通道单人</Badge>
      case 'guard_absent':
        return <Badge className="bg-red-700">保安离岗</Badge>
      case 'guard_phone_use':
        return <Badge className="bg-orange-700">保安玩手机</Badge>
      case 'guard_prone_sleep':
        return <Badge className="bg-yellow-600">保安趴睡</Badge>
      case 'security_vlm_non_compliant':
        return <Badge className="bg-cyan-700">安检流程不规范</Badge>
      case 'security_vlm_error':
        return <Badge className="bg-amber-600">安检判定错误</Badge>
      default:
        return <Badge variant="secondary">未知报警</Badge>
    }
  }

  const getDispositionBadge = (status: AlarmDispositionStatus) => {
    switch (status) {
      case 'pending':
        return <Badge className="bg-red-600">待处理</Badge>
      case 'acknowledged':
        return <Badge className="bg-blue-600">已确认</Badge>
      case 'resolved':
        return <Badge className="bg-emerald-600">已处理</Badge>
      case 'false_positive':
        return <Badge variant="secondary">误报</Badge>
      default:
        return <Badge variant="secondary">未知</Badge>
    }
  }

  const formatTime = (timestamp?: string) => (timestamp ? new Date(timestamp).toLocaleString('zh-CN') : '-')

  const applyDisposition = (alarmId: string, disposition: AlarmDisposition) => {
    const patch = (alarm: AlarmEvent): AlarmEvent =>
      alarm.id === alarmId
        ? {
            ...alarm,
            disposition_status: disposition.status,
            disposition_note: disposition.note,
            disposition_updated_at: disposition.updated_at,
            disposition_updated_by: disposition.updated_by || null,
          }
        : alarm
    setAlarms((items) => items.map(patch))
    setSelectedAlarm((alarm) => (alarm ? patch(alarm) : alarm))
  }

  const handleDisposition = async (alarm: AlarmEvent, status: AlarmDispositionStatus) => {
    setDispositionBusy(status)
    setDispositionError('')
    try {
      const disposition = await updateAlarmDisposition(alarm.id, status, dispositionNote)
      applyDisposition(alarm.id, disposition)
    } catch (error) {
      setDispositionError(error instanceof Error ? error.message : '处置状态保存失败')
    } finally {
      setDispositionBusy(null)
    }
  }

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
        <StatCard title="待处理" value={counts.byStatus.pending} icon={<CircleAlert className="w-6 h-6 text-red-600" />} valueClassName="text-red-600" />
        <StatCard title="已确认" value={counts.byStatus.acknowledged} icon={<CircleDashed className="w-6 h-6 text-blue-600" />} valueClassName="text-blue-600" />
        <StatCard title="已处理" value={counts.byStatus.resolved} icon={<CheckCircle2 className="w-6 h-6 text-emerald-600" />} valueClassName="text-emerald-600" />
        <StatCard title="误报" value={counts.byStatus.false_positive} icon={<XCircle className="w-6 h-6 text-slate-500" />} valueClassName="text-slate-600" />
        {alarmTypeOptions.map((item) => (
          <StatCard
            key={item.eventType}
            title={item.label}
            value={counts.byType[item.eventType] || 0}
            icon={item.icon}
            valueClassName={item.valueClassName}
          />
        ))}
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
              value={effectiveTypeFilter}
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
                {alarmTypeOptions.map((item) => (
                  <SelectItem key={item.eventType} value={item.eventType}>{item.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={statusFilter}
              onValueChange={(value) => {
                setStatusFilter(value)
                setCurrentPage(1)
              }}
            >
              <SelectTrigger className="w-full md:w-44">
                <CircleDashed className="mr-2 h-4 w-4" />
                <SelectValue placeholder="处置状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="open">待处理/已确认</SelectItem>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="pending">待处理</SelectItem>
                <SelectItem value="acknowledged">已确认</SelectItem>
                <SelectItem value="resolved">已处理</SelectItem>
                <SelectItem value="false_positive">误报</SelectItem>
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
                <TableHead>类型</TableHead>
                <TableHead>摄像头</TableHead>
                <TableHead>说明</TableHead>
                <TableHead>处置状态</TableHead>
                <TableHead>时间</TableHead>
                <TableHead>截图</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedAlarms.map((alarm) => (
                <TableRow key={alarm.id}>
                  <TableCell>{getAlarmBadge(alarm.event_type)}</TableCell>
                  <TableCell className="max-w-[12rem] truncate">{alarm.camera_name || alarm.camera_no || '-'}</TableCell>
                  <TableCell className="max-w-xs truncate">{alarm.reason || '-'}</TableCell>
                  <TableCell>{getDispositionBadge(alarm.disposition_status || 'pending')}</TableCell>
                  <TableCell className="text-sm text-slate-500">{formatTime(alarm.created_at)}</TableCell>
                  <TableCell>
                    {alarm.image_path || alarm.image_url ? (
                      <Button variant="outline" size="sm" className="gap-2" onClick={() => setSelectedAlarm(alarm)}>
                        <Eye className="w-4 h-4" />
                        可查看
                      </Button>
                    ) : (
                      <Badge variant="secondary">无</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <div className="mt-4 flex flex-col gap-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
            <span>
              显示 {pageStart} - {pageEnd} 条，共 {filteredAlarms.length} 条
            </span>
            <div className="flex items-center justify-between gap-2 sm:justify-start">
              <Button
                variant="outline"
                size="sm"
                disabled={safeCurrentPage <= 1}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </Button>
              <span>
                {safeCurrentPage}/{totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={safeCurrentPage >= totalPages}
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

              <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="font-semibold text-slate-900">处置状态</div>
                    <div className="mt-1 text-slate-500">
                      {selectedAlarm.disposition_updated_at
                        ? `${formatTime(selectedAlarm.disposition_updated_at)} 由 ${selectedAlarm.disposition_updated_by?.name || selectedAlarm.disposition_updated_by?.employee_id || '-'} 更新`
                        : '尚未处置'}
                    </div>
                  </div>
                  {getDispositionBadge(selectedAlarm.disposition_status || 'pending')}
                </div>

                <div className="mt-4 space-y-2">
                  <div className="text-sm font-medium text-slate-700">处置备注</div>
                  <Textarea
                    value={dispositionNote}
                    onChange={(event) => setDispositionNote(event.target.value)}
                    placeholder="可填写现场情况、误报原因或处理结果"
                    className="min-h-20"
                  />
                </div>

                {dispositionError && (
                  <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                    {dispositionError}
                  </div>
                )}

                <div className="mt-4 flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className="gap-2"
                    disabled={Boolean(dispositionBusy)}
                    onClick={() => handleDisposition(selectedAlarm, 'acknowledged')}
                  >
                    <CircleDashed className="h-4 w-4" />
                    {dispositionBusy === 'acknowledged' ? '保存中' : '确认'}
                  </Button>
                  <Button
                    className="gap-2 bg-emerald-600 hover:bg-emerald-700"
                    disabled={Boolean(dispositionBusy)}
                    onClick={() => handleDisposition(selectedAlarm, 'resolved')}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    {dispositionBusy === 'resolved' ? '保存中' : '标记已处理'}
                  </Button>
                  <Button
                    variant="secondary"
                    className="gap-2"
                    disabled={Boolean(dispositionBusy)}
                    onClick={() => handleDisposition(selectedAlarm, 'false_positive')}
                  >
                    <XCircle className="h-4 w-4" />
                    {dispositionBusy === 'false_positive' ? '保存中' : '标记误报'}
                  </Button>
                  <Button
                    variant="outline"
                    className="gap-2"
                    disabled={Boolean(dispositionBusy)}
                    onClick={() => handleDisposition(selectedAlarm, 'pending')}
                  >
                    <CircleAlert className="h-4 w-4" />
                    {dispositionBusy === 'pending' ? '保存中' : '退回待处理'}
                  </Button>
                </div>
              </div>

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
                  <div className="text-sm text-slate-500">
                    {selectedAlarm.source === 'security_vlm' ? '当前安检流程记录来自 VLM 历史判定；后端未提供单条截图接口。' : '当前 AiVision 报警记录已保存截图；未配置报警视频文件。'}
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
