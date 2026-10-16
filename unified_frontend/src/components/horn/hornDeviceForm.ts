import type { HornConnectionInput, HornDevice, HornState, HornWrite } from '@/lib/horns'
import type { DepartmentId } from '@/auth/permissions'

export const DEFAULT_HORN_SIP = { username: '10000', auth_id: '10000', port: 5060, password: '' }

export const HORN_STATE_LABELS: Record<HornState, string> = {
  online: '在线', offline: '离线', connecting: '连接中', failed: '连接失败',
  disabled: '已停用', stopping: '停止中', stopped: '已停止', pending: '等待同步', not_started: '服务未启动',
}

export function hornDraft(device: HornDevice | null, department: DepartmentId): HornWrite & { password: string } {
  return {
    name: device?.name ?? '', url: device?.url ?? '', username: device?.username ?? 'admin',
    department: device?.department ?? department,
    password: '', enable: device?.enable ?? false, description: device?.description ?? '',
    sip: device ? (device.sip ? { username: device.sip.username, auth_id: device.sip.auth_id, port: device.sip.port, password: '' } : null)
      : { ...DEFAULT_HORN_SIP },
  }
}

export function validateHornDraft(draft: HornWrite, editing: boolean, connectionOnly = false, sipPasswordSet = false): string | null {
  if (!connectionOnly && !draft.name.trim()) return '请输入设备名称。'
  if (!connectionOnly && draft.name.trim().length > 100) return '设备名称不能超过 100 个字符。'
  if (!draft.username.trim() || draft.username.trim().length > 100) return '请输入有效的设备用户名（最多 100 个字符）。'
  try {
    const url = new URL(draft.url.trim())
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash
      || /\s|\\/.test(draft.url.trim()) || draft.url.trim().length > 500) throw new Error('invalid URL')
  } catch {
    return '请输入 HTTP/HTTPS 设备地址，不要在地址中填写账号、密码或查询参数。'
  }
  if (!editing && !draft.password) return '新建设备必须输入密码。'
  if ((draft.password?.length ?? 0) > 200) return '密码不能超过 200 个字符。'
  if (!connectionOnly && (draft.description?.length ?? 0) > 10000) return '备注不能超过 10000 个字符。'
  if (!connectionOnly && draft.sip) {
    if (![draft.sip.username, draft.sip.auth_id].every((value) => /^[A-Za-z0-9_.+-]{1,64}$/.test(value))) {
      return 'SIP 账户和认证 ID 需填写 1–64 位字母、数字或 _ . + -。'
    }
    if (!Number.isInteger(draft.sip.port) || draft.sip.port < 1 || draft.sip.port > 65535) return '喇叭 SIP 本地端口必须为 1–65535 的整数。'
    if (!draft.sip.password && !sipPasswordSet) return '请输入 SIP 注册密码。'
    if ((draft.sip.password?.length ?? 0) > 128) return 'SIP 密码不能超过 128 个字符。'
  }
  return null
}

export function hornWritePayload(draft: HornWrite): HornWrite {
  return {
    name: draft.name.trim(), url: draft.url.trim(), username: draft.username.trim(),
    department: draft.department,
    enable: draft.enable, description: draft.description?.trim() || null,
    // 编辑留空时不发送 password，密码中的有效空格不做 trim。
    ...(draft.password ? { password: draft.password } : {}),
    ...(draft.sip === undefined ? {} : { sip: draft.sip ? {
      username: draft.sip.username, auth_id: draft.sip.auth_id, port: draft.sip.port,
      ...(draft.sip.password ? { password: draft.sip.password } : {}),
    } : null }),
  }
}

export function hornConnectionPayload(draft: HornWrite, id?: number): HornConnectionInput {
  return {
    ...(id === undefined ? {} : { horn_id: id }),
    url: draft.url.trim(), username: draft.username.trim(),
    ...(draft.password ? { password: draft.password } : {}),
  }
}
