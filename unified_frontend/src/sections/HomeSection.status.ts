// 文件说明：实现`HomeSection.status` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

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

/**
 * 功能：读取或查询 `getRecognitionAbilityText` 对应的`HomeSection.status` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `props`（RecognitionAbilityTextInput）：React 组件属性对象；解构字段包括 modelLoaded, running
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `ServiceStatusCard` 调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function getRecognitionAbilityText({
  modelLoaded,
  running,
}: RecognitionAbilityTextInput) {
  if (!modelLoaded) return '待确认'
  return running ? '已启用' : '已就绪'
}

/**
 * 功能：读取或查询 `getServiceStatusText` 对应的`HomeSection.status` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `props`（ServiceStatusTextInput）：React 组件属性对象；解构字段包括 online, running, hasError, false, featureKey, cameraCount
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `ServiceStatusCard` 调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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
