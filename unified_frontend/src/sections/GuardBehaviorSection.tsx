import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { GuardConfigView } from '@/components/guard_behavior/GuardConfigView'
import { GuardMonitorView } from '@/components/guard_behavior/GuardMonitorView'
import { useGuardSites } from '@/components/guard_behavior/useGuardSites'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent } from '@/components/ui/tabs'

function DepartmentGuardBehavior({ department }: { department: DepartmentId }) {
  const { sites, site, selectedId, setSelectedId, loading, error, reload } = useGuardSites(department)
  return <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
    <Tabs defaultValue="monitor" className="space-y-5">
      <DetectionPageHeader title="保安行为规范检测" departmentLabel={DEPARTMENT_LABELS[department]} />
      {error && <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">{error}</p>}
      <TabsContent value="monitor" className="mt-0 space-y-5">
        <GuardMonitorView key={site?.id ?? 'empty'} site={site} sites={sites} loadingSites={loading}
          onSelectSite={setSelectedId} onRefreshSites={() => reload()} />
      </TabsContent>
      <TabsContent value="config" className="mt-0 space-y-5">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <Label htmlFor="guard-site-selector">保安室</Label>
        <Select value={selectedId === null ? '' : String(selectedId)} disabled={loading || !sites.length} onValueChange={(id) => setSelectedId(Number(id))}>
          <SelectTrigger id="guard-site-selector" className="w-full sm:w-72"><SelectValue placeholder={loading ? '读取中…' : '尚无保安室'} /></SelectTrigger>
          <SelectContent>{sites.map((item) => <SelectItem key={item.id} value={String(item.id)}>{item.name}{item.enabled ? '' : '（已停用）'}</SelectItem>)}</SelectContent>
        </Select>
        <Button variant="outline" disabled={loading} onClick={() => void reload()}>刷新保安室</Button>
      </div>
        {!loading && <GuardConfigView key={site?.id ?? 'empty'} site={site} department={department} onSitesChanged={(id) => reload(undefined, id)} />}
      </TabsContent>
    </Tabs>
  </div>
}

export function GuardBehaviorSection({ department }: { department: DepartmentId }) {
  // 事业部切换时卸载上一组请求与草稿，避免延迟响应串入新的工作区。
  return <DepartmentGuardBehavior key={department} department={department} />
}
export default GuardBehaviorSection
