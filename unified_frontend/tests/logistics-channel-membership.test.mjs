import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/components/logistics_single_person/membershipState.ts', import.meta.url), 'utf8').catch(() => '')
const configSource = await readFile(new URL('../src/components/logistics_single_person/LogisticsChannelConfigView.tsx', import.meta.url), 'utf8').catch(() => '')

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
