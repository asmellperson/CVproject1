import {
  BarChart3,
  Bell,
  Clock3,
  DoorOpen,
  History,
  LayoutDashboard,
  MessageSquareText,
  Radar,
  ScanFace,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Truck,
  UserCog,
  UsersRound,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { DepartmentId, PageId } from '@/auth/permissions'

export type NavItem = {
  id: PageId
  label: string
  icon: LucideIcon
  description?: string
}

export type NavGroup = {
  id: string
  label: string
  items: NavItem[]
  children?: NavGroup[]
  department?: DepartmentId
}

export const detectionNavItems: NavItem[] = [
  { id: 'security-fence', label: '警戒围栏', icon: ShieldCheck, description: '每日时段警戒、独立白名单与人员身份监控' },
  { id: 'visual-language-detection', label: '指令驱动智慧安防', icon: MessageSquareText, description: '通过自然语言定义监控任务，持续理解视频场景，并在目标事件发生时自动触发告警。' },
  { id: 'security-vlm', label: '安检流程规范检测', icon: ShieldAlert, description: '安检流程规范监控与 ROI 配置' },
  { id: 'guard-behavior', label: '保安行为规范检测', icon: ShieldCheck, description: '保安行为规范监控与配置' },
  { id: 'intrusion-detection', label: '区域入侵检测', icon: Radar, description: '区域入侵监控与配置入口' },
  { id: 'door-detection', label: '大门开关异常检测', icon: DoorOpen, description: '大门开关状态监控与配置入口' },
  { id: 'face-detection', label: '人脸逗留检测', icon: ScanFace, description: '人脸逗留检测监控与配置入口' },
  { id: 'face-recognition', label: '人脸身份识别', icon: ScanFace, description: '人脸身份识别、识别记录与配置' },
  { id: 'human-detection', label: '人员违规逗留检测', icon: Clock3, description: '人员违规逗留检测监控与配置入口' },
  { id: 'logistics-single-person', label: '物流通道单人检测', icon: UsersRound, description: '物流通道单人监控与配置入口' },
  { id: 'phone-detection', label: '手机使用检测', icon: Smartphone, description: '手机检测监控与配置入口' },
  { id: 'agv-person-check', label: 'AGV无人运货检测', icon: Truck, description: '实时画面与 AGV 请求触发检测配置' },
]

export const navGroups: NavGroup[] = [
  {
    id: 'overview',
    label: '',
    items: [
      { id: 'overview', label: '平台总览', icon: LayoutDashboard, description: '平台总览' },
    ],
  },
  {
    id: 'modules',
    label: '能力中心',
    items: detectionNavItems,
  },
  {
    id: 'data',
    label: '数据中心',
    items: [
      { id: 'alarms', label: '报警记录', icon: Bell, description: '告警事件列表' },
      { id: 'statistics', label: '统计分析', icon: BarChart3, description: '指标与趋势' },
    ],
  },
  {
    id: 'system',
    label: '系统管理',
    items: [
      { id: 'user-management', label: '用户管理', icon: UserCog, description: '添加用户、分配角色与事业部、管理账号状态' },
      { id: 'feature-management', label: '功能分配', icon: ShieldCheck, description: '配置各事业部可访问的检测功能' },
      { id: 'access-audit', label: '访问记录', icon: History, description: '查看最近访问视觉平台的用户' },
    ],
  },
]

export const flatNavItems: NavItem[] = navGroups.flatMap((group) => group.items)

export function findNavItem(id: string): NavItem | undefined {
  return flatNavItems.find((item) => item.id === id)
}
