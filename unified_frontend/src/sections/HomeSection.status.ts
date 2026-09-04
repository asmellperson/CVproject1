export type ServiceStatusTextInput = {
  online: boolean
  running: boolean
  hasError?: boolean
  featureKey?: string
  cameraCount: number
}

export type RecognitionAbilityTextInput = {
  modelLoaded: boolean
  running: boolean
}

export function getRecognitionAbilityText({
  modelLoaded,
  running,
}: RecognitionAbilityTextInput) {
  if (!modelLoaded) return '待确认'
  return running ? '已启用' : '已就绪'
}

export function getServiceStatusText({
  online,
  running,
  hasError = false,
  featureKey,
  cameraCount,
}: ServiceStatusTextInput) {
  if (!online) return '暂时不可用'
  if (hasError) return '服务在线，状态获取异常'
  if (running) return '正常检测中'
  if (featureKey && cameraCount <= 0) return '未配置检测摄像头'
  if (featureKey) return '服务在线，能力未启动'
  return '已连接，未开始检测'
}
