import { useEffect, useState } from 'react'
import { UserCheck } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader } from '@/components/detection/DetectionConfigUi'
import { getFencePersons, type PersonChoices } from './api'

export function FenceWhitelist({ department, selected, disabled, onChange }: {
  department: DepartmentId; selected: number[]; disabled: boolean; onChange: (ids: number[]) => void
}) {
  const [keyword, setKeyword] = useState('')
  const [query, setQuery] = useState({ keyword: '', page: 1, selectedOnly: false })
  const [result, setResult] = useState<PersonChoices | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      setLoading(true)
      setError('')
      setResult(null)
      try {
        const value = query.selectedOnly && selected.length === 0
          ? { total: 0, items: [] }
          : await getFencePersons(department, query.keyword, query.page, controller.signal, query.selectedOnly ? selected : undefined)
        if (!controller.signal.aborted) setResult(value)
      } catch (cause) {
        if (!controller.signal.aborted) setError(String(cause))
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [department, query, selected])
  return <Card className={DETECTION_CONFIG_CARD_CLASS}>
    <DetectionConfigCardHeader icon={UserCheck} tone="emerald" title="当前围栏白名单" description={`已选择 ${selected.length} 人；只影响当前摄像头，修改后请保存。`} />
    <DetectionConfigCardContent className="space-y-4">
      <form className="flex gap-3" onSubmit={(event) => { event.preventDefault(); setQuery({ ...query, keyword: keyword.trim(), page: 1 }) }}>
        <Input aria-label="搜索人员" placeholder="姓名或工号" value={keyword} onChange={(event) => setKeyword(event.target.value)} />
        <Button type="submit">搜索</Button>
      </form>
      <div className="flex items-center gap-2"><Switch id="fence-selected-only" checked={query.selectedOnly} onCheckedChange={(selectedOnly) => setQuery({ ...query, selectedOnly, page: 1 })} /><Label htmlFor="fence-selected-only">仅查看已选人员</Label></div>
      {error && <p role="alert" className="text-red-600 dark:text-red-400">{error}</p>}
      <Table><TableHeader><TableRow><TableHead>姓名</TableHead><TableHead>工号</TableHead><TableHead>人员状态</TableHead><TableHead>允许进入</TableHead></TableRow></TableHeader>
        <TableBody>{loading ? <TableRow><TableCell colSpan={4}>正在读取人员…</TableCell></TableRow> : result?.items.map((person) => <TableRow key={person.id}>
          <TableCell>{person.person_name || '未命名人员'}</TableCell><TableCell>{person.job_no || '—'}</TableCell><TableCell>{person.is_active ? '在用' : '已停用'}</TableCell>
          <TableCell><Switch aria-label={`${person.person_name || person.job_no}允许进入`} checked={selected.includes(person.id)} disabled={disabled || (!person.is_active && !selected.includes(person.id))}
            onCheckedChange={(checked) => onChange(checked ? [...selected, person.id] : selected.filter((id) => id !== person.id))} /></TableCell>
        </TableRow>)}</TableBody></Table>
      {!loading && result?.total === 0 && <p className="text-sm text-slate-500">没有符合条件的人员。</p>}
      <div className="flex items-center justify-between"><span className="text-sm">共 {result?.total ?? 0} 人 · 第 {query.page} 页</span><div className="flex gap-2">
        <Button variant="outline" disabled={loading || query.page <= 1} onClick={() => setQuery({ ...query, page: query.page - 1 })}>上一页</Button>
        <Button variant="outline" disabled={loading || !result || query.page * 20 >= result.total} onClick={() => setQuery({ ...query, page: query.page + 1 })}>下一页</Button>
      </div></div>
    </DetectionConfigCardContent>
  </Card>
}
