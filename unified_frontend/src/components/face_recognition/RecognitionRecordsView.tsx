import { getEnabledFeatureCameras } from '@/lib/feature-cameras'
import type { DepartmentId } from '@/auth/permissions'
import { useEffect, useState } from 'react'
import { History, RefreshCw } from 'lucide-react'
import { ImagePreviewDialog } from '@/components/ImagePreviewDialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getAiVisionCameras, type AiVisionCamera } from '@/lib/aivision'
import { FACE_FEATURE, getRecognitionRecords, recognitionImageUrl, type RecognitionRecord, type RecognitionRecordPage } from './api'

export function RecognitionRecordsView({ department }: { department: DepartmentId }) {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [cameraId, setCameraId] = useState('')
  const [previewRecord, setPreviewRecord] = useState<RecognitionRecord | null>(null)
  const [page, setPage] = useState(1)
  const [revision, setRevision] = useState(0)
  const queryKey = `${department}:${cameraId}:${page}:${revision}`
  const [responseState, setResponseState] = useState<{ key: string; result: RecognitionRecordPage | null; error: string } | null>(null)
  const [cameraError, setCameraError] = useState('')
  const loading = responseState?.key !== queryKey
  const result = loading ? null : responseState.result
  const error = loading ? '' : responseState.error
  useEffect(() => {
    let cancelled = false
    getAiVisionCameras(department).then((items) => {
      if (!cancelled) {
        const featureCameras = getEnabledFeatureCameras(items, FACE_FEATURE, department)
        setCameras(featureCameras)
        setCameraId((current) => featureCameras.some((camera) => String(camera.camera_id) === current) ? current : '')
        setCameraError('')
      }
    }).catch((reason) => {
      if (!cancelled) setCameraError(`摄像头列表读取失败：${String(reason)}`)
    })
    return () => { cancelled = true }
  }, [department, revision])
  useEffect(() => {
    const controller = new AbortController()
    getRecognitionRecords(department, page, cameraId, controller.signal).then((value) => {
      if (!controller.signal.aborted) setResponseState({ key: queryKey, result: value, error: '' })
    }).catch((reason) => {
      if (!controller.signal.aborted) setResponseState({ key: queryKey, result: null, error: reason instanceof Error ? reason.message : String(reason) })
    })
    return () => controller.abort()
  }, [department, page, cameraId, queryKey])
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
            <thead className="bg-slate-50 text-slate-500 dark:bg-slate-950 dark:text-slate-400"><tr>{['识别时间', '摄像头', '姓名', '相似度', '截图'].map((title) => <th key={title} className="whitespace-nowrap px-4 py-3 font-medium">{title}</th>)}</tr></thead>
            <tbody>{result?.items.map((record) => <tr key={record.id} className="border-b border-slate-100 dark:border-slate-800">
              <td className="whitespace-nowrap px-4 py-3">{new Date(record.recognized_at).toLocaleString('zh-CN', { hour12: false })}</td>
              <td className="px-4 py-3">{cameras.find((camera) => camera.camera_id === record.camera_id)?.name || `摄像头 ${record.camera_id}`}</td>
              <td className="px-4 py-3">{record.person_name}</td>
              <td className="px-4 py-3 font-mono">{(record.similarity * 100).toFixed(1)}%</td>
              <td className="px-4 py-3">{record.image_url ? <button type="button" className="block cursor-zoom-in overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700" aria-label="放大查看识别截图" onClick={() => setPreviewRecord(record)}>
                <img src={recognitionImageUrl(record.image_url)} alt="识别截图" loading="lazy" className="h-16 w-28 object-cover" />
              </button> : <span className="text-slate-400">无截图</span>}</td>
            </tr>)}</tbody>
          </table>
          {!result?.items.length && <p className="py-10 text-center text-sm text-slate-500 dark:text-slate-400">{loading ? '正在读取识别记录…' : error ? '识别记录读取失败' : '暂无识别记录'}</p>}
        </div>
        <div className="flex items-center justify-between gap-3 text-sm text-slate-500 dark:text-slate-400">
          <span>共 {result?.total ?? 0} 条 · 第 {page} 页</span>
          <div className="flex gap-2"><Button variant="outline" disabled={loading || page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</Button><Button variant="outline" disabled={loading || !result || page * result.page_size >= result.total} onClick={() => setPage((value) => value + 1)}>下一页</Button></div>
        </div>
      </CardContent>
      {previewRecord?.image_url && <ImagePreviewDialog
        src={recognitionImageUrl(previewRecord.image_url)} title="识别截图" filename={`recognition-${previewRecord.id}.png`}
        onClose={() => setPreviewRecord(null)}
      />}
    </Card>
  )
}
