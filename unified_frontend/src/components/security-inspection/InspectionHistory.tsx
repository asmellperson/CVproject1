import { useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import type { AiVisionCamera } from '@/lib/aivision'
import { getInspectionHistory, inspectionImageUrl, type InspectionHistory as History, type InspectionSession } from '@/lib/security-inspection'
import { ImagePreviewDialog } from '@/components/ImagePreviewDialog'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export function InspectionHistory({ department, cameras }: { department: DepartmentId; cameras: AiVisionCamera[] }) {
  const [data, setData] = useState<History | null>(null)
  const [error, setError] = useState('')
  const [page, setPage] = useState(0)
  const [size, setSize] = useState(10)
  const [cameraId, setCameraId] = useState('all')
  const [preview, setPreview] = useState<InspectionSession | null>(null)
  useSerialPoll(async (signal) => {
    const next = await getInspectionHistory(department, size, page * size, cameraId === 'all' ? undefined : Number(cameraId), signal)
    if (signal.aborted) return
    // 取消会话仍留在历史中，分页必须包含这部分记录。
    const lastPage = Math.max(0, Math.ceil((next.stats.total + next.stats.cancelled) / size) - 1)
    if (page > lastPage) { setPage(lastPage); setData(null); setError(''); return }
    setData(next); setError('')
  }, { intervalMs: 4000, timeoutMs: 10000, restartKey: `${department}:${page}:${size}:${cameraId}`,
    onError: (cause) => setError(cause instanceof Error ? cause.message : String(cause)) })
  const recordCount = data ? data.stats.total + data.stats.cancelled : 0
  const status = { compliant: '合规', non_compliant: '不合规', error: '判定失败', cancelled: '已取消' }
  return <Card>
    <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <CardTitle className="text-lg">历史判定结果 · 最近 {data?.retention_days ?? 31} 天</CardTitle>
      <Select value={cameraId} onValueChange={(value) => { setCameraId(value); setPage(0); setData(null) }}>
        <SelectTrigger className="w-44"><SelectValue /></SelectTrigger><SelectContent>
          <SelectItem value="all">全部摄像头</SelectItem>
          {cameras.map((camera) => <SelectItem key={camera.camera_id} value={String(camera.camera_id)}>{camera.name}</SelectItem>)}
        </SelectContent>
      </Select>
    </CardHeader>
    <CardContent>
      {error && <p role="alert" className="mb-3 text-sm text-red-600">{error}</p>}
      <Table><TableHeader><TableRow>
        {['时间', '摄像头', '工位', '时长', '判定', '原因', '抓拍图像'].map((name) => <TableHead key={name}>{name}</TableHead>)}
      </TableRow></TableHeader><TableBody>
        {data?.items.map((item) => <TableRow key={item.session_id}>
          <TableCell className="whitespace-nowrap">{item.started_at.replace('T', ' ')}</TableCell>
          <TableCell>{item.camera_name}</TableCell><TableCell>{item.roi_name}</TableCell>
          <TableCell>{item.duration_sec.toFixed(1)} 秒</TableCell>
          <TableCell><Badge variant={item.status === 'non_compliant' ? 'destructive' : 'secondary'} className={item.status === 'compliant' ? 'bg-emerald-600 text-white' : ''}>{status[item.status]}</Badge></TableCell>
          <TableCell className="max-w-xl whitespace-normal">{item.error || item.verdict?.reason || '—'}</TableCell>
          <TableCell>{item.has_image ? <button type="button" aria-label="放大查看安检抓拍图像"
            className="block cursor-zoom-in overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700"
            onClick={() => setPreview(item)}>
            <img src={inspectionImageUrl(department, item.session_id)} alt="安检关键帧拼图" loading="lazy" className="h-16 w-28 object-cover" />
          </button> : <span className="text-slate-400">{item.status === 'non_compliant' ? '无留存图片' : '—'}</span>}</TableCell>
        </TableRow>)}
        {!data?.items.length && <TableRow><TableCell colSpan={7} className="h-24 text-center text-slate-500">{data ? '暂无判定结果' : error ? '读取失败' : '加载中…'}</TableCell></TableRow>}
      </TableBody></Table>
      <div className="mt-4 flex items-center justify-between gap-3 text-sm text-slate-500">
        <span>共 {recordCount} 条{data && data.stats.cancelled > 0 && `（含取消 ${data.stats.cancelled} 条）`}</span>
        <div className="flex items-center gap-3">
          <Select value={String(size)} onValueChange={(value) => { setSize(Number(value)); setPage(0); setData(null) }}>
            <SelectTrigger className="w-28"><SelectValue /></SelectTrigger><SelectContent>{[10,20,50].map((value) => <SelectItem key={value} value={String(value)}>{value} 条 / 页</SelectItem>)}</SelectContent>
          </Select>
          <Button variant="outline" disabled={page === 0} onClick={() => { setPage(page - 1); setData(null) }}>上一页</Button>
          <span>{page + 1}</span>
          <Button variant="outline" disabled={!data || (page + 1) * size >= recordCount} onClick={() => { setPage(page + 1); setData(null) }}>下一页</Button>
        </div>
      </div>
    </CardContent>
    {preview && <ImagePreviewDialog src={inspectionImageUrl(department, preview.session_id)}
      title={`${preview.camera_name} · 安检抓拍图像`} filename={`inspection-${preview.session_id}.jpg`}
      onClose={() => setPreview(null)} />}
  </Card>
}
