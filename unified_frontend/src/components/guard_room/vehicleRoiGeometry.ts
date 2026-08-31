// 文件说明：实现感兴趣区域、几何计算的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

export type Size = {
  width: number
  height: number
}

export type Rect = Size & {
  left: number
  top: number
}

export type ImagePoint = {
  x: number
  y: number
}

export type VehicleRoiPoint = [number, number]

/**
 * 功能：实现 `clamp` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（number）：待转换、校验或写入的值
 *   - `min`（number）：`min` 对应的业务输入值
 *   - `max`（number）：`max` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`max`、`min`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

/**
 * 功能：实现 `roundRatio` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（number）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/guard_room/vehicleRoiGeometry.ts` 的 `imagePointsToVehicleRoi` 调用本符号
 *   - 内部调用：`round`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function roundRatio(value: number) {
  return Math.round(value * 1_000_000) / 1_000_000
}

/**
 * 功能：实现 `safeImageSize` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `size`（Size）：`size` 对应的数量或大小
 * 返回：Size；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/guard_room/vehicleRoiGeometry.ts` 的 `vehicleRoiToImagePoints`
 *         调用本符号；`unified_frontend/src/components/guard_room/vehicleRoiGeometry.ts` 的 `imagePointsToVehicleRoi`
 *         调用本符号；`unified_frontend/src/components/guard_room/vehicleRoiGeometry.ts` 的 `containedImageBox`
 *         调用本符号；`unified_frontend/src/components/guard_room/vehicleRoiGeometry.ts` 的 `clientPointToImagePoint` 调用本符号；另有 1 处静态调用
 *   - 内部调用：`max`、`isFinite`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function safeImageSize(size: Size): Size {
  return {
    width: Math.max(1, Number.isFinite(size.width) ? size.width : 1),
    height: Math.max(1, Number.isFinite(size.height) ? size.height : 1),
  }
}

/**
 * 功能：转换或规范化 `normalizeVehicleRoi` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `points`（VehicleRoiPoint[] | undefined）：`points` 对应的业务输入值
 * 返回：VehicleRoiPoint[]；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/guard_room/vehicleRoiGeometry.ts` 的 `vehicleRoiToImagePoints`
 *         调用本符号；`unified_frontend/src/components/guard_room/vehicleRoiGeometry.ts` 的 `formatVehicleRoiText` 调用本符号
 *   - 内部调用：`return`、`filter`、`isArray`、`map`、`clamp`、`Number`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function normalizeVehicleRoi(points: VehicleRoiPoint[] | undefined): VehicleRoiPoint[] {
  return (points || [])
    .filter((point) => Array.isArray(point) && point.length >= 2)
    .map(([x, y]) => [clamp(Number(x) || 0, 0, 1), clamp(Number(y) || 0, 0, 1)] as VehicleRoiPoint)
}

/**
 * 功能：转换或规范化 `vehicleRoiToImagePoints` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `points`（VehicleRoiPoint[] | undefined）：`points` 对应的业务输入值
 *   - `size`（Size）：`size` 对应的数量或大小
 * 返回：ImagePoint[]；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`safeImageSize`、`normalizeVehicleRoi`、`map`、`round`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function vehicleRoiToImagePoints(points: VehicleRoiPoint[] | undefined, size: Size): ImagePoint[] {
  const imageSize = safeImageSize(size)
  return normalizeVehicleRoi(points).map(([x, y]) => ({
    x: Math.round(x * imageSize.width),
    y: Math.round(y * imageSize.height),
  }))
}

/**
 * 功能：转换或规范化 `imagePointsToVehicleRoi` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `points`（ImagePoint[]）：`points` 对应的业务输入值
 *   - `size`（Size）：`size` 对应的数量或大小
 * 返回：VehicleRoiPoint[]；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`safeImageSize`、`map`、`roundRatio`、`clamp`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function imagePointsToVehicleRoi(points: ImagePoint[], size: Size): VehicleRoiPoint[] {
  const imageSize = safeImageSize(size)
  return points.map((point) => [
    roundRatio(clamp(point.x / imageSize.width, 0, 1)),
    roundRatio(clamp(point.y / imageSize.height, 0, 1)),
  ])
}

/**
 * 功能：转换或规范化 `parseVehicleRoiText` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `text`（string）：`text` 对应的业务输入值
 * 返回：VehicleRoiPoint[]；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/ConfigSection.tsx` 的 `ConfigSection` 调用本符号
 *   - 内部调用：`split`、`map`、`trim`、`filter`、`Number`、`isFinite`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function parseVehicleRoiText(text: string): VehicleRoiPoint[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [xRaw, yRaw] = line.split(',').map((item) => Number(item.trim()))
      return [xRaw, yRaw] as VehicleRoiPoint
    })
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y) && x >= 0 && x <= 1 && y >= 0 && y <= 1)
}

/**
 * 功能：转换或规范化 `formatVehicleRoiText` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `points`（VehicleRoiPoint[] | undefined）：`points` 对应的业务输入值
 * 返回：string；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/ConfigSection.tsx` 的 `ConfigSection` 调用本符号
 *   - 内部调用：`normalizeVehicleRoi`、`map`、`join`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function formatVehicleRoiText(points: VehicleRoiPoint[] | undefined): string {
  return normalizeVehicleRoi(points)
    .map(([x, y]) => `${x},${y}`)
    .join('\n')
}

/**
 * 功能：实现 `polygonArea` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `points`（ImagePoint[]）：`points` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`reduce`、`abs`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function polygonArea(points: ImagePoint[]) {
  if (points.length < 3) return 0
  const area = points.reduce((sum, point, index) => {
    const next = points[(index + 1) % points.length]
    return sum + point.x * next.y - next.x * point.y
  }, 0)
  return Math.abs(area) / 2
}

/**
 * 功能：实现 `pointDistance` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `a`（ImagePoint）：`a` 对应的业务输入值
 *   - `b`（ImagePoint）：`b` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`hypot`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function pointDistance(a: ImagePoint, b: ImagePoint) {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

/**
 * 功能：实现 `containedImageBox` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `overlayRect`（Rect）：`overlayRect` 对应的业务输入值
 *   - `imageSize`（Size）：`imageSize` 对应的数量或大小
 * 返回：Rect；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`safeImageSize`、`min`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function containedImageBox(overlayRect: Rect, imageSize: Size): Rect {
  const safeSize = safeImageSize(imageSize)
  const scale = Math.min(
    overlayRect.width / safeSize.width,
    overlayRect.height / safeSize.height,
  )
  const width = safeSize.width * scale
  const height = safeSize.height * scale

  return {
    left: overlayRect.left + (overlayRect.width - width) / 2,
    top: overlayRect.top + (overlayRect.height - height) / 2,
    width,
    height,
  }
}

/**
 * 功能：转换或规范化 `clientPointToImagePoint` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 clientX, clientY, overlayRect, imageSize, clientX, number, clientY, number
 * 返回：ImagePoint；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`safeImageSize`、`containedImageBox`、`clamp`、`max`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function clientPointToImagePoint({
  clientX,
  clientY,
  overlayRect,
  imageSize,
}: {
  clientX: number
  clientY: number
  overlayRect: Rect
  imageSize: Size
}): ImagePoint {
  const safeSize = safeImageSize(imageSize)
  const imageBox = containedImageBox(overlayRect, safeSize)

  return {
    x: clamp((clientX - imageBox.left) * (safeSize.width / Math.max(1, imageBox.width)), 0, safeSize.width),
    y: clamp((clientY - imageBox.top) * (safeSize.height / Math.max(1, imageBox.height)), 0, safeSize.height),
  }
}

/**
 * 功能：实现 `imagePixelsPerRenderedPixel` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `overlayRect`（Rect）：`overlayRect` 对应的业务输入值
 *   - `imageSize`（Size）：`imageSize` 对应的数量或大小
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`safeImageSize`、`containedImageBox`、`max`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function imagePixelsPerRenderedPixel(overlayRect: Rect, imageSize: Size) {
  const safeSize = safeImageSize(imageSize)
  const imageBox = containedImageBox(overlayRect, safeSize)
  return safeSize.width / Math.max(1, imageBox.width)
}
