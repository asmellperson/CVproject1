import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)

test('AiVision model partial updates use PATCH only', async () => {
  const source = await readFile(new URL('src/lib/aivision.ts', frontendRoot), 'utf8')
  const start = source.indexOf('export async function updateAiVisionModel')
  const end = source.indexOf('export async function createAiVisionModel', start)
  const updateSource = source.slice(start, end)

  assert.ok(start >= 0 && end > start)
  assert.match(updateSource, /\/api\/models\//)
  assert.match(updateSource, /method:\s*'PATCH'/)
  assert.doesNotMatch(updateSource, /method:\s*'PUT'/)
})
