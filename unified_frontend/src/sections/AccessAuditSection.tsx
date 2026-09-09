import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { useDepartmentCatalog } from '@/hooks/use-department-catalog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { listAccessAudit, type AccessAuditItem } from '@/lib/access-audit'

const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

function formatDateTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateTimeFormatter.format(date)
}

export function AccessAuditSection() {
  const { user } = useAuth()
  const canViewAccessAudit = user?.capabilities?.view_access_audit === true
  const {
    labels: departmentLabels,
    error: departmentsError,
    reload: reloadDepartments,
  } = useDepartmentCatalog(canViewAccessAudit)
  const [items, setItems] = useState<AccessAuditItem[]>([])
  const [loading, setLoading] = useState(canViewAccessAudit)
  const [error, setError] = useState('')

  const loadItems = useCallback(async () => {
    if (!canViewAccessAudit) return
    setLoading(true)
    setError('')
    try {
      setItems(await listAccessAudit())
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '访问记录加载失败')
    } finally {
      setLoading(false)
    }
  }, [canViewAccessAudit])

  useEffect(() => {
    void loadItems()
  }, [loadItems])

  if (!canViewAccessAudit) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>无权访问</CardTitle>
          <CardDescription>只有平台所有者可以查看访问记录。</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-950 dark:text-white">访问记录</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            最近访问过视觉平台的 {items.length} 位用户
          </p>
        </div>
        <Button variant="outline" onClick={() => { reloadDepartments(); void loadItems() }} disabled={loading}>
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新
        </Button>
      </div>

      {(error || departmentsError) && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/70 dark:bg-red-950/40 dark:text-red-200">
          {error || departmentsError}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>最近访问用户</CardTitle>
          <CardDescription>
            按账号聚合；用户登录或重新打开平台时更新最近访问时间和次数。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>用户</TableHead>
                  <TableHead>工号</TableHead>
                  <TableHead>角色</TableHead>
                  <TableHead>事业部</TableHead>
                  <TableHead>首次访问</TableHead>
                  <TableHead>最近访问</TableHead>
                  <TableHead className="text-right">访问次数</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.employee_id}>
                    <TableCell className="font-medium">{item.name}</TableCell>
                    <TableCell className="font-mono">{item.employee_id}</TableCell>
                    <TableCell>
                      <Badge variant={item.role === 'admin' ? 'default' : 'secondary'}>
                        {item.role === 'admin' ? '管理员' : '普通用户'}
                      </Badge>
                    </TableCell>
                    <TableCell>{departmentLabels[item.department || ''] || item.department || '未设置'}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDateTime(item.first_seen_at)}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDateTime(item.last_seen_at)}</TableCell>
                    <TableCell className="text-right font-semibold">{item.visit_count}</TableCell>
                  </TableRow>
                ))}
                {!loading && items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                      暂无访问记录
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {loading && <div className="py-8 text-center text-sm text-muted-foreground">正在加载访问记录...</div>}
        </CardContent>
      </Card>
    </div>
  )
}
