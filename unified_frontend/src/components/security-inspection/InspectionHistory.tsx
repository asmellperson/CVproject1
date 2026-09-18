import { useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import type { AiVisionCamera } from '@/lib/aivision'
import { getInspectionHistory, type InspectionHistory as History } from '@/lib/security-inspection'
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
  useSerialPoll(async (signal) => {
    const next = await getInspectionHistory(department, size, page * size, cameraId === 'all' ? undefined : Number(cameraId), signal)
    if (!signal.aborted) { setData(next); setError('') }
  }, { intervalMs: 4000, timeoutMs: 10000, restartKey: `${department}:${page}:${size}:${cameraId}`,
    onError: (cause) => setError(cause instanceof Error ? cause.message : String(cause)) })
  const status = { compliant: '合规', non_compliant: '不合规', error: '判定失败', cancelled: '已取消' }
  return <Card>
    <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <CardTitle className="text-lg">历史判定结果</CardTitle>
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
        {['时间', '摄像头', '工位', '时长', '判定', '原因'].map((name) => <TableHead key={name}>{name}</TableHead>)}
      </TableRow></TableHeader><TableBody>
        {data?.items.map((item) => <TableRow key={item.session_id}>
          <TableCell className="whitespace-nowrap">{item.started_at.replace('T', ' ')}</TableCell>
          <TableCell>{item.camera_name}</TableCell><TableCell>{item.roi_name}</TableCell>
          <TableCell>{item.duration_sec.toFixed(1)} 秒</TableCell>
          <TableCell><Badge variant={item.status === 'non_compliant' ? 'destructive' : 'secondary'} className={item.status === 'compliant' ? 'bg-emerald-600 text-white' : ''}>{status[item.status]}</Badge></TableCell>
          <TableCell className="max-w-xl whitespace-normal">{item.error || item.verdict?.reason || '—'}</TableCell>
        </TableRow>)}
        {!data?.items.length && <TableRow><TableCell colSpan={6} className="h-24 text-center text-slate-500">{data ? '暂无判定结果' : '加载中…'}</TableCell></TableRow>}
      </TableBody></Table>
      <div className="mt-4 flex items-center justify-between gap-3 text-sm text-slate-500">
        <span>共 {data?.stats.total ?? 0} 条</span>
        <div className="flex items-center gap-3">
          <Select value={String(size)} onValueChange={(value) => { setSize(Number(value)); setPage(0); setData(null) }}>
            <SelectTrigger className="w-28"><SelectValue /></SelectTrigger><SelectContent>{[10,20,50].map((value) => <SelectItem key={value} value={String(value)}>{value} 条 / 页</SelectItem>)}</SelectContent>
          </Select>
          <Button variant="outline" disabled={page === 0} onClick={() => { setPage(page - 1); setData(null) }}>上一页</Button>
          <span>{page + 1}</span>
          <Button variant="outline" disabled={!data || (page + 1) * size >= data.stats.total} onClick={() => { setPage(page + 1); setData(null) }}>下一页</Button>
        </div>
      </div>
    </CardContent>
  </Card>
}
