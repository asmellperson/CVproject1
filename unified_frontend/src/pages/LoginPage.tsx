import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  Eye,
  EyeOff,
  LoaderCircle,
  LockKeyhole,
  LogIn,
  ShieldCheck,
} from 'lucide-react'
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
    const handleChange = (event: MediaQueryListEvent) => {
      setPrefersReducedMotion(event.matches)
    }

    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
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
        <section
          className="login-brand-panel"
          aria-label="福达视觉平台品牌展示"
        >
          <div className="login-brand-lockup">
            <div className="login-brand-copy">
              <p className="login-brand-name">福达视觉平台</p>
              <p className="login-brand-english">FUDA VISION PLATFORM</p>
            </div>
          </div>

          <div className="login-video-stage" aria-hidden="true">
            <div className="login-video-glow" />
            <div className="login-tech-ring" />
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
                  <source
                    src="/assets/login/login-mascot.mp4"
                    type="video/mp4"
                  />
                </video>
              )}
            </div>
          </div>
        </section>

        <section className="login-auth-panel">
          <div className="login-card">
            <header className="login-card-header">
              <div className="login-access-label">
                <span className="login-access-icon">
                  <LockKeyhole aria-hidden="true" />
                </span>
                <span>SECURE ACCESS</span>
              </div>
              <h1 className="login-title">福达视觉平台</h1>
              <p className="login-subtitle">统一登录鉴权</p>
            </header>

            <form className="login-form" onSubmit={onSubmit}>
              <div className="login-form-field">
                <Label className="login-label" htmlFor="account">
                  工号或姓名
                </Label>
                <Input
                  className="login-input"
                  id="account"
                  value={account}
                  onChange={(event) => setAccount(event.target.value)}
                  autoComplete="username"
                  placeholder="请输入工号或姓名"
                  required
                />
              </div>

              <div className="login-form-field">
                <Label className="login-label" htmlFor="password">
                  密码
                </Label>
                <div className="login-password-field">
                  <Input
                    className="login-input login-password-input"
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
                    {showPassword ? (
                      <EyeOff className="login-toggle-icon" aria-hidden="true" />
                    ) : (
                      <Eye className="login-toggle-icon" aria-hidden="true" />
                    )}
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
                aria-busy={submitting}
              >
                {submitting ? (
                  <LoaderCircle className="login-spinner" aria-hidden="true" />
                ) : (
                  <LogIn className="login-submit-icon" aria-hidden="true" />
                )}
                {submitting ? '登录中' : '登录'}
              </Button>
            </form>

            <div className="login-security-note">
              <ShieldCheck aria-hidden="true" />
              <span>企业级身份认证 · 安全访问受保护</span>
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}
