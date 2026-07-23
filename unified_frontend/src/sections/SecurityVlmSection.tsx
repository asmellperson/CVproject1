import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Crosshair,
  FileCheck2,
  Layers3,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  Video,
  XCircle,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import {
  getSecurityVlmHealth,
  getSecurityVlmRois,
  saveSecurityVlmRois,
  securityVlmVideoUrl,
  startSecurityVlmRuntime,
  stopSecurityVlmRuntime,
  type SecurityVlmHealth,
  type SecurityVlmHistoryItem,
} from '@/lib/security-vlm'
import { useAuth } from '@/auth/useAuth'

const POLL_MS = 2000
const ROI_COLORS = ['#2563eb', '#059669', '#d97706', '#db2777', '#7c3aed', '#0891b2']

type RoiDraftRect = {
  left: number
  top: number
  width: number
  height: number
  sx: number
  sy: number
  ex: number
  ey: number
}

function formatNumber(value?: number, suffix = '') {
  if (!Number.isFinite(value)) return `0${suffix}`
  return `${value}${suffix}`
}

function statusBadge(status?: string) {
  if (status === 'compliant') return <Badge className="bg-emerald-600">合规</Badge>
  if (status === 'non_compliant') return <Badge variant="destructive">不合规</Badge>
  if (status === 'error') return <Badge className="bg-amber-500">错误</Badge>
  return <Badge variant="secondary">未知</Badge>
}

function boolMark(value?: boolean | null) {
  if (value === true) return <CheckCircle2 className="h-4 w-4 text-emerald-600" />
  if (value === false) return <XCircle className="h-4 w-4 text-slate-300" />
  return <span className="text-slate-400">-</span>
}

function nextRoiName(names: string[]) {
  const used = new Set(names)
  let index = 1
  while (used.has(`security_staff_${index}`)) index += 1
  return `security_staff_${index}`
}

function normalizeRoi(values: number[]) {
  return values.slice(0, 4).map((value) => Math.round(Number(value) || 0))
}

export function SecurityVlmSection() {
  const { isAdmin } = useAuth()
  const [activeTab, setActiveTab] = useState('dashboard')
  const [health, setHealth] = useState<SecurityVlmHealth | null>(null)
  const [message, setMessage] = useState('正在连接安检流程规范检测服务...')
  const [controlMessage, setControlMessage] = useState('')
  const [controlBusy, setControlBusy] = useState(false)
  const [videoNonce, setVideoNonce] = useState(Date.now())
  const [rois, setRois] = useState<Record<string, number[]>>({})
  const [slotNames, setSlotNames] = useState<string[]>([])
  const [currentRoi, setCurrentRoi] = useState<string | null>(null)
  const [roiMessage, setRoiMessage] = useState('')
  const [savingRoi, setSavingRoi] = useState(false)
  const [draftRect, setDraftRect] = useState<RoiDraftRect | null>(null)
  const [drawing, setDrawing] = useState(false)
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 })
  const startPointRef = useRef<{ rx: number; ry: number; ix: number; iy: number } | null>(null)
  const stageRef = useRef<HTMLDivElement | null>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)

  const stats = health?.stats || {}
  const history = health?.history || []
  const sourceWidth = Number(health?.capture?.width || 0)
  const sourceHeight = Number(health?.capture?.height || 0)
  const runtimeRunning = Boolean(health?.running)

  const activeVideoUrl = useMemo(() => {
    if (activeTab === 'roi') return securityVlmVideoUrl('original', videoNonce)
    return securityVlmVideoUrl('rule', videoNonce)
  }, [activeTab, videoNonce])

  const loadHealth = async () => {
    const next = await getSecurityVlmHealth()
    setHealth(next)
    setMessage('服务已连接')
  }

  const handleToggleRuntime = async () => {
    if (!isAdmin) {
      setControlMessage('当前账号为 viewer，只能查看运行状态。')
      return
    }
    setControlBusy(true)
    setControlMessage(runtimeRunning ? '正在关闭检测...' : '正在开启检测...')
    try {
      if (runtimeRunning) {
        await stopSecurityVlmRuntime()
        setVideoNonce(Date.now())
        setControlMessage('检测已关闭，VLM 不会继续产生新的调用费用。')
      } else {
        await startSecurityVlmRuntime()
        setVideoNonce(Date.now())
        setControlMessage('检测已开启。')
      }
      await loadHealth()
    } catch (error) {
      setControlMessage(`操作失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setControlBusy(false)
    }
  }

  const loadRois = async () => {
    const data = await getSecurityVlmRois()
    const names = data.available_slots?.length ? data.available_slots : Object.keys(data.staff_rois || {})
    setRois(data.staff_rois || {})
    setSlotNames(names)
    setCurrentRoi((prev) => (prev && names.includes(prev) ? prev : names[0] || null))
  }

  useEffect(() => {
    let mounted = true

    const load = async () => {
      try {
        const next = await getSecurityVlmHealth()
        if (mounted) {
          setHealth(next)
          setMessage('服务已连接')
        }
      } catch (error) {
        if (mounted) {
          setMessage(`连接失败：${error instanceof Error ? error.message : String(error)}`)
        }
      }
    }

    load().catch(() => undefined)
    const timer = window.setInterval(() => {
      load().catch(() => undefined)
    }, POLL_MS)

    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'roi') {
      loadRois().catch((error) => {
        setRoiMessage(`ROI 读取失败：${error instanceof Error ? error.message : String(error)}`)
      })
    }
  }, [activeTab])

  useEffect(() => {
    const onResize = () => {
      const rect = imageRef.current?.getBoundingClientRect()
      if (rect) setImageSize({ width: rect.width, height: rect.height })
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const imageMetrics = () => {
    const image = imageRef.current
    const stage = stageRef.current
    if (!image || !stage) return null

    const imageRect = image.getBoundingClientRect()
    const stageRect = stage.getBoundingClientRect()
    return {
      left: imageRect.left - stageRect.left,
      top: imageRect.top - stageRect.top,
      width: imageRect.width,
      height: imageRect.height,
      sourceWidth: sourceWidth || image.naturalWidth || 1,
      sourceHeight: sourceHeight || image.naturalHeight || 1,
    }
  }

  const toImagePoint = (clientX: number, clientY: number) => {
    const metrics = imageMetrics()
    const stage = stageRef.current
    if (!metrics || !stage) return null

    const stageRect = stage.getBoundingClientRect()
    const x = clientX - stageRect.left
    const y = clientY - stageRect.top
    const rx = Math.max(metrics.left, Math.min(metrics.left + metrics.width, x))
    const ry = Math.max(metrics.top, Math.min(metrics.top + metrics.height, y))
    return {
      rx,
      ry,
      ix: ((rx - metrics.left) / Math.max(1, metrics.width)) * metrics.sourceWidth,
      iy: ((ry - metrics.top) / Math.max(1, metrics.height)) * metrics.sourceHeight,
    }
  }

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!currentRoi) {
      setRoiMessage('请先新增或选择一个 ROI。')
      return
    }
    const point = toImagePoint(event.clientX, event.clientY)
    if (!point) return
    event.currentTarget.setPointerCapture(event.pointerId)
    startPointRef.current = point
    setDrawing(true)
    setDraftRect({
      left: point.rx,
      top: point.ry,
      width: 0,
      height: 0,
      sx: point.ix,
      sy: point.iy,
      ex: point.ix,
      ey: point.iy,
    })
  }

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!drawing || !startPointRef.current) return
    const point = toImagePoint(event.clientX, event.clientY)
    if (!point) return
    const start = startPointRef.current
    setDraftRect({
      left: Math.min(start.rx, point.rx),
      top: Math.min(start.ry, point.ry),
      width: Math.abs(point.rx - start.rx),
      height: Math.abs(point.ry - start.ry),
      sx: start.ix,
      sy: start.iy,
      ex: point.ix,
      ey: point.iy,
    })
  }

  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!drawing || !draftRect || !currentRoi) return
    event.currentTarget.releasePointerCapture(event.pointerId)
    setDrawing(false)

    const x1 = Math.min(draftRect.sx, draftRect.ex)
    const y1 = Math.min(draftRect.sy, draftRect.ey)
    const x2 = Math.max(draftRect.sx, draftRect.ex)
    const y2 = Math.max(draftRect.sy, draftRect.ey)
    if (Math.abs(x2 - x1) >= 4 && Math.abs(y2 - y1) >= 4) {
      setRois((prev) => ({ ...prev, [currentRoi]: normalizeRoi([x1, y1, x2, y2]) }))
    }
    setDraftRect(null)
    startPointRef.current = null
  }

  const handleAddRoi = () => {
    const name = nextRoiName(slotNames)
    setSlotNames((prev) => [...prev, name])
    setCurrentRoi(name)
    setRoiMessage(`已新增 ${name}，请在画面中拖拽绘制区域。`)
  }

  const handleDeleteRoi = () => {
    if (!currentRoi) return
    const nextNames = slotNames.filter((name) => name !== currentRoi)
    setRois((prev) => {
      const next = { ...prev }
      delete next[currentRoi]
      return next
    })
    setSlotNames(nextNames)
    setCurrentRoi(nextNames[0] || null)
    setRoiMessage('已删除当前 ROI，保存后生效。')
  }

  const handleSaveRois = async () => {
    if (!isAdmin) {
      setRoiMessage('当前账号为 viewer，只能查看 ROI。')
      return
    }
    setSavingRoi(true)
    try {
      const data = await saveSecurityVlmRois(rois)
      const names = data.available_slots?.length ? data.available_slots : Object.keys(data.staff_rois || {})
      setRois(data.staff_rois || rois)
      setSlotNames(names)
      setCurrentRoi((prev) => (prev && names.includes(prev) ? prev : names[0] || null))
      setRoiMessage('ROI 已保存，后端会自动热加载。')
    } catch (error) {
      setRoiMessage(`ROI 保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSavingRoi(false)
    }
  }

  const renderRoiBoxes = () => {
    const metrics = imageMetrics()
    if (!metrics || !imageSize.width || !imageSize.height) return null

    return slotNames.map((name, index) => {
      const roi = rois[name]
      if (!roi || roi.length < 4) return null
      const [x1, y1, x2, y2] = roi
      const color = ROI_COLORS[index % ROI_COLORS.length]
      const left = metrics.left + (Math.min(x1, x2) / metrics.sourceWidth) * metrics.width
      const top = metrics.top + (Math.min(y1, y2) / metrics.sourceHeight) * metrics.height
      const width = (Math.abs(x2 - x1) / metrics.sourceWidth) * metrics.width
      const height = (Math.abs(y2 - y1) / metrics.sourceHeight) * metrics.height

      return (
        <div
          key={name}
          className="pointer-events-none absolute rounded-md border-2"
          style={{ left, top, width, height, borderColor: color, backgroundColor: `${color}33` }}
        >
          <span className="absolute left-1.5 top-1.5 rounded-full bg-white/95 px-2 py-0.5 text-xs font-semibold text-slate-900 shadow-sm">
            {name}
          </span>
        </div>
      )
    })
  }

  return (
    <div className="space-y-6">
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="grid h-auto w-full max-w-lg grid-cols-2 p-1">
          <TabsTrigger value="dashboard" className="gap-2 py-2">
            <Video className="h-4 w-4" />
            检测面板
          </TabsTrigger>
          <TabsTrigger value="roi" className="gap-2 py-2">
            <Crosshair className="h-4 w-4" />
            ROI 绘制
          </TabsTrigger>
        </TabsList>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-2xl font-bold text-slate-900">安检流程规范检测</h2>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={runtimeRunning ? 'default' : 'secondary'} className={cn('gap-2', runtimeRunning && 'bg-emerald-600')}>
              <span className={cn('h-2 w-2 rounded-full', runtimeRunning ? 'bg-emerald-200' : 'bg-slate-400')} />
              {runtimeRunning ? '检测开启' : '检测关闭'}
            </Badge>
            <Button
              variant={runtimeRunning ? 'destructive' : 'default'}
              size="sm"
              className="gap-2"
              onClick={handleToggleRuntime}
              disabled={!isAdmin || controlBusy}
            >
              {runtimeRunning ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              {controlBusy ? '处理中' : runtimeRunning ? '关闭功能' : '开启功能'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => {
                setVideoNonce(Date.now())
                loadHealth().catch((error) => setMessage(`刷新失败：${error instanceof Error ? error.message : String(error)}`))
              }}
            >
              <RefreshCw className="h-4 w-4" />
              刷新
            </Button>
          </div>
        </div>

        <TabsContent value="dashboard" className="space-y-6">
          <Card className="overflow-hidden">
            <CardHeader className="flex flex-col gap-3 border-b bg-slate-50 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0">
                <CardTitle className="text-lg">摄像头画面</CardTitle>
                <p className="mt-1 text-sm text-slate-500">{controlMessage || message}</p>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <div className="aspect-video w-full bg-slate-950">
                {runtimeRunning ? (
                  <img src={activeVideoUrl} alt="安检流程规范检测实时画面" className="h-full w-full object-contain" />
                ) : (
                  <div className="flex h-full w-full flex-col items-center justify-center gap-3 text-slate-300">
                    <Pause className="h-10 w-10" />
                    <div className="text-base font-semibold">检测功能已关闭</div>
                    <div className="text-sm text-slate-400">开启功能后恢复摄像头画面和 VLM 判定</div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <HistoryTable items={history} />

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-7">
            <StatCard title="总 session" value={formatNumber(stats.total)} icon={<Layers3 className="h-5 w-5 text-slate-600" />} />
            <StatCard title="合规" value={formatNumber(stats.compliant)} icon={<CheckCircle2 className="h-5 w-5 text-emerald-600" />} valueClassName="text-emerald-600" />
            <StatCard title="不合规" value={formatNumber(stats.non_compliant)} icon={<AlertTriangle className="h-5 w-5 text-red-600" />} valueClassName="text-red-600" />
            <StatCard title="错误" value={formatNumber(stats.error)} icon={<XCircle className="h-5 w-5 text-amber-600" />} valueClassName="text-amber-600" />
            <StatCard title="合规率" value={formatNumber(stats.rate, '%')} icon={<FileCheck2 className="h-5 w-5 text-cyan-600" />} valueClassName="text-cyan-600" />
            <StatCard title="VLM 队列" value={formatNumber(stats.queue)} icon={<Clock3 className="h-5 w-5 text-slate-600" />} />
            <StatCard title="今日花费" value={`¥${stats.budget?.spent_yuan ?? 0}`} icon={<CircleDollarSign className="h-5 w-5 text-slate-600" />} />
          </div>
        </TabsContent>

        <TabsContent value="roi" className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <div>
                <CardTitle className="text-lg">工位 ROI 绘制</CardTitle>
                <p className="mt-1 text-sm text-slate-500">拖拽画出安检员与被检人所在工位区域，保存后由后端自动热加载。</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" className="gap-2" onClick={handleAddRoi}>
                  <Plus className="h-4 w-4" />
                  新增
                </Button>
                <Button variant="outline" size="sm" className="gap-2" onClick={handleDeleteRoi} disabled={!currentRoi}>
                  <Trash2 className="h-4 w-4" />
                  删除
                </Button>
                <Button size="sm" className="gap-2" onClick={handleSaveRois} disabled={!isAdmin || savingRoi}>
                  <Save className="h-4 w-4" />
                  {savingRoi ? '保存中' : '保存'}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
              <div ref={stageRef} className="relative overflow-hidden rounded-lg bg-slate-950">
                <img
                  ref={imageRef}
                  src={activeVideoUrl}
                  alt="ROI 绘制画面"
                  className="w-full select-none object-contain"
                  draggable={false}
                  onLoad={(event) => {
                    const rect = event.currentTarget.getBoundingClientRect()
                    setImageSize({ width: rect.width, height: rect.height })
                  }}
                />
                <div
                  className="absolute inset-0 cursor-crosshair touch-none"
                  onPointerDown={handlePointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                  onPointerCancel={() => {
                    setDrawing(false)
                    setDraftRect(null)
                  }}
                >
                  {renderRoiBoxes()}
                  {draftRect && (
                    <div
                      className="pointer-events-none absolute rounded-md border-2 border-blue-500 bg-blue-500/20"
                      style={{
                        left: draftRect.left,
                        top: draftRect.top,
                        width: draftRect.width,
                        height: draftRect.height,
                      }}
                    />
                  )}
                </div>
              </div>

              <div className="space-y-3">
                {roiMessage && <div className="rounded-lg border bg-slate-50 px-3 py-2 text-sm text-slate-600">{roiMessage}</div>}
                <div className="space-y-2">
                  {slotNames.map((name, index) => {
                    const roi = rois[name]
                    const color = ROI_COLORS[index % ROI_COLORS.length]
                    return (
                      <button
                        key={name}
                        type="button"
                        className={cn(
                          'flex w-full items-center gap-3 rounded-lg border p-3 text-left transition',
                          currentRoi === name ? 'border-blue-500 bg-blue-50' : 'hover:bg-slate-50',
                        )}
                        onClick={() => setCurrentRoi(name)}
                      >
                        <span className="h-4 w-4 rounded" style={{ backgroundColor: color }} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-semibold text-slate-900">{name}</span>
                          <span className="block truncate text-xs text-slate-500">{roi ? `[${normalizeRoi(roi).join(', ')}]` : '未设置'}</span>
                        </span>
                      </button>
                    )
                  })}
                  {slotNames.length === 0 && (
                    <div className="rounded-lg border border-dashed p-8 text-center text-sm text-slate-500">暂无 ROI，请新增后绘制。</div>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
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
  value: string
  icon: ReactNode
  valueClassName?: string
}) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between gap-3 p-4">
        <div>
          <p className="text-sm text-slate-500">{title}</p>
          <p className={cn('mt-1 text-2xl font-bold text-slate-900', valueClassName)}>{value}</p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100">{icon}</div>
      </CardContent>
    </Card>
  )
}

const PAGE_SIZE_OPTIONS = [10, 20, 50]

function HistoryTable({ items }: { items: SecurityVlmHistoryItem[] }) {
  const [pageSize, setPageSize] = useState(10)
  const [currentPage, setCurrentPage] = useState(1)

  const total = items.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const safePage = Math.min(currentPage, totalPages)
  const startIndex = (safePage - 1) * pageSize
  const pageItems = items.slice(startIndex, startIndex + pageSize)

  useEffect(() => {
    setCurrentPage((prev) => Math.min(prev, totalPages))
  }, [total, pageSize, totalPages])

  const pageNumbers = useMemo(() => {
    const pages: (number | 'ellipsis')[] = []
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i += 1) pages.push(i)
    } else if (safePage <= 4) {
      for (let i = 1; i <= 5; i += 1) pages.push(i)
      pages.push('ellipsis')
      pages.push(totalPages)
    } else if (safePage >= totalPages - 3) {
      pages.push(1)
      pages.push('ellipsis')
      for (let i = totalPages - 4; i <= totalPages; i += 1) pages.push(i)
    } else {
      pages.push(1)
      pages.push('ellipsis')
      for (let i = safePage - 1; i <= safePage + 1; i += 1) pages.push(i)
      pages.push('ellipsis')
      pages.push(totalPages)
    }
    return pages
  }, [safePage, totalPages])

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <CardTitle className="text-lg">历史判定结果</CardTitle>
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span>
            共 {total} 条，第 {total > 0 ? safePage : 0}/{totalPages} 页
          </span>
          <Select
            value={String(pageSize)}
            onValueChange={(value) => {
              setPageSize(Number(value))
              setCurrentPage(1)
            }}
          >
            <SelectTrigger className="h-8 w-[5.5rem]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((size) => (
                <SelectItem key={size} value={String(size)}>
                  {size} 条/页
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>时间</TableHead>
              <TableHead>Session</TableHead>
              <TableHead>工位</TableHead>
              <TableHead>时长</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>上身</TableHead>
              <TableHead>中段</TableHead>
              <TableHead>下身</TableHead>
              <TableHead>抬手</TableHead>
              <TableHead>说明</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageItems.map((item) => (
              <TableRow key={`${item.session_id}-${item.time}`}>
                <TableCell className="text-slate-500">{item.time || '-'}</TableCell>
                <TableCell className="font-mono text-xs">{item.session_id || '-'}</TableCell>
                <TableCell>{item.roi_name || '-'}</TableCell>
                <TableCell>{item.duration_sec ?? 0}s</TableCell>
                <TableCell>{statusBadge(item.status)}</TableCell>
                <TableCell>{boolMark(item.upper_checked)}</TableCell>
                <TableCell>{boolMark(item.middle_checked)}</TableCell>
                <TableCell>{boolMark(item.lower_checked)}</TableCell>
                <TableCell>{boolMark(item.arms_open)}</TableCell>
                <TableCell className="max-w-md whitespace-normal">{item.reason || item.error || '-'}</TableCell>
              </TableRow>
            ))}
            {items.length === 0 && (
              <TableRow>
                <TableCell colSpan={10} className="py-10 text-center text-slate-500">
                  暂无历史判定结果
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>

        {totalPages > 1 && (
          <Pagination>
            <PaginationContent>
              <PaginationItem>
                <PaginationPrevious
                  href="#"
                  onClick={(event) => {
                    event.preventDefault()
                    setCurrentPage((prev) => Math.max(1, prev - 1))
                  }}
                  aria-disabled={safePage === 1}
                  className={cn(safePage === 1 && 'pointer-events-none opacity-50')}
                />
              </PaginationItem>
              {pageNumbers.map((page, index) =>
                page === 'ellipsis' ? (
                  <PaginationItem key={`ellipsis-${index}`}>
                    <PaginationEllipsis />
                  </PaginationItem>
                ) : (
                  <PaginationItem key={page}>
                    <PaginationLink
                      href="#"
                      isActive={page === safePage}
                      onClick={(event) => {
                        event.preventDefault()
                        setCurrentPage(page)
                      }}
                    >
                      {page}
                    </PaginationLink>
                  </PaginationItem>
                ),
              )}
              <PaginationItem>
                <PaginationNext
                  href="#"
                  onClick={(event) => {
                    event.preventDefault()
                    setCurrentPage((prev) => Math.min(totalPages, prev + 1))
                  }}
                  aria-disabled={safePage === totalPages}
                  className={cn(safePage === totalPages && 'pointer-events-none opacity-50')}
                />
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        )}
      </CardContent>
    </Card>
  )
}

export default SecurityVlmSection
