// 文件说明：包含运行时的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
/**
 * 功能：读取或查询 `read` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（未显式标注）：目标路径
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`readFile`、`URL`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const read = (path) => readFile(new URL(path, root), 'utf8')

test('ordinary AiVision pages share the same runtime control', async () => {
  const expected = new Map([
    ['IntrusionDetectionSection.tsx', 'blocks'],
    ['DoorDetectionSection.tsx', 'detect_door'],
    ['FaceDetectionSection.tsx', 'detect_face'],
    ['PhoneDetectionSection.tsx', 'detect_phone'],
  ])

  for (const [file, feature] of expected) {
    const source = await read(`src/sections/${file}`)
    assert.match(source, /AiVisionFeatureRuntimeControl/)
    assert.match(source, new RegExp(`feature="${feature}" isAdmin=\\{isAdmin\\}`))
  }

  const [humanPage, haodaPage] = await Promise.all([
    read('src/sections/HumanDetectionSection.tsx'),
    read('src/sections/HaodaHumanDetectionSection.tsx'),
  ])
  assert.match(humanPage, /AiVisionFeatureRuntimeControl feature=\{feature\} isAdmin=\{isAdmin\}/)
  assert.match(haodaPage, /feature="detect_human_haoda"/)
})

test('runtime control polls status and exposes separate admin start and stop actions', async () => {
  const [control, sharedControl, api, platformHook] = await Promise.all([
    read('src/components/AiVisionFeatureRuntimeControl.tsx'),
    read('src/components/detection/DetectionRuntimeControl.tsx'),
    read('src/lib/aivision.ts'),
    read('src/hooks/use-platform-status.ts'),
  ])

  assert.match(control, /useSerialPoll/)
  assert.match(control, /startAiVisionCapability\(feature\)/)
  assert.match(control, /stopAiVisionCapability\(feature\)/)
  assert.match(control, /isAdmin=\{isAdmin\}/)
  assert.match(sharedControl, /!isAdmin/)
  assert.match(control, /检测控制/)
  assert.match(sharedControl, /PowerOff/)
  assert.match(sharedControl, /Power/)
  assert.doesNotMatch(sharedControl, /Play|Pause/)
  assert.match(api, /\/api\/v2\/runtime\/capabilities/)
  assert.match(platformHook, /PLATFORM_RUNTIME_CHANGED_EVENT/)
})

test('guard configuration saves without implicitly starting a manually stopped site', async () => {
  const [config, monitor, guardPage, runtime] = await Promise.all([
    read('src/sections/ConfigSection.tsx'),
    read('src/sections/MonitorSection.tsx'),
    read('src/sections/GuardBehaviorSection.tsx'),
    read('src/components/guard_room/GuardRoomRuntimeControl.tsx'),
  ])

  assert.match(config, /if \(site\.enabled\)/)
  assert.match(config, /配置已保存，检测保持关闭/)
  assert.doesNotMatch(monitor, /startGuardRoomSiteRuntime|stopGuardRoomSiteRuntime/)
  assert.match(runtime, /startGuardRoomSiteRuntime\(site\.id\)/)
  assert.match(runtime, /stopGuardRoomSiteRuntime\(site\.id\)/)
  assert.match(runtime, /await onChanged\(\)/)
  assert.match(guardPage, /onChanged=\{loadSites\}/)
})
