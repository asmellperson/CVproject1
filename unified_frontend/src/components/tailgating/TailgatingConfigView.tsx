import { lazy, Suspense } from 'react'
import { Bell, Box, Camera, MousePointer2, SlidersHorizontal, Waypoints } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { useAuth } from '@/auth/useAuth'
import { FeatureCameraManager } from '@/components/FeatureCameraManager'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { DetectionConfigTabs } from '@/components/detection/DetectionConfigTabs'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionConfigTab, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { FeatureConfigGate } from '@/components/detection/FeatureConfigGate'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TabsContent } from '@/components/ui/tabs'
import { normalizeFeatureAlarmConfig } from '@/lib/alarm-config'
import { NUMBER_FIELDS, TAILGATING_FEATURE } from './config'
import { useTailgatingConfig } from './useTailgatingConfig'

const AiVisionRoiEditor = lazy(() => import('@/components/AiVisionRoiEditor').then((module) => ({ default: module.AiVisionRoiEditor })))
const AiVisionModelConfig = lazy(() => import('@/components/AiVisionModelConfig').then((module) => ({ default: module.AiVisionModelConfig })))

export function TailgatingConfigView({ department }: { department: DepartmentId }) {
  const { isAdmin } = useAuth()
  const state = useTailgatingConfig(department, isAdmin)
  const { draft, cameraKey, loading, saving, message, update } = state
  const disabled = !isAdmin || loading || saving || !draft
  const save = () => { void state.save() }
  const saveBar = <DetectionSaveBar
    message={message}
    loading={loading}
    saving={saving}
    disabled={disabled}
    onReload={() => state.reload(cameraKey)}
    onSave={save} />
  return <DetectionConfigTabs
    defaultValue="camera"
    className="space-y-6"
    tabListClassName="lg:grid-cols-7"
    tabs={<>
      <DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
      <DetectionConfigTab value="params" icon={SlidersHorizontal}>检测参数</DetectionConfigTab>
      <DetectionConfigTab value="roi" icon={MousePointer2}>ROI 配置</DetectionConfigTab>
      <DetectionConfigTab value="line" icon={Waypoints}>计数线</DetectionConfigTab>
      <DetectionConfigTab value="model" icon={Box}>模型配置</DetectionConfigTab>
      <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab>
    </>}>
    <TabsContent value="camera" className="space-y-4">
      <FeatureCameraManager
        cameras={state.cameras}
        feature={TAILGATING_FEATURE}
        department={department}
        currentCameraName={cameraKey}
        disabled={!isAdmin || loading || saving}
        onSelectCamera={state.selectCamera}
        onCamerasChanged={state.reload}
        onConfigCopied={state.reload} />
      <p role="status" className="text-sm text-slate-500 dark:text-slate-400">{message}</p>
    </TabsContent>
    <TabsContent value="params" className="space-y-6">
      <FeatureConfigGate cameraKey={cameraKey} disabled={disabled}>
        <Card className={DETECTION_CONFIG_CARD_CLASS}>
          <DetectionConfigCardHeader
            icon={SlidersHorizontal}
            tone="emerald"
            title="非法闯闸判定"
            description="两个不同人员同向通过计数线，并在 ROI 内共同出现达到确认时间，才触发报警。" />
          <DetectionConfigCardContent className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="tailgating-camera">摄像头</Label>
              <Select value={cameraKey} onValueChange={state.selectCamera} disabled={loading || saving}>
                <SelectTrigger id="tailgating-camera">
                  <SelectValue placeholder="选择摄像头" />
                </SelectTrigger>
                <SelectContent>{state.enabledCameras.map((camera) => <SelectItem key={camera.id} value={camera.shm_name}>{camera.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            {draft && <>
              <div className="space-y-2">
                <Label htmlFor="tailgating-direction">监测方向</Label>
                <Select
                  value={String(draft.config.value.direction)}
                  disabled={disabled}
                  onValueChange={(direction) => update((current) => ({ ...current, config: { ...current.config, value: { ...current.config.value, direction: Number(direction) as -1 | 0 | 1 } } }))}>
                  <SelectTrigger id="tailgating-direction">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">沿计数线箭头方向</SelectItem>
                    <SelectItem value="-1">反向（箭头随配置调整）</SelectItem>
                    <SelectItem value="0">双向监测，分别判定</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {NUMBER_FIELDS.filter(([key]) => key !== 'alarm_interval').map(([key, label, min, max, step]) => <div className="space-y-2" key={key}>
                <Label htmlFor={`tailgating-${key}`}>{label}</Label>
                <Input
                  id={`tailgating-${key}`}
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  value={draft.numbers[key]}
                  disabled={disabled}
                  onChange={(event) => update((current) => ({ ...current, numbers: { ...current.numbers, [key]: event.target.value } }))} />
              </div>)}
            </>}
            <p className="text-sm text-slate-500 dark:text-slate-400 md:col-span-2">请先保存 ROI 和计数线，再在监控画面核对箭头。共同出现结束后，关联窗口用于等待双方完成过线；采样间隔过大或推理失败时重新建立通行状态。</p>
          </DetectionConfigCardContent>
        </Card>{saveBar}
      </FeatureConfigGate>
    </TabsContent>
    {(['roi', 'line'] as const).map((kind) => <TabsContent value={kind} key={kind}>
      <FeatureConfigGate cameraKey={cameraKey} disabled={disabled}>
        {draft && <Suspense fallback={<p>正在加载区域编辑器…</p>}>
          <AiVisionRoiEditor
            key={`${cameraKey}:${kind}`}
            title={kind === 'roi' ? '闸机通道 ROI' : '闸机通行计数线'}
            cameraKey={cameraKey}
            mode={kind === 'line' ? 'line' : 'polygon'}
            roiJson={draft[kind]}
            emptyRoiLabel="请绘制并保存，配置完整后开始检测"
            disabled={disabled}
            saving={saving}
            message={message}
            onChange={(value) => update((current) => ({ ...current, [kind]: value }))}
            onSave={save} />
        </Suspense>}
      </FeatureConfigGate>
    </TabsContent>)}
    <TabsContent value="model">
      <Suspense fallback={<p>正在加载模型配置…</p>}>
        <AiVisionModelConfig requiredModels={['yolo_human']} />
      </Suspense>
    </TabsContent>
    <TabsContent value="alarm">
      <FeatureConfigGate cameraKey={cameraKey} disabled={disabled}>
        {draft && <AlarmPushConfig
          key={cameraKey}
          alarm={draft.config.alarm}
          alarmInterval={draft.numbers.alarm_interval}
          disabled={disabled}
          saving={saving}
          message={message}
          onSave={save}
          onAlarmIntervalChange={(alarm_interval) => update((current) => ({ ...current, numbers: { ...current.numbers, alarm_interval } }))}
          onChange={(alarm) => update((current) => ({ ...current, config: { ...current.config, alarm: normalizeFeatureAlarmConfig(alarm) } }))} />}
        <p className="text-sm text-slate-500 dark:text-slate-400">同组人员的一次通行只记录一次，多人同行合并为同组事件；独立通行事件分别报警。截图、视频、喇叭和企业微信沿用平台统一报警配置。</p>
      </FeatureConfigGate>
    </TabsContent>
  </DetectionConfigTabs>
}
