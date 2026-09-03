// 文件说明：实现告警的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useEffect, useMemo, useRef, useState } from 'react'
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
  ZoomIn,
  ZoomOut,
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
import { buildUrlWithoutAlarmId, findInitialAlarm } from './AlarmsSection.initialAlarm'

type AlarmsSectionProps = {
  initialAlarmId?: string
}

function alarmSubjectName(alarm: AlarmEvent) {
  return alarm.subject_name || alarm.channel_name || alarm.camera_name || alarm.site_name || alarm.camera_no || '-'
}

function alarmSubjectTypeLabel(subjectType?: string) {
  if (subjectType === 'logistics_channel') return '物流通道'
  if (subjectType === 'guard_room_site') return '保安室'
  if (subjectType === 'camera') return '摄像头'
  return '告警主体'
}

/**
 * 功能：渲染 `AlarmsSection` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（AlarmsSectionProps）：React 组件属性对象；解构字段包括 initialAlarmId
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useAuth`、`useState`、`useRef`、`useMemo`、`getAccessibleAlarmEventTypes`、`Set`、`useEffect`、`async`、`getAlarms`、`setAlarms`
 *          等共 106 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
export function AlarmsSection({ initialAlarmId = '' }: AlarmsSectionProps) {
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
  const [imagePreviewOpen, setImagePreviewOpen] = useState(false)
  const [imageZoom, setImageZoom] = useState(1)
  const [videoError, setVideoError] = useState(false)
  const initialAlarmOpenedRef = useRef(false)
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
    setVideoError(false)
  }, [selectedAlarm?.id, selectedAlarm?.disposition_note])

  useEffect(() => {
    if (!selectedAlarm) return
    const refreshed = alarms.find((alarm) => alarm.id === selectedAlarm.id)
    if (
      refreshed
      && (
        refreshed.video_status !== selectedAlarm.video_status
        || refreshed.video_url !== selectedAlarm.video_url
      )
    ) {
      setSelectedAlarm(refreshed)
    }
  }, [alarms, selectedAlarm])

  useEffect(() => {
    if (!initialAlarmId || initialAlarmOpenedRef.current || selectedAlarm || !alarms.length) return
    const alarm = findInitialAlarm(alarms, initialAlarmId)
    if (alarm) {
      initialAlarmOpenedRef.current = true
      setSelectedAlarm(alarm)
    }
  }, [alarms, initialAlarmId, selectedAlarm])

  const handleAlarmDialogOpenChange = (open: boolean) => {
    if (open) return
    setImagePreviewOpen(false)
    setImageZoom(1)
    setSelectedAlarm(null)

    const params = new URLSearchParams(window.location.search)
    if (params.has('alarmId')) {
      window.history.replaceState(window.history.state, '', buildUrlWithoutAlarmId(window.location))
    }
  }

  const effectiveTypeFilter =
    typeFilter !== 'all' && allowedAlarmTypes && !allowedAlarmTypes.has(typeFilter) ? 'all' : typeFilter

  const filteredAlarms = useMemo(
    () =>
      alarms.filter((alarm) => {
        const matchesSearch =
          (alarm.reason || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
          (alarm.id || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
          (alarm.subject_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
          (alarm.subject_id || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
          (alarm.department || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
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
        { eventType: 'detect_human', label: '人员违规逗留检测', icon: <UserRound className="w-6 h-6 text-blue-600" />, valueClassName: 'text-blue-600' },
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
        return <Badge className="bg-blue-600">人员违规逗留检测</Badge>
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
    <div className="space-y-6 text-slate-950 dark:text-slate-100">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100">报警记录</h2>
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
                <TableHead>告警主体</TableHead>
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
                  <TableCell className="max-w-[12rem] truncate">{alarmSubjectName(alarm)}</TableCell>
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

      <Dialog open={!!selectedAlarm} onOpenChange={handleAlarmDialogOpenChange}>
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
                  <span className="text-slate-500">{alarmSubjectTypeLabel(selectedAlarm.subject_type)}：</span>
                  {alarmSubjectName(selectedAlarm)}
                </div>
                <div>
                  <span className="text-slate-500">主体标识：</span>
                  {selectedAlarm.subject_id || selectedAlarm.camera_no || '-'}
                </div>
              </div>

              <div className="rounded-lg border bg-slate-50 p-3 text-sm">{selectedAlarm.reason || '-'}</div>

              <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="font-semibold text-slate-900 dark:text-slate-100">处置状态</div>
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
                  <button
                    type="button"
                    className="group relative block w-full cursor-zoom-in overflow-hidden rounded-lg border bg-black/5 text-left dark:bg-black/30"
                    onClick={() => {
                      setImageZoom(1)
                      setImagePreviewOpen(true)
                    }}
                    aria-label="放大查看报警截图"
                  >
                    <img
                      src={selectedAlarm.image_url || alarmImageUrl(selectedAlarm.source_id || selectedAlarm.id)}
                      alt="报警截图"
                      className="w-full transition duration-200 group-hover:brightness-90"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none'
                      }}
                    />
                    <span className="pointer-events-none absolute bottom-3 right-3 inline-flex items-center gap-1.5 rounded-full bg-slate-950/75 px-3 py-1.5 text-xs font-medium text-white opacity-0 backdrop-blur transition group-hover:opacity-100">
                      <ZoomIn className="h-3.5 w-3.5" />
                      点击放大
                    </span>
                  </button>
                </div>
                
                {selectedAlarm.video_status === 'ready' && (
                  <div>
                    <div className="text-sm text-slate-500 mb-1">报警视频</div>
                    <video
                      src={selectedAlarm.video_url || alarmVideoUrl(selectedAlarm.source_id || selectedAlarm.id)}
                      controls
                      preload="metadata"
                      className="w-full rounded-lg border bg-black"
                      onLoadedData={() => setVideoError(false)}
                      onError={() => setVideoError(true)}
                    />
                    {videoError && (
                      <div className="mt-2 text-sm text-red-500">
                        报警视频加载失败，请稍后重试或联系管理员检查视频文件。
                      </div>
                    )}
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

      <Dialog open={imagePreviewOpen} onOpenChange={setImagePreviewOpen}>
        <DialogContent className="flex h-[94dvh] max-h-none w-[calc(100vw-1rem)] max-w-none flex-col gap-0 overflow-hidden border-slate-700 bg-slate-950/95 p-0 text-white sm:max-w-[96vw]">
          <DialogHeader className="flex-col gap-3 border-b border-white/10 px-4 py-3 pr-12 sm:flex-row sm:items-center sm:justify-between">
            <DialogTitle className="text-base text-white">报警截图</DialogTitle>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
                onClick={() => setImageZoom((value) => Math.max(0.5, value - 0.25))}
                aria-label="缩小图片"
              >
                <ZoomOut className="h-4 w-4" />
              </Button>
              <span className="w-14 text-center text-xs text-slate-300">{Math.round(imageZoom * 100)}%</span>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
                onClick={() => setImageZoom((value) => Math.min(3, value + 0.25))}
                aria-label="放大图片"
              >
                <ZoomIn className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="outline"
                className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
                onClick={() => setImageZoom(1)}
              >
                适应窗口
              </Button>
              {selectedAlarm && (
                <Button asChild variant="outline" className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white">
                  <a
                    href={selectedAlarm.image_url || alarmImageUrl(selectedAlarm.source_id || selectedAlarm.id)}
                    download={`alarm-${selectedAlarm.source_id || selectedAlarm.id}.jpg`}
                  >
                    <Download className="mr-2 h-4 w-4" />
                    下载
                  </a>
                </Button>
              )}
            </div>
          </DialogHeader>
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-4">
            {selectedAlarm && (
              <img
                src={selectedAlarm.image_url || alarmImageUrl(selectedAlarm.source_id || selectedAlarm.id)}
                alt="报警截图大图"
                className="select-none object-contain transition-[width] duration-150"
                style={{
                  width: `${imageZoom * 100}%`,
                  maxWidth: imageZoom <= 1 ? '100%' : 'none',
                  maxHeight: imageZoom <= 1 ? '100%' : 'none',
                }}
                draggable={false}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/**
 * 功能：渲染 `StatCard` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 title, value, icon, valueClassName, title, string, value, number
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`Card`、`CardContent`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
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
        <Card className="dark:border-slate-800 dark:bg-slate-900">
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
