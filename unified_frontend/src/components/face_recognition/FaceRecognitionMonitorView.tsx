import type { ReactNode } from 'react'
import { Camera, RefreshCw, ScanFace, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { getAiVisionCameraKey, type AiVisionCamera } from '@/lib/aivision'
import { useFaceRecognitionStatus } from './useFaceRecognitionStatus'

const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'

export function FaceRecognitionMonitorView({
  cameras, selectedCamera, loading, message, frameConnected, frameContent, onSelectCamera, onRefreshCameras,
}: {
  cameras: AiVisionCamera[]
  selectedCamera: string
  loading: boolean
  message: string
  frameConnected: boolean
  frameContent: ReactNode
  onSelectCamera: (key: string) => void
  onRefreshCameras: () => void
}) {
  const result = useFaceRecognitionStatus(selectedCamera, frameConnected)
  const status = result?.status
  const detections = status?.online && status.reason === 'normal' ? status.detections : []
  const known = detections.filter((face) => face.matched).length
  return (
    <ResizableMonitorLayout id="face-recognition">
      <div className="space-y-5">
        <Card className={CARD_CLASS}>
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Camera className="h-4 w-4" />监控对象</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Label htmlFor="identity-monitor-camera">摄像头</Label>
            <Select value={selectedCamera} onValueChange={onSelectCamera} disabled={loading || !cameras.length}>
              <SelectTrigger id="identity-monitor-camera" className="w-full"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
              <SelectContent>{cameras.map((camera) => <SelectItem key={camera.id} value={getAiVisionCameraKey(camera)}>{camera.name}</SelectItem>)}</SelectContent>
            </Select>
            <Button variant="outline" className="w-full gap-2" disabled={loading} onClick={onRefreshCameras}><RefreshCw className="h-4 w-4" />刷新状态</Button>
          </CardContent>
        </Card>
        <Card className={CARD_CLASS}>
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><ScanFace className="h-4 w-4" />当前识别结果</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-slate-500 dark:text-slate-400">已识别 {known} 人 · 未知 {detections.length - known} 人</p>
            {detections.map((face, index) => (
              <div key={index} className="flex items-center justify-between gap-2 rounded-xl border border-slate-100 p-3 dark:border-slate-800">
                <span className={face.matched ? 'font-medium text-emerald-700 dark:text-emerald-400' : 'font-medium text-amber-700 dark:text-amber-400'}>{face.person_name}</span>
                <span className="shrink-0 font-mono text-sm">{(face.similarity * 100).toFixed(1)}%</span>
              </div>
            ))}
            {!detections.length && <p className="text-sm text-slate-500 dark:text-slate-400">{status?.reason === 'normal' ? '当前画面未检测到人脸' : '等待有效识别结果'}</p>}
            {result?.error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{result.error}</p>}
          </CardContent>
        </Card>
      </div>
      <Card className={`${CARD_CLASS} overflow-hidden`}>
        <CardHeader><CardTitle className="flex items-center justify-between gap-2 text-base"><span className="flex items-center gap-2"><Video className="h-4 w-4" />人脸身份识别监控</span><span className="text-sm font-normal text-slate-500 dark:text-slate-400">{frameConnected ? '实时画面' : '等待连接'}</span></CardTitle></CardHeader>
        <CardContent className="p-0">
          <div className="relative aspect-video overflow-hidden bg-slate-950">
            {frameContent}
            {status?.frame_width && status.frame_height && (
              <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${status.frame_width} ${status.frame_height}`} preserveAspectRatio="xMidYMid meet" aria-label="人脸框、姓名和相似度">
                {detections.map((face, index) => {
                  const [x1, y1, x2, y2] = face.bbox
                  const color = face.matched ? '#34d399' : '#fbbf24'
                  const fontSize = Math.max(14, status.frame_width! / 65)
                  return <g key={index}>
                    <rect x={x1} y={y1} width={Math.max(0, x2 - x1)} height={Math.max(0, y2 - y1)} fill="none" stroke={color} strokeWidth="2" />
                    <text x={Math.max(0, x1)} y={Math.max(fontSize, y1 - 6)} fontSize={fontSize} fill={color} stroke="#0f172a" strokeWidth="3" paintOrder="stroke" fontWeight="600">{face.person_name} {(face.similarity * 100).toFixed(1)}%</text>
                  </g>
                })}
              </svg>
            )}
          </div>
          <p className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{message}</p>
        </CardContent>
      </Card>
    </ResizableMonitorLayout>
  )
}
