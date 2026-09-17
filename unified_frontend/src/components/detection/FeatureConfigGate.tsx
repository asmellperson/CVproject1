import type { ReactNode } from 'react'
import { EMPTY_FEATURE_CAMERA_MESSAGE } from '@/lib/feature-cameras'

export function FeatureConfigGate({ cameraKey, disabled, children }: {
  cameraKey: string
  disabled: boolean
  children: ReactNode
}) {
  if (!cameraKey) return <p role="status" className="rounded-xl border p-5 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">{EMPTY_FEATURE_CAMERA_MESSAGE}</p>
  return <fieldset disabled={disabled} className="contents">{children}</fieldset>
}
