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
    <div className="min-w-0 rounded-2xl bg-slate-100/70 p-4 dark:bg-slate-950/50 sm:p-6">
      <Card className="gap-0 overflow-hidden rounded-xl border-slate-200/80 bg-white py-0 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <CardHeader className="border-b border-slate-200/80 px-5 py-6 dark:border-slate-800 sm:px-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <CardTitle className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">事业部功能分配</CardTitle>
              <CardDescription className="leading-6 text-slate-500 dark:text-slate-400">勾选各事业部显示的检测功能。管理员和普通账号均按此分配显示检测页面。</CardDescription>
            </div>
            <div className="ml-auto flex shrink-0 gap-2">
              <Button className="border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800" variant="outline" disabled={busy} onClick={() => dirty ? setConfirmation('reload') : reload()}>
                <RefreshCw className="mr-2 h-4 w-4" />重新加载
              </Button>
              <Button className="bg-blue-600 text-white hover:bg-blue-700 dark:bg-blue-600 dark:hover:bg-blue-500" disabled={busy || !dirty} onClick={() => removed.length ? setConfirmation('save') : void handleSave()}>
                <Save className="mr-2 h-4 w-4" />{saving ? '保存中…' : '保存分配'}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="min-w-0 p-0">
          {error && <div role="alert" className="mx-5 my-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300 sm:mx-6">{error}</div>}
          {loading ? <p role="status" className="py-12 text-center text-sm text-muted-foreground">正在加载功能分配…</p> : draft && (
            <Table className="min-w-[1120px] table-fixed">
              <TableHeader className="bg-slate-100/80 dark:bg-slate-800/70">
                <TableRow className="border-slate-200/80 hover:bg-transparent dark:border-slate-700">
                  <TableHead className="h-24 w-56 pl-6 text-base font-semibold text-slate-700 dark:text-slate-200">检测功能</TableHead>
                  {draft.assignments.map((item) => (
                    <TableHead key={item.department} className="h-24 px-2 text-center">
                      <div className="text-base font-bold leading-6 text-slate-800 dark:text-slate-100">{DEPARTMENT_LABELS[item.department]}</div>
                      <span className="mt-2 inline-flex rounded-md bg-blue-50 px-2 py-1 text-xs font-medium leading-4 text-blue-600 dark:bg-blue-500/15 dark:text-blue-300">已分配 {item.features.length} 项</span>
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {draft.features.map((feature) => (
                  <TableRow key={feature.name} className="h-14 border-slate-100 even:bg-slate-50/70 hover:bg-blue-50/50 dark:border-slate-800 dark:even:bg-slate-800/30 dark:hover:bg-blue-950/30">
                    <TableCell className="py-4 pl-6 text-[15px] font-medium text-slate-700 dark:text-slate-200">{feature.display_name}</TableCell>
                    {draft.assignments.map((item) => (
                      <TableCell key={item.department} className="px-2 text-center [&:has([role=checkbox])]:pr-2">
                        <Checkbox
                          className="size-5 border-slate-300 data-[state=checked]:border-blue-600 data-[state=checked]:bg-blue-600 data-[state=checked]:text-white dark:border-slate-600 dark:data-[state=checked]:border-blue-500 dark:data-[state=checked]:bg-blue-500"
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
        </CardContent>
        <div className="space-y-2 border-t border-slate-200/80 bg-slate-50 px-5 py-4 text-sm leading-6 dark:border-slate-800 dark:bg-slate-950/40 sm:px-6">
          {dirty && <p className="text-amber-700 dark:text-amber-300">有尚未保存的分配调整。</p>}
          <p className="text-slate-500 dark:text-slate-400">
            保存后接口权限立即生效，已登录页面会在 30 秒内同步。取消分配不会停止已有检测任务，也不会删除配置或历史报警。
          </p>
        </div>
      </Card>
      <AlertDialog open={confirmation !== null} onOpenChange={(open) => !open && setConfirmation(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmation === 'save' ? '确认收回功能访问权限' : '放弃未保存的调整？'}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmation === 'save'
                ? '以下功能将从对应事业部的检测页面中隐藏，对管理员和普通账号同时生效。已经启用的检测仍按原配置运行；如需停止，请先取消保存并在检测配置中停用。'
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
