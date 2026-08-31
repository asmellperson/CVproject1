// 文件说明：实现监控展示的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

export type OverlayPoint = {
  x: number
  y: number
}

export type OverlayShape = {
  polygons: OverlayPoint[][]
  lines: [OverlayPoint, OverlayPoint][]
}

type ImageSize = {
  width: number
  height: number
}

/**
 * 功能：转换或规范化 `toNumber` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Number`、`isFinite`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function toNumber(value: unknown) {
  const next = Number(value)
  return Number.isFinite(next) ? next : 0
}

/**
 * 功能：实现 `pointFromUnknown` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 *   - `imageSize?`（ImageSize）：`imageSize` 对应的数量或大小
 * 返回：OverlayPoint | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.overlay.ts` 的 `normalizePolygons`
 *         调用本符号；`unified_frontend/src/components/AiVisionMonitor.overlay.ts` 的 `normalizeLine` 调用本符号
 *   - 内部调用：`isArray`、`toNumber`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function pointFromUnknown(value: unknown, imageSize?: ImageSize): OverlayPoint | null {
  if (!Array.isArray(value) || value.length < 2) return null
  let x = toNumber(value[0])
  let y = toNumber(value[1])
  if (imageSize && x >= 0 && x <= 1 && y >= 0 && y <= 1) {
    x *= imageSize.width
    y *= imageSize.height
  }
  return { x, y }
}

/**
 * 功能：转换或规范化 `rectToPolygon` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `rect`（unknown[]）：`rect` 对应的业务输入值
 * 返回：OverlayPoint[]；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.overlay.ts` 的 `normalizePolygons` 调用本符号
 *   - 内部调用：`map`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function rectToPolygon(rect: unknown[]): OverlayPoint[] {
  const [x1, y1, x2, y2] = rect.map(toNumber)
  return [
    { x: x1, y: y1 },
    { x: x2, y: y1 },
    { x: x2, y: y2 },
    { x: x1, y: y2 },
  ]
}

/**
 * 功能：转换或规范化 `normalizePolygons` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 * 返回：OverlayPoint[][]；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.overlay.ts` 的 `buildAiVisionMonitorOverlay` 调用本符号
 *   - 内部调用：`isArray`、`every`、`rectToPolygon`、`map`、`pointFromUnknown`、`filter`、`Boolean`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function normalizePolygons(value: unknown): OverlayPoint[][] {
  if (!Array.isArray(value) || value.length === 0) return []
  if (value.length >= 4 && value.every((item) => typeof item === 'number')) {
    return [rectToPolygon(value)]
  }

  const first = value[0]
  const polygonInputs = Array.isArray(first) && first.length >= 2 && typeof first[0] === 'number' ? [value] : value
  if (!Array.isArray(polygonInputs)) return []

  return polygonInputs
    .map((polygon) => {
      if (!Array.isArray(polygon)) return []
      return polygon.map((point) => pointFromUnknown(point)).filter((point): point is OverlayPoint => Boolean(point))
    })
    .filter((polygon) => polygon.length >= 2)
}

/**
 * 功能：转换或规范化 `normalizeLine` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 *   - `imageSize?`（ImageSize）：`imageSize` 对应的数量或大小
 * 返回：[OverlayPoint, OverlayPoint][]；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.overlay.ts` 的 `buildAiVisionMonitorOverlay` 调用本符号
 *   - 内部调用：`isArray`、`slice`、`every`、`pointFromUnknown`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function normalizeLine(value: unknown, imageSize?: ImageSize): [OverlayPoint, OverlayPoint][] {
  if (!Array.isArray(value) || value.length === 0) return []
  if (value.length >= 4 && value.slice(0, 4).every((item) => typeof item === 'number')) {
    const p1 = pointFromUnknown([value[0], value[1]], imageSize)
    const p2 = pointFromUnknown([value[2], value[3]], imageSize)
    return p1 && p2 ? [[p1, p2]] : []
  }
  if (value.length < 2) return []
  const p1 = pointFromUnknown(value[0], imageSize)
  const p2 = pointFromUnknown(value[1], imageSize)
  return p1 && p2 ? [[p1, p2]] : []
}

/**
 * 功能：创建或构建 `buildAiVisionMonitorOverlay` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 feature, value, imageSize, feature, string, value, Record, string
 * 返回：OverlayShape；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor` 调用本符号
 *   - 内部调用：`normalizePolygons`、`isArray`、`normalizeLine`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function buildAiVisionMonitorOverlay({
  feature,
  value,
  imageSize,
}: {
  feature: string
  value: Record<string, unknown> | null | undefined
  imageSize?: ImageSize
}): OverlayShape {
  const configValue = value || {}
  const region = configValue.region
  const roiPos = configValue.roi_pos
  const roiPolygons = normalizePolygons(roiPos)
  const polygons = feature === 'detect_logistics_single_person'
    || feature === 'detect_logistics_single_person_electronics_electrician'
    || feature === 'detect_logistics_single_person_electrical_components'
    || feature === 'detect_logistics_single_person_precious_metal_recycling'
    ? []
    : (feature === 'detect_human' || feature === 'detect_human_haoda') && roiPolygons.length === 0 && Array.isArray(region) && region.length >= 4
      ? normalizePolygons(region)
      : roiPolygons

  return {
    polygons,
    lines: feature === 'blocks' ? normalizeLine(configValue.line_points, imageSize) : [],
  }
}
