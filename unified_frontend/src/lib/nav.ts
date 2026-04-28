import {
  BarChart3,
  Bell,
  Clock3,
  DoorOpen,
  LayoutDashboard,
  Radar,
  ScanFace,
  ShieldCheck,
  Smartphone,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export type NavItem = {
  id: string
  label: string
  icon: LucideIcon
  description?: string
}

export type NavGroup = {
  id: string
  label: string
  items: NavItem[]
}

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
    items: [
      { id: 'guard-behavior', label: '保安行为规范检测', icon: ShieldCheck, description: '保安行为规范监控与配置' },
      { id: 'intrusion-detection', label: '区域入侵检测', icon: Radar, description: '区域入侵监控与配置入口' },
      { id: 'door-detection', label: '大门检测', icon: DoorOpen, description: '大门状态监控与配置入口' },
      { id: 'face-detection', label: '人脸检测', icon: ScanFace, description: '人脸检测监控与配置入口' },
      { id: 'human-detection', label: '人体逗留检测', icon: Clock3, description: '人体逗留监控与配置入口' },
      { id: 'phone-detection', label: '手机检测', icon: Smartphone, description: '手机检测监控与配置入口' },
    ],
  },
  { 
    id: 'data',
    label: '数据中心',
    items: [
      { id: 'alarms', label: '报警记录', icon: Bell, description: '告警事件列表' },
      { id: 'statistics', label: '统计分析', icon: BarChart3, description: '指标与趋势' },
    ],
  },
]

export const flatNavItems: NavItem[] = navGroups.flatMap((group) => group.items)

export function findNavItem(id: string): NavItem | undefined {
  return flatNavItems.find((item) => item.id === id)
}
