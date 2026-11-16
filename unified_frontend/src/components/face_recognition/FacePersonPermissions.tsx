import { useState } from 'react'
import { UserCheck } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader } from '@/components/detection/DetectionConfigUi'
import type { FacePerson, PersonPermissionsApi } from './api'
import { useFacePersons } from './useRecognitionConfig'

export function FacePersonPermissions<Scope extends string>({ scope, permissions, title = '人员权限' }: {
  scope: Scope; permissions: PersonPermissionsApi<Scope>; title?: string
}) {
  const state = useFacePersons(scope, permissions)
  const [keyword, setKeyword] = useState('')
  const saving = state.savingId !== null
  const pages = state.result ? Math.max(1, Math.ceil(state.result.total / state.result.page_size)) : 1
  return (
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={UserCheck} tone="emerald" title={title} />
      <DetectionConfigCardContent className="space-y-4">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => {
          event.preventDefault()
          state.setQuery((query) => ({ ...query, page: 1, keyword: keyword.trim() || undefined }))
        }}>
          <div className="min-w-64 flex-1 space-y-2">
            <Label htmlFor="face-person-keyword">搜索人员</Label>
            <Input id="face-person-keyword" value={keyword} maxLength={255} disabled={saving} placeholder="姓名、工号、人员编码、海康 ID 或组织编码" onChange={(event) => setKeyword(event.target.value)} />
          </div>
          <Button type="submit" disabled={saving}>搜索</Button>
          <Button type="button" variant="outline" disabled={saving || state.loading} onClick={() => { void state.loadPersons() }}>刷新</Button>
        </form>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-2"><Label htmlFor="face-person-source">数据来源</Label>
            <Select value={state.query.source || 'all'} disabled={saving} onValueChange={(source) => state.setQuery((query) => ({ ...query, page: 1, source: source === 'all' ? undefined : source as FacePerson['hik_source'] }))}>
              <SelectTrigger id="face-person-source" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="all">全部来源</SelectItem><SelectItem value="one">海康 one</SelectItem><SelectItem value="two">海康 two</SelectItem></SelectContent>
            </Select>
          </div>
          <div className="space-y-2"><Label htmlFor="face-person-active">人员状态</Label>
            <Select value={state.query.is_active === undefined ? 'all' : String(state.query.is_active)} disabled={saving} onValueChange={(active) => state.setQuery((query) => ({ ...query, page: 1, is_active: active === 'all' ? undefined : active === 'true' }))}>
              <SelectTrigger id="face-person-active" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="all">全部状态</SelectItem><SelectItem value="true">已激活</SelectItem><SelectItem value="false">已停用</SelectItem></SelectContent>
            </Select>
          </div>
          <div className="space-y-2"><Label htmlFor="face-person-allowed">允许状态</Label>
            <Select value={state.query.is_allowed === undefined ? 'all' : String(state.query.is_allowed)} disabled={saving} onValueChange={(allowed) => state.setQuery((query) => ({ ...query, page: 1, is_allowed: allowed === 'all' ? undefined : allowed === 'true' }))}>
              <SelectTrigger id="face-person-allowed" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="all">全部权限</SelectItem><SelectItem value="true">允许</SelectItem><SelectItem value="false">不允许</SelectItem></SelectContent>
            </Select>
          </div>
        </div>
        {state.error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{state.error}</p>}
        {state.message && <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">{state.message}</p>}
        <Table>
          <TableHeader><TableRow>{['姓名', '工号', '人员编码', '组织编码', '海康人员 ID', '数据来源', '服务节点', '人员状态', '允许状态', '最近同步时间'].map((title) => <TableHead key={title} className="whitespace-nowrap">{title}</TableHead>)}</TableRow></TableHeader>
          <TableBody>
            {state.loading ? <TableRow><TableCell colSpan={10} className="text-center">正在读取人员…</TableCell></TableRow> : state.result?.items.map((person) => (
              <TableRow key={person.id}>
                <TableCell>{person.person_name || '—'}</TableCell><TableCell>{person.job_no || '—'}</TableCell>
                <TableCell>{person.person_code || '—'}</TableCell><TableCell>{person.org_index_code || '—'}</TableCell>
                <TableCell>{person.hik_person_id}</TableCell><TableCell>海康 {person.hik_source}</TableCell>
                <TableCell>{person.server_index_code || '—'}</TableCell><TableCell className="whitespace-nowrap">{person.is_active ? '已激活' : '已停用'}</TableCell>
                <TableCell><div className="flex items-center gap-2 whitespace-nowrap">
                  <Switch aria-label={`${person.person_name || person.hik_person_id}允许通行`} checked={person.is_allowed} disabled={!state.canConfigure || saving || state.loading} onCheckedChange={(allowed) => { void state.setPersonAllowed(person.id, allowed) }} />
                  <span>{state.savingId === person.id ? '保存中…' : person.is_allowed ? '允许' : '不允许'}</span>
                </div></TableCell>
                <TableCell className="whitespace-nowrap">{new Date(person.last_synced_at).toLocaleString('zh-CN', { hour12: false })}</TableCell>
              </TableRow>
            ))}
            {!state.loading && !state.error && !state.result?.items.length && <TableRow><TableCell colSpan={10} className="text-center">没有符合条件的人员。</TableCell></TableRow>}
          </TableBody>
        </Table>
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500 dark:text-slate-400">
          <span>{state.result ? `共 ${state.result.total} 人 · 第 ${state.query.page} / ${pages} 页` : '人员列表尚未加载'}</span>
          <div className="flex gap-2">
            <Button variant="outline" disabled={saving || state.loading || !state.result || state.query.page <= 1} onClick={() => state.setQuery((query) => ({ ...query, page: query.page - 1 }))}>上一页</Button>
            <Button variant="outline" disabled={saving || state.loading || !state.result || state.query.page >= pages} onClick={() => state.setQuery((query) => ({ ...query, page: query.page + 1 }))}>下一页</Button>
          </div>
        </div>
      </DetectionConfigCardContent>
    </Card>
  )
}
