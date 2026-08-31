// 文件说明：包含`logistics-channel-create-dialog.test` 模块的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(
  new URL('../src/components/logistics_single_person/channelCreateDialogState.ts', import.meta.url),
  'utf8',
).catch(() => '')

/**
 * 功能：实现 `importTypeScript` 对应的`logistics-channel-create-dialog.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
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

test('channel creation dialog closes and clears only after success', async () => {
  const { channelCreateDialogReducer, initialChannelCreateDialogState } = await importTypeScript(source)
  let state = channelCreateDialogReducer(initialChannelCreateDialogState, { type: 'open' })
  state = channelCreateDialogReducer(state, { type: 'change-name', name: '一号物流通道' })
  state = channelCreateDialogReducer(state, { type: 'submit' })

  assert.deepEqual(state, { open: true, name: '一号物流通道', error: '', submitting: true })
  assert.deepEqual(channelCreateDialogReducer(state, { type: 'success' }), {
    open: false,
    name: '',
    error: '',
    submitting: false,
  })
})

test('channel creation failure keeps dialog and input available for correction', async () => {
  const { channelCreateDialogReducer, initialChannelCreateDialogState } = await importTypeScript(source)
  let state = channelCreateDialogReducer(initialChannelCreateDialogState, { type: 'open' })
  state = channelCreateDialogReducer(state, { type: 'change-name', name: '重复名称' })
  state = channelCreateDialogReducer(state, { type: 'submit' })
  state = channelCreateDialogReducer(state, { type: 'failure', error: '名称已存在' })

  assert.deepEqual(state, {
    open: true,
    name: '重复名称',
    error: '名称已存在',
    submitting: false,
  })
})
