import type { ComponentProps } from 'react'
import { SelectContent } from '@/components/ui/select'
import { cn } from '@/lib/utils'

type Props = Omit<ComponentProps<typeof SelectContent>, 'position' | 'align' | 'showScrollButtons'>

export function CameraSelectContent({ className, ...props }: Props) {
  // 固定锚点并让长列表在内部滚动，避免按选中项重新定位或随滚动扩展弹层。
  return <SelectContent {...props} position="popper" align="start" showScrollButtons={false}
    className={cn(
      'w-[var(--radix-select-trigger-width)] max-w-[calc(100vw-1.5rem)]',
      'max-h-[min(20rem,var(--radix-select-content-available-height))] overflow-hidden',
      '[&_[data-radix-select-viewport]]:h-auto [&_[data-radix-select-viewport]]:overscroll-contain',
      '[&_[data-radix-select-viewport]]:[scrollbar-width:thin] [&_[data-radix-select-viewport]::-webkit-scrollbar]:block',
      className,
    )} />
}
