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
