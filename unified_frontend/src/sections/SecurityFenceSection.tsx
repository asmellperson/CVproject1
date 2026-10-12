import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { AiVisionMonitor } from '@/components/AiVisionMonitor'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { FenceConfigView } from '@/components/security_fence/FenceConfigView'
import { FenceRecordsView } from '@/components/security_fence/FenceRecordsView'
import { FENCE_FEATURE } from '@/components/security_fence/api'
import { Tabs, TabsContent } from '@/components/ui/tabs'

export function SecurityFenceSection({ department }: { department: DepartmentId }) {
  return <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
    <Tabs defaultValue="monitor" className="space-y-5">
      <DetectionPageHeader title="警戒围栏" subtitle="每日时段警戒与人员白名单核验" departmentLabel={DEPARTMENT_LABELS[department]} recordsValue="records" recordsLabel="报警记录" />
      <TabsContent value="monitor" className="mt-0 space-y-5"><AiVisionMonitor title="警戒围栏监控" feature={FENCE_FEATURE} department={department} presentation="security-fence" /></TabsContent>
      <TabsContent value="records" className="mt-0 space-y-5"><FenceRecordsView key={department} department={department} /></TabsContent>
      <TabsContent value="config" className="mt-0 space-y-6"><FenceConfigView key={department} department={department} /></TabsContent>
    </Tabs>
  </div>
}
