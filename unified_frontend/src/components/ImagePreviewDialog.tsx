import { useState } from 'react'
import { Download, ZoomIn, ZoomOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'

export function ImagePreviewDialog({ src, title, filename, onClose }: {
  src: string
  title: string
  filename: string
  onClose: () => void
}) {
  const [imageZoom, setImageZoom] = useState(1)
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="flex h-[94dvh] max-h-none w-[calc(100vw-1rem)] max-w-none flex-col gap-0 overflow-hidden border-slate-700 bg-slate-950/95 p-0 text-white sm:max-w-[96vw]">
        <DialogHeader className="flex-col gap-3 border-b border-white/10 px-4 py-3 pr-12 sm:flex-row sm:items-center sm:justify-between">
          <DialogTitle className="text-base text-white">{title}</DialogTitle>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
              onClick={() => setImageZoom((value) => Math.max(0.5, value - 0.25))}
              aria-label="缩小图片"
            >
              <ZoomOut className="h-4 w-4" />
            </Button>
            <span className="w-14 text-center text-xs text-slate-300">{Math.round(imageZoom * 100)}%</span>
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
              onClick={() => setImageZoom((value) => Math.min(3, value + 0.25))}
              aria-label="放大图片"
            >
              <ZoomIn className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="outline"
              className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
              onClick={() => setImageZoom(1)}
            >
              适应窗口
            </Button>
            {src && (
              <Button asChild variant="outline" className="border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white">
                <a
                  href={src}
                  download={filename}
                >
                  <Download className="mr-2 h-4 w-4" />
                  下载
                </a>
              </Button>
            )}
          </div>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-4">
          {src && (
            <img
              src={src}
              alt={`${title}大图`}
              className="select-none object-contain transition-[width] duration-150"
              style={{
                width: `${imageZoom * 100}%`,
                maxWidth: imageZoom <= 1 ? '100%' : 'none',
                maxHeight: imageZoom <= 1 ? '100%' : 'none',
              }}
              draggable={false}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
