// 文件说明：包含感兴趣区域的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

/**
 * 功能：读取或查询 `read` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（未显式标注）：目标路径
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`readFileSync`、`URL`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8')

test('ROI editor uses a raw frame and exposes no feature prop', () => {
  const editor = read('src/components/AiVisionRoiEditor.tsx')

  assert.match(editor, /aiVisionFrameUrl\(cameraKey, undefined, nonce\)/)
  assert.doesNotMatch(editor, /feature\?: string/)
})

test('logistics ROI hydration depends on stable IDs instead of polled objects', () => {
  const config = read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')
  const hydrationCall = config.indexOf('getLogisticsCameraConfig(feature')
  const hydrationStart = config.lastIndexOf('  useEffect(() => {', hydrationCall)
  const hydration = config.slice(
    hydrationStart,
    config.indexOf('  const invalidateMemberships'),
  )

  assert.notEqual(hydrationCall, -1)
  assert.notEqual(hydrationStart, -1)
  assert.match(config, /const selectedChannelDetailId = selectedChannelDetail\?\.id \?\? null/)
  assert.match(hydration, /getLogisticsCameraConfig\(feature, selectedChannelDetailId, selectedCameraId\)/)
  assert.match(hydration, /\[feature, selectedCameraId, selectedChannelDetailId\]/)
  assert.doesNotMatch(hydration, /\[feature, selectedCamera, selectedChannelDetail\]/)
})
