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

function cssRuleBody(stylesheet, selector) {
  return stylesheet.match(new RegExp(`${selector}\\s*{([^}]*)}`))?.[1] ?? ''
}

test('keeps the existing login request and error lifecycle', () => {
  assert.match(page, /await login\(account\.trim\(\), password\)/)
  assert.match(page, /setError\(err instanceof Error \? err\.message : '登录失败'\)/)
  assert.match(page, /finally\s*{\s*setSubmitting\(false\)/)
  assert.match(page, /disabled={submitting}/)
})

test('declares the browser-compatible mascot video contract', () => {
  const videoElement = page.match(/<video\b[\s\S]*?<\/video>/)?.[0] ?? ''
  const source = videoElement.match(/<source\b[^>]*>/)?.[0] ?? ''
  const fallbackImage = [...page.matchAll(/<img\b[^>]*>/g)]
    .map(([image]) => image)
    .find((image) =>
      /className="login-video-media"/.test(image)
      && /src="\/assets\/login\/login-video-cover\.png"/.test(image),
    ) ?? ''

  assert.ok(videoElement, 'expected a mascot video element')
  assert.match(videoElement, /\bautoPlay\b/)
  assert.match(videoElement, /\bmuted\b/)
  assert.match(videoElement, /\bloop\b/)
  assert.match(videoElement, /\bplaysInline\b/)
  assert.match(videoElement, /\bpreload="auto"/)
  assert.doesNotMatch(videoElement, /\scontrols(?:=|\s|>)/)
  assert.match(videoElement, /\bposter="\/assets\/login\/login-video-cover\.png"/)
  assert.match(source, /\bsrc="\/assets\/login\/login-mascot\.mp4"/)
  assert.match(source, /\btype="video\/mp4"/)
  assert.match(fallbackImage, /\bclassName="login-video-media"/)
  assert.match(fallbackImage, /\bsrc="\/assets\/login\/login-video-cover\.png"/)
})

test('keeps passwords hidden until the user presses the visibility button', () => {
  const passwordToggle = [...page.matchAll(/<Button\b[\s\S]*?<\/Button>/g)]
    .map(([button]) => button)
    .find((button) =>
      /className="login-password-toggle"/.test(button)
      && /aria-label={showPassword \? '隐藏密码' : '显示密码'}/.test(button),
    ) ?? ''

  assert.match(page, /const \[showPassword, setShowPassword\] = useState\(false\)/)
  assert.match(page, /type={showPassword \? 'text' : 'password'}/)
  assert.match(passwordToggle, /\btype="button"/)
  assert.match(passwordToggle, /onClick={\(\) => setShowPassword\(\(visible\) => !visible\)}/)
  assert.match(passwordToggle, /aria-label={showPassword \? '隐藏密码' : '显示密码'}/)
  assert.match(passwordToggle, /aria-pressed={showPassword}/)
})

test('uses measured video colors and edge fading in page-scoped CSS', () => {
  const videoMedia = cssRuleBody(css, '\\.login-video-media')
  const videoCrop = cssRuleBody(css, '\\.login-video-crop')

  assert.match(page, /import '\.\/LoginPage\.css'/)
  assert.match(css, /--login-video-bg:\s*#0b1b39/)
  assert.match(css, /--login-video-bg-soft:\s*#1a2c50/)
  assert.match(videoMedia, /^\s*-webkit-mask-image:\s*radial-gradient/m)
  assert.match(videoMedia, /^\s*mask-image:\s*radial-gradient/m)
  assert.match(videoCrop, /^\s*overflow:\s*hidden/m)
  assert.match(css, /@media \(max-width: 1200px\)/)
  assert.match(css, /@media \(max-width: 767px\)/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/)
})

test('ships the converted video and local fallback cover', () => {
  assert.equal(existsSync(videoUrl), true, 'expected converted H.264 login video')
  assert.equal(existsSync(coverUrl), true, 'expected extracted login video cover')
})
