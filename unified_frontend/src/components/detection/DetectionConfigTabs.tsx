import type { ComponentProps, ReactNode } from 'react'
import { Volume2 } from 'lucide-react'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { DetectionConfigTab, DetectionConfigTabsList } from './DetectionConfigUi'
import { HornDeviceManager } from '@/components/horn/HornDeviceManager'

type Props = ComponentProps<typeof Tabs> & { tabs: ReactNode; tabListClassName?: string; showHorns?: boolean }

/** 检测配置保留各自业务面板；全局喇叭入口与设备管理只在这里挂载一次。 */
export function DetectionConfigTabs({ tabs, children, tabListClassName = 'lg:grid-cols-6', showHorns = true, ...props }: Props) {
  return (
    <Tabs {...props}>
      <DetectionConfigTabsList className={tabListClassName}>
        {tabs}
        {showHorns && <DetectionConfigTab value="horns" icon={Volume2}>喇叭设备</DetectionConfigTab>}
      </DetectionConfigTabsList>
      {children}
      {showHorns && <TabsContent value="horns" className="mt-0 space-y-5">
        <HornDeviceManager />
      </TabsContent>}
    </Tabs>
  )
}
