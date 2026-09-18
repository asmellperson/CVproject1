import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/components/security-inspection/statusPresentation.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const { inspectionStatusPresentation: present } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

const status = {
  running: true, queue: 0, active: 0, error: null,
  vlm: { reachable: null, checking: true, last_success: null, last_error: null,
    consecutive_failures: 0, circuit_state: 'closed', retry_after_sec: null },
}
const withHealth = (health) => ({ ...status, vlm: { ...status.vlm, ...health } })

test('starting a worker and passing the probe do not claim successful detection', () => {
  assert.equal(present(null, '').label, '正在读取检测状态')
  assert.equal(present(status, '').label, '正在检查千问连接')
  assert.equal(present(withHealth({ reachable: true, checking: false }), '').label, '千问接口可达，等待首次判定')
  assert.equal(present(withHealth({ reachable: true, last_success: '2026-09-18T00:00:00Z' }), '').label, '检测服务就绪')
})

test('circuit state overrides previous success and explains automatic retry', () => {
  const unavailable = withHealth({ reachable: false, circuit_state: 'open', checking: false,
    last_success: '2026-09-18T00:00:00Z', last_error: '连接失败', retry_after_sec: 10 })
  assert.deepEqual(present(unavailable, ''), {
    label: '千问不可用，已暂停判定', error: '连接失败；10 秒后自动检查连接。',
  })
  assert.match(present({ ...unavailable, vlm: { ...unavailable.vlm, checking: true } }, '').error, /正在重新检查连接/)
  assert.equal(present(withHealth({ reachable: true, circuit_state: 'half_open', last_error: '上一次失败' }), '').label,
    '千问恢复验证中')
})

test('poll errors and stopped consumers cannot display stale readiness', () => {
  const ready = withHealth({ reachable: true, last_success: '2026-09-18T00:00:00Z' })
  assert.deepEqual(present(ready, '状态请求超时'), { label: '状态读取失败', error: '状态请求超时' })
  assert.equal(present({ ...ready, running: false, error: '人体模型未运行' }, '').label, '检测服务未运行')
  assert.deepEqual(present({ ...ready, error: '保存失败' }, ''), { label: '判定服务异常', error: '保存失败' })
  assert.equal(present(withHealth({ reachable: true, last_error: '判定失败' }), '').label, '判定服务异常')
})
