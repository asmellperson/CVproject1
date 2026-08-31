// 文件说明：包含`overview-mascot-contract.test` 模块的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)
const sectionUrl = new URL('src/sections/HomeSection.tsx', frontendRoot)
const componentUrl = new URL('src/components/OverviewMascot.tsx', frontendRoot)
const webmUrl = new URL('public/assets/overview/overview-mascot-alpha.webm', frontendRoot)
const finalPoseUrl = new URL('public/assets/overview/overview-mascot-final.png', frontendRoot)

const section = await readFile(sectionUrl, 'utf8')
const component = existsSync(componentUrl) ? await readFile(componentUrl, 'utf8') : ''

test('renders a focused mascot overlay instead of a rectangular banner video', () => {
  assert.equal(existsSync(componentUrl), true, 'expected the OverviewMascot component')
  assert.match(section, /import \{ OverviewMascot \}/)
  assert.match(section, /<OverviewMascot\s*\/>/)
  assert.doesNotMatch(section, /平台总览动画-蓝白版\.mp4/)
  assert.match(component, /src="\/assets\/overview\/overview-mascot-alpha\.webm"/)
  assert.match(component, /type="video\/webm"/)
  assert.match(component, /src="\/assets\/overview\/overview-mascot-final\.png"/)
})

test('plays once on entry, holds the final pose, and replays only on click', () => {
  const videoElement = component.match(/<video\b[\s\S]*?<\/video>/)?.[0] ?? ''
  const triggerElement = component.match(/<button\b[\s\S]*?<\/button>/)?.[0] ?? ''

  assert.match(component, /useRef<HTMLVideoElement/)
  assert.match(component, /useState\(true\)/)
  assert.match(videoElement, /\bautoPlay\b/)
  assert.match(videoElement, /\bmuted\b/)
  assert.match(videoElement, /\bplaysInline\b/)
  assert.match(videoElement, /\bpreload="auto"/)
  assert.doesNotMatch(videoElement, /\bloop\b/)
  assert.doesNotMatch(videoElement, /\scontrols(?:=|\s|>)/)
  assert.match(videoElement, /onEnded=/)
  assert.match(triggerElement, /onClick=/)
  assert.match(component, /currentTime = 0/)
  assert.match(component, /\.play\(\)/)
  assert.match(component, /setIsPlaying\(false\)/)
})

test('matches the banner height and derives width from the media aspect ratio', () => {
  assert.match(component, /absolute left-0 top-0/)
  assert.match(component, /h-full/)
  assert.match(component, /aspect-\[600\/544\]/)
  assert.doesNotMatch(component, /w-\[140px\]/)
  assert.doesNotMatch(component, /md:w-\[300px\]/)
  assert.match(component, /pointer-events-none/)
  assert.match(component, /pointer-events-auto/)
  assert.match(component, /opacity-50/)
  assert.match(component, /md:hidden/)
  assert.match(component, /hidden md:block/)
  assert.doesNotMatch(component, /\bfixed\b/)
})

test('keeps the banner title centered on one line without mascot spacing', () => {
  assert.match(section, /福达 AI 视觉安全监管平台/)
  assert.match(section, /justify-center/)
  assert.match(section, /text-center/)
  assert.match(section, /whitespace-nowrap/)
  assert.doesNotMatch(section, /md:pl-\[340px\]/)
  assert.doesNotMatch(section, /lg:pl-\[390px\]/)
  assert.doesNotMatch(section, /2xl:pl-\[620px\]/)
})

test('ships transparent WebM media and a transparent final-pose fallback', () => {
  assert.equal(existsSync(webmUrl), true, 'expected transparent VP9 WebM mascot media')
  assert.equal(existsSync(finalPoseUrl), true, 'expected transparent final-pose PNG')
})
