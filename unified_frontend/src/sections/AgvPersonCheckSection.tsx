import { lazy, Suspense } from 'react'
import { Camera, MousePointer2, SlidersHorizontal, Webhook } from 'lucide-react'
import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { useAuth } from '@/auth/useAuth'
import { AgvPersonCheckForm } from '@/components/agv_person_check/AgvPersonCheckForm'
import { useAgvPersonCheckConfig } from '@/components/agv_person_check/useAgvPersonCheckConfig'
import {
  DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader,
  DetectionConfigTab, DetectionConfigTabsList, DetectionSaveBar,
} from '@/components/detection/DetectionConfigUi'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent } from '@/components/ui/tabs'

const AiVisionRoiEditor = lazy(() => import('@/components/AiVisionRoiEditor').then((module) => ({ default: module.AiVisionRoiEditor })))

export function AgvPersonCheckSection({ department }: { department: DepartmentId }) {
  const { isAdmin } = useAuth()
  const { cameras, cameraKey, form, loading, saving, message, updateForm, save, reload, selectCamera } = useAgvPersonCheckConfig(department, isAdmin)
  const camera = cameras.find((item) => item.shm_name === cameraKey)
  const readOnly = !isAdmin || loading || saving || !form

  return (
    <div className="min-h-[calc(100vh-7rem)] space-y-5 rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <DetectionPageHeader title="AGV无人运货检测" subtitle="配置指定摄像头的 ROI、多帧人体检测与 AGV HTTP 通信。"
        departmentLabel={DEPARTMENT_LABELS[department]} configurationOnly />
      <Card className={DETECTION_CONFIG_CARD_CLASS}>
        <DetectionConfigCardHeader icon={Camera} tone="blue" title="摄像头与功能开关"
          description="选择当前事业部的摄像头，填写通信返回值后保存并启用检测。"
          actions={<Badge variant="outline">{isAdmin ? '管理员可编辑' : '当前账号只读'}</Badge>} />
        <DetectionConfigCardContent className="grid gap-5 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="agv-camera">摄像头</Label>
            <Select value={cameraKey} onValueChange={selectCamera} disabled={loading || saving || cameras.length === 0}>
              <SelectTrigger id="agv-camera" className="w-full"><SelectValue placeholder={loading ? '正在读取摄像头' : '选择摄像头'} /></SelectTrigger>
              <SelectContent>{cameras.map((item) => <SelectItem key={item.camera_id} value={item.shm_name}>
                {item.name}{item.enabled ? '' : '（摄像头已关闭）'}
              </SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="flex items-center justify-between gap-4 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
            <div className="space-y-1">
              <Label htmlFor="agv-enable">启用 AGV 检测</Label>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {camera && !camera.enabled ? '摄像头已关闭，启用检测前请先在平台总览开启。' : '开关随配置一起保存，检测由 AGV 的 HTTP 请求触发。'}
              </p>
            </div>
            <Switch id="agv-enable" checked={form?.enable ?? false}
              disabled={readOnly || (!camera?.enabled && !form?.enable)}
              onCheckedChange={(enable) => updateForm((current) => ({ ...current, enable }))} />
          </div>
        </DetectionConfigCardContent>
      </Card>

      {form && <Tabs defaultValue="params" className="space-y-5">
        <DetectionConfigTabsList className="grid-cols-3 sm:grid-cols-3 lg:grid-cols-3">
          <DetectionConfigTab value="params" icon={SlidersHorizontal}>检测参数</DetectionConfigTab>
          <DetectionConfigTab value="roi" icon={MousePointer2}>ROI 配置</DetectionConfigTab>
          <DetectionConfigTab value="http" icon={Webhook}>HTTP 通信</DetectionConfigTab>
        </DetectionConfigTabsList>
        <AgvPersonCheckForm form={form} disabled={readOnly} onChange={updateForm} />
        <TabsContent value="roi" className="mt-0">
          <Suspense fallback={<p role="status" className="p-5 text-sm text-slate-500">正在加载 ROI 编辑器...</p>}>
            <AiVisionRoiEditor key={cameraKey} title="AGV 人体检测 ROI 绘制" cameraKey={cameraKey} roiJson={form.roiJson}
              disabled={readOnly} saving={saving} message={message}
              onChange={(roiJson) => updateForm((current) => ({ ...current, roiJson }))} onSave={save} />
          </Suspense>
        </TabsContent>
      </Tabs>}
      <div role="status" aria-live="polite">
        <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={readOnly} onReload={reload} onSave={save} />
      </div>
    </div>
  )
}
