import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  KeyRound,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserCheck,
  UserX,
  UsersRound,
} from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/auth/useAuth'
import {
  createAdminUser,
  deleteAdminUser,
  listAdminUsers,
  resetAdminUserPassword,
  updateAdminUser,
  type AdminUser,
  type AdminUserDepartment,
  type AdminUserRole,
} from '@/lib/admin-users'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const departments: Array<{ value: Exclude<AdminUserDepartment, 'all'>; label: string }> = [
  { value: 'general_electric', label: '通用电气事业部' },
  { value: 'research_institute', label: '福达新材院' },
  { value: 'electronics_electrician', label: '电子电工事业部' },
  { value: 'electrical_components', label: '电气部件事业部' },
  { value: 'precious_metal_recycling', label: '贵金属回收事业部' },
]

const departmentLabels: Record<AdminUserDepartment, string> = {
  all: '全部事业部',
  general_electric: '通用电气事业部',
  research_institute: '福达新材院',
  electronics_electrician: '电子电工事业部',
  electrical_components: '电气部件事业部',
  precious_metal_recycling: '贵金属回收事业部',
}

type EditorForm = {
  employeeId: string
  name: string
  role: AdminUserRole
  department: Exclude<AdminUserDepartment, 'all'>
  password: string
  confirmPassword: string
}

const emptyEditorForm: EditorForm = {
  employeeId: '',
  name: '',
  role: 'viewer',
  department: 'general_electric',
  password: '',
  confirmPassword: '',
}

const compactActionClass =
  'h-9 w-9 rounded-xl border-slate-200/80 bg-white/70 p-0 text-slate-500 shadow-none transition-all hover:-translate-y-0.5 hover:border-cyan-400/70 hover:bg-cyan-50 hover:text-cyan-600 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-400 dark:hover:border-cyan-500/60 dark:hover:bg-cyan-500/10 dark:hover:text-cyan-300'

function getAvatarLabel(name: string) {
  const normalizedName = name.trim()
  return normalizedName.slice(-1) || '用'
}

export function UserManagementSection() {
  const { user: currentUser, isAdmin } = useAuth()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null)
  const [editorForm, setEditorForm] = useState<EditorForm>(emptyEditorForm)
  const [resetUser, setResetUser] = useState<AdminUser | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [resetConfirmation, setResetConfirmation] = useState('')
  const [deleteUser, setDeleteUser] = useState<AdminUser | null>(null)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setUsers(await listAdminUsers())
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '用户列表加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  const enabledCount = useMemo(
    () => users.filter((item) => item.enabled).length,
    [users],
  )

  const openCreate = () => {
    setEditingUser(null)
    setEditorForm(emptyEditorForm)
    setError('')
    setEditorOpen(true)
  }

  const openEdit = (target: AdminUser) => {
    setEditingUser(target)
    setEditorForm({
      employeeId: target.employee_id,
      name: target.name,
      role: target.role,
      department: target.department === 'all' ? 'general_electric' : target.department,
      password: '',
      confirmPassword: '',
    })
    setError('')
    setEditorOpen(true)
  }

  const handleEditorSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    if (!editorForm.employeeId.trim() || !editorForm.name.trim()) {
      setError('工号和姓名不能为空。')
      return
    }
    if (!editingUser) {
      if (editorForm.password.length < 6) {
        setError('初始密码至少需要 6 位。')
        return
      }
      if (editorForm.password !== editorForm.confirmPassword) {
        setError('两次输入的初始密码不一致。')
        return
      }
    }
    setBusy(true)
    try {
      if (editingUser) {
        await updateAdminUser(editingUser.employee_id, {
          name: editorForm.name.trim(),
          role: editorForm.role,
          department: editorForm.role === 'admin' ? null : editorForm.department,
          enabled: editingUser.enabled,
        })
        toast.success('用户信息已更新')
      } else {
        await createAdminUser({
          employee_id: editorForm.employeeId.trim(),
          name: editorForm.name.trim(),
          role: editorForm.role,
          department: editorForm.role === 'admin' ? null : editorForm.department,
          password: editorForm.password,
        })
        toast.success('用户已添加')
      }
      setEditorOpen(false)
      setEditorForm(emptyEditorForm)
      await loadUsers()
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '用户保存失败')
    } finally {
      setBusy(false)
    }
  }

  const toggleEnabled = async (target: AdminUser) => {
    setBusy(true)
    setError('')
    try {
      await updateAdminUser(target.employee_id, {
        name: target.name,
        role: target.role,
        department: target.department,
        enabled: !target.enabled,
      })
      toast.success(target.enabled ? '用户已禁用' : '用户已启用')
      await loadUsers()
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : '状态修改失败')
    } finally {
      setBusy(false)
    }
  }

  const handleResetPassword = async (event: FormEvent) => {
    event.preventDefault()
    if (!resetUser) return
    setError('')
    if (resetPassword.length < 6) {
      setError('新密码至少需要 6 位。')
      return
    }
    if (resetPassword !== resetConfirmation) {
      setError('两次输入的新密码不一致。')
      return
    }
    setBusy(true)
    try {
      await resetAdminUserPassword(resetUser.employee_id, resetPassword)
      toast.success(`已重置 ${resetUser.name} 的密码，该用户需要重新登录`)
      setResetUser(null)
      setResetPassword('')
      setResetConfirmation('')
      await loadUsers()
    } catch (resetError) {
      setError(resetError instanceof Error ? resetError.message : '密码重置失败')
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteUser) return
    setBusy(true)
    setError('')
    try {
      await deleteAdminUser(deleteUser.employee_id)
      toast.success('用户已永久删除')
      setDeleteUser(null)
      await loadUsers()
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : '用户删除失败')
    } finally {
      setBusy(false)
    }
  }

  if (!isAdmin) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>无权访问</CardTitle>
          <CardDescription>只有管理员可以管理用户。</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="space-y-5">
      <div className="relative overflow-hidden rounded-2xl border border-slate-200/80 bg-white/80 px-5 py-5 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/55 sm:px-6">
        <div className="pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full bg-cyan-400/10 blur-3xl dark:bg-cyan-400/15" />
        <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3.5">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-cyan-400/30 bg-cyan-50 text-cyan-600 shadow-[0_0_24px_rgba(34,211,238,0.12)] dark:bg-cyan-500/10 dark:text-cyan-300">
              <UsersRound className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-slate-950 dark:text-white">用户管理</h1>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
                <span>共 {users.length} 个账号</span>
                <span className="hidden text-slate-300 dark:text-slate-700 sm:inline">/</span>
                <span className="inline-flex items-center gap-1.5 text-emerald-600 dark:text-emerald-300">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.9)]" />
                  {enabledCount} 个已启用
                </span>
              </p>
            </div>
          </div>
          <div className="flex gap-2.5">
            <Button
              variant="outline"
              className="h-10 flex-1 rounded-xl border-cyan-500/30 bg-cyan-50/60 px-4 text-cyan-700 shadow-none hover:border-cyan-500/60 hover:bg-cyan-100/70 hover:text-cyan-800 dark:bg-cyan-500/5 dark:text-cyan-300 dark:hover:bg-cyan-500/10 sm:flex-none"
              onClick={() => void loadUsers()}
              disabled={loading || busy}
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </Button>
            <Button
              className="h-10 flex-1 rounded-xl border-0 bg-gradient-to-r from-cyan-500 to-blue-600 px-4 text-white shadow-[0_8px_22px_rgba(14,165,233,0.25)] transition-all hover:-translate-y-0.5 hover:from-cyan-400 hover:to-blue-500 hover:shadow-[0_10px_26px_rgba(14,165,233,0.32)] sm:flex-none"
              onClick={openCreate}
              disabled={busy}
            >
              <Plus className="mr-2 h-4 w-4" />
              添加用户
            </Button>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/70 dark:bg-red-950/40 dark:text-red-200">
          {error}
        </div>
      )}

      <Card className="overflow-hidden border-slate-200/80 bg-white/80 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/55">
        <CardHeader className="border-b border-slate-200/70 px-5 py-4 dark:border-slate-800/90 sm:px-6">
          <div className="flex items-center gap-2.5">
            <ShieldCheck className="h-4 w-4 text-cyan-500 dark:text-cyan-300" />
            <div>
              <CardTitle className="text-base">账号列表</CardTitle>
              <CardDescription className="mt-0.5">账号操作受后端权限和最后管理员保护</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table className="min-w-[940px]">
              <TableHeader className="bg-slate-50/90 dark:bg-slate-950/80">
                <TableRow className="border-slate-200/70 hover:bg-transparent dark:border-slate-800">
                  <TableHead className="h-11 pl-6 text-[11px] font-semibold tracking-[0.12em] text-slate-500 dark:text-slate-500">工号</TableHead>
                  <TableHead className="h-11 text-[11px] font-semibold tracking-[0.12em] text-slate-500 dark:text-slate-500">姓名</TableHead>
                  <TableHead className="h-11 text-[11px] font-semibold tracking-[0.12em] text-slate-500 dark:text-slate-500">角色</TableHead>
                  <TableHead className="h-11 text-[11px] font-semibold tracking-[0.12em] text-slate-500 dark:text-slate-500">事业部</TableHead>
                  <TableHead className="h-11 text-[11px] font-semibold tracking-[0.12em] text-slate-500 dark:text-slate-500">状态</TableHead>
                  <TableHead className="h-11 min-w-[230px] pr-6 text-right text-[11px] font-semibold tracking-[0.12em] text-slate-500 dark:text-slate-500">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((item) => {
                  const isCurrent = item.employee_id === currentUser?.employee_id
                  return (
                    <TableRow
                      key={item.employee_id}
                      className="group h-[68px] border-slate-200/70 transition-colors hover:bg-cyan-50/40 dark:border-slate-800/90 dark:hover:bg-cyan-400/[0.035]"
                    >
                      <TableCell className="pl-6">
                        <div className="flex items-center gap-2.5">
                          <span className={`h-1.5 w-1.5 rounded-full ${item.enabled ? 'bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.9)]' : 'bg-slate-400 dark:bg-slate-600'}`} />
                          <span className="font-mono text-xs font-semibold tracking-wide text-slate-600 dark:text-slate-300">
                            {item.employee_id}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-3">
                          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-cyan-300/40 bg-gradient-to-br from-cyan-400 via-sky-500 to-violet-500 text-base font-bold text-slate-950 shadow-[0_6px_18px_rgba(14,165,233,0.2)]">
                            {getAvatarLabel(item.name)}
                          </div>
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{item.name}</div>
                            {isCurrent && (
                              <span className="mt-0.5 block text-[11px] font-medium text-cyan-600 dark:text-cyan-300">当前账号</span>
                            )}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={item.role === 'admin'
                            ? 'rounded-full border-violet-400/35 bg-violet-500/10 px-2.5 py-1 font-medium text-violet-600 dark:text-violet-300'
                            : 'rounded-full border-cyan-400/35 bg-cyan-500/10 px-2.5 py-1 font-medium text-cyan-700 dark:text-cyan-300'}
                        >
                          {item.role === 'admin' ? '管理员' : '普通用户'}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <span className="inline-flex rounded-lg bg-slate-100/80 px-2.5 py-1.5 text-xs font-medium text-slate-600 dark:bg-slate-800/70 dark:text-slate-300">
                          {departmentLabels[item.department] || item.department}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={item.enabled
                            ? 'rounded-full border-emerald-400/35 bg-emerald-500/10 px-2.5 py-1 font-medium text-emerald-700 dark:text-emerald-300'
                            : 'rounded-full border-slate-400/30 bg-slate-500/10 px-2.5 py-1 font-medium text-slate-500 dark:text-slate-400'}
                        >
                          <span className={`mr-1.5 h-1.5 w-1.5 rounded-full ${item.enabled ? 'bg-emerald-400 shadow-[0_0_7px_rgba(52,211,153,0.9)]' : 'bg-slate-400'}`} />
                          {item.enabled ? '已启用' : '已禁用'}
                        </Badge>
                      </TableCell>
                      <TableCell className="pr-6">
                        <div className="flex justify-end gap-2">
                          <Button
                            size="icon"
                            variant="outline"
                            className={compactActionClass}
                            onClick={() => openEdit(item)}
                            disabled={busy}
                            aria-label={`编辑 ${item.name}`}
                            title="编辑用户"
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            size="icon"
                            variant="outline"
                            className={compactActionClass}
                            onClick={() => void toggleEnabled(item)}
                            disabled={busy || isCurrent}
                            aria-label={`${item.enabled ? '禁用' : '启用'} ${item.name}`}
                            title={isCurrent ? '不能修改当前账号状态' : item.enabled ? '禁用用户' : '启用用户'}
                          >
                            {item.enabled ? <UserX className="h-4 w-4" /> : <UserCheck className="h-4 w-4" />}
                          </Button>
                          <Button
                            size="icon"
                            variant="outline"
                            className={compactActionClass}
                            onClick={() => setResetUser(item)}
                            disabled={busy}
                            aria-label={`重置 ${item.name} 的密码`}
                            title="重置密码"
                          >
                            <KeyRound className="h-4 w-4" />
                          </Button>
                          <Button
                            size="icon"
                            variant="outline"
                            className={`${compactActionClass} hover:border-red-400/60 hover:bg-red-50 hover:text-red-600 dark:hover:border-red-500/50 dark:hover:bg-red-500/10 dark:hover:text-red-300`}
                            onClick={() => setDeleteUser(item)}
                            disabled={busy || isCurrent}
                            aria-label={`删除 ${item.name}`}
                            title={isCurrent ? '不能删除当前账号' : '删除用户'}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
                {!loading && users.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="py-14 text-center text-muted-foreground">
                      暂无用户
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {loading && <div className="border-t border-slate-200/70 py-8 text-center text-sm text-muted-foreground dark:border-slate-800">正在加载用户...</div>}
        </CardContent>
      </Card>

      <Dialog open={editorOpen} onOpenChange={(open) => !busy && setEditorOpen(open)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingUser ? '编辑用户' : '添加用户'}</DialogTitle>
            <DialogDescription>
              {editingUser ? '修改姓名、角色和所属事业部。' : '设置用户身份和初始登录密码。'}
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={handleEditorSubmit}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="user-employee-id">工号</Label>
                <Input
                  id="user-employee-id"
                  value={editorForm.employeeId}
                  onChange={(event) => setEditorForm((value) => ({ ...value, employeeId: event.target.value }))}
                  disabled={Boolean(editingUser)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="user-name">姓名</Label>
                <Input
                  id="user-name"
                  value={editorForm.name}
                  onChange={(event) => setEditorForm((value) => ({ ...value, name: event.target.value }))}
                  required
                />
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="user-role">角色</Label>
                <select
                  id="user-role"
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={editorForm.role}
                  onChange={(event) => setEditorForm((value) => ({ ...value, role: event.target.value as AdminUserRole }))}
                >
                  <option value="viewer">普通用户</option>
                  <option value="admin">管理员</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="user-department">事业部</Label>
                <select
                  id="user-department"
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm disabled:opacity-60"
                  value={editorForm.role === 'admin' ? 'all' : editorForm.department}
                  disabled={editorForm.role === 'admin'}
                  onChange={(event) => setEditorForm((value) => ({
                    ...value,
                    department: event.target.value as EditorForm['department'],
                  }))}
                >
                  {editorForm.role === 'admin' && <option value="all">全部事业部</option>}
                  {departments.map((department) => (
                    <option key={department.value} value={department.value}>{department.label}</option>
                  ))}
                </select>
              </div>
            </div>
            {!editingUser && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="user-password">初始密码</Label>
                  <Input
                    id="user-password"
                    type="password"
                    value={editorForm.password}
                    onChange={(event) => setEditorForm((value) => ({ ...value, password: event.target.value }))}
                    autoComplete="new-password"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="user-confirm-password">确认初始密码</Label>
                  <Input
                    id="user-confirm-password"
                    type="password"
                    value={editorForm.confirmPassword}
                    onChange={(event) => setEditorForm((value) => ({ ...value, confirmPassword: event.target.value }))}
                    autoComplete="new-password"
                    required
                  />
                </div>
              </div>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setEditorOpen(false)} disabled={busy}>取消</Button>
              <Button type="submit" disabled={busy}>{busy ? '保存中...' : '保存'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(resetUser)}
        onOpenChange={(open) => {
          if (!open && !busy) {
            setResetUser(null)
            setResetPassword('')
            setResetConfirmation('')
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>重置用户密码</DialogTitle>
            <DialogDescription>
              为 {resetUser?.name} 设置新密码。保存后该用户已有登录会失效。
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={handleResetPassword}>
            <div className="space-y-2">
              <Label htmlFor="reset-user-password">新密码</Label>
              <Input id="reset-user-password" type="password" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} autoComplete="new-password" required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="reset-user-confirmation">确认新密码</Label>
              <Input id="reset-user-confirmation" type="password" value={resetConfirmation} onChange={(event) => setResetConfirmation(event.target.value)} autoComplete="new-password" required />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setResetUser(null)} disabled={busy}>取消</Button>
              <Button type="submit" disabled={busy}>{busy ? '保存中...' : '重置密码'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog open={Boolean(deleteUser)} onOpenChange={(open) => !open && !busy && setDeleteUser(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>永久删除用户？</AlertDialogTitle>
            <AlertDialogDescription>
              将永久删除 {deleteUser?.name}（{deleteUser?.employee_id}）。该操作不可撤销，用户已有登录会立即失效。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>取消</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={(event) => {
                event.preventDefault()
                void handleDelete()
              }}
              disabled={busy}
            >
              {busy ? '删除中...' : '确认永久删除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
