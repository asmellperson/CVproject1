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

test('ordinary AiVision pages do not expose global runtime controls', async () => {
  const pages = [
    'IntrusionDetectionSection.tsx',
    'DoorDetectionSection.tsx',
    'FaceDetectionSection.tsx',
    'PhoneDetectionSection.tsx',
    'HumanDetectionSection.tsx',
  ]

  for (const file of pages) {
    const source = await read(`src/sections/${file}`)
    assert.doesNotMatch(source, /AiVisionFeatureRuntimeControl/)
    assert.doesNotMatch(source, /runtimeControl=/)
  }
})

test('AiVision API client does not expose global capability controls', async () => {
  const api = await read('src/lib/aivision.ts')

  assert.doesNotMatch(api, /getAiVisionCapabilities/)
  assert.doesNotMatch(api, /startAiVisionCapability/)
  assert.doesNotMatch(api, /stopAiVisionCapability/)
  assert.doesNotMatch(api, /\/api\/runtime\/capabilities/)
})

test('exception alert settings use the dedicated API route', async () => {
  const api = await read('src/lib/aivision.ts')

  assert.match(api, /\/api\/exception-alert/)
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
