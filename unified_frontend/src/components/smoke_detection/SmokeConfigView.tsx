import { Bell, Camera, MousePointer2, Plug, SlidersHorizontal } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { useDepartmentConfigAccess } from '@/auth/useDepartmentConfigAccess'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { FeatureCameraManager } from '@/components/FeatureCameraManager'
import { DetectionConfigTabs } from '@/components/detection/DetectionConfigTabs'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionConfigTab, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { FeatureConfigGate } from '@/components/detection/FeatureConfigGate'
import { useCameraFeatureConfig } from '@/components/detection/useCameraFeatureConfig'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TabsContent } from '@/components/ui/tabs'
import { normalizeFeatureAlarmConfig } from '@/lib/alarm-config'
import { DeviceParameters } from './DeviceParameters'
import { SmokeShields } from './SmokeShields'
import { buildSmokeConfig, CONNECTION_FIELDS, createSmokeDraft, SMOKE_FEATURE } from './config'

export function SmokeConfigView({ department }: { department: DepartmentId }) {
  const canConfigure = useDepartmentConfigAccess(department, SMOKE_FEATURE)
  const state = useCameraFeatureConfig({ feature: SMOKE_FEATURE, department, canConfigure, createDraft: createSmokeDraft, buildConfig: buildSmokeConfig })
  const { draft, cameraKey, loading, saving, message, update } = state
  const disabled = !canConfigure || loading || saving || !draft
  const deviceKey = `${department}:${cameraKey}:${JSON.stringify(draft?.config.value)}`
  return <DetectionConfigTabs defaultValue="camera" className="space-y-6" tabListClassName="lg:grid-cols-5" tabs={<>
    <DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
    <DetectionConfigTab value="connection" icon={Plug}>设备连接</DetectionConfigTab>
    <DetectionConfigTab value="parameters" icon={SlidersHorizontal}>设备参数</DetectionConfigTab>
    <DetectionConfigTab value="shields" icon={MousePointer2}>烟雾屏蔽区</DetectionConfigTab>
    <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab>
  </>}>
    <TabsContent value="camera" className="space-y-4">
      <FeatureCameraManager cameras={state.cameras} feature={SMOKE_FEATURE} department={department} currentCameraName={cameraKey}
        disabled={!canConfigure || loading || saving} onSelectCamera={state.selectCamera} onCamerasChanged={state.reload} onConfigCopied={state.reload} />
      <p role="status" className="text-sm text-slate-500 dark:text-slate-400">{message}</p>
    </TabsContent>
    <TabsContent value="connection" className="space-y-5">
      <FeatureConfigGate cameraKey={cameraKey} disabled={disabled}>
        <Card className={DETECTION_CONFIG_CARD_CLASS}>
          <DetectionConfigCardHeader icon={Plug} tone="blue" title="设备连接" />
          <DetectionConfigCardContent className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2"><Label htmlFor="smoke-camera">摄像头</Label><Select value={cameraKey} onValueChange={state.selectCamera} disabled={loading || saving}>
              <SelectTrigger id="smoke-camera" className="w-full"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
              <SelectContent>{state.enabledCameras.map((camera) => <SelectItem key={camera.id} value={camera.shm_name}>{camera.name}</SelectItem>)}</SelectContent>
            </Select></div>
            {draft && <><div className="space-y-2"><Label htmlFor="smoke-scheme">设备协议</Label>
              <Select value={draft.config.value.device_scheme} disabled={disabled} onValueChange={(device_scheme: 'http' | 'https') => update((current) => ({ ...current, config: { ...current.config, value: { ...current.config.value, device_scheme } } }))}>
                <SelectTrigger id="smoke-scheme" className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="http">HTTP</SelectItem><SelectItem value="https">HTTPS</SelectItem></SelectContent>
              </Select></div>
              {CONNECTION_FIELDS.map(([key, label, min, max]) => <div key={key} className="space-y-2"><Label htmlFor={`smoke-${key}`}>{label}</Label>
                <Input id={`smoke-${key}`} type="number" min={min} max={max} step={1} value={draft.numbers[key]} disabled={disabled}
                  onChange={(event) => update((current) => ({ ...current, numbers: { ...current.numbers, [key]: event.target.value } }))} /></div>)}
            </>}
          </DetectionConfigCardContent>
        </Card>
        <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={disabled} onReload={() => { void state.reload(cameraKey) }} onSave={() => { void state.save() }} />
      </FeatureConfigGate>
    </TabsContent>
    <TabsContent value="parameters"><FeatureConfigGate cameraKey={cameraKey} disabled={disabled}>
      {draft && <DeviceParameters key={deviceKey} cameraKey={cameraKey} department={department} disabled={disabled} />}
    </FeatureConfigGate></TabsContent>
    <TabsContent value="shields"><FeatureConfigGate cameraKey={cameraKey} disabled={disabled}>
      {draft && <SmokeShields key={deviceKey} cameraKey={cameraKey} department={department} disabled={disabled} />}
    </FeatureConfigGate></TabsContent>
    <TabsContent value="alarm"><FeatureConfigGate cameraKey={cameraKey} disabled={disabled}>
      {draft && <AlarmPushConfig key={cameraKey} showSql alarm={draft.config.alarm} alarmInterval={draft.numbers.alarm_interval}
        disabled={disabled} saving={saving} message={message} onSave={() => { void state.save() }}
        onAlarmIntervalChange={(alarm_interval) => update((current) => ({ ...current, numbers: { ...current.numbers, alarm_interval } }))}
        onChange={(alarm) => update((current) => ({ ...current, config: { ...current.config, alarm: normalizeFeatureAlarmConfig(alarm, Number(current.numbers.alarm_interval)) } }))} />}
    </FeatureConfigGate></TabsContent>
  </DetectionConfigTabs>
}
