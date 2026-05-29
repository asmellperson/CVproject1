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
import { getAiVisionDepartments, getAiVisionDepartmentFeatures } from './aivision'

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
  'intrusion-detection': Radar,
  'human-detection': Clock3,
  'phone-detection': Smartphone,
  'door-detection': DoorOpen,
  'face-detection': ScanFace,
}

export const featureLabels: Record<string, string> = {
  blocks: '区域入侵检测',
  'detect-door': '大门开关异常检测',
  'detect-face': '人脸检测',
  'detect-human': '人员逗留检测',
  'detect-phone': '手机使用检测',
  'intrusion-detection': '区域入侵检测',
  'human-detection': '人员逗留检测',
  'phone-detection': '手机使用检测',
  'door-detection': '大门开关异常检测',
  'face-detection': '人脸检测',
}

export function getFeatureIcon(featureName: string): LucideIcon {
  return featureIcons[featureName] || Radar
}

export function getFeatureLabel(featureName: string): string {
  return featureLabels[featureName] || featureName
}

// 硬编码的 fallback 数据
export const navGroupsFallback: NavGroup[] = [
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
          { id: 'phone-detection@research-institute', featureId: 'phone-detection', department: 'general_electric', label: '手机使用检测', icon: Smartphone, description: '手机检测监控与配置入口' },

        ],
      },
      {
        name: 'research-institute',
        label: '研究院',
        items: [
                    { id: 'door-detection@general-electric', featureId: 'door-detection', department: 'research_institute', label: '大门开关异常检测', icon: DoorOpen, description: '大门开关状态监控与配置入口' },
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

// 默认导出还是用 fallback 数据
export const navGroups: NavGroup[] = navGroupsFallback

// 后端特征名到前端页面ID的映射
const backendFeatureToFrontendPage: Record<string, string> = {
  'blocks': 'intrusion-detection',
  'detect_door': 'door-detection',
  'detect_face': 'face-detection',
  'detect_human': 'human-detection',
  'detect_phone': 'phone-detection',
}

// 从后端动态构建导航数据
export async function buildDynamicNavGroups(): Promise<NavGroup[]> {
  // 先复制静态部分
  const staticGroups: NavGroup[] = [
    {
      id: 'overview',
      label: '',
      items: [
        { id: 'overview', label: '平台总览', icon: LayoutDashboard, description: '平台总览' },
      ],
    },
  ]

  try {
    // 从后端获取部门列表
    const departments = await getAiVisionDepartments()

    // 为每个部门构建导航项
    const navDepartments: NavDepartment[] = []
    for (const dept of departments) {
      try {
        // 获取该部门的功能列表
        const features = await getAiVisionDepartmentFeatures(dept.name)
        
        // 构建部门的功能项
        const items: NavItem[] = features.map((feature) => {
          const featureName = feature.name
          // 映射到正确的前端页面ID
          const pageId = backendFeatureToFrontendPage[featureName] || featureName.replace('detect_', '').replace('_', '-')
          return {
            id: `${pageId}@${dept.name.replace('_', '-')}`,
            featureId: pageId,
            department: dept.name,
            label: feature.display_name || getFeatureLabel(pageId),
            icon: getFeatureIcon(pageId),
            description: `${feature.display_name || getFeatureLabel(pageId)} 监控与配置`,
          }
        })

        navDepartments.push({
          name: dept.name.replace('_', '-'),
          label: dept.display_name,
          items,
        })
      } catch (error) {
        console.error(`Failed to load features for department ${dept.name}:`, error)
        // 跳过加载失败的部门
      }
    }

    // 添加能力中心导航组（包含静态项和动态部门项）
    staticGroups.push({
      id: 'modules',
      label: '能力中心',
      items: [
        { id: 'security-vlm', label: '安检流程规范检测', icon: ShieldAlert, description: '安检流程规范监控与 ROI 配置' },
        { id: 'guard-behavior', label: '保安行为规范检测', icon: ShieldCheck, description: '保安行为规范监控与配置' },
      ],
      departments: navDepartments.length > 0 ? navDepartments : undefined,
    })
  } catch (error) {
    console.error('Failed to load dynamic navigation, using fallback:', error)
    // 如果加载失败，使用 fallback 的部门数据
    staticGroups.push(navGroupsFallback[1])
  }

  // 添加数据中心导航组
  staticGroups.push(navGroupsFallback[2])

  return staticGroups
}

// 辅助函数 - 从导航组获取所有导航项
export function getAllNavItems(groups?: NavGroup[]): NavItem[] {
  const useGroups = groups || navGroups
  const items: NavItem[] = []
  for (const group of useGroups) {
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

// 查找导航项 - 支持传入特定的导航组
export function findNavItem(id: string, groups?: NavGroup[]): NavItem | undefined {
  const useGroups = groups || navGroups
  const allItems = getAllNavItems(useGroups)
  return allItems.find((item) => item.id === id)
}
