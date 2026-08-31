// 文件说明：实现摄像头、状态管理的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

export type LogisticsCameraDraft = {
  name: string
  fps: string
  url: string
}

export type LogisticsCameraCreateInput = {
  name: string
  fps: number
  url: string
}

export const initialLogisticsCameraDraft: LogisticsCameraDraft = {
  name: '',
  fps: '5',
  url: '',
}

/**
 * 功能：检查或判断 `validateLogisticsCameraDraft` 对应的摄像头、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `draft`（LogisticsCameraDraft）：`draft` 对应的业务输入值
 * 返回：string | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/logisticsCameraCreateState.ts` 的 `normalizeLogisticsCameraDraft`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/LogisticsCameraCreateDialog.tsx` 的
 *         `LogisticsCameraCreateDialog` 调用本符号
 *   - 内部调用：`trim`、`Number`、`isInteger`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function validateLogisticsCameraDraft(draft: LogisticsCameraDraft): string | null {
  if (!draft.name.trim()) return '请输入摄像头名称。'
  const fps = Number(draft.fps)
  if (!Number.isInteger(fps) || fps < 1) return 'FPS 必须是大于等于 1 的整数。'
  if (!draft.url.trim()) return '请输入 RTSP 地址。'
  return null
}

/**
 * 功能：转换或规范化 `normalizeLogisticsCameraDraft` 对应的摄像头、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `draft`（LogisticsCameraDraft）：`draft` 对应的业务输入值
 * 返回：LogisticsCameraCreateInput；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsCameraCreateDialog.tsx` 的 `LogisticsCameraCreateDialog`
 *         调用本符号
 *   - 内部调用：`validateLogisticsCameraDraft`、`Error`、`trim`、`Number`。
 * 副作用/注意事项：校验或请求失败时会主动抛出异常。
 */
export function normalizeLogisticsCameraDraft(
  draft: LogisticsCameraDraft,
): LogisticsCameraCreateInput {
  const error = validateLogisticsCameraDraft(draft)
  if (error) throw new Error(error)
  return {
    name: draft.name.trim(),
    fps: Number(draft.fps),
    url: draft.url.trim(),
  }
}
