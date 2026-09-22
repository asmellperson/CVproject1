import { useRef, useState } from 'react'
import { Bell, Camera, MessageSquareText, MousePointer2, Settings2 } from 'lucide-react'
import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { AiVisionMonitor } from '@/components/AiVisionMonitor'
import { FeatureCameraManager } from '@/components/FeatureCameraManager'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { DetectionConfigTabs } from '@/components/detection/DetectionConfigTabs'
import { DetectionConfigTab } from '@/components/detection/DetectionConfigUi'
import { VisualLanguageConfiguration } from '@/components/visual_language_detection/VisualLanguageConfiguration'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { apiGet } from '@/lib/api'
import type { AiVisionCamera } from '@/lib/aivision'
import { getEnabledFeatureCameras } from '@/lib/feature-cameras'
import { VISUAL_LANGUAGE_FEATURE } from '@/lib/visual-language-detection'

export function VisualLanguageDetectionSection({ department }: { department: DepartmentId }) {
  return <VisualLanguagePage key={department} department={department} />
}

function VisualLanguagePage({ department }: { department: DepartmentId }) {
  const [activeTab, setActiveTab] = useState('monitor')
  const [configTab, setConfigTab] = useState('camera')
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  const [configVersion, setConfigVersion] = useState(0)
  const requestVersion = useRef(0)
  const enabled = getEnabledFeatureCameras(cameras, VISUAL_LANGUAGE_FEATURE, department)
  const current = enabled.find((camera) => camera.shm_name === selected) || enabled[0]
  const loadCameras = async (signal?: AbortSignal, preferred?: string) => {
    const version = ++requestVersion.current
    const next = await apiGet<AiVisionCamera[]>(`/cameras?department=${encodeURIComponent(department)}`, { signal })
    if (signal?.aborted || version !== requestVersion.current) return
    setCameras(next); setError('')
    if (preferred !== undefined) setSelected(preferred)
  }
  useSerialPoll((signal) => loadCameras(signal), {
    intervalMs: 3000, timeoutMs: 10000, enabled: activeTab === 'config', restartKey: department,
    onError: (cause) => setError(cause instanceof Error ? cause.message : String(cause)),
  })
  const refreshCameras = async (preferred?: string) => {
    await loadCameras(undefined, preferred)
    setConfigVersion((version) => version + 1)
  }
  return <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
    <DetectionPageHeader title="指令驱动智慧安防" subtitle="通过自然语言定义监控任务，持续理解视频场景，并在目标事件发生时自动触发告警。" departmentLabel={DEPARTMENT_LABELS[department]} />
    <TabsContent value="monitor">
      <AiVisionMonitor title="指令驱动智慧安防" feature={VISUAL_LANGUAGE_FEATURE} department={department} rawPreview presentation="visual-language" />
    </TabsContent>
    <TabsContent value="config" className="space-y-6">
      {error && <p role="alert" className="text-sm text-red-600 dark:text-red-300">{error}</p>}
      <DetectionConfigTabs value={configTab} onValueChange={setConfigTab} className="space-y-6"
        tabs={<><DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
          <DetectionConfigTab value="prompt" icon={MessageSquareText}>监控指令</DetectionConfigTab>
          <DetectionConfigTab value="roi" icon={MousePointer2}>ROI 配置</DetectionConfigTab>
          <DetectionConfigTab value="parameters" icon={Settings2}>推理参数</DetectionConfigTab>
          <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab></>}>
        <TabsContent value="camera"><FeatureCameraManager cameras={cameras} feature={VISUAL_LANGUAGE_FEATURE} department={department}
          currentCameraName={current?.shm_name || ''} onSelectCamera={setSelected} onCamerasChanged={refreshCameras} onConfigCopied={refreshCameras} /></TabsContent>
        {(['prompt', 'roi', 'parameters', 'alarm'] as const).map((tab) => <TabsContent key={tab} value={tab} className="space-y-4">
          <Select value={current?.shm_name || ''} onValueChange={setSelected} disabled={!enabled.length}>
            <SelectTrigger className="w-full sm:w-64" aria-label="配置摄像头"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
            <SelectContent>{enabled.map((camera) => <SelectItem key={camera.camera_id} value={camera.shm_name}>{camera.name}</SelectItem>)}</SelectContent>
          </Select>
          {current ? <VisualLanguageConfiguration key={`${current.shm_name}:${configVersion}`} cameraKey={current.shm_name} tab={tab} />
            : <p className="p-6 text-sm text-slate-500">请先在摄像头配置中为指令驱动智慧安防添加摄像头。</p>}
        </TabsContent>)}
      </DetectionConfigTabs>
    </TabsContent>
  </Tabs>
}
