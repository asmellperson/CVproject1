// 文件说明：包含`logistics-channel-membership.test` 模块的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/components/logistics_single_person/membershipState.ts', import.meta.url), 'utf8').catch(() => '')
const configSource = await readFile(new URL('../src/components/logistics_single_person/LogisticsChannelConfigView.tsx', import.meta.url), 'utf8').catch(() => '')

/**
 * 功能：实现 `importTypeScript` 对应的`logistics-channel-membership.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
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

test('filters cameras bound to any channel in the current feature', async () => {
  const { collectBoundCameraIds, filterBindableCameras } = await importTypeScript(source)
  const bound = collectBoundCameraIds([
    { members: [{ camera_id: 1, enabled: true }, { camera_id: 2, enabled: false }] },
    { members: [{ camera_id: 3, enabled: true }] },
  ])
  assert.deepEqual([...bound].sort(), [1, 2, 3])
  assert.deepEqual(
    filterBindableCameras([{ camera_id: 1 }, { camera_id: 2 }, { camera_id: 3 }, { camera_id: 4 }], bound).map((camera) => camera.camera_id),
    [4],
  )
})

test('derives enabled and total camera counts for every loaded channel detail', async () => {
  const { collectChannelMemberCounts } = await importTypeScript(source)
  const counts = collectChannelMemberCounts([
    { id: 7, members: [{ enabled: true }, { enabled: false }, { enabled: true }] },
    { id: 8, members: [] },
  ])

  assert.deepEqual(counts, {
    7: { enabled: 2, total: 3 },
    8: { enabled: 0, total: 0 },
  })
})

test('cancelled removal never invokes the mutation', async () => {
  const { confirmMembershipRemoval, removalConfirmationText } = await importTypeScript(source)
  let calls = 0
  assert.equal(confirmMembershipRemoval(() => false, () => { calls += 1 }), false)
  assert.equal(calls, 0)
  assert.equal(confirmMembershipRemoval(() => true, () => { calls += 1 }), true)
  assert.equal(calls, 1)
  assert.match(removalConfirmationText('东门', '物流一通道'), /东门.*物流一通道/)
})

test('a late response from the previous feature cannot replace current membership ids', async () => {
  const { isMembershipLoadCurrent } = await importTypeScript(source)
  let current = { generation: 1, feature: 'feature-a', channelIdsKey: '1' }
  let applied = []
  let resolveSlow
  const slow = new Promise((resolve) => { resolveSlow = resolve })
  const apply = async (request, promise) => {
    const cameraIds = await promise
    if (isMembershipLoadCurrent(request, current)) applied = cameraIds
  }

  const oldRequest = { ...current }
  const oldWork = apply(oldRequest, slow)
  current = { generation: 2, feature: 'feature-b', channelIdsKey: '9' }
  await apply({ ...current }, Promise.resolve([9]))
  resolveSlow([1])
  await oldWork

  assert.deepEqual(applied, [9])
})

test('enabling or disabling a member refreshes membership counts only through the successful run path', () => {
  const setEnabledBlock = configSource.slice(
    configSource.indexOf('const setMemberEnabled'),
    configSource.indexOf('const saveRoi'),
  )
  assert.match(setEnabledBlock, /enabled \? '摄像头已启用。' : '摄像头已停用。',\s*true,?\s*\)/)

  const runBlock = configSource.slice(configSource.indexOf('const run = async'), configSource.indexOf('const createChannel'))
  const mutationPosition = runBlock.indexOf('await action()')
  const refreshPosition = runBlock.indexOf('if (reloadMemberships)')
  const catchPosition = runBlock.indexOf('} catch (reason)')
  assert.ok(mutationPosition >= 0 && refreshPosition > mutationPosition)
  assert.ok(catchPosition > refreshPosition, 'membership refresh must remain inside the success-only try path')
})

test('creating a camera refreshes memberships, channel data, and the global camera list', () => {
  const createBlock = configSource.slice(
    configSource.indexOf('const createCameraAndBind'),
    configSource.indexOf('const moveMember'),
  )
  assert.match(createBlock, /await addLogisticsChannelCamera/)
  assert.match(createBlock, /invalidateMemberships\(\)/)
  assert.match(createBlock, /onChanged\(\)/)
  assert.match(createBlock, /aivision:cameras-changed/)
  assert.match(createBlock, /throw reason/)
})
