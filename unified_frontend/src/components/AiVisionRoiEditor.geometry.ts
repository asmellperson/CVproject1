// 文件说明：实现感兴趣区域、几何计算的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

type Size = {
  width: number
  height: number
}

type Rect = Size & {
  left: number
  top: number
}

type Point = {
  x: number
  y: number
}

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
 * 功能：实现 `containedImageBox` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `overlayRect`（Rect）：`overlayRect` 对应的业务输入值
 *   - `imageSize`（Size）：`imageSize` 对应的数量或大小
 * 返回：Rect；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`min`、`max`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function containedImageBox(overlayRect: Rect, imageSize: Size): Rect {
  const scale = Math.min(
    overlayRect.width / Math.max(1, imageSize.width),
    overlayRect.height / Math.max(1, imageSize.height),
  )
  const width = imageSize.width * scale
  const height = imageSize.height * scale

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
 * 返回：Point；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`containedImageBox`、`clamp`、`max`。
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
}): Point {
  const imageBox = containedImageBox(overlayRect, imageSize)

  return {
    x: clamp((clientX - imageBox.left) * (imageSize.width / Math.max(1, imageBox.width)), 0, imageSize.width),
    y: clamp((clientY - imageBox.top) * (imageSize.height / Math.max(1, imageBox.height)), 0, imageSize.height),
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
 *   - 内部调用：`containedImageBox`、`max`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function imagePixelsPerRenderedPixel(overlayRect: Rect, imageSize: Size) {
  const imageBox = containedImageBox(overlayRect, imageSize)
  return imageSize.width / Math.max(1, imageBox.width)
}
