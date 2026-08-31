// 文件说明：实现`AccessAuditSection` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
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

const departmentLabels: Record<string, string> = {
  all: '全部事业部',
  general_electric: '通用电气事业部',
  research_institute: '福达新材院',
  electronics_electrician: '电子电工事业部',
  electrical_components: '电气部件事业部',
  precious_metal_recycling: '伟达公司',
  haoda_company: '皓达公司',
}

const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/**
 * 功能：转换或规范化 `formatDateTime` 对应的`AccessAuditSection` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（string）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/AccessAuditSection.tsx` 的 `AccessAuditSection` 调用本符号
 *   - 内部调用：`Date`、`isNaN`、`getTime`、`format`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function formatDateTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateTimeFormatter.format(date)
}

/**
 * 功能：渲染 `AccessAuditSection` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：无。
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useAuth`、`useState`、`useCallback`、`async`、`setLoading`、`setError`、`setItems`、`listAccessAudit`、`useEffect`、`loadItems`
 *          等共 28 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
 */
export function AccessAuditSection() {
  const { user } = useAuth()
  const canViewAccessAudit = user?.capabilities?.view_access_audit === true
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
        <Button variant="outline" onClick={() => void loadItems()} disabled={loading}>
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/70 dark:bg-red-950/40 dark:text-red-200">
          {error}
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
