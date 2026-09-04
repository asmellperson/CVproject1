import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('shared logistics section owns channel selection and polled composite frame state', () => {
  const section = read('src/components/logistics_single_person/LogisticsChannelSection.tsx')
  const monitor = read('src/components/logistics_single_person/LogisticsChannelMonitorView.tsx')

  assert.match(section, /LogisticsChannelMonitorView/)
  assert.match(section, /useLogisticsChannels/)
  assert.match(section, /useLogisticsChannelStatus/)
  assert.match(monitor, /物流通道/)
  assert.match(monitor, /今日通道告警/)
  assert.match(monitor, /结果过期/)
  assert.match(monitor, /等待检测结果/)
  assert.match(monitor, /camera\.updated_at/)
  assert.match(monitor, /暂无更新时间/)
  assert.match(monitor, /Number\.isFinite/)
  assert.match(monitor, /frameUrl/)
  assert.doesNotMatch(monitor, /camera_id.*frame/i)
})

test('shared logistics monitor follows the approved dwell dashboard layout', () => {
  const section = read('src/components/logistics_single_person/LogisticsChannelSection.tsx')
  const monitor = read('src/components/logistics_single_person/LogisticsChannelMonitorView.tsx')
  const pageHeader = read('src/components/detection/DetectionPageHeader.tsx')

  assert.match(section, /min-h-\[calc\(100vh-7rem\)\] rounded-3xl bg-\[#F3F5FA\]/)
  assert.match(section, /DetectionPageHeader/)
  assert.match(section, /LogisticsChannelRuntimeControl/)
  assert.match(pageHeader, /data-\[state=active\]:bg-\[#0B1226\]/)

  assert.match(monitor, /grid grid-cols-2 gap-4 lg:grid-cols-4/)
  assert.match(monitor, /ResizableMonitorLayout id=\{`logistics-channel-\$\{feature\}`\}/)
  assert.match(monitor, /lg:col-span-2/)
  for (const label of ['监控对象', '判定说明', '实时事件', '物流通道实时监控']) {
    assert.match(monitor, new RegExp(label))
  }

  assert.doesNotMatch(monitor, /pointer-events-none absolute/)
  assert.doesNotMatch(monitor, /GlassPill/)
  assert.doesNotMatch(monitor, /from-(rose|emerald|black).*via-transparent/)
})

test('shared channel configuration separates parameters and alarm push for every logistics feature', () => {
  const config = read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')

  for (const label of ['通道管理', '摄像头', '检测参数', 'ROI 配置', '报警推送']) {
    assert.match(config, new RegExp(label))
  }
  assert.doesNotMatch(config, /通道规则/)
  assert.match(config, /AlarmPushConfig/)
  assert.match(config, /人体检测阈值/)
  assert.match(config, /confidence_threshold/)
  assert.doesNotMatch(config, /保存数据库告警|启用警号|警号 ID|警号事件 ID/)
  assert.doesNotMatch(config, /corpid|corp_id|corpsecret|corp_secret|agentid|agent_id/i)
  assert.match(config, /DialogContent/)
  assert.match(config, /DialogTitle>添加通道/)
  assert.match(config, /确认添加/)
  assert.match(config, /取消/)
  assert.doesNotMatch(config, /CardTitle[^\n]*新增物流通道/)
  assert.doesNotMatch(config, /aria-label="物流通道名称"/)
  assert.match(config, /onChannelCreated\(result\)/)
  assert.match(config, /dispatchCreateDialog\(\{ type: 'success' \}\)/)
  assert.match(config, /collectChannelMemberCounts/)
  assert.match(config, /enabled.*total.*路/)
  assert.match(config, /onCheckedChange=\{\(enabled\) => setChannelEnabled\(channel, enabled\)\}/)
  assert.match(config, /channel\.enabled \? '停用通道' : '启用通道'/)
  assert.doesNotMatch(config, /启用当前物流通道/)
  assert.match(config, /DetectionConfigTabsList/)
  assert.match(config, /DetectionConfigCardHeader/)
  assert.match(config, /绑定已有摄像头/)
  assert.match(config, /新建摄像头并绑定/)
  assert.match(config, /LogisticsCameraCreateDialog/)
  assert.match(config, /setCameraDialogOpen\(true\)/)
  assert.doesNotMatch(config, /setNewCamera/)
  assert.match(config, /最多 9 路/)
  assert.match(config, /上移/)
  assert.match(config, /下移/)
  assert.match(config, /逐路 ROI 摄像头/)
  assert.match(config, /每日检测开始时间/)
  assert.match(config, /每日检测结束时间/)
  assert.match(config, /无人持续时间/)
  assert.match(config, /多人持续时间/)
  assert.match(config, /AiVisionRoiEditor/)
  assert.match(config, /getLogisticsCameraConfig/)
  assert.match(config, /updateLogisticsCameraConfig/)
  assert.match(config, /setLogisticsChannelCameraEnabled/)
  assert.match(config, /if \(!isAdmin\)/)
  assert.match(config, /Promise\.all\(channelIds\.map/)
  assert.match(config, /filterBindableCameras/)
  assert.match(config, /confirmMembershipRemoval/)
  assert.match(config, /removalConfirmationText\(cameraName, selectedChannelDetail\.name\)/)
  assert.match(config, /isAdmin/)
  assert.match(config, /disabled=\{!isAdmin/)
})

test('all logistics mutations use the typed channel API rather than camera-id config routes', () => {
  const config = read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')
  for (const operation of [
    'createLogisticsChannel',
    'updateLogisticsChannel',
    'deleteLogisticsChannel',
    'addLogisticsChannelCamera',
    'moveLogisticsChannelCamera',
    'reorderLogisticsChannelCameras',
    'removeLogisticsChannelCamera',
  ]) assert.match(config, new RegExp(operation))

  assert.match(config, /updateLogisticsChannel[\s\S]*?config: \{/)

  assert.doesNotMatch(config, /\/configs\/\$\{[^}]*camera_id/)
})

test('existing camera select disables Radix scroll buttons without changing the shared default', () => {
  const select = read('src/components/ui/select.tsx')
  const config = read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')

  assert.match(select, /showScrollButtons = true/)
  assert.match(select, /showScrollButtons \? <SelectScrollUpButton \/> : null/)
  assert.match(select, /showScrollButtons \? <SelectScrollDownButton \/> : null/)
  assert.match(config, /<SelectContent showScrollButtons=\{false\}>/)
})

test('camera binding actions share one module with two choices', () => {
  const config = read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')
  const members = config.slice(
    config.indexOf('<TabsContent value="members"'),
    config.indexOf('<TabsContent value="roi"'),
  )

  assert.match(members, /title="绑定摄像头"/)
  assert.match(members, /<div className="grid gap-4 lg:grid-cols-2">/)
  assert.match(members, /<h3 className="text-sm font-semibold">绑定已有摄像头<\/h3>/)
  assert.match(members, /<h3 className="text-sm font-semibold">新建摄像头并绑定<\/h3>/)
  assert.doesNotMatch(members, /title="绑定已有摄像头"/)
  assert.doesNotMatch(members, /title="新建摄像头并绑定"/)
})
