import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { cn } from '@/lib/utils'
import type { PolicyField, PolicyTone } from './policyFields'

const tones = {
  green: { panel: 'border-emerald-100 shadow-emerald-500/5 dark:border-emerald-900/60', icon: 'bg-emerald-500', title: 'text-emerald-700 dark:text-emerald-300', badge: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300', slider: '[&_[data-slot=slider-range]]:bg-emerald-500 [&_[data-slot=slider-thumb]]:border-emerald-500', advanced: 'border-emerald-300 bg-emerald-50/35 dark:border-emerald-900 dark:bg-emerald-950/20' },
  blue: { panel: 'border-blue-100 shadow-blue-500/5 dark:border-blue-900/60', icon: 'bg-blue-600', title: 'text-blue-700 dark:text-blue-300', badge: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-300', slider: '[&_[data-slot=slider-range]]:bg-blue-600 [&_[data-slot=slider-thumb]]:border-blue-600', advanced: 'border-blue-300 bg-blue-50/35 dark:border-blue-900 dark:bg-blue-950/20' },
  purple: { panel: 'border-violet-100 shadow-violet-500/5 dark:border-violet-900/60', icon: 'bg-violet-600', title: 'text-violet-700 dark:text-violet-300', badge: 'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-300', slider: '[&_[data-slot=slider-range]]:bg-violet-600 [&_[data-slot=slider-thumb]]:border-violet-600', advanced: 'border-violet-300 bg-violet-50/35 dark:border-violet-900 dark:bg-violet-950/20' },
  amber: { panel: 'border-amber-100 shadow-amber-500/5 dark:border-amber-900/60', icon: 'bg-amber-500', title: 'text-amber-700 dark:text-amber-300', badge: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300', slider: '[&_[data-slot=slider-range]]:bg-amber-500 [&_[data-slot=slider-thumb]]:border-amber-500', advanced: 'border-amber-300 bg-amber-50/35 dark:border-amber-900 dark:bg-amber-950/20' },
}

export function PolicyRuleGroup({ title, icon: Icon, tone, children }: { title: string; icon: LucideIcon; tone: PolicyTone; children: ReactNode }) {
  return <section className={cn('rounded-2xl border bg-white p-4 shadow-lg dark:bg-slate-900 sm:p-5', tones[tone].panel)}>
    <div className="mb-5 flex items-center gap-3"><span className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-white shadow-sm', tones[tone].icon)}><Icon className="h-4 w-4" /></span><h3 className={cn('text-base font-bold', tones[tone].title)}>{title}</h3></div>
    <div className="grid gap-x-8 gap-y-6 md:grid-cols-2">{children}</div>
  </section>
}

export function PolicyAdvancedFields({ tone, children }: { tone: PolicyTone; children: ReactNode }) {
  return <div className={cn('space-y-4 rounded-xl border border-dashed p-4 md:col-span-2', tones[tone].advanced)}>
    <h4 className={cn('text-sm font-semibold', tones[tone].title)}>高级参数</h4>
    <div className="grid gap-5 md:grid-cols-2">{children}</div>
  </div>
}

export function PolicySliderField({ field, value, tone, disabled, onChange }: { field: PolicyField; value: number; tone: PolicyTone; disabled: boolean; onChange: (value: number) => void }) {
  const safeValue = Number.isFinite(value) ? value : field.min
  const sliderMin = field.exclusiveMin ? field.step : field.min
  const sliderMax = Math.max(field.sliderMax, safeValue)
  return <div className="space-y-3">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0"><Label htmlFor={`guard-policy-${field.key}`} className="text-sm font-bold text-[#1a2e55] dark:text-slate-100">{field.label}</Label></div>
      <Input id={`guard-policy-${field.key}`} type="number" value={Number.isFinite(value) ? value : ''} min={field.min} max={field.max} step={field.integer ? 1 : 'any'} disabled={disabled}
        className={cn('!h-8 !w-24 shrink-0 !rounded-md !border !px-2 text-right text-xs font-bold shadow-sm', tones[tone].badge)}
        onChange={(event) => onChange(event.target.value === '' ? NaN : Number(event.target.value))} />
    </div>
    <Slider aria-label={field.label} min={Math.min(sliderMin, safeValue)} max={sliderMax} step={field.step} value={[safeValue]} disabled={disabled} className={tones[tone].slider} onValueChange={([number]) => onChange(number)} />
    <div className="flex justify-between text-[11px] font-medium text-slate-500 dark:text-slate-400"><span>{Math.min(sliderMin, safeValue)}</span><span>{sliderMax}</span></div>
  </div>
}
