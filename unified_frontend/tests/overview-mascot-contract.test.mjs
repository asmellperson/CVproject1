import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)
const sectionUrl = new URL('src/sections/HomeSection.tsx', frontendRoot)
const webmUrl = new URL('public/assets/overview/overview-mascot.webm', frontendRoot)
const posterUrl = new URL('public/assets/overview/overview-mascot-poster.png', frontendRoot)

const section = await readFile(sectionUrl, 'utf8')

test('places the overview mascot inside the platform hero banner', () => {
  assert.match(section, /福达 AI 视觉安全监管平台/)
  assert.match(section, /overview-mascot-trigger/)
  assert.match(section, /overview-mascot-media/)
  assert.match(section, /src="\/assets\/overview\/overview-mascot\.webm"/)
  assert.match(section, /poster="\/assets\/overview\/overview-mascot-poster\.png"/)
})

test('plays once on entry and replays only when the mascot is clicked', () => {
  const videoElement = section.match(/<video\b[\s\S]*?<\/video>/)?.[0] ?? ''
  const triggerElement = section.match(/<button\b[\s\S]*?overview-mascot-trigger[\s\S]*?<\/button>/)?.[0] ?? ''

  assert.match(videoElement, /\bautoPlay\b/)
  assert.match(videoElement, /\bmuted\b/)
  assert.match(videoElement, /\bplaysInline\b/)
  assert.match(videoElement, /\bpreload="auto"/)
  assert.doesNotMatch(videoElement, /\bloop\b/)
  assert.doesNotMatch(videoElement, /\scontrols(?:=|\s|>)/)
  assert.match(videoElement, /onEnded=/)
  assert.match(triggerElement, /onClick=/)
  assert.match(section, /currentTime = 0/)
  assert.match(section, /\.play\(\)/)
})

test('keeps the mascot non-blocking and responsive', () => {
  assert.match(section, /absolute left-4/)
  assert.match(section, /w-\[140px\]/)
  assert.match(section, /md:w-\[300px\]/)
  assert.match(section, /pointer-events-none/)
  assert.match(section, /pointer-events-auto/)
  assert.match(section, /z-\[2\]/)
})

test('ships transparent overview mascot media and fallback poster', () => {
  assert.equal(existsSync(webmUrl), true, 'expected transparent WebM mascot')
  assert.equal(existsSync(posterUrl), true, 'expected final-pose poster')
})
