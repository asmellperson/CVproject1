// 文件说明：实现`nav` 模块相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import {
  BarChart3,
  Bell,
  Clock3,
  DoorOpen,
  History,
  LayoutDashboard,
  Radar,
  ScanFace,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  UserCog,
  UsersRound,
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
  children?: NavGroup[]
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
      { id: 'security-vlm-general-electric', label: '安检流程规范检测', icon: ShieldAlert, description: '通用电气安检流程规范监控与 ROI 配置' },
      { id: 'security-vlm-electronics-electrician', label: '安检流程规范检测', icon: ShieldAlert, description: '电子电工安检流程规范监控与 ROI 配置' },
      { id: 'security-vlm-electrical-components', label: '安检流程规范检测', icon: ShieldAlert, description: '电气部件安检流程规范监控与 ROI 配置' },
      { id: 'security-vlm-precious-metal-recycling', label: '安检流程规范检测', icon: ShieldAlert, description: '伟达公司安检流程规范监控与 ROI 配置' },
      { id: 'guard-behavior-general-electric', label: '保安行为规范检测', icon: ShieldCheck, description: '通用电气保安行为规范监控与配置' },
      { id: 'guard-behavior-electronics-electrician', label: '保安行为规范检测', icon: ShieldCheck, description: '电子电工保安行为规范监控与配置' },
      { id: 'intrusion-detection', label: '区域入侵检测', icon: Radar, description: '区域入侵监控与配置入口' },
      { id: 'door-detection', label: '大门开关异常检测', icon: DoorOpen, description: '大门开关状态监控与配置入口' },
      { id: 'face-detection', label: '人脸检测', icon: ScanFace, description: '人脸检测监控与配置入口' },
      { id: 'human-detection', label: '人员违规逗留检测', icon: Clock3, description: '人员违规逗留检测监控与配置入口' },
      { id: 'haoda-human-detection', label: '人员违规逗留检测', icon: Clock3, description: '皓达公司人员违规逗留检测监控与配置入口' },
      { id: 'logistics-single-person-detection', label: '物流通道单人检测', icon: UsersRound, description: '物流通道单人监控与配置入口' },
      { id: 'logistics-single-person-electronics-electrician-detection', label: '物流通道单人检测', icon: UsersRound, description: '电子电工物流通道单人监控与配置入口' },
      { id: 'logistics-single-person-electrical-components-detection', label: '物流通道单人检测', icon: UsersRound, description: '电气部件物流通道单人监控与配置入口' },
      { id: 'logistics-single-person-precious-metal-recycling-detection', label: '物流通道单人检测', icon: UsersRound, description: '伟达公司物流通道单人监控与配置入口' },
      { id: 'phone-detection', label: '手机使用检测', icon: Smartphone, description: '手机检测监控与配置入口' },
      
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
  {
    id: 'system',
    label: '系统管理',
    items: [
      { id: 'user-management', label: '用户管理', icon: UserCog, description: '添加用户、分配角色与事业部、管理账号状态' },
      { id: 'access-audit', label: '访问记录', icon: History, description: '查看最近访问视觉平台的用户' },
    ],
  },
]

export const flatNavItems: NavItem[] = navGroups.flatMap((group) => group.items)

/**
 * 功能：读取或查询 `findNavItem` 对应的`nav` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `id`（string）：`id` 对应业务对象的唯一标识
 * 返回：NavItem | undefined；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`find`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function findNavItem(id: string): NavItem | undefined {
  return flatNavItems.find((item) => item.id === id)
}
