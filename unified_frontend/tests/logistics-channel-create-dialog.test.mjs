import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(
  new URL('../src/components/logistics_single_person/channelCreateDialogState.ts', import.meta.url),
  'utf8',
).catch(() => '')

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
  state = channelCreateDialogReducer(state, { type: 'change-department', department: 'electronics_electrician' })
  state = channelCreateDialogReducer(state, { type: 'submit' })

  assert.deepEqual(state, { open: true, name: '一号物流通道', department: 'electronics_electrician', error: '', submitting: true })
  assert.deepEqual(channelCreateDialogReducer(state, { type: 'success' }), {
    open: false,
    name: '',
    department: '',
    error: '',
    submitting: false,
  })
})

test('channel creation failure keeps dialog and input available for correction', async () => {
  const { channelCreateDialogReducer, initialChannelCreateDialogState } = await importTypeScript(source)
  let state = channelCreateDialogReducer(initialChannelCreateDialogState, { type: 'open' })
  state = channelCreateDialogReducer(state, { type: 'change-name', name: '重复名称' })
  state = channelCreateDialogReducer(state, { type: 'change-department', department: 'electronics_electrician' })
  state = channelCreateDialogReducer(state, { type: 'submit' })
  state = channelCreateDialogReducer(state, { type: 'failure', error: '名称已存在' })

  assert.deepEqual(state, {
    open: true,
    name: '重复名称',
    department: 'electronics_electrician',
    error: '名称已存在',
    submitting: false,
  })
})
