import { getEnabledFeatureCameras } from '@/lib/feature-cameras'
import type { DepartmentId } from '@/auth/permissions'
import type { ReactNode } from 'react'
import { Camera, ScanFace, Users, Video } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { MonitorCameraToolbar } from '@/components/monitor/MonitorCameraToolbar'
import { getAiVisionCameraKey, type AiVisionCamera } from '@/lib/aivision'
import { StatCard } from '@/components/feature_dashboard/FeatureDashboardMonitorView'
import { FACE_FEATURE } from './api'
import { freshFaceDetections, useFaceRecognitionStatus } from './useFaceRecognitionStatus'

const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'

export function FaceRecognitionMonitorView({
  department, cameras, selectedCamera, loading, message, frameConnected, frameContent, onSelectCamera, onRefreshCameras,
}: {
  department: DepartmentId
  cameras: AiVisionCamera[]
  selectedCamera: string
  loading: boolean
  message: string
  frameConnected: boolean
  frameContent: ReactNode
  onSelectCamera: (key: string) => void
  onRefreshCameras: () => void
}) {
  const featureCameras = getEnabledFeatureCameras(cameras, FACE_FEATURE, department)
  const camera = featureCameras.find((item) => getAiVisionCameraKey(item) === selectedCamera)
  const result = useFaceRecognitionStatus(selectedCamera, Boolean(camera))
  const status = result?.status
  const detections = camera?.enabled ? freshFaceDetections(status) : []
  const online = Boolean(camera?.enabled && (status ? status.online : frameConnected))
  const allowed = detections.filter((face) => face.is_allowed).length
  const unauthorized = detections.filter((face) => face.matched && !face.is_allowed).length
  const unknown = detections.filter((face) => !face.matched).length
  const alarm = Boolean(status?.alarm && detections.length)
  return (
    <div className="space-y-5">
      <ResizableMonitorLayout id="face-recognition" summary={
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="人脸识别实时状态">
          <StatCard label="摄像头状态" value={online ? '在线' : '离线'} detail={camera?.name || '未选择摄像头'} icon={Video} tone={online ? 'emerald' : 'rose'} ping={online} />
          <StatCard label="启用摄像头" value={`${featureCameras.length} 路`} detail="已启用人脸身份识别" icon={Camera} tone="indigo" />
          <StatCard label="当前检测人脸" value={`${detections.length} 人`} detail="当前有效识别结果" icon={Users} tone="indigo" />
          <StatCard label="通行权限状态" value={alarm ? '未授权人员报警' : detections.length ? '允许通行' : '等待识别'} detail={`允许 ${allowed} / 未授权 ${unauthorized} / 未知 ${unknown}`} icon={ScanFace} tone={alarm ? 'rose' : 'emerald'} ping={alarm} />
        </section>
      }>
        <div className="space-y-5">
          <Card className={CARD_CLASS}>
            <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><ScanFace className="h-4 w-4" />当前识别结果</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-4 pb-4 sm:px-5 sm:pb-5">
              <p className="text-sm text-slate-500 dark:text-slate-400">允许 {allowed} 人 · 未授权 {unauthorized} 人 · 未知 {unknown} 人</p>
              {alarm && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-400">报警：当前画面存在{unauthorized ? '未授权人员' : '未知人员'}。</p>}
              {detections.map((face, index) => (
                <div key={index} className={`flex items-center justify-between gap-2 rounded-xl border p-3 ${face.is_allowed ? 'border-emerald-200 dark:border-emerald-900' : face.matched ? 'border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/40' : 'border-orange-300 bg-orange-50 dark:border-orange-900 dark:bg-orange-950/40'}`}>
                  <div className="min-w-0"><span className="break-words font-medium text-slate-950 dark:text-slate-100">{face.matched ? face.person_name : '未知人员'}</span>
                    <Badge variant="outline" className={`ml-2 ${face.is_allowed ? 'border-emerald-300 text-emerald-700 dark:border-emerald-800 dark:text-emerald-400' : face.matched ? 'border-red-300 text-red-700 dark:border-red-800 dark:text-red-400' : 'border-orange-300 text-orange-700 dark:border-orange-800 dark:text-orange-400'}`}>{face.is_allowed ? '允许人员' : face.matched ? '未授权人员' : '未知人员'}</Badge>
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
        <Card className={`${CARD_CLASS} gap-0 overflow-hidden py-0`}>
          <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3"><CardTitle className="flex items-center justify-between gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><span className="flex items-center gap-2"><Video className="h-4 w-4" />人脸身份识别监控</span><span className="text-sm font-normal text-slate-500 dark:text-slate-400">{frameConnected ? '实时画面' : '等待连接'}</span></CardTitle></CardHeader>
          <CardContent className="p-0">
            <MonitorCameraToolbar
              cameras={featureCameras}
              selectedCamera={selectedCamera}
              loading={loading}
              onSelectCamera={onSelectCamera}
              onRefreshCameras={onRefreshCameras}
            />
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
