import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/components/logistics_single_person/membershipState.ts', import.meta.url), 'utf8').catch(() => '')

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
