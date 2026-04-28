import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Save, RotateCcw, Video, Shield, Box, CheckCircle2, Bell } from 'lucide-react'
import { getConfig, saveConfig, restartRuntime, getStatus } from '@/lib/api'
import { useAuth } from '@/auth/AuthContext'
// ==================== 类型定义 ====================

type AppConfigPayload = {
  video: {
    source: string
    source_cam1: string
    source_cam2: string
    source_cam3: string
    process_every_n_frames: number
    output_dir: string
    save_annotated_video: boolean
    annotated_video_fps: number
    reconnect_seconds: number
    jpeg_quality: number
    camera_buffer_size: number
  }
  models: {
    detector_model: string
    uniform_cls_model: string
    pose_model_task: string
    detector_conf: number
    detector_iou: number
    tracker: string
    device: string
    uniform_cls_imgsz: number
    uniform_cls_conf: number
  }
  room: {
    frame_width: number
    frame_height: number
  }
  rules: {
    absent_seconds: number
    phone_seconds: number
    prone_sleep_seconds: number
    phone_near_person_px: number
    phone_near_head_px: number
    static_motion_threshold: number
    prone_head_down_ratio_threshold: number
    prone_bbox_height_ratio_threshold: number
    prone_consecutive_frames: number
    state_ttl_seconds: number
    phone_window_seconds: number
    phone_min_hits_in_window: number
    phone_grace_seconds: number
    guard_hold_seconds: number
    dual_sync_seconds: number
    absent_alarm_seconds: number
    alarm_cooldown_absent: number
    alarm_cooldown_phone: number
    alarm_cooldown_prone_sleep: number
  }
  classes: {
    person: number
    play_phone: number
  }
  runtime: {
    show_window: boolean
    debug: boolean
    draw_debug: boolean
    max_alarm_history: number
  }
  wechat: {
    enable: boolean
    corpid: string
    corpsecret: string
    agentid: number
    alarm_user: string
    camera_name: string
    clip_seconds: number
  }
}

const defaultConfig: AppConfigPayload = {
  video: {
    source: '',
    source_cam1: '',
    source_cam2: '',
    source_cam3: '',
    process_every_n_frames: 3,
    output_dir: 'outputs',
    save_annotated_video: false,
    annotated_video_fps: 10,
    reconnect_seconds: 1.0,
    jpeg_quality: 80,
    camera_buffer_size: 1,
  },
  models: {
    detector_model: 'yolo11n.pt',
    uniform_cls_model: '',
    pose_model_task: '',
    detector_conf: 0.35,
    detector_iou: 0.45,
    tracker: 'bytetrack.yaml',
    device: '',
    uniform_cls_imgsz: 224,
    uniform_cls_conf: 0.75,
  },
  room: {
    frame_width: 1920,
    frame_height: 1080,
  },
  rules: {
    absent_seconds: 900,
    phone_seconds: 300,
    prone_sleep_seconds: 300,
    phone_near_person_px: 220,
    phone_near_head_px: 160,
    static_motion_threshold: 8.0,
    prone_head_down_ratio_threshold: 0.22,
    prone_bbox_height_ratio_threshold: 0.18,
    prone_consecutive_frames: 8,
    state_ttl_seconds: 20,
    phone_window_seconds: 4,
    phone_min_hits_in_window: 6,
    phone_grace_seconds: 3,
    guard_hold_seconds: 1.3,
    dual_sync_seconds: 1.5,
    absent_alarm_seconds: 60.0,
    alarm_cooldown_absent: 120,
    alarm_cooldown_phone: 60,
    alarm_cooldown_prone_sleep: 300,

  },
  classes: {
    person: 0,
    play_phone: 1,
  },
  runtime: {
    show_window: false,
    debug: true,
    draw_debug: false,
    max_alarm_history: 1000,
  },
  wechat: {
    enable: false,
    corpid: '',
    corpsecret: '',
    agentid: 1000050,
    alarm_user: '',
    camera_name: '值班室双摄像头',
    clip_seconds: 5.0,
  },
}

function mergeConfig(data: Partial<AppConfigPayload> | null | undefined): AppConfigPayload {
  return {
    video: { ...defaultConfig.video, ...(data?.video || {}) },
    models: { ...defaultConfig.models, ...(data?.models || {}) },
    room: { ...defaultConfig.room, ...(data?.room || {}) },
    rules: { ...defaultConfig.rules, ...(data?.rules || {}) },
    classes: { ...defaultConfig.classes, ...(data?.classes || {}) },
    runtime: { ...defaultConfig.runtime, ...(data?.runtime || {}) },
    wechat: { ...defaultConfig.wechat, ...(data?.wechat || {}) },
  }
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  return fallback
}

// ==================== 主组件 ====================

function ConfigSection() {
  const { isAdmin } = useAuth()
  const [activeTab, setActiveTab] = useState('video')
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)
  const [config, setConfig] = useState<AppConfigPayload>(defaultConfig)

  const loadConfig = async () => {
    const next = await getConfig()
    setConfig(mergeConfig(next))
  }

  useEffect(() => {
    loadConfig()
      .catch((err) => {
        console.error('加载配置失败:', err)
      })
      .finally(() => setLoading(false))
  }, [])

  const [saveError, setSaveError] = useState('')
  const [saving, setSaving] = useState(false)
  const [savePhase, setSavePhase] = useState('')  // 显示当前阶段

  const handleSave = async () => {
    if (!isAdmin) {
      setSaveError('当前账号为 viewer，只能查看配置。')
      return
    }
    setSaveError('')
    setSaving(true)
    try {
      // 阶段 1: 保存配置
      setSavePhase('正在保存配置...')
      await saveConfig({
        video: config.video,
        models: config.models,
        room: config.room,
        rules: config.rules,
        classes: config.classes,
        runtime: config.runtime,
        wechat: config.wechat,
      })

      // 阶段 2: 重启算法
      setSavePhase('正在重启算法（约 15 秒）...')
      await restartRuntime()

      // 阶段 3: 等后端真的起来
      setSavePhase('等待算法就绪...')
      await waitUntilRunning(20000)  // 最多等 20 秒

      setSavePhase('')
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      await loadConfig()
    } catch (err: unknown) {
      console.error('保存配置失败:', err)
      setSaveError(getErrorMessage(err, '保存失败'))
      setSavePhase('')
    } finally {
      setSaving(false)
    }
  }

// 轮询 /api/status 直到 running=true 或超时
async function waitUntilRunning(timeoutMs: number) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const s = await getStatus()
      if (s.running && !s.error) return
    } catch {
      // 重启期间 API 可能短暂不可达，继续等
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error('算法启动超时，请检查后端日志')
}

  if (loading) {
    return <div className="text-slate-500">正在加载配置...</div>
  }

  // 便捷更新函数
  const setVideo = (patch: Partial<AppConfigPayload['video']>) =>
    setConfig({ ...config, video: { ...config.video, ...patch } })
  const setModels = (patch: Partial<AppConfigPayload['models']>) =>
    setConfig({ ...config, models: { ...config.models, ...patch } })
  const setRoom = (patch: Partial<AppConfigPayload['room']>) =>
    setConfig({ ...config, room: { ...config.room, ...patch } })
  const setRules = (patch: Partial<AppConfigPayload['rules']>) =>
    setConfig({ ...config, rules: { ...config.rules, ...patch } })
  const setClasses = (patch: Partial<AppConfigPayload['classes']>) =>
    setConfig({ ...config, classes: { ...config.classes, ...patch } })
  const setRuntime = (patch: Partial<AppConfigPayload['runtime']>) =>
    setConfig({ ...config, runtime: { ...config.runtime, ...patch } })
  const setWechat = (patch: Partial<AppConfigPayload['wechat']>) =>
    setConfig({ ...config, wechat: { ...config.wechat, ...patch } })

  return (
    <div className="space-y-6">
      {/* 顶部标题栏 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold text-slate-900">配置管理</h2>
          <p className="text-slate-500">系统参数和规则配置</p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:gap-3">
          {saved && (
            <Badge className="bg-green-500 gap-1">
              <CheckCircle2 className="w-4 h-4" />
              已保存并生效
            </Badge>
          )}
          {savePhase && (
            <Badge className="bg-blue-500 gap-1 animate-pulse">
              {savePhase}
            </Badge>
          )}
          {saveError && (
            <Badge variant="destructive" className="gap-1 max-w-xs truncate" title={saveError}>
              {saveError}
            </Badge>
          )}
          <Button 
            variant="outline" 
            className="gap-2" 
            onClick={() => loadConfig().catch(() => undefined)}
            disabled={saving}
          >
            <RotateCcw className="w-4 h-4" />
            重载配置
          </Button>
          <Button 
            className="gap-2" 
            onClick={() => handleSave()}
            disabled={!isAdmin || saving}
          >
            <Save className="w-4 h-4" />
            {saving ? '处理中...' : '保存配置'}
          </Button>
        </div>
      </div>

      {/* 标签页 */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="grid h-auto w-full max-w-2xl grid-cols-2 p-1 sm:grid-cols-4">
          <TabsTrigger value="video" className="gap-2">
            <Video className="w-4 h-4" />
            视频源
          </TabsTrigger>
          <TabsTrigger value="rules" className="gap-2">
            <Shield className="w-4 h-4" />
            检测规则
          </TabsTrigger>
          <TabsTrigger value="model" className="gap-2">
            <Box className="w-4 h-4" />
            模型配置
          </TabsTrigger>
          <TabsTrigger value="wechat" className="gap-2">
            <Bell className="w-4 h-4" />
            报警推送
          </TabsTrigger>
        </TabsList>

        {/* ==================== 视频源 ==================== */}
        <TabsContent value="video" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Video className="w-5 h-5 text-blue-600" />
                视频源配置
              </CardTitle>
              <CardDescription>配置多路摄像头视频输入源、抽帧、编码与输出参数</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* 多路摄像头地址 */}
              <div className="space-y-4 p-4 bg-blue-50 rounded-lg border border-blue-100">
                <Label className="text-base font-semibold text-blue-800">摄像头 RTSP 地址</Label>
                <div className="grid grid-cols-1 gap-4">
                  <Field label="摄像头 1（cam1）">
                    <Input
                      value={config.video.source_cam1}
                      onChange={(e) => setVideo({ source_cam1: e.target.value })}
                      placeholder="rtsp://admin:password@192.168.1.100:554/Streaming/Channels/101"
                    />
                  </Field>
                  <Field label="摄像头 2（cam2）">
                    <Input
                      value={config.video.source_cam2}
                      onChange={(e) => setVideo({ source_cam2: e.target.value })}
                      placeholder="rtsp://admin:password@192.168.1.101:554/Streaming/Channels/101"
                    />
                  </Field>
                  <Field label="摄像头 3（cam3）">
                    <Input
                      value={config.video.source_cam3}
                      onChange={(e) => setVideo({ source_cam3: e.target.value })}
                      placeholder="rtsp://admin:password@192.168.1.102:554/Streaming/Channels/101"
                    />
                  </Field>
                </div>
                <p className="text-xs text-blue-600">
                  至少需要两路摄像头。第三路填上后会自动参与联合判定。修改地址后需重启算法才能生效。
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Field label="输出目录">
                  <Input value={config.video.output_dir} onChange={(e) => setVideo({ output_dir: e.target.value })} />
                </Field>
                <Field label="抽帧间隔">
                  <Input
                    type="number"
                    value={config.video.process_every_n_frames}
                    onChange={(e) => setVideo({ process_every_n_frames: Number(e.target.value) })}
                  />
                </Field>
                <Field label="输出视频 FPS">
                  <Input
                    type="number"
                    value={config.video.annotated_video_fps}
                    onChange={(e) => setVideo({ annotated_video_fps: Number(e.target.value) })}
                  />
                </Field>
                <Field label="重连间隔（秒）">
                  <Input
                    type="number"
                    step="0.1"
                    value={config.video.reconnect_seconds}
                    onChange={(e) => setVideo({ reconnect_seconds: Number(e.target.value) })}
                  />
                </Field>
                <Field label="JPEG 质量">
                  <Input
                    type="number"
                    value={config.video.jpeg_quality}
                    onChange={(e) => setVideo({ jpeg_quality: Number(e.target.value) })}
                  />
                </Field>
                <Field label="摄像头缓冲区">
                  <Input
                    type="number"
                    value={config.video.camera_buffer_size}
                    onChange={(e) => setVideo({ camera_buffer_size: Number(e.target.value) })}
                  />
                </Field>
                <Field label="房间宽度基准">
                  <Input
                    type="number"
                    value={config.room.frame_width}
                    onChange={(e) => setRoom({ frame_width: Number(e.target.value) })}
                  />
                </Field>
                <Field label="房间高度基准">
                  <Input
                    type="number"
                    value={config.room.frame_height}
                    onChange={(e) => setRoom({ frame_height: Number(e.target.value) })}
                  />
                </Field>
              </div>

              <SwitchRow
                id="save_annotated_video"
                label="保存标注视频"
                description="是否保存带标注的检测结果视频"
                checked={config.video.save_annotated_video}
                onChange={(checked) => setVideo({ save_annotated_video: checked })}
              />
              <SwitchRow
                id="show_window"
                label="本地窗口显示"
                description="服务器环境一般保持关闭"
                checked={config.runtime.show_window}
                onChange={(checked) => setRuntime({ show_window: checked })}
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* ==================== 检测规则 ==================== */}
        <TabsContent value="rules" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Shield className="w-5 h-5 text-green-600" />
                检测规则配置
              </CardTitle>
              <CardDescription>配置离岗、玩手机、趴睡等行为检测的阈值参数</CardDescription>
            </CardHeader>
            <CardContent className="space-y-8">
              {/* 离岗相关 */}
              <div className="space-y-6">
                <Label className="text-base font-semibold text-slate-700">离岗检测</Label>
                <SliderRow title="离岗触发时间（秒）" value={config.rules.absent_seconds} min={10} max={1800} step={10} onChange={(v) => setRules({ absent_seconds: v })} />
                <SliderRow title="双摄离岗报警时间（秒）" value={config.rules.absent_alarm_seconds} min={10} max={600} step={10} onChange={(v) => setRules({ absent_alarm_seconds: v })} />
              </div>

              {/* 手机检测相关 */}
              <div className="space-y-6">
                <Label className="text-base font-semibold text-slate-700">手机检测</Label>
                <SliderRow title="玩手机触发时间（秒）" value={config.rules.phone_seconds} min={0.3} max={600} step={0.1} onChange={(v) => setRules({ phone_seconds: v })} />
                <SliderRow title="手机检测窗口（秒）" value={config.rules.phone_window_seconds} min={1} max={20} step={1} onChange={(v) => setRules({ phone_window_seconds: v })} />
                <SliderRow title="窗口内最小命中帧数" value={config.rules.phone_min_hits_in_window} min={1} max={30} step={1} onChange={(v) => setRules({ phone_min_hits_in_window: v })} />
                <SliderRow title="手机检测宽限（秒）" value={config.rules.phone_grace_seconds} min={0.5} max={10} step={0.5} onChange={(v) => setRules({ phone_grace_seconds: v })} />
                <SliderRow title="手机靠近人体阈值（px）" value={config.rules.phone_near_person_px} min={50} max={400} step={10} onChange={(v) => setRules({ phone_near_person_px: v })} />
                <SliderRow title="手机靠近头部阈值（px）" value={config.rules.phone_near_head_px} min={50} max={300} step={10} onChange={(v) => setRules({ phone_near_head_px: v })} />
              </div>

              {/* 趴睡检测相关 */}
              <div className="space-y-6">
                <Label className="text-base font-semibold text-slate-700">趴睡检测</Label>
                <SliderRow title="趴睡触发时间（秒）" value={config.rules.prone_sleep_seconds} min={60} max={1200} step={30} onChange={(v) => setRules({ prone_sleep_seconds: v })} />
                <SliderRow title="低头比例阈值" value={config.rules.prone_head_down_ratio_threshold} min={0.05} max={0.5} step={0.01} onChange={(v) => setRules({ prone_head_down_ratio_threshold: v })} />
                <SliderRow title="趴睡框高度比例阈值" value={config.rules.prone_bbox_height_ratio_threshold} min={0.05} max={0.5} step={0.01} onChange={(v) => setRules({ prone_bbox_height_ratio_threshold: v })} />
                <SliderRow title="趴睡连续帧阈值" value={config.rules.prone_consecutive_frames} min={1} max={30} step={1} onChange={(v) => setRules({ prone_consecutive_frames: v })} />
              </div>

              {/* 通用参数 */}
              <div className="space-y-6">
                <Label className="text-base font-semibold text-slate-700">通用参数</Label>
                <SliderRow title="静止运动阈值" value={config.rules.static_motion_threshold} min={1} max={20} step={1} onChange={(v) => setRules({ static_motion_threshold: v })} />
                <SliderRow title="人员状态 TTL（秒）" value={config.rules.state_ttl_seconds} min={5} max={120} step={1} onChange={(v) => setRules({ state_ttl_seconds: v })} />
                <SliderRow title="保安识别保活时间（秒）" value={config.rules.guard_hold_seconds} min={0.5} max={10} step={0.1} onChange={(v) => setRules({ guard_hold_seconds: v })} />
                <SliderRow title="双摄同步窗口（秒）" value={config.rules.dual_sync_seconds} min={0.5} max={10} step={0.5} onChange={(v) => setRules({ dual_sync_seconds: v })} />
              </div>

              {/* 报警冷却 */}
              <div className="space-y-6">
                <Label className="text-base font-semibold text-slate-700">报警冷却</Label>
                <SliderRow title="离岗报警冷却（秒）" value={config.rules.alarm_cooldown_absent} min={30} max={1800} step={30} onChange={(v) => setRules({ alarm_cooldown_absent: v })} />
                <SliderRow title="手机报警冷却（秒）" value={config.rules.alarm_cooldown_phone} min={30} max={1800} step={30} onChange={(v) => setRules({ alarm_cooldown_phone: v })} />
                <SliderRow title="趴睡报警冷却（秒）" value={config.rules.alarm_cooldown_prone_sleep} min={30} max={1800} step={30} onChange={(v) => setRules({ alarm_cooldown_prone_sleep: v })} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>


        {/* ==================== 模型配置 ==================== */}
        <TabsContent value="model" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Box className="w-5 h-5 text-purple-600" />
                模型配置
              </CardTitle>
              <CardDescription>配置检测模型、制服分类模型、类别映射和运行时参数</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <Field label="检测模型">
                <Input value={config.models.detector_model} onChange={(e) => setModels({ detector_model: e.target.value })} />
              </Field>
              <Field label="制服分类模型">
                <Input value={config.models.uniform_cls_model} onChange={(e) => setModels({ uniform_cls_model: e.target.value })} placeholder="路径留空则不启用制服分类" />
              </Field>
              <Field label="姿态模型">
                <Input value={config.models.pose_model_task} onChange={(e) => setModels({ pose_model_task: e.target.value })} placeholder="文件不存在则自动关闭姿态估计" />
              </Field>
              <Field label="跟踪器">
                <Input value={config.models.tracker} onChange={(e) => setModels({ tracker: e.target.value })} />
              </Field>
              <Field label="运行设备">
                <Input value={config.models.device} onChange={(e) => setModels({ device: e.target.value })} placeholder="留空为默认；可填 0 / cpu" />
              </Field>
              <Field label="检测置信度">
                <Input type="number" step="0.01" value={config.models.detector_conf} onChange={(e) => setModels({ detector_conf: Number(e.target.value) })} />
              </Field>
              <Field label="检测 IOU">
                <Input type="number" step="0.01" value={config.models.detector_iou} onChange={(e) => setModels({ detector_iou: Number(e.target.value) })} />
              </Field>
              <Field label="制服分类置信度">
                <Input type="number" step="0.01" value={config.models.uniform_cls_conf} onChange={(e) => setModels({ uniform_cls_conf: Number(e.target.value) })} />
              </Field>

              {/* 类别ID */}
              <Field label="person 类别 ID">
                <Input type="number" value={config.classes.person} onChange={(e) => setClasses({ person: Number(e.target.value) })} />
              </Field>
              <Field label="play_phone 类别 ID">
                <Input type="number" value={config.classes.play_phone} onChange={(e) => setClasses({ play_phone: Number(e.target.value) })} />
              </Field>

              {/* 运行时开关 */}
              <div className="md:col-span-2 flex flex-col gap-4">
                <SwitchRow id="debug" label="调试模式" description="输出更多调试信息" checked={config.runtime.debug} onChange={(checked) => setRuntime({ debug: checked })} />
                <SwitchRow id="draw_debug" label="叠加调试文字" description="关闭后不再在视频画面左上角绘制调试状态" checked={config.runtime.draw_debug} onChange={(checked) => setRuntime({ draw_debug: checked })} />
                <Field label="最大报警历史">
                  <Input type="number" value={config.runtime.max_alarm_history} onChange={(e) => setRuntime({ max_alarm_history: Number(e.target.value) })} />
                </Field>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ==================== 报警推送 ==================== */}
        <TabsContent value="wechat" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Bell className="w-5 h-5 text-orange-600" />
                企业微信报警推送
              </CardTitle>
              <CardDescription>配置企业微信应用消息推送，报警时自动发送视频到指定用户</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <SwitchRow
                id="wechat_enable"
                label="启用企业微信推送"
                description="关闭后报警只在前端显示，不推送到企业微信"
                checked={config.wechat.enable}
                onChange={(checked) => setWechat({ enable: checked })}
              />

              {config.wechat.enable && (
                <div className="space-y-6 p-4 bg-orange-50 rounded-lg border border-orange-100">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <Field label="企业 ID（corpid）">
                      <Input
                        value={config.wechat.corpid}
                        onChange={(e) => setWechat({ corpid: e.target.value })}
                        placeholder="企业微信后台 → 我的企业 → 企业ID"
                      />
                    </Field>
                    <Field label="应用 Secret（corpsecret）">
                      <Input
                        type="password"
                        value={config.wechat.corpsecret}
                        onChange={(e) => setWechat({ corpsecret: e.target.value })}
                        placeholder="企业微信后台 → 应用管理 → Secret"
                      />
                    </Field>
                    <Field label="应用 AgentId">
                      <Input
                        type="number"
                        value={config.wechat.agentid}
                        onChange={(e) => setWechat({ agentid: Number(e.target.value) })}
                      />
                    </Field>
                    <Field label="接收报警的用户（alarm_user）">
                      <Input
                        value={config.wechat.alarm_user}
                        onChange={(e) => setWechat({ alarm_user: e.target.value })}
                        placeholder="多个用户用 | 分隔，如 zhangsan|lisi"
                      />
                    </Field>
                    <Field label="摄像头名称">
                      <Input
                        value={config.wechat.camera_name}
                        onChange={(e) => setWechat({ camera_name: e.target.value })}
                        placeholder="显示在报警消息中的摄像头名称"
                      />
                    </Field>
                    <Field label="报警录制时长（秒）">
                      <Input
                        type="number"
                        step="1"
                        value={config.wechat.clip_seconds}
                        onChange={(e) => setWechat({ clip_seconds: Number(e.target.value) })}
                      />
                    </Field>
                  </div>
                  <p className="text-xs text-orange-600">
                    企业微信视频消息限制：单个文件不超过 10MB。如果推送失败请缩短录制时长。修改后需重启算法生效。
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ==================== 通用子组件 ====================

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
    </div>
  )
}

function SwitchRow({
  id,
  label,
  description,
  checked,
  onChange,
}: {
  id: string
  label: string
  description: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg">
      <div>
        <Label htmlFor={id} className="cursor-pointer">{label}</Label>
        <p className="text-sm text-slate-500">{description}</p>
      </div>
      <Switch id={id} checked={checked ?? false} onCheckedChange={onChange} />
    </div>
  )
}

function SliderRow({
  title,
  value,
  min,
  max,
  step,
  onChange,
}: {
  title: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}) {
  const safeValue = Number.isFinite(value) ? value : min
  return (
    <div className="space-y-3">
      <div className="flex justify-between text-sm">
        <Label>{title}</Label>
        <span>{safeValue}</span>
      </div>
      <Slider value={[safeValue]} onValueChange={([next]) => onChange(next ?? min)} min={min} max={max} step={step} />
    </div>
  )
}

export { ConfigSection }
export default ConfigSection
