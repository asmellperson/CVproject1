import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const frontendRoot = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, frontendRoot), 'utf8').catch(() => '')

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
