import { useEffect, useState } from 'react'
import { History, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getAiVisionCameras, type AiVisionCamera } from '@/lib/aivision'
import { FACE_DEPARTMENT, getRecognitionRecords, type RecognitionRecordPage } from './api'

export function RecognitionRecordsView() {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [cameraId, setCameraId] = useState('')
  const [page, setPage] = useState(1)
  const [revision, setRevision] = useState(0)
  const queryKey = `${cameraId}:${page}:${revision}`
  const [responseState, setResponseState] = useState<{ key: string; result: RecognitionRecordPage | null; error: string } | null>(null)
  const [cameraError, setCameraError] = useState('')
  const loading = responseState?.key !== queryKey
  const result = loading ? null : responseState.result
  const error = loading ? '' : responseState.error
  useEffect(() => {
    let cancelled = false
    getAiVisionCameras(FACE_DEPARTMENT).then((items) => { if (!cancelled) setCameras(items) }).catch((reason) => {
      if (!cancelled) setCameraError(`摄像头列表读取失败：${String(reason)}`)
    })
    return () => { cancelled = true }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    getRecognitionRecords(page, cameraId, controller.signal).then((value) => {
      if (!controller.signal.aborted) setResponseState({ key: queryKey, result: value, error: '' })
    }).catch((reason) => {
      if (!controller.signal.aborted) setResponseState({ key: queryKey, result: null, error: reason instanceof Error ? reason.message : String(reason) })
    })
    return () => controller.abort()
  }, [page, cameraId, queryKey])
  return (
    <Card className="rounded-2xl border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <CardHeader className="flex flex-wrap items-center justify-between gap-3 sm:flex-row">
        <CardTitle className="flex items-center gap-2"><History className="h-5 w-5" />识别记录</CardTitle>
        <div className="flex flex-wrap gap-2">
          <Select value={cameraId || 'all'} onValueChange={(value) => { setCameraId(value === 'all' ? '' : value); setPage(1) }}>
            <SelectTrigger className="w-52" aria-label="按摄像头筛选识别记录"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">全部摄像头</SelectItem>{cameras.map((camera) => <SelectItem key={camera.id} value={String(camera.camera_id)}>{camera.name}</SelectItem>)}</SelectContent>
          </Select>
          <Button variant="outline" onClick={() => setRevision((value) => value + 1)} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" />刷新</Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        {cameraError && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{cameraError}</p>}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-slate-500 dark:bg-slate-950 dark:text-slate-400"><tr>{['识别时间', '摄像头', '姓名', '相似度'].map((title) => <th key={title} className="whitespace-nowrap px-4 py-3 font-medium">{title}</th>)}</tr></thead>
            <tbody>{result?.items.map((record) => <tr key={record.id} className="border-b border-slate-100 dark:border-slate-800">
              <td className="whitespace-nowrap px-4 py-3">{new Date(record.recognized_at).toLocaleString('zh-CN', { hour12: false })}</td>
              <td className="px-4 py-3">{cameras.find((camera) => camera.camera_id === record.camera_id)?.name || `摄像头 ${record.camera_id}`}</td>
              <td className="px-4 py-3">{record.person_name}</td>
              <td className="px-4 py-3 font-mono">{(record.similarity * 100).toFixed(1)}%</td>
            </tr>)}</tbody>
          </table>
          {!result?.items.length && <p className="py-10 text-center text-sm text-slate-500 dark:text-slate-400">{loading ? '正在读取识别记录…' : error ? '识别记录读取失败' : '暂无识别记录'}</p>}
        </div>
        <div className="flex items-center justify-between gap-3 text-sm text-slate-500 dark:text-slate-400">
          <span>共 {result?.total ?? 0} 条 · 第 {page} 页</span>
          <div className="flex gap-2"><Button variant="outline" disabled={loading || page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</Button><Button variant="outline" disabled={loading || !result || page * result.page_size >= result.total} onClick={() => setPage((value) => value + 1)}>下一页</Button></div>
        </div>
      </CardContent>
    </Card>
  )
}
