import { useState } from 'react'
import { Bot, Settings } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { DEPARTMENT_LABELS, getAccessibleDepartments, type DepartmentId } from '@/auth/permissions'
import { AssistantChat } from '@/components/assistant/AssistantChat'
import { AssistantSettingsDialog } from '@/components/assistant/AssistantSettingsDialog'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export function AssistantSection() {
  const { user, isAdmin } = useAuth()
  const [department, setDepartment] = useState<DepartmentId | 'all'>('all')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const departments = getAccessibleDepartments(user)
  const scope = department !== 'all' && departments.includes(department) ? department : null
  const identity = JSON.stringify([user?.employee_id, user?.role, user?.departments, user?.feature_access, scope])
  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-4"><div><h1 className="flex items-center gap-3 text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100"><Bot className="h-7 w-7 text-blue-600 dark:text-blue-400" />千问平台助手</h1><p className="mt-2 text-sm text-slate-500 dark:text-slate-400">查询平台配置、添加摄像头，并通过自然语言完成日常调整。</p></div>
      <div className="flex gap-3"><Select value={scope ?? 'all'} onValueChange={(value) => setDepartment(value as DepartmentId | 'all')}><SelectTrigger className="w-52" aria-label="助手会话部门"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">全部可访问部门</SelectItem>{departments.map((item) => <SelectItem key={item} value={item}>{DEPARTMENT_LABELS[item]}</SelectItem>)}</SelectContent></Select>
        {isAdmin && <Button variant="outline" className="gap-2" onClick={() => setSettingsOpen(true)}><Settings className="h-4 w-4" />模型设置</Button>}
      </div>
    </div>
    <AssistantChat key={identity} department={scope} isAdmin={isAdmin} />
    {isAdmin && settingsOpen && <AssistantSettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />}
  </div>
}
