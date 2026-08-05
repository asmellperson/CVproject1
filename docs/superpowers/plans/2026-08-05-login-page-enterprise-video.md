# Enterprise Video Login Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current centered login card with the approved left-dark-video/right-light-form enterprise login page while preserving the existing login request, validation, error, authentication, and post-login behavior.

**Architecture:** Keep all login business state and submission code inside the existing `LoginPage` component, adding only presentation state for password visibility, video failure, and reduced-motion handling. Put page-specific visual rules in a namespaced `LoginPage.css`; serve the converted H.264 video and extracted cover from Vite's existing `public/assets/login/` directory.

**Tech Stack:** React 19, TypeScript 5.9, Vite 7, existing shadcn-style UI components, CSS media queries/masks, Node's built-in test runner, ffmpeg/ffprobe, headless Chromium.

---

## File map

- Create `unified_frontend/tests/login-page-contract.test.mjs`: dependency-free source/resource contract checks for visual media, password visibility, and preserved login submission behavior.
- Modify `unified_frontend/src/pages/LoginPage.tsx`: approved layout and presentation-only interactions; retain the existing login business flow verbatim.
- Create `unified_frontend/src/pages/LoginPage.css`: all login-only layout, video blending, form styling, responsiveness, and reduced-motion styling.
- Create `unified_frontend/public/assets/login/login-mascot.mp4`: H.264, silent browser-compatible video.
- Create `unified_frontend/public/assets/login/login-video-cover.png`: first-frame poster and fallback.
- Do not modify `unified_frontend/src/auth/AuthContext.tsx`, `unified_frontend/src/components/ProtectedRoute.tsx`, `unified_frontend/src/main.tsx`, or backend files.

### Task 1: Add a failing login-page contract test

**Files:**
- Create: `unified_frontend/tests/login-page-contract.test.mjs`
- Test: `unified_frontend/tests/login-page-contract.test.mjs`

- [ ] **Step 1: Write the source and resource contract test**

```javascript
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
  assert.match(css, /-webkit-mask-image:\s*radial-gradient/)
  assert.match(css, /mask-image:\s*radial-gradient/)
  assert.match(css, /\.login-video-crop\s*{[\s\S]*?overflow:\s*hidden/)
  assert.match(css, /@media \(max-width: 1200px\)/)
  assert.match(css, /@media \(max-width: 767px\)/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/)
})

test('ships the converted video and local fallback cover', () => {
  assert.equal(existsSync(videoUrl), true, 'expected converted H.264 login video')
  assert.equal(existsSync(coverUrl), true, 'expected extracted login video cover')
})
```

- [ ] **Step 2: Run the test and verify the expected red state**

Run from `unified_frontend`:

```bash
node --test tests/login-page-contract.test.mjs
```

Expected: FAIL because the current page has no video contract, no password visibility state, no `LoginPage.css`, and no converted assets. The existing-login-lifecycle assertion should already pass, proving the failure is caused by the missing presentation work.

- [ ] **Step 3: Commit the red test only**

```bash
git add -- unified_frontend/tests/login-page-contract.test.mjs
git commit -m "test: define login page visual contract"
```

### Task 2: Convert and verify the login media

**Files:**
- Source: `unified_frontend/public/0671754d-914a-4c23-8bf3-0a4ad883edff.mp4`
- Create: `unified_frontend/public/assets/login/login-mascot.mp4`
- Create: `unified_frontend/public/assets/login/login-video-cover.png`

- [ ] **Step 1: Create the scoped static-resource directory**

```bash
mkdir -p unified_frontend/public/assets/login
```

- [ ] **Step 2: Convert HEVC + AAC to silent H.264 MP4**

Run from the repository root:

```bash
ffmpeg -y \
  -i unified_frontend/public/0671754d-914a-4c23-8bf3-0a4ad883edff.mp4 \
  -an \
  -c:v libx264 \
  -preset medium \
  -crf 23 \
  -pix_fmt yuv420p \
  -movflags +faststart \
  unified_frontend/public/assets/login/login-mascot.mp4
```

Expected: one `720x720` H.264 video stream and no copied audio stream.

- [ ] **Step 3: Extract the first-frame poster from the converted file**

```bash
ffmpeg -y \
  -i unified_frontend/public/assets/login/login-mascot.mp4 \
  -frames:v 1 \
  -update 1 \
  unified_frontend/public/assets/login/login-video-cover.png
```

Expected: a readable `720x720` PNG matching the first animation frame.

- [ ] **Step 4: Verify codec, pixel format, stream count, and cover dimensions**

```bash
ffprobe -v error \
  -show_entries stream=index,codec_name,codec_type,width,height,pix_fmt \
  -of json \
  unified_frontend/public/assets/login/login-mascot.mp4

ffprobe -v error \
  -show_entries stream=codec_name,codec_type,width,height,pix_fmt \
  -of json \
  unified_frontend/public/assets/login/login-video-cover.png
```

Expected video result: exactly one stream with `codec_name: h264`, `codec_type: video`, `width: 720`, `height: 720`, and `pix_fmt: yuv420p`; no audio stream. Expected cover result: one `png` video/image stream at `720x720`.

- [ ] **Step 5: Re-run the contract test to confirm media is green while UI assertions remain red**

```bash
cd unified_frontend
node --test tests/login-page-contract.test.mjs
```

Expected: the resource test passes; video markup, password visibility, and CSS tests still fail.

- [ ] **Step 6: Commit only the converted media**

```bash
git add -f -- \
  unified_frontend/public/assets/login/login-mascot.mp4 \
  unified_frontend/public/assets/login/login-video-cover.png
git commit -m "feat: add browser-compatible login mascot media"
```

### Task 3: Implement the approved login presentation

**Files:**
- Modify: `unified_frontend/src/pages/LoginPage.tsx`
- Create: `unified_frontend/src/pages/LoginPage.css`
- Test: `unified_frontend/tests/login-page-contract.test.mjs`

- [ ] **Step 1: Replace `LoginPage.tsx` with the approved presentation while preserving `onSubmit`**

```tsx
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Eye, EyeOff, LoaderCircle, LockKeyhole, LogIn, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/auth/useAuth'
import './LoginPage.css'

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

export function LoginPage() {
  const { login } = useAuth()
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [videoFailed, setVideoFailed] = useState(false)
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(
    () => window.matchMedia(REDUCED_MOTION_QUERY).matches,
  )

  useEffect(() => {
    const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY)
    const updatePreference = () => setPrefersReducedMotion(mediaQuery.matches)

    updatePreference()
    mediaQuery.addEventListener('change', updatePreference)
    return () => mediaQuery.removeEventListener('change', updatePreference)
  }, [])

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(account.trim(), password)
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  const showVideoPoster = prefersReducedMotion || videoFailed

  return (
    <main className="login-page">
      <div className="login-layout">
        <section className="login-brand-panel" aria-label="福达视觉平台品牌展示">
          <div className="login-brand-lockup">
            <img className="login-brand-logo" src="/mascot.png" alt="福达视觉平台" />
            <div>
              <strong>福达视觉平台</strong>
              <span>FUDA VISION PLATFORM</span>
            </div>
          </div>

          <div className="login-video-stage" aria-hidden="true">
            <div className="login-video-glow" />
            <div className="login-video-crop">
              {showVideoPoster ? (
                <img
                  className="login-video-media"
                  src="/assets/login/login-video-cover.png"
                  alt=""
                />
              ) : (
                <video
                  className="login-video-media"
                  autoPlay
                  muted
                  loop
                  playsInline
                  preload="auto"
                  poster="/assets/login/login-video-cover.png"
                  onError={() => setVideoFailed(true)}
                >
                  <source src="/assets/login/login-mascot.mp4" type="video/mp4" />
                </video>
              )}
            </div>
            <div className="login-tech-ring" />
          </div>
        </section>

        <section className="login-auth-panel">
          <div className="login-card">
            <div className="login-card-heading">
              <div className="login-card-kicker">
                <LockKeyhole aria-hidden="true" />
                <span>SECURE ACCESS</span>
              </div>
              <h1>福达视觉平台</h1>
              <p>统一登录鉴权</p>
            </div>

            <form className="login-form" onSubmit={onSubmit}>
              <div className="login-field">
                <Label htmlFor="account">工号或姓名</Label>
                <Input
                  id="account"
                  value={account}
                  onChange={(event) => setAccount(event.target.value)}
                  autoComplete="username"
                  placeholder="请输入工号或姓名"
                  required
                />
              </div>

              <div className="login-field">
                <Label htmlFor="password">密码</Label>
                <div className="login-password-field">
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="current-password"
                    placeholder="请输入密码"
                    required
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="login-password-toggle"
                    aria-label={showPassword ? '隐藏密码' : '显示密码'}
                    aria-pressed={showPassword}
                    onClick={() => setShowPassword((visible) => !visible)}
                  >
                    {showPassword ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
                  </Button>
                </div>
              </div>

              {error && (
                <div className="login-error" role="alert">
                  {error}
                </div>
              )}

              <Button
                type="submit"
                className={`login-submit${submitting ? ' is-loading' : ''}`}
                disabled={submitting}
              >
                {submitting ? (
                  <LoaderCircle className="login-spinner" aria-hidden="true" />
                ) : (
                  <LogIn aria-hidden="true" />
                )}
                {submitting ? '登录中' : '登录'}
              </Button>
            </form>

            <div className="login-security-note">
              <ShieldCheck aria-hidden="true" />
              <span>企业级统一身份认证</span>
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}
```

- [ ] **Step 2: Add the page-scoped visual and responsive CSS**

```css
.login-page {
  --login-video-bg: #0b1b39;
  --login-video-bg-soft: #1a2c50;
  --login-page-bg: #eef4fb;
  --login-ink: #10213f;
  position: relative;
  width: 100%;
  height: 100vh;
  min-height: 100svh;
  overflow: hidden;
  color: var(--login-ink);
  background: linear-gradient(
    90deg,
    var(--login-video-bg) 0%,
    var(--login-video-bg) 55%,
    var(--login-page-bg) 55%,
    var(--login-page-bg) 100%
  );
}

.login-page::after {
  content: '';
  position: fixed;
  z-index: 0;
  inset: 0 0 0 55%;
  pointer-events: none;
  background:
    radial-gradient(circle at 24% 20%, rgb(174 213 249 / 32%), transparent 31%),
    radial-gradient(circle at 84% 78%, rgb(190 218 246 / 26%), transparent 35%),
    linear-gradient(135deg, rgb(255 255 255 / 62%), transparent 54%);
}

.login-layout {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 55fr 45fr;
  width: min(1500px, 100%);
  height: 100%;
  min-height: 100svh;
  margin: 0 auto;
  overflow: hidden;
}

.login-brand-panel {
  position: relative;
  min-width: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at 50% 56%, rgb(50 84 128 / 28%), transparent 45%),
    radial-gradient(circle at 12% 8%, rgb(56 116 180 / 12%), transparent 24%),
    var(--login-video-bg);
}

.login-brand-lockup {
  position: absolute;
  z-index: 4;
  top: clamp(24px, 3.5vh, 46px);
  left: clamp(28px, 4vw, 66px);
  display: flex;
  align-items: center;
  gap: 13px;
  color: #fff;
}

.login-brand-logo {
  width: 48px;
  height: 48px;
  border-radius: 15px;
  object-fit: cover;
  box-shadow: 0 9px 28px rgb(0 0 0 / 20%), inset 0 0 0 1px rgb(255 255 255 / 22%);
}

.login-brand-lockup strong {
  display: block;
  font-size: 18px;
  line-height: 1.25;
  letter-spacing: 0.02em;
}

.login-brand-lockup span {
  display: block;
  margin-top: 4px;
  color: #a9c8e9;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.login-video-stage {
  position: absolute;
  z-index: 2;
  inset: 10% 0 0;
  display: grid;
  place-items: center;
  overflow: hidden;
}

.login-video-glow {
  position: absolute;
  width: 84%;
  max-width: 680px;
  aspect-ratio: 1;
  border-radius: 50%;
  background: rgb(50 84 128 / 24%);
  filter: blur(72px);
}

.login-video-crop {
  position: relative;
  width: min(620px, 80%);
  aspect-ratio: 1 / 0.88;
  overflow: hidden;
  background: transparent;
}

.login-video-media {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 26%;
  -webkit-mask-image: radial-gradient(
    ellipse at 50% 43%,
    #000 55%,
    rgb(0 0 0 / 94%) 67%,
    rgb(0 0 0 / 58%) 82%,
    transparent 100%
  );
  mask-image: radial-gradient(
    ellipse at 50% 43%,
    #000 55%,
    rgb(0 0 0 / 94%) 67%,
    rgb(0 0 0 / 58%) 82%,
    transparent 100%
  );
}

.login-video-crop::after {
  content: '';
  position: absolute;
  z-index: 3;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 24%;
  pointer-events: none;
  background: linear-gradient(
    to bottom,
    transparent 0%,
    rgb(11 27 57 / 68%) 43%,
    var(--login-video-bg) 84%
  );
}

.login-tech-ring {
  position: absolute;
  z-index: 3;
  left: 50%;
  bottom: 7%;
  width: min(520px, 64%);
  height: 42px;
  transform: translateX(-50%);
  border: 1px solid rgb(108 192 255 / 20%);
  border-radius: 50%;
  background: radial-gradient(ellipse, rgb(64 158 237 / 16%), transparent 68%);
  box-shadow: 0 0 40px rgb(52 145 224 / 10%);
}

.login-auth-panel {
  position: relative;
  z-index: 2;
  display: grid;
  min-width: 0;
  place-items: center;
  padding: 32px;
}

.login-card {
  width: min(448px, 100%);
  padding: 42px 42px 36px;
  border: 1px solid rgb(120 161 207 / 20%);
  border-radius: 22px;
  background: rgb(255 255 255 / 91%);
  box-shadow: 0 28px 72px rgb(37 72 113 / 14%), inset 0 1px 0 rgb(255 255 255 / 94%);
  backdrop-filter: blur(18px);
}

.login-card-heading {
  margin-bottom: 28px;
}

.login-card-kicker {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 10px;
  color: #2475c5;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.12em;
}

.login-card-kicker svg {
  width: 16px;
  height: 16px;
}

.login-card h1 {
  margin: 0;
  color: #0c2447;
  font-size: clamp(30px, 2.3vw, 34px);
  line-height: 1.18;
  letter-spacing: -0.035em;
}

.login-card-heading > p {
  margin: 10px 0 0;
  color: #667993;
  font-size: 16px;
}

.login-form {
  display: grid;
  gap: 19px;
}

.login-field {
  display: grid;
  gap: 9px;
}

.login-field label {
  color: #263b59;
  font-size: 15px;
  font-weight: 700;
}

.login-field input {
  height: 52px;
  border-color: #d5e1ed;
  border-radius: 12px;
  color: #142944;
  font-size: 15px;
  background: rgb(249 252 255 / 92%);
  box-shadow: none;
}

.login-field input::placeholder {
  color: #9aa9ba;
}

.login-field input:focus-visible {
  border-color: #4b9ce8;
  background: #fff;
  box-shadow: 0 0 0 4px rgb(42 132 219 / 11%);
}

.login-password-field {
  position: relative;
}

.login-password-field input {
  padding-right: 52px;
}

.login-password-toggle {
  position: absolute;
  top: 50%;
  right: 7px;
  width: 38px;
  height: 38px;
  transform: translateY(-50%);
  border-radius: 10px;
  color: #66809c;
}

.login-password-toggle:hover {
  color: #1d72be;
  background: #ebf5ff;
}

.login-password-toggle svg {
  width: 20px;
  height: 20px;
}

.login-error {
  border: 1px solid #fecaca;
  border-radius: 11px;
  padding: 10px 12px;
  color: #b42318;
  font-size: 14px;
  background: #fff1f2;
}

.login-submit {
  width: 100%;
  height: 52px;
  margin-top: 2px;
  gap: 9px;
  border: 0;
  border-radius: 12px;
  color: #fff;
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0.04em;
  background: linear-gradient(100deg, #092a59 0%, #0d5ea9 52%, #1d91ed 100%);
  box-shadow: 0 13px 26px rgb(18 100 178 / 23%);
  transition: transform 150ms ease, filter 150ms ease, box-shadow 150ms ease;
}

.login-submit:hover:not(:disabled) {
  filter: brightness(1.06);
  box-shadow: 0 16px 32px rgb(18 100 178 / 29%);
}

.login-submit:active:not(:disabled) {
  transform: translateY(1px) scale(0.995);
}

.login-submit:disabled,
.login-submit.is-loading {
  cursor: wait;
  opacity: 0.76;
}

.login-submit svg {
  width: 18px;
  height: 18px;
}

.login-spinner {
  animation: login-spin 800ms linear infinite;
}

.login-security-note {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin-top: 20px;
  color: #8290a3;
  font-size: 12px;
}

.login-security-note svg {
  width: 15px;
  height: 15px;
}

@keyframes login-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1200px) {
  .login-page {
    background: linear-gradient(
      90deg,
      var(--login-video-bg) 0%,
      var(--login-video-bg) 45%,
      var(--login-page-bg) 45%,
      var(--login-page-bg) 100%
    );
  }

  .login-page::after {
    inset: 0 0 0 45%;
  }

  .login-layout {
    grid-template-columns: 45fr 55fr;
  }

  .login-brand-lockup {
    left: 28px;
  }

  .login-video-crop {
    width: min(500px, 94%);
  }

  .login-auth-panel {
    padding: 28px;
  }
}

@media (max-width: 767px) {
  .login-page {
    height: 100svh;
    background: linear-gradient(150deg, #f8fbff, var(--login-page-bg));
  }

  .login-page::after {
    inset: 74px 0 0;
  }

  .login-layout {
    display: block;
    min-height: 100svh;
    padding: 74px 0 0;
  }

  .login-brand-panel {
    position: absolute;
    inset: 0 0 auto;
    display: flex;
    align-items: center;
    height: 74px;
    overflow: hidden;
    background: var(--login-video-bg);
  }

  .login-brand-lockup {
    position: static;
    margin-left: 20px;
  }

  .login-brand-logo {
    width: 42px;
    height: 42px;
    border-radius: 13px;
  }

  .login-brand-lockup strong {
    font-size: 16px;
  }

  .login-video-stage {
    display: none;
  }

  .login-auth-panel {
    display: flex;
    min-height: calc(100svh - 74px);
    align-items: center;
    justify-content: center;
    padding: 16px 0;
  }

  .login-card {
    width: calc(100% - 32px);
    padding: 30px 24px 28px;
    border-radius: 20px;
  }

  .login-card-heading {
    margin-bottom: 24px;
  }

  .login-card h1 {
    font-size: 30px;
  }

  .login-form {
    gap: 16px;
  }
}

@media (max-height: 700px) and (min-width: 768px) {
  .login-card {
    padding-top: 30px;
    padding-bottom: 28px;
  }

  .login-card-heading {
    margin-bottom: 20px;
  }

  .login-form {
    gap: 14px;
  }

  .login-video-crop {
    width: min(520px, 76%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-submit,
  .login-spinner,
  .login-field input,
  .login-password-toggle {
    animation: none;
    transition: none;
  }
}
```

- [ ] **Step 3: Run the focused contract test and verify green**

```bash
cd unified_frontend
node --test tests/login-page-contract.test.mjs
```

Expected: 5 tests pass, 0 fail.

- [ ] **Step 4: Run TypeScript compilation and the production build**

```bash
cd unified_frontend
npm run build
```

Expected: `tsc -b && vite build` exits 0 and writes the production bundle to `unified_frontend/dist`.

- [ ] **Step 5: Run lint and address only findings caused by this task**

```bash
cd unified_frontend
npm run lint
```

Expected: exits 0. If unrelated pre-existing lint errors occur, record them without modifying unrelated files.

- [ ] **Step 6: Commit the page implementation**

```bash
git add -- \
  unified_frontend/src/pages/LoginPage.tsx \
  unified_frontend/src/pages/LoginPage.css
git commit -m "feat: redesign enterprise login page"
```

### Task 4: Capture and inspect playback and responsive screenshots

**Files:**
- Verify: `unified_frontend/src/pages/LoginPage.tsx`
- Verify: `unified_frontend/src/pages/LoginPage.css`
- Output: temporary PNG screenshots under `/tmp/fuda-login-page-screenshots-20260805`

- [ ] **Step 1: Start the frontend development server**

Run from `unified_frontend` and keep the process active:

```bash
VITE_DEV_PORT=4173 npm run dev
```

Expected: Vite reports `http://localhost:4173/`. A missing backend is acceptable for this visual check because `AuthProvider` catches the failed `/api/auth/me` request and renders the login page.

- [ ] **Step 2: Create a unique screenshot directory**

```bash
mkdir -p /tmp/fuda-login-page-screenshots-20260805
```

Use `/tmp/fuda-login-page-screenshots-20260805` for every screenshot command below.

- [ ] **Step 3: Capture poster, mid-playback, and loop-seam desktop states**

```bash
chromium-browser \
  --headless --no-sandbox --disable-gpu --disable-dev-shm-usage \
  --hide-scrollbars --run-all-compositor-stages-before-draw \
  --force-prefers-reduced-motion \
  --window-size=1440,900 --virtual-time-budget=1500 \
  --screenshot=/tmp/fuda-login-page-screenshots-20260805/login-poster.png \
  http://127.0.0.1:4173/

chromium-browser \
  --headless --no-sandbox --disable-gpu --disable-dev-shm-usage \
  --hide-scrollbars --run-all-compositor-stages-before-draw \
  --window-size=1440,900 --virtual-time-budget=3500 \
  --screenshot=/tmp/fuda-login-page-screenshots-20260805/login-playing.png \
  http://127.0.0.1:4173/

chromium-browser \
  --headless --no-sandbox --disable-gpu --disable-dev-shm-usage \
  --hide-scrollbars --run-all-compositor-stages-before-draw \
  --window-size=1440,900 --virtual-time-budget=7200 \
  --screenshot=/tmp/fuda-login-page-screenshots-20260805/login-loop-seam.png \
  http://127.0.0.1:4173/
```

Expected: all three files are non-empty PNGs showing the unauthenticated login page.

- [ ] **Step 4: Capture tablet and mobile layouts**

```bash
chromium-browser \
  --headless --no-sandbox --disable-gpu --disable-dev-shm-usage \
  --hide-scrollbars --run-all-compositor-stages-before-draw \
  --window-size=1024,768 --virtual-time-budget=3000 \
  --screenshot=/tmp/fuda-login-page-screenshots-20260805/login-tablet.png \
  http://127.0.0.1:4173/

chromium-browser \
  --headless --no-sandbox --disable-gpu --disable-dev-shm-usage \
  --hide-scrollbars --run-all-compositor-stages-before-draw \
  --window-size=390,844 --virtual-time-budget=1800 \
  --screenshot=/tmp/fuda-login-page-screenshots-20260805/login-mobile.png \
  http://127.0.0.1:4173/
```

Expected: tablet uses the `45% / 55%` split; mobile hides the video, shows the compact brand strip, and renders a card exactly `calc(100% - 32px)` wide.

- [ ] **Step 5: Inspect all five screenshots**

Check each image at full resolution for these exact acceptance conditions:

- No visible square edge at the video's top, left, right, or bottom.
- No visible “LOGION” text in poster, playing, or loop-seam frames.
- The mascot remains recognizable and is not overlapped by the login card.
- The right panel stays light and the left panel stays matched to `#0B1B39`.
- No horizontal or vertical page scrollbar is visible.
- The mobile card is fully usable and the video is absent.

If a media-boundary defect is visible, change only the measured-color compensation, `radial-gradient` mask stops, bottom overlay height, or `object-position` in `LoginPage.css`, then repeat Tasks 3 Step 3 through Task 4 Step 5. Do not change `onSubmit`, auth files, routing, or backend code.

### Task 5: Final regression and scope verification

**Files:**
- Verify: all task files
- Confirm unchanged: auth, route guard, entry point, backend

- [ ] **Step 1: Run the complete focused verification set one final time**

```bash
cd unified_frontend
node --test tests/login-page-contract.test.mjs
npm run build
```

Expected: contract tests and build both exit 0.

- [ ] **Step 2: Confirm protected business and backend files have no task diff**

Run from the repository root:

```bash
git diff --exit-code HEAD -- \
  unified_frontend/src/auth/AuthContext.tsx \
  unified_frontend/src/components/ProtectedRoute.tsx \
  unified_frontend/src/main.tsx \
  unified_backend guard_room security_vlm
```

Expected for this task's work: no new diff in the protected paths. Existing unrelated user changes visible before this task must remain untouched and should be reported separately rather than reverted.

- [ ] **Step 3: Review the final scoped diff and whitespace**

```bash
git diff --check -- \
  unified_frontend/src/pages/LoginPage.tsx \
  unified_frontend/src/pages/LoginPage.css \
  unified_frontend/tests/login-page-contract.test.mjs
git status --short -- \
  unified_frontend/src/pages/LoginPage.tsx \
  unified_frontend/src/pages/LoginPage.css \
  unified_frontend/tests/login-page-contract.test.mjs \
  unified_frontend/public/assets/login/login-mascot.mp4 \
  unified_frontend/public/assets/login/login-video-cover.png
```

Expected: no whitespace errors; only the five intended implementation/test/media files appear in the scoped status output.

- [ ] **Step 4: Record the final handoff**

Report the modified files, final video path, unchanged login/auth behavior, exact test/build commands and results, screenshot paths, visual inspection result, and any unresolved environment or rendering risk.
