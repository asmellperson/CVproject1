// 文件说明：包含`logistics-channel-deletion.test` 模块的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const frontendRoot = new URL('../', import.meta.url)
/**
 * 功能：读取或查询 `read` 对应的`logistics-channel-deletion.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
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
 * 功能：实现 `importTypeScript` 对应的`logistics-channel-deletion.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
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

test('selects the next channel, then previous channel, after deleting the selection', async () => {
  const source = await read('src/components/logistics_single_person/channelSelection.ts')
  const { selectAfterChannelDeletion } = await importTypeScript(source)
  const a = { id: 1 }
  const b = { id: 2 }
  const c = { id: 3 }

  assert.equal(selectAfterChannelDeletion([a, b, c], b.id, b.id), c.id)
  assert.equal(selectAfterChannelDeletion([a, b], b.id, b.id), a.id)
  assert.equal(selectAfterChannelDeletion([a], a.id, a.id), null)
  assert.equal(selectAfterChannelDeletion([a, b], a.id, b.id), b.id)
})

test('delete convergence happens only after the delete request resolves', async () => {
  const config = await read('src/components/logistics_single_person/LogisticsChannelConfigView.tsx')
  const deleteBlock = config.slice(config.indexOf('const deleteChannelById'), config.indexOf('const addExisting'))
  const requestPosition = deleteBlock.indexOf('await deleteLogisticsChannel(feature, channelId)')
  const convergencePosition = deleteBlock.indexOf('onChannelDeleted(channelId)')
  assert.ok(requestPosition >= 0, 'delete API call must be awaited')
  assert.ok(convergencePosition > requestPosition, 'local convergence must happen only after delete succeeds')
})

test('the channel hook invalidates stale list and detail requests when removing locally', async () => {
  const hook = await read('src/components/logistics_single_person/useLogisticsChannels.ts')
  assert.match(hook, /const removeChannelLocally = useCallback/)
  assert.match(hook, /listRequestGenerationRef\.current \+= 1/)
  assert.match(hook, /detailRequestGenerationRef\.current \+= 1/)
  assert.match(hook, /currentSelectedChannelIdRef\.current = nextSelected/)
  assert.match(hook, /setSelectedChannelDetail\(null\)/)
})

/**
 * 功能：实现 `deferred` 对应的`logistics-channel-deletion.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Promise`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

test('stale list requests cannot apply delayed resolve, reject, or finally state', async () => {
  const source = await read('src/components/logistics_single_person/channelRequestState.ts')
  const { isCurrentChannelListRequest } = await importTypeScript(source)
  let current = { feature: 'feature-a', generation: 0 }
  const state = { channels: ['current'], error: null, loading: true }

  const run = async (work) => {
    const request = { ...current }
    try {
      const channels = await work
      if (isCurrentChannelListRequest(request, current)) state.channels = channels
    } catch (reason) {
      if (isCurrentChannelListRequest(request, current)) state.error = String(reason)
    } finally {
      if (isCurrentChannelListRequest(request, current)) state.loading = false
    }
  }

  const slowResolve = deferred()
  const resolving = run(slowResolve.promise)
  current = { ...current, generation: 1 }
  slowResolve.resolve(['deleted-channel'])
  await resolving
  assert.deepEqual(state, { channels: ['current'], error: null, loading: true })

  const slowReject = deferred()
  const rejecting = run(slowReject.promise)
  current = { ...current, generation: 2 }
  slowReject.reject(new Error('stale list failure'))
  await rejecting
  assert.deepEqual(state, { channels: ['current'], error: null, loading: true })
})

test('stale detail requests cannot apply delayed resolve or reject state', async () => {
  const source = await read('src/components/logistics_single_person/channelRequestState.ts')
  const { isCurrentChannelDetailRequest } = await importTypeScript(source)
  let current = { feature: 'feature-a', channelId: 1, generation: 0 }
  const state = { detail: 'current', error: null }

  const run = async (work) => {
    const request = { ...current }
    try {
      const detail = await work
      if (isCurrentChannelDetailRequest(request, current)) state.detail = detail
    } catch (reason) {
      if (isCurrentChannelDetailRequest(request, current)) state.error = String(reason)
    }
  }

  const slowResolve = deferred()
  const resolving = run(slowResolve.promise)
  current = { feature: 'feature-a', channelId: 2, generation: 1 }
  slowResolve.resolve('deleted-channel-detail')
  await resolving
  assert.deepEqual(state, { detail: 'current', error: null })

  const slowReject = deferred()
  const rejecting = run(slowReject.promise)
  current = { ...current, generation: 2 }
  slowReject.reject(new Error('stale detail failure'))
  await rejecting
  assert.deepEqual(state, { detail: 'current', error: null })
})

test('a delayed pre-create list response cannot replace the newly selected channel', async () => {
  const source = await read('src/components/logistics_single_person/channelRequestState.ts')
  const { advanceChannelRequestsForCreatedChannel, isCurrentChannelListRequest } = await importTypeScript(source)
  let cursor = {
    feature: 'feature-a',
    listGeneration: 4,
    detailGeneration: 8,
    selectedChannelId: 1,
  }
  const state = { channels: [{ id: 1 }], selectedChannelId: 1 }
  const oldRequest = { feature: cursor.feature, generation: cursor.listGeneration }
  const slowList = deferred()
  const applyingOldList = slowList.promise.then((items) => {
    const current = { feature: cursor.feature, generation: cursor.listGeneration }
    if (!isCurrentChannelListRequest(oldRequest, current)) return
    state.channels = items
    state.selectedChannelId = items[0]?.id ?? null
  })

  cursor = advanceChannelRequestsForCreatedChannel(cursor, 9)
  state.channels = [...state.channels, { id: 9 }]
  state.selectedChannelId = cursor.selectedChannelId
  slowList.resolve([{ id: 1 }])
  await applyingOldList

  assert.deepEqual(cursor, {
    feature: 'feature-a',
    listGeneration: 5,
    detailGeneration: 9,
    selectedChannelId: 9,
  })
  assert.deepEqual(state, { channels: [{ id: 1 }, { id: 9 }], selectedChannelId: 9 })
})

test('a failed create request leaves request generations and selection unchanged', async () => {
  const source = await read('src/components/logistics_single_person/channelRequestState.ts')
  const { advanceChannelRequestsForCreatedChannel } = await importTypeScript(source)
  const original = {
    feature: 'feature-a',
    listGeneration: 2,
    detailGeneration: 3,
    selectedChannelId: 1,
  }
  let cursor = original
  const createRequest = deferred()
  const create = async () => {
    try {
      const created = await createRequest.promise
      cursor = advanceChannelRequestsForCreatedChannel(cursor, created.id)
    } catch {
      // The production callback is likewise only reached after create resolves.
    }
  }

  const pending = create()
  createRequest.reject(new Error('duplicate channel'))
  await pending
  assert.equal(cursor, original)
})
