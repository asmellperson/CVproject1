import type { DepartmentId } from '@/auth/permissions'
import { lazy, Suspense, useState } from 'react'
import { Bell, Box, Camera, MousePointer2, SlidersHorizontal, UserCheck, Volume2 } from 'lucide-react'
import { FeatureCameraManager } from '@/components/FeatureCameraManager'
import { WechatAlarmSettings } from '@/components/AlarmPushConfig'
import { HornAlarmBinding } from '@/components/horn/HornAlarmBinding'
import { HornDeviceManager } from '@/components/horn/HornDeviceManager'
import {
  DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader,
  DetectionConfigTab, DetectionConfigTabsList, DetectionSaveBar,
} from '@/components/detection/DetectionConfigUi'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { isAiVisionFeatureEnabled } from '@/lib/aivision'
import { FACE_FEATURE, type FacePerson } from './api'
import { useFacePersons, useRecognitionConfig } from './useRecognitionConfig'

const AiVisionRoiEditor = lazy(() => import('@/components/AiVisionRoiEditor').then((module) => ({ default: module.AiVisionRoiEditor })))
const AiVisionModelConfig = lazy(() => import('@/components/AiVisionModelConfig').then((module) => ({ default: module.AiVisionModelConfig })))

function FacePersonPermissions() {
  const state = useFacePersons()
  const [keyword, setKeyword] = useState('')
  const saving = state.savingId !== null
  const pages = state.result ? Math.max(1, Math.ceil(state.result.total / state.result.page_size)) : 1
  return (
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={UserCheck} tone="emerald" title="人员权限" description={state.isAdmin ? '管理同步人员的通行权限；新同步人员默认不允许通行。' : '查看同步人员及通行权限；仅管理员可以修改允许状态。'} />
      <DetectionConfigCardContent className="space-y-4">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => {
          event.preventDefault()
          state.setQuery((query) => ({ ...query, page: 1, keyword: keyword.trim() || undefined }))
        }}>
          <div className="min-w-64 flex-1 space-y-2">
            <Label htmlFor="face-person-keyword">搜索人员</Label>
            <Input id="face-person-keyword" value={keyword} maxLength={255} disabled={saving} placeholder="姓名、工号、人员编码、海康 ID 或组织编码" onChange={(event) => setKeyword(event.target.value)} />
          </div>
          <Button type="submit" disabled={saving}>搜索</Button>
          <Button type="button" variant="outline" disabled={saving || state.loading} onClick={() => { void state.loadPersons() }}>刷新</Button>
        </form>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-2"><Label htmlFor="face-person-source">数据来源</Label>
            <Select value={state.query.source || 'all'} disabled={saving} onValueChange={(source) => state.setQuery((query) => ({ ...query, page: 1, source: source === 'all' ? undefined : source as FacePerson['hik_source'] }))}>
              <SelectTrigger id="face-person-source" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="all">全部来源</SelectItem><SelectItem value="one">海康 one</SelectItem><SelectItem value="two">海康 two</SelectItem></SelectContent>
            </Select>
          </div>
          <div className="space-y-2"><Label htmlFor="face-person-active">人员状态</Label>
            <Select value={state.query.is_active === undefined ? 'all' : String(state.query.is_active)} disabled={saving} onValueChange={(active) => state.setQuery((query) => ({ ...query, page: 1, is_active: active === 'all' ? undefined : active === 'true' }))}>
              <SelectTrigger id="face-person-active" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="all">全部状态</SelectItem><SelectItem value="true">已激活</SelectItem><SelectItem value="false">已停用</SelectItem></SelectContent>
            </Select>
          </div>
          <div className="space-y-2"><Label htmlFor="face-person-allowed">允许状态</Label>
            <Select value={state.query.is_allowed === undefined ? 'all' : String(state.query.is_allowed)} disabled={saving} onValueChange={(allowed) => state.setQuery((query) => ({ ...query, page: 1, is_allowed: allowed === 'all' ? undefined : allowed === 'true' }))}>
              <SelectTrigger id="face-person-allowed" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="all">全部权限</SelectItem><SelectItem value="true">允许</SelectItem><SelectItem value="false">不允许</SelectItem></SelectContent>
            </Select>
          </div>
        </div>
        {state.error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{state.error}</p>}
        {state.message && <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">{state.message}</p>}
        <Table>
          <TableHeader><TableRow>{['姓名', '工号', '人员编码', '组织编码', '海康人员 ID', '数据来源', '服务节点', '人员状态', '允许状态', '最近同步时间'].map((title) => <TableHead key={title} className="whitespace-nowrap">{title}</TableHead>)}</TableRow></TableHeader>
          <TableBody>
            {state.loading ? <TableRow><TableCell colSpan={10} className="text-center">正在读取人员…</TableCell></TableRow> : state.result?.items.map((person) => (
              <TableRow key={person.id}>
                <TableCell>{person.person_name || '—'}</TableCell><TableCell>{person.job_no || '—'}</TableCell>
                <TableCell>{person.person_code || '—'}</TableCell><TableCell>{person.org_index_code || '—'}</TableCell>
                <TableCell>{person.hik_person_id}</TableCell><TableCell>海康 {person.hik_source}</TableCell>
                <TableCell>{person.server_index_code || '—'}</TableCell><TableCell className="whitespace-nowrap">{person.is_active ? '已激活' : '已停用'}</TableCell>
                <TableCell><div className="flex items-center gap-2 whitespace-nowrap">
                  <Switch aria-label={`${person.person_name || person.hik_person_id}允许通行`} checked={person.is_allowed} disabled={!state.isAdmin || saving} onCheckedChange={(allowed) => { void state.setPersonAllowed(person.id, allowed) }} />
                  <span>{state.savingId === person.id ? '保存中…' : person.is_allowed ? '允许' : '不允许'}</span>
                </div></TableCell>
                <TableCell className="whitespace-nowrap">{new Date(person.last_synced_at).toLocaleString('zh-CN', { hour12: false })}</TableCell>
              </TableRow>
            ))}
            {!state.loading && !state.error && !state.result?.items.length && <TableRow><TableCell colSpan={10} className="text-center">没有符合条件的人员。</TableCell></TableRow>}
          </TableBody>
        </Table>
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500 dark:text-slate-400">
          <span>{state.result ? `共 ${state.result.total} 人 · 第 ${state.query.page} / ${pages} 页` : '人员列表尚未加载'}</span>
          <div className="flex gap-2">
            <Button variant="outline" disabled={saving || state.loading || !state.result || state.query.page <= 1} onClick={() => state.setQuery((query) => ({ ...query, page: query.page - 1 }))}>上一页</Button>
            <Button variant="outline" disabled={saving || state.loading || !state.result || state.query.page >= pages} onClick={() => state.setQuery((query) => ({ ...query, page: query.page + 1 }))}>下一页</Button>
          </div>
        </div>
      </DetectionConfigCardContent>
    </Card>
  )
}

export function RecognitionConfigView({ department }: { department: DepartmentId }) {
  const state = useRecognitionConfig(department)
  const featureCameras = state.cameras.filter((camera) => isAiVisionFeatureEnabled(camera, FACE_FEATURE) || camera.shm_name === state.cameraKey)
  const alarm = state.config?.alarm
  const cameraName = featureCameras.find((camera) => camera.shm_name === state.cameraKey)?.name
  return (
    <Tabs defaultValue="camera" className="space-y-6">
      <DetectionConfigTabsList className="lg:grid-cols-7">
        <DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
        <DetectionConfigTab value="params" icon={SlidersHorizontal}>识别参数</DetectionConfigTab>
        <DetectionConfigTab value="roi" icon={MousePointer2}>ROI 配置</DetectionConfigTab>
        <DetectionConfigTab value="model" icon={Box}>模型配置</DetectionConfigTab>
        <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab>
        <DetectionConfigTab value="horns" icon={Volume2}>喇叭配置</DetectionConfigTab>
        <DetectionConfigTab value="persons" icon={UserCheck}>人员权限</DetectionConfigTab>
      </DetectionConfigTabsList>
      <TabsContent value="camera" className="space-y-4">
        <FeatureCameraManager cameras={state.cameras} feature={FACE_FEATURE} department={department}
          currentCameraName={state.cameraKey} disabled={state.disabled} onSelectCamera={state.selectCamera}
          onAddCamera={(key) => state.setCameraEnabled(key, true)} onRemoveCamera={(key) => state.setCameraEnabled(key, false)}
          onConfigCopied={(key) => {
            state.selectCamera(key)
            return state.loadConfig(key)
          }}
          />
        <p role="status" className="text-sm text-slate-500 dark:text-slate-400">{state.message}</p>
      </TabsContent>
      <TabsContent value="params" className="space-y-6">
        <Card className={DETECTION_CONFIG_CARD_CLASS}>
          <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="识别参数" description="对画面中的每张人脸分别比对；低于相似度阈值时显示未知人员。" />
          <DetectionConfigCardContent className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2"><Label htmlFor="identity-config-camera">摄像头</Label>
              <Select value={state.cameraKey} onValueChange={state.selectCamera} disabled={state.loading || state.saving || !featureCameras.length}>
                <SelectTrigger id="identity-config-camera" className="w-full"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
                <SelectContent>{featureCameras.map((camera) => <SelectItem key={camera.id} value={camera.shm_name}>{camera.name}{!camera.enabled ? '（摄像头已停用）' : ''}</SelectItem>)}</SelectContent>
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
      </TabsContent>
      <TabsContent value="roi">
        <Suspense fallback={<p>正在加载 ROI 编辑器…</p>}><AiVisionRoiEditor title="人脸身份识别 ROI 绘制" cameraKey={state.cameraKey} roiJson={state.form.roi} disabled={!state.canSave} saving={state.saving} message={state.message} onChange={(roi) => state.setForm((form) => ({ ...form, roi }))} onSave={state.save} /></Suspense>
      </TabsContent>
      <TabsContent value="model"><Suspense fallback={<p>正在加载模型配置…</p>}><AiVisionModelConfig requiredModels={['insightface']} /></Suspense></TabsContent>
      <TabsContent value="alarm" className="space-y-6">
        <Card className={DETECTION_CONFIG_CARD_CLASS}>
          <DetectionConfigCardHeader icon={Bell} tone="amber" title="报警推送" description={cameraName ? `${cameraName} · 人脸身份识别企业微信报警` : '请先添加并选择摄像头。'} />
          <DetectionConfigCardContent className="space-y-4">
            {alarm ? <WechatAlarmSettings value={alarm.wechat} disabled={!state.canSave}
              onChange={(wechat) => state.setAlarm({ ...alarm, wechat })} /> : null}
            <div className="space-y-2">
              <Label htmlFor="identity-alarm-interval">报警间隔（秒）</Label>
              <Input id="identity-alarm-interval" type="number" min={0.1} step={0.1} value={state.form.alarmInterval} disabled={!state.canSave}
                onChange={(event) => state.setForm((form) => ({ ...form, alarmInterval: event.target.value }))} />
            </div>
          </DetectionConfigCardContent>
        </Card>
        <DetectionSaveBar message={state.message} loading={state.loading} saving={state.saving} disabled={!state.canSave || Boolean(state.hornError)} onReload={() => state.loadConfig(state.cameraKey)} onSave={state.save} />
      </TabsContent>
      <TabsContent value="horns" className="space-y-6">
        <Card className={DETECTION_CONFIG_CARD_CLASS}>
          <DetectionConfigCardHeader icon={Volume2} tone="violet" title="当前摄像头喇叭绑定" description={cameraName ? `${cameraName} · 人脸身份识别喇叭报警` : '请先添加并选择摄像头。'} />
          <DetectionConfigCardContent>
            {alarm ? <HornAlarmBinding value={alarm.horn} disabled={!state.canSave}
              onChange={(horn) => state.setAlarm({ ...alarm, horn })} onValidationChange={state.setHornError} /> : null}
          </DetectionConfigCardContent>
        </Card>
        <DetectionSaveBar message={state.message} loading={state.loading} saving={state.saving} disabled={!state.canSave || Boolean(state.hornError)} onReload={() => state.loadConfig(state.cameraKey)} onSave={state.save} />
        <HornDeviceManager />
      </TabsContent>
      <TabsContent value="persons"><FacePersonPermissions /></TabsContent>
    </Tabs>
  )
}
