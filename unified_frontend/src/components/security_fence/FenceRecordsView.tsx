import { useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { apiGet, alarmImageUrl, type AlarmEvent } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ImagePreviewDialog } from '@/components/ImagePreviewDialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { FENCE_FEATURE } from './api'

export function FenceRecordsView({ department }: { department: DepartmentId }) {
  const [items, setItems] = useState<AlarmEvent[]>([])
  const [error, setError] = useState('')
  const [image, setImage] = useState<AlarmEvent | null>(null)
  useSerialPoll(async (signal) => {
    const params = new URLSearchParams({ department, feature: FENCE_FEATURE, limit: '100' })
    const result = await apiGet<{ items: AlarmEvent[] }>(`/alarms?${params}`, { signal, cache: 'no-store' })
    if (!signal.aborted) { setItems(result.items); setError('') }
  }, { restartKey: department, intervalMs: 3000, timeoutMs: 5000,
    onError: (cause) => { setItems([]); setError(String(cause)) } })
  return <Card className="rounded-2xl border-slate-200 dark:border-slate-800">
    <CardHeader><CardTitle>最近 100 条围栏报警</CardTitle></CardHeader><CardContent>
      {error && <p role="alert" className="text-red-600 dark:text-red-400">{error}</p>}
      <Table><TableHeader><TableRow><TableHead>时间</TableHead><TableHead>摄像头</TableHead><TableHead>报警类型</TableHead><TableHead>截图</TableHead></TableRow></TableHeader>
        <TableBody>{items.map((item) => <TableRow key={item.id}><TableCell>{item.created_at}</TableCell><TableCell>{item.camera_name}</TableCell><TableCell>{item.event_label}</TableCell><TableCell><Button variant="outline" onClick={() => setImage(item)}>查看</Button></TableCell></TableRow>)}</TableBody>
      </Table>{!items.length && !error && <p className="py-6 text-center text-slate-500">暂无围栏报警记录。</p>}
      {image && <ImagePreviewDialog src={alarmImageUrl(image.id)} title="围栏报警截图" filename={`围栏报警-${image.id}.png`} onClose={() => setImage(null)} />}
    </CardContent>
  </Card>
}
