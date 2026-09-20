import { lazy, Suspense } from 'react'
import { Bell, Box, Camera, MousePointer2, SlidersHorizontal, Webhook } from 'lucide-react'
import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { useAuth } from '@/auth/useAuth'
import { AiVisionMonitor } from '@/components/AiVisionMonitor'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { FeatureCameraManager } from '@/components/FeatureCameraManager'
import { AgvDetectionParameters, AgvHttpConfig } from '@/components/agv_person_check/AgvPersonCheckForm'
import { AGV_FEATURE } from '@/components/agv_person_check/config'
import { useAgvPersonCheckConfig } from '@/components/agv_person_check/useAgvPersonCheckConfig'
import { DetectionConfigTab, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { DetectionConfigTabs } from '@/components/detection/DetectionConfigTabs'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { FeatureConfigGate } from '@/components/detection/FeatureConfigGate'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { normalizeFeatureAlarmConfig } from '@/lib/alarm-config'

const AiVisionRoiEditor = lazy(() => import('@/components/AiVisionRoiEditor').then((module) => ({ default: module.AiVisionRoiEditor })))
const AiVisionModelConfig = lazy(() => import('@/components/AiVisionModelConfig').then((module) => ({ default: module.AiVisionModelConfig })))

export function AgvPersonCheckSection({ department }: { department: DepartmentId }) {
  const { isAdmin } = useAuth()
  const { cameras, enabledCameras, cameraKey, form, loading, saving, message, updateForm, save, reload, selectCamera } = useAgvPersonCheckConfig(department, isAdmin)
  const readOnly = !isAdmin || loading || saving || !form
  const saveBar = <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={readOnly}
    onReload={() => void reload()} onSave={save} />

  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader title="AGV无人运货检测" subtitle="实时查看摄像头画面；收到 HTTP 请求后检测，返回结果后结束本次检测。"
          departmentLabel={DEPARTMENT_LABELS[department]} />
        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="AGV无人运货检测监控" feature={AGV_FEATURE} department={department} presentation="feature-dashboard" rawPreview />
        </TabsContent>
        <TabsContent value="config" className="mt-0 space-y-6">
          <DetectionConfigTabs defaultValue="camera" className="space-y-6" tabListClassName="lg:grid-cols-7" tabs={<>
            <DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
            <DetectionConfigTab value="params" icon={SlidersHorizontal}>检测参数</DetectionConfigTab>
            <DetectionConfigTab value="http" icon={Webhook}>HTTP 通信</DetectionConfigTab>
            <DetectionConfigTab value="roi" icon={MousePointer2}>ROI 配置</DetectionConfigTab>
            <DetectionConfigTab value="model" icon={Box}>模型配置</DetectionConfigTab>
            <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab>
          </>}>
            {!form && <p role="status" className="text-sm text-slate-500 dark:text-slate-400">{message}</p>}
            <TabsContent value="camera" className="mt-0 space-y-6">
              <FeatureCameraManager cameras={cameras} feature={AGV_FEATURE} department={department} currentCameraName={cameraKey}
                disabled={!isAdmin || loading || saving} onSelectCamera={selectCamera} onCamerasChanged={reload} onConfigCopied={reload} />
            </TabsContent>
            <TabsContent value="params" className="mt-0 space-y-6">
              <FeatureConfigGate cameraKey={cameraKey} disabled={readOnly}>
                {form && <AgvDetectionParameters form={form} disabled={readOnly} onChange={updateForm}
                  cameras={enabledCameras} cameraKey={cameraKey} onSelectCamera={selectCamera} />}
                {saveBar}
              </FeatureConfigGate>
            </TabsContent>
            <TabsContent value="http" className="mt-0 space-y-6">
              <FeatureConfigGate cameraKey={cameraKey} disabled={readOnly}>
                {form && <AgvHttpConfig form={form} disabled={readOnly} onChange={updateForm} />}
                {saveBar}
              </FeatureConfigGate>
            </TabsContent>
            <TabsContent value="roi" className="mt-0 space-y-6">
              <FeatureConfigGate cameraKey={cameraKey} disabled={readOnly}>
                {form && <Suspense fallback={<p role="status">正在加载 ROI 编辑器...</p>}>
                  <AiVisionRoiEditor key={cameraKey} title="AGV 人体检测 ROI 绘制" cameraKey={cameraKey} roiJson={form.roiJson}
                    disabled={readOnly} saving={saving} message={message}
                    onChange={(roiJson) => updateForm((current) => ({ ...current, roiJson }))} onSave={save} />
                </Suspense>}
              </FeatureConfigGate>
            </TabsContent>
            <TabsContent value="model" className="mt-0 space-y-6">
              <FeatureConfigGate cameraKey={cameraKey} disabled={readOnly}>
                <Suspense fallback={<p role="status">正在加载模型配置...</p>}>
                  <AiVisionModelConfig requiredModels={['yolo_human']} />
                </Suspense>
              </FeatureConfigGate>
            </TabsContent>
            <TabsContent value="alarm" className="mt-0 space-y-6">
              <FeatureConfigGate cameraKey={cameraKey} disabled={readOnly}>
                {form && <AlarmPushConfig alarmInterval={form.alarmInterval} alarm={form.alarm} disabled={readOnly}
                  saving={saving} message={message} onSave={save}
                  onAlarmIntervalChange={(alarmInterval) => updateForm((current) => ({ ...current, alarmInterval }))}
                  onChange={(alarm) => updateForm((current) => ({ ...current, alarm: normalizeFeatureAlarmConfig(alarm) }))} />}
              </FeatureConfigGate>
            </TabsContent>
          </DetectionConfigTabs>
        </TabsContent>
      </Tabs>
    </div>
  )
}
