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
  const deleteBlock = config.slice(config.indexOf('const deleteChannel'), config.indexOf('const addExisting'))
  const requestPosition = deleteBlock.indexOf('await deleteLogisticsChannel(feature, deletedChannelId)')
  const convergencePosition = deleteBlock.indexOf('onChannelDeleted(deletedChannelId)')
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
