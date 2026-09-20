import { SlidersHorizontal, Webhook } from 'lucide-react'
import {
  DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionFormSection,
} from '@/components/detection/DetectionConfigUi'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { AiVisionCamera } from '@/lib/aivision'
import { Textarea } from '@/components/ui/textarea'
import { AGV_NUMBER_FIELDS, type AgvForm } from './config'

type Props = { form: AgvForm; disabled: boolean; onChange: (update: (form: AgvForm) => AgvForm) => void }

export function AgvDetectionParameters({ form, disabled, onChange, cameras, cameraKey, onSelectCamera }: Props & {
  cameras: AiVisionCamera[]
  cameraKey: string
  onSelectCamera: (key: string) => void
}) {
  return (
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="检测参数"
        description="任意一帧检测到人即判定有人；只有全部采样帧无人，才判定无人。" />
      <DetectionConfigCardContent className="space-y-5">
        <div className="space-y-2">
          <Label htmlFor="agv-camera">摄像头</Label>
          <Select value={cameraKey} onValueChange={onSelectCamera} disabled={disabled}>
            <SelectTrigger id="agv-camera" className="w-full"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
            <SelectContent>{cameras.map((camera) => <SelectItem key={camera.camera_id} value={camera.shm_name}>{camera.name}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <fieldset disabled={disabled} className="space-y-5">
          <DetectionFormSection title="多帧人体检测">
            <div className="grid gap-5 md:grid-cols-2">
              {AGV_NUMBER_FIELDS.slice(0, 4).map(({ key, label, min, max, step }) => <div key={key} className="space-y-2">
                <Label htmlFor={`agv-${key}`}>{label}</Label>
                <Input id={`agv-${key}`} type="number" min={min} max={max} step={step} value={form.parameters[key]}
                  onChange={(event) => onChange((current) => ({ ...current, parameters: { ...current.parameters, [key]: event.target.value } }))} />
              </div>)}
            </div>
            <p className="text-xs leading-6 text-slate-500 dark:text-slate-400">
              检测时长为请求超时上限，检测到人或完成采样后会提前结束。采样只计不同的新帧，断流或推理失败不判为无人。
            </p>
          </DetectionFormSection>
          <DetectionFormSection title="推理与画面有效性">
            <div className="grid gap-5 md:grid-cols-3">
              {AGV_NUMBER_FIELDS.slice(4).map(({ key, label, min, max, step }) => <div key={key} className="space-y-2">
                <Label htmlFor={`agv-${key}`}>{label}</Label>
                <Input id={`agv-${key}`} type="number" min={min} max={max} step={step} value={form.parameters[key]}
                  onChange={(event) => onChange((current) => ({ ...current, parameters: { ...current.parameters, [key]: event.target.value } }))} />
              </div>)}
            </div>
          </DetectionFormSection>
        </fieldset>
      </DetectionConfigCardContent>
    </Card>
  )
}

export function AgvHttpConfig({ form, disabled, onChange }: Props) {
  const updateHttp = (patch: Partial<AgvForm['http']>) => onChange((current) => ({ ...current, http: { ...current.http, ...patch } }))
  return (
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={Webhook} tone="violet" title="HTTP 通信配置"
        description="同步模式直接返回检测结果；回调模式先接受请求，检测完成后发送 HTTP 回调。" />
      <DetectionConfigCardContent>
        <fieldset disabled={disabled} className="space-y-6">
          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="agv-http-mode">通信模式</Label>
              <Select value={form.http.mode} disabled={disabled} onValueChange={(mode: AgvForm['http']['mode']) => updateHttp({ mode })}>
                <SelectTrigger id="agv-http-mode" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="sync">同步返回</SelectItem><SelectItem value="callback">HTTP 回调</SelectItem></SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="agv-http-method">回调 HTTP 方法</Label>
              <Select value={form.http.method} disabled={disabled} onValueChange={(method: AgvForm['http']['method']) => updateHttp({ method })}>
                <SelectTrigger id="agv-http-method" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="GET">GET</SelectItem><SelectItem value="POST">POST</SelectItem></SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="agv-callback-url">回调 URL</Label>
              <Input id="agv-callback-url" type="url" value={form.http.callback_url} placeholder="填写 AGV 接收结果的 HTTP/HTTPS 地址"
                onChange={(event) => updateHttp({ callback_url: event.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="agv-callback-timeout">回调超时（秒）</Label>
              <Input id="agv-callback-timeout" type="number" min={0} max={10} step={0.1} value={form.http.timeout_seconds}
                onChange={(event) => updateHttp({ timeout_seconds: event.target.value })} />
            </div>
          </div>
          <p className="text-xs leading-6 text-slate-500 dark:text-slate-400">
            回调 URL、HTTP 方法、Headers 和回调超时仅在 HTTP 回调模式生效。GET 与 POST 均发送 JSON Body。未填写完整通信参数时，检测请求会被拒绝。
          </p>
          <DetectionFormSection title="有人 / 无人返回值" hint="接收检测请求前必填">
            <div className="grid gap-5 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="agv-present-value">有人返回值（JSON 值）</Label>
                <Input id="agv-present-value" value={form.http.present_value} placeholder={'例如 1、true 或 "STOP"'}
                  onChange={(event) => updateHttp({ present_value: event.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="agv-absent-value">无人返回值（JSON 值）</Label>
                <Input id="agv-absent-value" value={form.http.absent_value} placeholder={'例如 0、false 或 "GO"'}
                  onChange={(event) => updateHttp({ absent_value: event.target.value })} />
              </div>
            </div>
            <p className="text-xs leading-6 text-slate-500 dark:text-slate-400">支持数字、布尔值和带双引号的文本；数字 1 与文本 "1" 会按不同类型发送。</p>
          </DetectionFormSection>
          <div className="space-y-2">
            <Label htmlFor="agv-headers">Headers（JSON 对象）</Label>
            <Textarea id="agv-headers" rows={4} spellCheck={false} className="font-mono text-sm" value={form.http.headers}
              onChange={(event) => updateHttp({ headers: event.target.value })} />
            <p className="text-xs text-slate-500 dark:text-slate-400">Header 名称和值均需使用字符串，无自定义 Header 时填写 {'{}'}。</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="agv-body-template">JSON Body 模板</Label>
            <Textarea id="agv-body-template" rows={7} spellCheck={false} className="font-mono text-sm" value={form.http.body_template}
              onChange={(event) => updateHttp({ body_template: event.target.value })} />
            <p className="text-xs leading-6 text-slate-500 dark:text-slate-400">
              {'同步响应与回调共用此模板。必须包含 "${result}"，可使用 "${camera_key}"、"${request_id}"；占位符须作为完整的 JSON 值，替换时保留返回值类型。'}
            </p>
          </div>
        </fieldset>
      </DetectionConfigCardContent>
    </Card>
  )
}
