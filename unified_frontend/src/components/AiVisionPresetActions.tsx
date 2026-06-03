import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'

type AiVisionPresetActionsProps = {
  disabled?: boolean
  onApplyDay: () => void
  onApplyNight: () => void
}

export function AiVisionPresetActions({ disabled, onApplyDay, onApplyNight }: AiVisionPresetActionsProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
      <div>
        <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">参数预设</div>
        <div className="mt-1 text-xs font-medium text-slate-500">应用后会先写入表单，确认无误后再保存。</div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" className="gap-2" onClick={onApplyDay} disabled={disabled}>
          <Sun className="h-4 w-4" />
          白天
        </Button>
        <Button variant="outline" className="gap-2" onClick={onApplyNight} disabled={disabled}>
          <Moon className="h-4 w-4" />
          夜间
        </Button>
      </div>
    </div>
  )
}
