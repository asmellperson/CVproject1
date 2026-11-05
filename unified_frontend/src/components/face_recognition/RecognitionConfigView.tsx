import { FeatureConfigGate } from '@/components/detection/FeatureConfigGate'
import { normalizeFeatureAlarmConfig } from '@/lib/alarm-config'
import type { DepartmentId } from '@/auth/permissions'
import { lazy, Suspense } from 'react'
import { Bell, Box, Camera, MousePointer2, SlidersHorizontal, UserCheck } from 'lucide-react'
import { FeatureCameraManager } from '@/components/FeatureCameraManager'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { DetectionConfigTabs } from '@/components/detection/DetectionConfigTabs'
import {
  DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader,
  DetectionConfigTab, DetectionSaveBar,
} from '@/components/detection/DetectionConfigUi'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TabsContent } from '@/components/ui/tabs'
import { FACE_FEATURE, facePersonPermissionsApi } from './api'
import { useRecognitionConfig } from './useRecognitionConfig'
import { FacePersonPermissions } from './FacePersonPermissions'

const AiVisionRoiEditor = lazy(() => import('@/components/AiVisionRoiEditor').then((module) => ({ default: module.AiVisionRoiEditor })))
const AiVisionModelConfig = lazy(() => import('@/components/AiVisionModelConfig').then((module) => ({ default: module.AiVisionModelConfig })))

export function RecognitionConfigView({ department }: { department: DepartmentId }) {
  const state = useRecognitionConfig(department)
  const alarm = state.config?.alarm
  return (
    <DetectionConfigTabs defaultValue="camera" className="space-y-6" tabListClassName="lg:grid-cols-7"
      tabs={<>
        <DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
        <DetectionConfigTab value="params" icon={SlidersHorizontal}>识别参数</DetectionConfigTab>
        <DetectionConfigTab value="persons" icon={UserCheck}>人员权限</DetectionConfigTab>
        <DetectionConfigTab value="roi" icon={MousePointer2}>ROI 配置</DetectionConfigTab>
        <DetectionConfigTab value="model" icon={Box}>模型配置</DetectionConfigTab>
        <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab>
      </>}
    >
      <TabsContent value="camera" className="space-y-4">
        <FeatureCameraManager cameras={state.cameras} feature={FACE_FEATURE} department={department}
          currentCameraName={state.cameraKey} disabled={state.disabled} onSelectCamera={state.selectCamera}
          onCamerasChanged={state.refreshCameras}
          onConfigCopied={(key) => {
            state.selectCamera(key)
            return state.loadConfig(key)
          }}
          />
        <p role="status" className="text-sm text-slate-500 dark:text-slate-400">{state.message}</p>
      </TabsContent>
      <TabsContent value="params" className="space-y-6">
        <FeatureConfigGate cameraKey={state.cameraKey} disabled={!state.canSave}>
        <Card className={DETECTION_CONFIG_CARD_CLASS}>
          <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="识别参数" description="对画面中的每张人脸分别比对；低于相似度阈值时显示未知人员。" />
          <DetectionConfigCardContent className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2"><Label htmlFor="identity-config-camera">摄像头</Label>
              <Select value={state.cameraKey} onValueChange={state.selectCamera} disabled={state.loading || state.saving || !state.enabledCameras.length}>
                <SelectTrigger id="identity-config-camera" className="w-full"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
                <SelectContent>{state.enabledCameras.map((camera) => <SelectItem key={camera.id} value={camera.shm_name}>{camera.name}{!camera.enabled ? '（摄像头已停用）' : ''}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            {([
              ['detectionThreshold', '人脸检测置信度阈值', '0', '1', '0.01'],
              ['threshold', '身份相似度阈值', '0', '1', '0.01'],
              ['interval', '采集间隔（秒）', '0.1', '1', '0.1'],
              ['cooldown', '识别记录冷却（秒）', '1', undefined, '1'],
            ] as const).map(([key, label, min, max, step]) => <div key={key} className="space-y-2">
              <Label htmlFor={`identity-${key}`}>{label}</Label><Input id={`identity-${key}`} type="number" min={min} max={max} step={step} value={state.form[key]} disabled={state.disabled || !state.cameraKey} onChange={(event) => state.setForm((form) => ({ ...form, [key]: event.target.value }))} />
            </div>)}
            <div className="flex items-center gap-3"><Switch id="identity-record-enabled" checked={state.form.recordEnabled} disabled={state.disabled || !state.cameraKey} onCheckedChange={(recordEnabled) => state.setForm((form) => ({ ...form, recordEnabled }))} /><Label htmlFor="identity-record-enabled">保存识别记录和截图</Label></div>
          </DetectionConfigCardContent>
        </Card>
        <DetectionSaveBar message={state.message} loading={state.loading} saving={state.saving} disabled={!state.canSave} onReload={() => state.loadConfig(state.cameraKey)} onSave={state.save} />

        </FeatureConfigGate></TabsContent>
      <TabsContent value="roi">
        <FeatureConfigGate cameraKey={state.cameraKey} disabled={!state.canSave}>
        <Suspense fallback={<p>正在加载 ROI 编辑器…</p>}><AiVisionRoiEditor title="人脸身份识别 ROI 绘制" cameraKey={state.cameraKey} roiJson={state.form.roi} disabled={!state.canSave} saving={state.saving} message={state.message} onChange={(roi) => state.setForm((form) => ({ ...form, roi }))} onSave={state.save} /></Suspense>

        </FeatureConfigGate></TabsContent>
      <TabsContent value="model">
        <FeatureConfigGate cameraKey={state.cameraKey} disabled={!state.canSave}><Suspense fallback={<p>正在加载模型配置…</p>}><AiVisionModelConfig requiredModels={['insightface']} /></Suspense>
        </FeatureConfigGate></TabsContent>
      <TabsContent value="alarm" className="space-y-6">
        <FeatureConfigGate cameraKey={state.cameraKey} disabled={!state.canSave}>
        <AlarmPushConfig alarm={alarm} alarmInterval={state.form.alarmInterval}
          onAlarmIntervalChange={(alarmInterval) => state.setForm((form) => ({ ...form, alarmInterval }))}
          disabled={!state.canSave} saving={state.saving} message={state.message}
          onChange={(value) => state.setAlarm(normalizeFeatureAlarmConfig(value))} onSave={state.save} />

        </FeatureConfigGate></TabsContent>
      <TabsContent value="persons"><FacePersonPermissions key={department} scope={department} permissions={facePersonPermissionsApi} /></TabsContent>
    </DetectionConfigTabs>
  )
}
