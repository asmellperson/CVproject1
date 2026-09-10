import { LogisticsChannelSection } from '@/components/logistics_single_person/LogisticsChannelSection'
import type { LogisticsDepartment } from '@/components/logistics_single_person/types'

export function LogisticsSinglePersonDetectionSection({ department }: { department: LogisticsDepartment }) {
  return (
    <LogisticsChannelSection
      key={department}
      department={department}
      feature="detect_logistics_single_person"
      title="物流通道单人检测监控与配置"
    />
  )
}

export default LogisticsSinglePersonDetectionSection
