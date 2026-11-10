import { useState } from 'react'
import { RefreshCw, Square, ZoomIn, ZoomOut } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { CameraLivePreview } from '@/components/monitor/CameraLivePreview'
import { Slider } from '@/components/ui/slider'
import type { AiVisionCamera } from '@/lib/aivision'
import { useCameraZoom } from './useCameraZoom'
import { CameraLocalPreview } from './CameraLocalPreview'

type ZoomCamera = Pick<AiVisionCamera, 'shm_name' | 'name' | 'department' | 'enabled' | 'fps'>
type Props = { camera: ZoomCamera; feature: string; disabled?: boolean }

export function CameraZoomButton({ camera, feature, disabled }: Props) {
  const { isAdmin } = useAuth()
  const available = isAdmin && camera.enabled && !!camera.department && !disabled
  // 管理状态变化时销毁弹窗会话，恢复可用后不自动重开旧设备。
  return <CameraZoomLauncher key={`${camera.department}:${feature}:${camera.shm_name}:${available}`} camera={camera} feature={feature} disabled={!available} />
}

function CameraZoomLauncher({ camera, feature, disabled }: Props) {
  const [open, setOpen] = useState(false)
  const available = !disabled
  return <Dialog open={open && available} onOpenChange={setOpen}>
    <DialogTrigger asChild><Button type="button" size="sm" variant="outline" className="h-11 sm:h-8"
      aria-label={`${camera.name}：变焦`} disabled={!available}><ZoomIn className="h-4 w-4" />变焦</Button></DialogTrigger>
    <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-4xl">
      <DialogHeader>
        <DialogTitle>摄像头变焦 · {camera.name}</DialogTitle>
        <DialogDescription>点击画面局部放大查看，或使用镜头控制调整摄像头取景范围。</DialogDescription>
      </DialogHeader>
      {open && available && <CameraZoomSession key={`${camera.department}:${feature}:${camera.shm_name}`} camera={camera} feature={feature} />}
    </DialogContent>
  </Dialog>
}

function CameraZoomSession({ camera, feature }: Props) {
  const [connected, setConnected] = useState(false)
  const zoom = useCameraZoom(camera.shm_name, feature, connected)
  const supported = zoom.capabilities?.status === 'supported'
  const canMove = supported && connected && !zoom.loading && !zoom.pending && !zoom.rate && !zoom.denied
  return <div className="space-y-4">
    <CameraLocalPreview connected={connected && !zoom.denied}>
      <CameraLivePreview cameraKey={camera.shm_name} feature={feature} department={camera.department!}
        enabled={camera.enabled && !zoom.denied} fps={camera.fps} value={null} onConnectionChange={setConnected} />
    </CameraLocalPreview>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">摄像头镜头</span>
        <Badge variant={supported ? 'default' : 'secondary'}>{zoom.loading ? '正在检测能力' : supported ? '支持变焦' : zoom.capabilities?.status === 'unsupported' ? '不支持变焦' : '能力未确认'}</Badge>
        <span className="text-slate-500 dark:text-slate-400">{zoom.capabilities?.message}</span>
      </div>
      <Button type="button" size="sm" variant="outline" disabled={zoom.loading || !!zoom.pending || !!zoom.rate || zoom.denied} onClick={zoom.reload}><RefreshCw className={`h-4 w-4 ${zoom.loading ? 'animate-spin' : ''}`} />重新检测</Button>
    </div>
    <div className="space-y-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="font-medium">连续变焦</span>
        <output aria-live="polite" className="tabular-nums text-slate-500 dark:text-slate-400">{zoom.rate ? `${zoom.rate > 0 ? '放大' : '缩小'} · 速度 ${Math.abs(zoom.rate)}%` : '停止'}</output>
      </div>
      <div className="relative py-2">
        <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-1/2 w-px bg-slate-300 dark:bg-slate-600" />
        <Slider aria-label="摄像头连续变焦速度" aria-valuetext={zoom.rate ? `${zoom.rate > 0 ? '放大' : '缩小'}，速度 ${Math.abs(zoom.rate)}%` : '停止'}
          min={-100} max={100} step={5} value={[zoom.rate]}
          disabled={!supported || !connected || zoom.loading || zoom.denied || zoom.pending === 'stop' || (!!zoom.pending && !zoom.rate)}
          onValueChange={([value]) => zoom.setRate(value)}
          onPointerUp={zoom.release} onPointerCancel={zoom.release} onLostPointerCapture={zoom.release}
          onKeyUp={zoom.release} onBlur={zoom.release} />
      </div>
      <div className="flex justify-between text-xs text-slate-500 dark:text-slate-400"><span>← 缩小</span><span>松手停止</span><span>放大 →</span></div>
      <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">向两侧拖动并保持可持续调整，离中心越远速度越快；滑条回到中间表示停止，不代表当前镜头倍率。</p>
    </div>
    <div className="grid grid-cols-3 gap-3">
      <Button type="button" variant="outline" className="h-11" disabled={!canMove || !zoom.capabilities?.zoom_out} onClick={() => void zoom.control('out')}><ZoomOut className="h-4 w-4" />{zoom.pending === 'out' ? '缩小中…' : '缩小'}</Button>
      <Button type="button" variant="outline" className="h-11" disabled={zoom.denied || zoom.pending === 'stop' || (!supported && !zoom.pending)} onClick={() => void zoom.control('stop')}><Square className="h-4 w-4" />{zoom.pending === 'stop' ? '停止中…' : '停止'}</Button>
      <Button type="button" className="h-11" disabled={!canMove || !zoom.capabilities?.zoom_in} onClick={() => void zoom.control('in')}><ZoomIn className="h-4 w-4" />{zoom.pending === 'in' ? '放大中…' : '放大'}</Button>
    </div>
    {zoom.error && <p role="alert" className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">{zoom.error}</p>}
    {zoom.message && <p role="status" className="text-sm text-emerald-700 dark:text-emerald-300">{zoom.message}</p>}
    <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">每次点击调整一小步并自动停止。调整会影响同一设备的所有检测功能，完成后请检查 ROI 和警戒线的位置。</p>
  </div>
}
