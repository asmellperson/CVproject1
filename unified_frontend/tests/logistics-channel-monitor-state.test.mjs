// 文件说明：包含监控展示、状态管理的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const frontendRoot = new URL('../', import.meta.url)
/**
 * 功能：读取或查询 `read` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（未显式标注）：目标路径
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`readFile`、`URL`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const read = (path) => readFile(new URL(path, frontendRoot), 'utf8').catch(() => '')

/**
 * 功能：实现 `importTypeScript` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
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

test('first status sample establishes a baseline without a synthetic event', async () => {
  const source = await read('src/components/logistics_single_person/monitorPresentation.ts')
  const { appendLogisticsStatusEvent } = await importTypeScript(source)

  assert.deepEqual(appendLogisticsStatusEvent([], null, { reason: 'normal' }), [])
  assert.deepEqual(appendLogisticsStatusEvent([], null, { reason: 'empty' }), [])
})

test('a real logistics reason transition appends an event', async () => {
  const source = await read('src/components/logistics_single_person/monitorPresentation.ts')
  const { appendLogisticsStatusEvent } = await importTypeScript(source)

  const next = appendLogisticsStatusEvent([], 'normal', { reason: 'multiple' })
  assert.equal(next.length, 1)
  assert.equal(next[0].reason, 'multiple')
  assert.match(next[0].id, /-multiple$/)
})

test('a retained frame with a new request error is stale rather than online', async () => {
  const source = await read('src/components/logistics_single_person/monitorPresentation.ts')
  const { getLogisticsFramePresentation } = await importTypeScript(source)

  assert.deepEqual(getLogisticsFramePresentation('blob:recent', '帧请求超时'), {
    state: 'stale',
    label: '画面异常 / 最近帧',
    showFrame: true,
    errorMessage: '帧请求超时',
  })
  assert.equal(getLogisticsFramePresentation('blob:live', null).state, 'live')
  assert.equal(getLogisticsFramePresentation(null, '连接失败').state, 'error')
  assert.equal(getLogisticsFramePresentation(null, null).state, 'waiting')
})
