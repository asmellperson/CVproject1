import { useState } from 'react'
import { RefreshCw, Save } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/auth/useAuth'
import { DEPARTMENT_LABELS } from '@/auth/permissions'
import { useFeatureSettings } from '@/hooks/use-feature-settings'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'

export function FeatureManagementSection() {
  const { refreshMe } = useAuth()
  const { draft, loading, saving, error, dirty, removed, reload, toggle, save } = useFeatureSettings()
  const [confirmation, setConfirmation] = useState<'save' | 'reload' | null>(null)
  const busy = loading || saving

  const handleSave = async () => {
    if (!await save()) return
    toast.success('功能分配已保存')
    try {
      await refreshMe()
    } catch {
      toast.error('配置已保存，但页面权限刷新失败，请刷新页面')
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <CardTitle>事业部功能分配</CardTitle>
              <CardDescription>勾选各事业部可访问的检测功能。管理员始终保留全部功能的维护权限。</CardDescription>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" disabled={busy} onClick={() => dirty ? setConfirmation('reload') : reload()}>
                <RefreshCw className="mr-2 h-4 w-4" />重新加载
              </Button>
              <Button disabled={busy || !dirty} onClick={() => removed.length ? setConfirmation('save') : void handleSave()}>
                <Save className="mr-2 h-4 w-4" />{saving ? '保存中…' : '保存分配'}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            保存后接口权限立即生效，已登录页面会在 30 秒内同步。取消分配不会停止已有检测任务，也不会删除配置或历史报警。
          </p>
          {error && <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</div>}
          {loading ? <p role="status" className="py-12 text-center text-sm text-muted-foreground">正在加载功能分配…</p> : draft && (
            <Table className="min-w-[1050px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-52">检测功能</TableHead>
                  {draft.assignments.map((item) => (
                    <TableHead key={item.department} className="min-w-28 text-center">
                      <div>{DEPARTMENT_LABELS[item.department]}</div>
                      <div className="mt-1 text-xs font-normal">已分配 {item.features.length} 项</div>
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {draft.features.map((feature) => (
                  <TableRow key={feature.name}>
                    <TableCell className="font-medium">{feature.display_name}</TableCell>
                    {draft.assignments.map((item) => (
                      <TableCell key={item.department} className="text-center">
                        <Checkbox
                          aria-label={`${DEPARTMENT_LABELS[item.department]}：${feature.display_name}`}
                          disabled={saving}
                          checked={item.features.includes(feature.name)}
                          onCheckedChange={(checked) => toggle(item.department, feature.name, checked === true)}
                        />
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {dirty && <p className="text-sm text-amber-700 dark:text-amber-300">有尚未保存的分配调整。</p>}
        </CardContent>
      </Card>
      <AlertDialog open={confirmation !== null} onOpenChange={(open) => !open && setConfirmation(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmation === 'save' ? '确认收回功能访问权限' : '放弃未保存的调整？'}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmation === 'save'
                ? '以下功能将对对应事业部的普通账号不可见，相关接口访问也会被拒绝。已经启用的检测仍按原配置运行；如需停止，请在检测配置中停用。'
                : '重新加载会丢弃当前勾选结果，并读取服务器上的最新配置。'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {confirmation === 'save' && <ul className="max-h-60 overflow-y-auto text-sm">
            {removed.map((item) => <li key={`${item.department}:${item.feature}`} className="py-1">
              {DEPARTMENT_LABELS[item.department]} · {draft?.features.find((feature) => feature.name === item.feature)?.display_name}
            </li>)}
          </ul>}
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={() => confirmation === 'save' ? void handleSave() : reload()}>
              {confirmation === 'save' ? '确认保存' : '重新加载'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
