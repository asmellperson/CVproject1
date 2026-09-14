import type { ReactNode } from 'react'
import { Camera, RefreshCw, ScanFace, Users, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { getAiVisionCameraKey, isAiVisionFeatureEnabled, type AiVisionCamera } from '@/lib/aivision'
import { StatCard } from '@/components/feature_dashboard/FeatureDashboardMonitorView'
import { FACE_FEATURE } from './api'
import { freshFaceDetections, useFaceRecognitionStatus } from './useFaceRecognitionStatus'

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
  const featureCameras = cameras.filter((camera) => isAiVisionFeatureEnabled(camera, FACE_FEATURE))
  const camera = featureCameras.find((item) => getAiVisionCameraKey(item) === selectedCamera)
  const result = useFaceRecognitionStatus(selectedCamera, Boolean(camera))
  const status = result?.status
  const detections = camera?.enabled ? freshFaceDetections(status) : []
  const online = Boolean(camera?.enabled && (status ? status.online : frameConnected))
  const known = detections.filter((face) => face.matched).length
  const unknown = detections.filter((face) => !face.matched).length
  return (
    <div className="space-y-5">
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4" aria-label="人脸识别实时状态">
        <StatCard label="摄像头状态" value={online ? '在线' : '离线'} detail={camera?.name || '未选择摄像头'} icon={Video} tone={online ? 'emerald' : 'rose'} ping={online} />
        <StatCard label="启用摄像头" value={`${featureCameras.length} 路`} detail="已启用人脸身份识别" icon={Camera} tone="indigo" />
        <StatCard label="当前检测人脸" value={`${detections.length} 人`} detail="当前有效识别结果" icon={Users} tone="indigo" />
        <StatCard label="当前识别结果" value={`已识别 ${known} / 未知 ${unknown}`} detail="当前画面身份比对" icon={ScanFace} tone={unknown ? 'amber' : 'emerald'} />
      </section>
      <ResizableMonitorLayout id="face-recognition">
        <div className="space-y-5">
          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><Camera className="h-4 w-4" />监控对象</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-5 pb-5">
              <Label htmlFor="identity-monitor-camera">摄像头</Label>
              <Select value={selectedCamera} onValueChange={onSelectCamera} disabled={loading || !featureCameras.length}>
                <SelectTrigger id="identity-monitor-camera" className="w-full rounded-xl border-slate-200 bg-slate-50/60 dark:border-slate-700 dark:bg-slate-950/60"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
                <SelectContent>{featureCameras.map((camera) => <SelectItem key={camera.id} value={getAiVisionCameraKey(camera)}>{camera.name}{!camera.enabled ? '（摄像头已停用）' : ''}</SelectItem>)}</SelectContent>
              </Select>
              <Button variant="outline" className="w-full gap-2 rounded-xl border-slate-200 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300" disabled={loading} onClick={onRefreshCameras}><RefreshCw className="h-4 w-4" />刷新状态</Button>
            </CardContent>
          </Card>
          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><ScanFace className="h-4 w-4" />当前识别结果</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-5 pb-5">
              <p className="text-sm text-slate-500 dark:text-slate-400">已识别 {known} 人 · 未知 {unknown} 人</p>
              {detections.map((face, index) => (
                <div key={index} className="flex items-center justify-between gap-2 rounded-xl border border-slate-100 p-3 dark:border-slate-800">
                  <div className="min-w-0"><span className={face.matched ? 'font-medium text-emerald-700 dark:text-emerald-400' : 'font-medium text-amber-700 dark:text-amber-400'}>{face.matched ? face.person_name : '未知人员'}</span>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">工号：{face.matched ? face.job_no || '未提供' : '—'}</p>
                  </div>
                  <span className="shrink-0 font-mono text-sm" aria-label="相似度">{(face.similarity * 100).toFixed(1)}%</span>
                </div>
              ))}
              {!detections.length && <p className="text-sm text-slate-500 dark:text-slate-400">{status?.reason === 'normal' ? '当前画面未检测到人脸' : '等待有效识别结果'}</p>}
              {result?.error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{result.error}</p>}
            </CardContent>
          </Card>
        </div>
        <Card className={`${CARD_CLASS} overflow-hidden`}>
          <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center justify-between gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><span className="flex items-center gap-2"><Video className="h-4 w-4" />人脸身份识别监控</span><span className="text-sm font-normal text-slate-500 dark:text-slate-400">{frameConnected ? '实时画面' : '等待连接'}</span></CardTitle></CardHeader>
          <CardContent className="p-0">
            <div className="relative aspect-video overflow-hidden bg-slate-950">
              {frameContent}
            </div>
            <p className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{message}</p>
          </CardContent>
        </Card>
      </ResizableMonitorLayout>
    </div>
  )
}
