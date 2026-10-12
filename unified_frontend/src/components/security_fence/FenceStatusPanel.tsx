import { Activity, ShieldAlert, UserCheck, UsersRound } from 'lucide-react'
import { StatCard } from '@/components/feature_dashboard/FeatureDashboardMonitorView'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useFenceStatus } from './useFenceStatus'

const STATES = { disabled: '未启用', offline: '视频离线', waiting: '等待检测', stale: '结果过期', error: '检测异常', ready: '检测中' }
const IDENTITIES = { pending: '身份待核验', allowed: '白名单', unauthorized: '非白名单' }

export function FenceStatusPanel({ cameraKey }: { cameraKey: string }) {
  const result = useFenceStatus(cameraKey)
  const status = result?.value
  return <div className="space-y-4 pb-4">
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatCard label="检测状态" value={status ? STATES[status.state] : '等待检测'} detail={status?.error || result?.error || '读取当前检测结果'} icon={Activity} tone={status?.state === 'ready' ? 'emerald' : 'amber'} />
      <StatCard label="当前规则" value={status ? status.mode === 'forbidden' ? '禁止任何人出现' : '仅允许白名单' : '—'} detail={status?.timezone || '按每日时段执行'} icon={ShieldAlert} tone="indigo" />
      <StatCard label="区域人数" value={status?.count == null ? '—' : String(status.count)} detail={status?.alarm ? '区域内存在违规人员' : status?.state === 'ready' ? '当前未触发报警' : '尚无有效判定'} icon={UsersRound} tone={status?.alarm ? 'rose' : 'slate'} />
      <StatCard label="待核验人数" value={status?.pending_count == null ? '—' : String(status.pending_count)} detail="看不清人脸不会按超时报警" icon={UserCheck} tone="amber" />
    </div>
    {(status?.error || result?.error) && <p role="alert" className="text-sm text-amber-700 dark:text-amber-400">{status?.error || result?.error}</p>}
    {Boolean(status?.persons.length) && <Table><TableHeader><TableRow><TableHead>人员</TableHead><TableHead>身份状态</TableHead><TableHead>位置</TableHead><TableHead>报警</TableHead></TableRow></TableHeader>
      <TableBody>{status?.persons.map((person) => <TableRow key={person.track_id}><TableCell>{person.person_name || `人员 ${person.track_id}`}</TableCell><TableCell>{IDENTITIES[person.identity]}</TableCell><TableCell>{person.in_roi ? '警戒区域内' : '警戒区域外'}</TableCell><TableCell>{person.alarm ? person.reason === 'forbidden_time' ? '禁入时段有人' : '非白名单人员' : '—'}</TableCell></TableRow>)}</TableBody>
    </Table>}
  </div>
}
