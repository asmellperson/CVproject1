import {
  BarChart3,
  Bell,
  Clock3,
  DoorOpen,
  LayoutDashboard,
  Radar,
  ScanFace,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export type NavItem = {
  id: string
  label: string
  icon: LucideIcon
  description?: string
  featureId?: string
  department?: string
}

export type NavDepartment = {
  name: string
  label: string
  items: NavItem[]
}

export type NavGroup = {
  id: string
  label: string
  items: NavItem[]
  departments?: NavDepartment[]
}

export const featureIcons: Record<string, LucideIcon> = {
  blocks: Radar,
  'detect-door': DoorOpen,
  'detect-face': ScanFace,
  'detect-human': Clock3,
  'detect-phone': Smartphone,
}

export const featureLabels: Record<string, string> = {
  blocks: '区域入侵检测',
  'detect-door': '大门开关异常检测',
  'detect-face': '人脸检测',
  'detect-human': '人员逗留检测',
  'detect-phone': '手机使用检测',
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
      { id: 'security-vlm', label: '安检流程规范检测', icon: ShieldAlert, description: '安检流程规范监控与 ROI 配置' },
      { id: 'guard-behavior', label: '保安行为规范检测', icon: ShieldCheck, description: '保安行为规范监控与配置' },
    ],
    departments: [
      {
        name: 'general-electric',
        label: '通用电气',
        items: [
          { id: 'human-detection@general-electric', featureId: 'human-detection', department: 'general_electric', label: '人员逗留检测', icon: Clock3, description: '人体逗留监控与配置入口' },
          { id: 'door-detection@general-electric', featureId: 'door-detection', department: 'general_electric', label: '大门开关异常检测', icon: DoorOpen, description: '大门开关状态监控与配置入口' },
        ],
      },
      {
        name: 'research-institute',
        label: '研究院',
        items: [
          { id: 'intrusion-detection@research-institute', featureId: 'intrusion-detection', department: 'research_institute', label: '区域入侵检测', icon: Radar, description: '区域入侵监控与配置入口' },
          { id: 'face-detection@research-institute', featureId: 'face-detection', department: 'research_institute', label: '人脸检测', icon: ScanFace, description: '人脸检测监控与配置入口' },
          { id: 'phone-detection@research-institute', featureId: 'phone-detection', department: 'research_institute', label: '手机使用检测', icon: Smartphone, description: '手机检测监控与配置入口' },
        ],
      },
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

export function getAllNavItems(): NavItem[] {
  const items: NavItem[] = []
  for (const group of navGroups) {
    items.push(...group.items)
    if (group.departments) {
      for (const dept of group.departments) {
        items.push(...dept.items)
      }
    }
  }
  return items
}

export const flatNavItems: NavItem[] = getAllNavItems()

export function findNavItem(id: string): NavItem | undefined {
  return flatNavItems.find((item) => item.id === id)
}