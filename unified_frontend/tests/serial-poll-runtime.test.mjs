// 文件说明：包含运行时的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'

import { buildSync } from 'esbuild'

const frontendRoot = new URL('../', import.meta.url)

test('executes deferred serial poll regressions without overlapping restarts', async () => {
  const temporaryDirectory = mkdtempSync(join(tmpdir(), 'aicv-serial-poll-'))
  const bundlePath = join(temporaryDirectory, 'serial-poll.test.mjs')

  try {
    buildSync({
      entryPoints: [fileURLToPath(new URL('src/lib/serial-poll.test.ts', frontendRoot))],
      outfile: bundlePath,
      bundle: true,
      platform: 'node',
      format: 'esm',
      logLevel: 'silent',
    })

    const runtimeModule = await import(pathToFileURL(bundlePath).href)
    assert.ok(runtimeModule.serialPollTestRun instanceof Promise)
    await runtimeModule.serialPollTestRun
  } finally {
    rmSync(temporaryDirectory, { recursive: true, force: true })
  }
})
