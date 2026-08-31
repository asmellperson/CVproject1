// 文件说明：包含摄像头的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const stateSource = await readFile(
  new URL('../src/components/logistics_single_person/logisticsCameraCreateState.ts', import.meta.url),
  'utf8',
).catch(() => '')
const dialogSource = await readFile(
  new URL('../src/components/logistics_single_person/LogisticsCameraCreateDialog.tsx', import.meta.url),
  'utf8',
).catch(() => '')

/**
 * 功能：实现 `importTypeScript` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（未显式标注）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`transpileModule`、`import`、`from`、`toString`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function importTypeScript(value) {
  const output = ts.transpileModule(value, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`)
}

test('validates and normalizes a logistics camera draft', async () => {
  assert.ok(stateSource, 'logistics camera draft state module must exist')
  const { validateLogisticsCameraDraft, normalizeLogisticsCameraDraft } = await importTypeScript(stateSource)

  assert.match(validateLogisticsCameraDraft({ name: '', fps: '5', url: 'rtsp://camera' }), /名称/)
  assert.match(validateLogisticsCameraDraft({ name: '东门', fps: '0', url: 'rtsp://camera' }), /FPS/)
  assert.match(validateLogisticsCameraDraft({ name: '东门', fps: '1.5', url: 'rtsp://camera' }), /FPS/)
  assert.match(validateLogisticsCameraDraft({ name: '东门', fps: '5', url: '' }), /RTSP/)
  assert.equal(validateLogisticsCameraDraft({ name: ' 东门 ', fps: '5', url: ' rtsp://camera ' }), null)
  assert.deepEqual(
    normalizeLogisticsCameraDraft({ name: ' 东门 ', fps: '5', url: ' rtsp://camera ' }),
    { name: '东门', fps: 5, url: 'rtsp://camera' },
  )
})

test('dialog exposes the approved fields and keeps failures visible', () => {
  assert.ok(dialogSource, 'logistics camera create dialog must exist')
  for (const label of ['摄像头名称', 'FPS', 'RTSP 地址', '新建并绑定']) {
    assert.match(dialogSource, new RegExp(label))
  }
  assert.match(dialogSource, /await onSubmit\(payload\)/)
  assert.match(dialogSource, /setError\(messageOf\(reason\)\)/)
  assert.match(dialogSource, /if \(!open && !busy\) onClose\(\)/)
})
