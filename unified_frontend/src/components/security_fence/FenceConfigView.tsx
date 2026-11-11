import { lazy, Suspense } from 'react'
import { Bell, Box, Camera, MousePointer2, SlidersHorizontal, UserCheck } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { useDepartmentConfigAccess } from '@/auth/useDepartmentConfigAccess'
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
import { FENCE_FEATURE, NUMBER_FIELDS } from './api'
import { useFenceConfig } from './useFenceConfig'
import { FenceWhitelist } from './FenceWhitelist'

const AiVisionRoiEditor = lazy(() => import('@/components/AiVisionRoiEditor').then((module) => ({ default: module.AiVisionRoiEditor })))
const AiVisionModelConfig = lazy(() => import('@/components/AiVisionModelConfig').then((module) => ({ default: module.AiVisionModelConfig })))

export function FenceConfigView({ department }: { department: DepartmentId }) {
  const canConfigure = useDepartmentConfigAccess(department, FENCE_FEATURE)
  const state = useFenceConfig(department, canConfigure)
  const { draft, update, cameraKey, loading, saving, message } = state
  const disabled = !canConfigure || loading || saving || !draft
  const save = () => { void state.save() }
  const saveBar = <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={disabled} onReload={() => state.reload(cameraKey)} onSave={save} />
  return <DetectionConfigTabs defaultValue="camera" className="space-y-6" tabListClassName="lg:grid-cols-7" tabs={<>
    <DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
    <DetectionConfigTab value="params" icon={SlidersHorizontal}>时段与参数</DetectionConfigTab>
    <DetectionConfigTab value="persons" icon={UserCheck}>围栏白名单</DetectionConfigTab>
    <DetectionConfigTab value="roi" icon={MousePointer2}>ROI 配置</DetectionConfigTab>
    <DetectionConfigTab value="model" icon={Box}>模型配置</DetectionConfigTab>
    <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab>
  </>}>
    <TabsContent value="camera" className="space-y-4">
      <FeatureCameraManager cameras={state.cameras} feature={FENCE_FEATURE} department={department} currentCameraName={cameraKey}
        disabled={!canConfigure || loading || saving} onSelectCamera={state.selectCamera} onCamerasChanged={state.reload} onConfigCopied={state.reload} />
      <p role="status" className="text-sm text-slate-500 dark:text-slate-400">{message}</p>
    </TabsContent>
    <TabsContent value="params" className="space-y-6"><FeatureConfigGate cameraKey={cameraKey} disabled={disabled}>
      <Card className={DETECTION_CONFIG_CARD_CLASS}>
        <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="每日警戒规则" description="禁入时段内任何人出现均报警；其余时间仅允许白名单。起止相同表示全天禁止，结束早于开始表示跨午夜。" />
        <DetectionConfigCardContent className="grid gap-5 md:grid-cols-2">
          <div className="space-y-2"><Label htmlFor="fence-camera">摄像头</Label><Select value={cameraKey} onValueChange={state.selectCamera} disabled={loading || saving}>
            <SelectTrigger id="fence-camera"><SelectValue placeholder="选择摄像头" /></SelectTrigger><SelectContent>{state.enabledCameras.map((camera) => <SelectItem key={camera.id} value={camera.shm_name}>{camera.name}</SelectItem>)}</SelectContent>
          </Select></div>
          {draft && <>
            {([['forbidden_start', '禁止开始'], ['forbidden_end', '禁止结束'], ['timezone', '规则时区']] as const).map(([key, label]) => <div className="space-y-2" key={key}>
              <Label htmlFor={`fence-${key}`}>{label}</Label><Input id={`fence-${key}`} type={key === 'timezone' ? 'text' : 'time'} value={draft.config.value[key]} disabled={disabled}
                onChange={(event) => update((current) => ({ ...current, config: { ...current.config, value: { ...current.config.value, [key]: event.target.value } } }))} />
            </div>)}
            {NUMBER_FIELDS.filter(([key]) => key !== 'alarm_interval').map(([key, label, min, max, step]) => <div className="space-y-2" key={key}>
              <Label htmlFor={`fence-${key}`}>{label}</Label><Input id={`fence-${key}`} type="number" min={min} max={max} step={step} value={draft.numbers[key]} disabled={disabled}
                onChange={(event) => update((current) => ({ ...current, numbers: { ...current.numbers, [key]: event.target.value } }))} />
            </div>)}
          </>}
          <p className="text-sm text-slate-500 dark:text-slate-400 md:col-span-2">库内身份按人脸匹配结果确认；尺寸、清晰度、偏转和未匹配阈值用于确认库外未知人员。身份确认帧数在连续可靠的轨迹内累计，单次无人脸不清零；跟踪中断或多人身份关联不明时重新核验。没有有效身份依据时保持待核验，不按超时报警。</p>
        </DetectionConfigCardContent>
      </Card>{saveBar}
    </FeatureConfigGate></TabsContent>
    <TabsContent value="persons" className="space-y-6">
      <div className="space-y-2"><Label htmlFor="fence-whitelist-camera">摄像头</Label>
        <Select value={cameraKey} onValueChange={state.selectCamera} disabled={loading || saving || !state.enabledCameras.length}>
          <SelectTrigger id="fence-whitelist-camera" className="w-full"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
          <SelectContent>{state.enabledCameras.map((camera) => <SelectItem key={camera.id} value={camera.shm_name}>{camera.name}{!camera.enabled ? '（摄像头已停用）' : ''}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <FeatureConfigGate cameraKey={cameraKey} disabled={false}>
        {cameraKey && <FenceWhitelist key={`${department}:${cameraKey}`} cameraKey={cameraKey} />}
      </FeatureConfigGate>
    </TabsContent>
    <TabsContent value="roi"><FeatureConfigGate cameraKey={cameraKey} disabled={disabled}>
      {draft && <Suspense fallback={<p>正在加载 ROI 编辑器…</p>}><AiVisionRoiEditor key={cameraKey} title="警戒围栏 ROI 绘制" cameraKey={cameraKey} roiJson={draft.roi} disabled={disabled} saving={saving} message={message}
        onChange={(roi) => update((current) => ({ ...current, roi }))} onSave={save} /></Suspense>}
    </FeatureConfigGate></TabsContent>
    <TabsContent value="model"><Suspense fallback={<p>正在加载模型配置…</p>}><AiVisionModelConfig requiredModels={['yolo_human', 'insightface']} /></Suspense></TabsContent>
    <TabsContent value="alarm"><FeatureConfigGate cameraKey={cameraKey} disabled={disabled}>
      {draft && <AlarmPushConfig key={cameraKey} alarm={draft.config.alarm} alarmInterval={draft.numbers.alarm_interval} disabled={disabled} saving={saving} message={message} onSave={save}
        onAlarmIntervalChange={(alarm_interval) => update((current) => ({ ...current, numbers: { ...current.numbers, alarm_interval } }))}
        onChange={(alarm) => update((current) => ({ ...current, config: { ...current.config, alarm: normalizeFeatureAlarmConfig(alarm) } }))} />}
      <p className="text-sm text-slate-500 dark:text-slate-400">报警记录与企业微信分别按当前摄像头限频，换人、重新识别和规则切换不会重置间隔；同一次持续异常各记录或推送一次。喇叭独立按自己的间隔播放。禁入时段先记录，身份确认后补全姓名与工号。</p>
    </FeatureConfigGate></TabsContent>
  </DetectionConfigTabs>
}
