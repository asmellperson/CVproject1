import { getEnabledFeatureCameras } from '@/lib/feature-cameras'
import { useState, type ReactNode } from 'react'
import { AlertTriangle, Bell, Box, Camera, CheckCircle2, Clock3, Columns2, Crosshair, FileCheck2, Layers3, Settings2 } from 'lucide-react'
import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { apiGet } from '@/lib/api'
import type { AiVisionCamera } from '@/lib/aivision'
import { getInspectionHistory, getInspectionStatus, INSPECTION_FEATURE, type InspectionHistory as History, type InspectionStatus } from '@/lib/security-inspection'
import { FeatureCameraManager } from '@/components/FeatureCameraManager'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { DetectionConfigTabs } from '@/components/detection/DetectionConfigTabs'
import { DetectionConfigTab } from '@/components/detection/DetectionConfigUi'
import { InspectionConfiguration } from '@/components/security-inspection/InspectionConfiguration'
import { InspectionModelConfig } from '@/components/security-inspection/InspectionModelConfig'
import { useInspectionConfig } from '@/components/security-inspection/useInspectionConfig'
import { InspectionHistory } from '@/components/security-inspection/InspectionHistory'
import { SecurityVideoPanel } from '@/components/security-inspection/SecurityVideoPanel'
import { inspectionStatusPresentation } from '@/components/security-inspection/statusPresentation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

export function SecurityVlmSection({ department }: { department: DepartmentId }) {
  return <InspectionPage key={department} department={department} />
}

function InspectionPage({ department }: { department: DepartmentId }) {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [configTab, setConfigTab] = useState('camera')
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [selected, setSelected] = useState('')
  const [status, setStatus] = useState<InspectionStatus | null>(null)
  const [stats, setStats] = useState<History['stats'] | null>(null)
  const [retentionDays, setRetentionDays] = useState(31)
  const [error, setError] = useState('')
  const [singleView, setSingleView] = useState(false)
  const [configVersion, setConfigVersion] = useState(0)
  const enabled = getEnabledFeatureCameras(cameras, INSPECTION_FEATURE, department)
  const current = enabled.find((camera) => camera.shm_name === selected) || enabled[0]
  const configuration = useInspectionConfig(current?.shm_name || '', configVersion)
  useSerialPoll(async (signal) => {
    const [nextCameras, nextStatus, history] = await Promise.all([
      apiGet<AiVisionCamera[]>(`/cameras?department=${encodeURIComponent(department)}`, { signal }),
      getInspectionStatus(department, signal), getInspectionHistory(department, 1, 0, undefined, signal),
    ])
    if (signal.aborted) return
    setCameras(nextCameras); setStatus(nextStatus); setStats(history.stats); setError('')
    setRetentionDays(history.retention_days)
  }, { intervalMs: 2000, timeoutMs: 10000, restartKey: department,
    onError: (cause) => setError(cause instanceof Error ? cause.message : String(cause)) })
  const refreshCameras = async (preferred?: string) => {
    const next = await apiGet<AiVisionCamera[]>(`/cameras?department=${encodeURIComponent(department)}`)
    setCameras(next)
    if (preferred !== undefined) setSelected(preferred)
    setConfigVersion((version) => version + 1)
  }
  const displayed = singleView ? (current && current.functions[INSPECTION_FEATURE] ? [current] : enabled.slice(0, 1)) : enabled
  const presentation = inspectionStatusPresentation(status, error)
  return <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
    <DetectionPageHeader title="安检流程规范检测" subtitle="实时查看安检画面、流程判定与工位配置。"
      departmentLabel={DEPARTMENT_LABELS[department]} monitorValue="dashboard"
      runtimeControl={<Badge variant={presentation.error ? 'destructive' : 'secondary'}>{presentation.label}</Badge>} />
    {presentation.error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">{presentation.error}</p>}
    {status?.vlm.last_success && <p className="text-xs text-slate-500 dark:text-slate-400">最近判定成功：{new Date(status.vlm.last_success).toLocaleString('zh-CN')}</p>}
    <TabsContent value="dashboard" className="mx-auto w-full space-y-6 2xl:w-[92%] 2xl:max-w-[120rem]">
      <Card className="overflow-hidden dark:border-slate-800 dark:bg-slate-900">
        <CardHeader className="flex flex-row items-center justify-between border-b bg-slate-50 dark:border-slate-800 dark:bg-slate-900">
          <CardTitle className="text-lg">安检检测概览</CardTitle>
          <Button variant="outline" size="sm" onClick={() => setSingleView(!singleView)} className="gap-2"><Columns2 className="h-4 w-4" />{singleView ? '多画面' : '单画面'}</Button>
        </CardHeader>
        <CardContent className="space-y-6 p-5 lg:p-6 2xl:space-y-8 2xl:p-8">
          <section className="space-y-3 2xl:space-y-4">
            <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100 2xl:text-lg">数据汇总 · 最近 {retentionDays} 天</h3>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 2xl:gap-4">
              <StatCard title="总 session" value={stats?.total ?? 0} icon={<Layers3 className="h-5 w-5 text-slate-600" />} />
              <StatCard title="合规" value={stats?.compliant ?? 0} icon={<CheckCircle2 className="h-5 w-5 text-emerald-600" />} valueClassName="text-emerald-600" />
              <StatCard title="不合规" value={stats?.non_compliant ?? 0} icon={<AlertTriangle className="h-5 w-5 text-red-600" />} valueClassName="text-red-600" />
              <StatCard title="合规率" value={`${stats?.rate ?? 0}%`} icon={<FileCheck2 className="h-5 w-5 text-cyan-600" />} valueClassName="text-cyan-600" />
              <StatCard title="VLM 队列" value={status?.queue ?? 0} icon={<Clock3 className="h-5 w-5 text-slate-600" />} />
            </div>
          </section>
          <section className="space-y-3 border-t pt-6 dark:border-slate-800 2xl:space-y-4 2xl:pt-8">
            <div className="flex items-center justify-between gap-4"><h3 className="text-base font-semibold text-slate-800 dark:text-slate-100 2xl:text-lg">安检画面</h3>
              {singleView && <Select value={displayed[0]?.shm_name || ''} onValueChange={setSelected}><SelectTrigger className="w-52"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
                <SelectContent>{enabled.map((camera) => <SelectItem key={camera.shm_name} value={camera.shm_name}>{camera.name}</SelectItem>)}</SelectContent></Select>}
            </div>
            <div className={cn('grid gap-4 2xl:gap-5', !singleView && enabled.length === 2 && 'lg:grid-cols-2', !singleView && enabled.length === 3 && 'md:grid-cols-2 xl:grid-cols-3', !singleView && enabled.length >= 4 && 'md:grid-cols-2')}>
              {displayed.map((camera) => <SecurityVideoPanel key={camera.shm_name} camera={camera} />)}
              {!displayed.length && <div className="flex aspect-video items-center justify-center rounded-lg bg-slate-950 text-sm text-slate-400">请在配置管理中选择摄像头并启用安检检测</div>}
            </div>
          </section>
        </CardContent>
      </Card>
      <InspectionHistory department={department} cameras={cameras} />
    </TabsContent>
    <TabsContent value="config" className="space-y-6">
      <DetectionConfigTabs value={configTab} onValueChange={setConfigTab} className="space-y-6"
        tabs={<><DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
          <DetectionConfigTab value="parameters" icon={Settings2}>检测参数</DetectionConfigTab><DetectionConfigTab value="roi" icon={Crosshair}>ROI 配置</DetectionConfigTab>
          <DetectionConfigTab value="model" icon={Box}>模型配置</DetectionConfigTab><DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab></>}>
        <TabsContent value="camera"><FeatureCameraManager cameras={cameras} feature={INSPECTION_FEATURE} department={department}
          currentCameraName={current?.shm_name || ''} onSelectCamera={setSelected} onCamerasChanged={refreshCameras} onConfigCopied={refreshCameras} /></TabsContent>
        <TabsContent value="model"><InspectionModelConfig /></TabsContent>
        {(['roi', 'parameters', 'alarm'] as const).map((tab) => <TabsContent key={tab} value={tab} className="space-y-4">
          <Select value={current?.shm_name || ''} onValueChange={setSelected}><SelectTrigger className="w-64"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
            <SelectContent>{enabled.map((camera) => <SelectItem key={camera.shm_name} value={camera.shm_name}>{camera.name}</SelectItem>)}</SelectContent></Select>
          {current ? <InspectionConfiguration key={`${current.shm_name}:${configVersion}`} cameraKey={current.shm_name} tab={tab} state={configuration} />
            : <p className="p-6 text-sm text-slate-500">请先添加摄像头</p>}
        </TabsContent>)}
      </DetectionConfigTabs>
    </TabsContent>
  </Tabs>
}

function StatCard({ title, value, icon, valueClassName }: { title: string; value: number | string; icon: ReactNode; valueClassName?: string }) {
  return <div className="flex min-w-0 items-center gap-3 rounded-xl border border-slate-200/80 bg-slate-50/70 px-4 py-3 dark:border-slate-800 dark:bg-slate-900 2xl:justify-center 2xl:gap-4 2xl:px-5 2xl:py-4">
    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white shadow-sm dark:bg-slate-800 2xl:h-12 2xl:w-12">{icon}</div>
    <div className="min-w-0"><p className="truncate text-base font-semibold text-slate-700 2xl:text-lg">{title}</p>
      <p className={cn('mt-0.5 text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100 2xl:text-3xl', valueClassName)}>{value}</p></div>
  </div>
}
