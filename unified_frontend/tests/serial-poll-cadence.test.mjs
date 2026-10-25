import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/serial-poll.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const { createSerialPoller } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

function setup(intervalMode) {
  let clock = 0
  let sequence = 0
  let active = 0
  let maxActive = 0
  const timers = new Map()
  const rounds = []
  const poller = createSerialPoller({
    intervalMs: 500, timeoutMs: 8000, intervalMode, now: () => clock,
    setTimeoutFn(callback, delay) {
      const id = ++sequence
      timers.set(id, { callback, delay, deadline: clock + delay })
      return id
    },
    clearTimeoutFn(id) { timers.delete(id) },
    task: (signal) => {
      active++
      maxActive = Math.max(maxActive, active)
      return new Promise((resolve) => rounds.push({
        signal, startedAt: clock, finish() { active--; resolve() },
      }))
    },
  })
  return {
    poller, rounds, timers,
    time(at) { clock = at },
    maxActive: () => maxActive,
    next() {
      const entry = [...timers].sort(([, a], [, b]) => a.deadline - b.deadline)[0]
      assert.ok(entry, '应该存在下一轮或超时定时器')
      const [id, timer] = entry
      timers.delete(id)
      clock = timer.deadline
      timer.callback()
      return timer
    },
  }
}

async function settle() { await Promise.resolve(); await Promise.resolve() }

test('预览取图耗时220毫秒时，仅再等待280毫秒，下一轮仍从500毫秒开始', async () => {
  const state = setup('from-start')
  state.poller.start()
  state.time(220)
  state.rounds[0].finish()
  await settle()
  assert.equal(state.next().delay, 280)
  assert.equal(state.rounds[1].startedAt, 500)
  assert.equal(state.maxActive(), 1)
  state.poller.stop()
  state.rounds[1].finish()
  await settle()
  assert.equal(state.timers.size, 0)
})

test('普通业务轮询保留任务完成后再等待500毫秒的行为', async () => {
  const state = setup()
  state.poller.start()
  state.time(220)
  state.rounds[0].finish()
  await settle()
  assert.equal(state.next().delay, 500)
  assert.equal(state.rounds[1].startedAt, 720)
  state.poller.stop()
  state.rounds[1].finish()
})

test('慢请求超过刷新周期时不积压、不并发，完成后才立即开始下一轮', async () => {
  const state = setup('from-start')
  state.poller.start()
  state.time(900)
  assert.equal(state.rounds.length, 1)
  state.rounds[0].finish()
  await settle()
  assert.equal(state.next().delay, 0)
  assert.equal(state.rounds[1].startedAt, 900)
  assert.equal(state.maxActive(), 1)
  state.poller.stop()
  state.rounds[1].finish()
})

test('隐藏期间停止调度，恢复后请求仍串行，退出会取消当前请求', async () => {
  const state = setup('from-start')
  state.poller.start()
  state.poller.setPaused(true)
  state.time(220)
  state.rounds[0].finish()
  await settle()
  assert.equal(state.timers.size, 0)
  state.time(4000)
  state.poller.setPaused(false)
  assert.equal(state.rounds[1].startedAt, 4000)
  assert.equal(state.maxActive(), 1)
  state.poller.stop()
  assert.equal(state.rounds[1].signal.aborted, true)
  state.rounds[1].finish()
  await settle()
  assert.equal(state.timers.size, 0)
})

test('调整周期或调度模式时，按最近一轮开始时间重新计算等待', async () => {
  const state = setup()
  state.poller.start()
  state.time(220)
  state.rounds[0].finish()
  await settle()
  state.poller.configure(500, 8000, 'from-start')
  assert.equal(state.next().delay, 280)
  state.poller.stop()
  state.rounds[1].finish()
})
