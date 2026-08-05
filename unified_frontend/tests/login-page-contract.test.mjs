import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)
const pageUrl = new URL('src/pages/LoginPage.tsx', frontendRoot)
const cssUrl = new URL('src/pages/LoginPage.css', frontendRoot)
const videoUrl = new URL('public/assets/login/login-mascot.mp4', frontendRoot)
const coverUrl = new URL('public/assets/login/login-video-cover.png', frontendRoot)

async function readIfPresent(url) {
  try {
    return await readFile(url, 'utf8')
  } catch (error) {
    if (error && typeof error === 'object' && error.code === 'ENOENT') return ''
    throw error
  }
}

const page = await readIfPresent(pageUrl)
const css = await readIfPresent(cssUrl)

test('keeps the existing login request and error lifecycle', () => {
  assert.match(page, /await login\(account\.trim\(\), password\)/)
  assert.match(page, /setError\(err instanceof Error \? err\.message : '登录失败'\)/)
  assert.match(page, /finally\s*{\s*setSubmitting\(false\)/)
  assert.match(page, /disabled={submitting}/)
})

test('declares the browser-compatible mascot video contract', () => {
  assert.match(page, /<video[\s\S]*?autoPlay[\s\S]*?muted[\s\S]*?loop[\s\S]*?playsInline[\s\S]*?preload="auto"/)
  assert.match(page, /<source src="\/assets\/login\/login-mascot\.mp4" type="video\/mp4"/)
  assert.doesNotMatch(page, /\scontrols(?:=|\s|>)/)
  assert.match(page, /login-video-cover\.png/)
})

test('keeps passwords hidden until the user presses the visibility button', () => {
  assert.match(page, /const \[showPassword, setShowPassword\] = useState\(false\)/)
  assert.match(page, /type={showPassword \? 'text' : 'password'}/)
  assert.match(page, /aria-label={showPassword \? '隐藏密码' : '显示密码'}/)
  assert.match(page, /aria-pressed={showPassword}/)
})

test('uses measured video colors and edge fading in page-scoped CSS', () => {
  assert.match(css, /--login-video-bg:\s*#0b1b39/)
  assert.match(css, /--login-video-bg-soft:\s*#1a2c50/)
  assert.match(css, /^\s*-webkit-mask-image:\s*radial-gradient/m)
  assert.match(css, /^\s*mask-image:\s*radial-gradient/m)
  assert.match(css, /\.login-video-crop\s*{[\s\S]*?overflow:\s*hidden/)
  assert.match(css, /@media \(max-width: 1200px\)/)
  assert.match(css, /@media \(max-width: 767px\)/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/)
})

test('ships the converted video and local fallback cover', () => {
  assert.equal(existsSync(videoUrl), true, 'expected converted H.264 login video')
  assert.equal(existsSync(coverUrl), true, 'expected extracted login video cover')
})
