import { useId } from 'react'
import { FileAudio, Trash2, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { useHornAudioCatalog } from './useHornAudioCatalog'

export function HornAudioLibrary({ catalog }: { catalog: ReturnType<typeof useHornAudioCatalog> }) {
  const id = useId()
  return <div className="space-y-4 rounded-xl border border-[#E8ECF5] bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
    <h3 className="flex items-center gap-2 font-semibold text-slate-900 dark:text-slate-100"><FileAudio className="h-4 w-4 text-violet-500" />报警音频库</h3>
    <div className="space-y-2">
      <Label htmlFor={id} className="flex items-center gap-2"><Upload className="h-4 w-4" />{catalog.busy ? '正在处理音频...' : '上传 AAC 音频'}</Label>
      <Input id={id} type="file" accept=".aac,audio/aac,audio/x-aac" disabled={catalog.busy} onChange={(event) => {
        const file = event.target.files?.[0]
        if (file) void catalog.upload(file)
        event.target.value = ''
      }} />
      <p className="text-xs text-slate-500 dark:text-slate-400">音频保存在本服务器，上传时会校验能否解码。上传后可在各喇叭下方试播，也可用于检测报警绑定。</p>
    </div>
    {catalog.error || catalog.loadError ? <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">{catalog.error || catalog.loadError}</p> : null}
    {catalog.files === null ? <p role="status" className="text-sm text-slate-500">正在读取音频...</p>
      : !catalog.files.length ? <p className="text-sm text-slate-500 dark:text-slate-400">暂无音频，请先上传 AAC 文件。</p>
        : <ul className="divide-y divide-slate-100 dark:divide-slate-800">{catalog.files.map((file) => <li key={file.id} className="flex items-center justify-between gap-3 py-2">
          <div className="min-w-0"><p className="break-all text-sm text-slate-800 dark:text-slate-100">{file.name}</p>
            <p className="text-xs text-slate-500">{file.duration.toFixed(1)} 秒 · {(file.size / 1024).toFixed(1)} KB</p></div>
          <Button size="sm" variant="ghost" disabled={catalog.busy} aria-label={`删除音频 ${file.name}`} onClick={() => {
            if (window.confirm(`确定删除音频“${file.name}”吗？已被检测配置引用的素材需要先解绑。`)) void catalog.remove(file.id)
          }}><Trash2 className="h-4 w-4 text-rose-500" /></Button>
        </li>)}</ul>}
  </div>
}
