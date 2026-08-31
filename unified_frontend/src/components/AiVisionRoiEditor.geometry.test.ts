// 文件说明：包含感兴趣区域、几何计算的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { clientPointToImagePoint } from './AiVisionRoiEditor.geometry'

/**
 * 功能：实现 `assertPoint` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `actual`（{ x: number; y: number }）：`actual` 对应的业务输入值
 *   - `expected`（{ x: number; y: number }）：`expected` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`abs`、`Error`、`expected`、`got`。
 * 副作用/注意事项：校验或请求失败时会主动抛出异常。
 */
function assertPoint(actual: { x: number; y: number }, expected: { x: number; y: number }) {
  if (Math.abs(actual.x - expected.x) > 0.000001 || Math.abs(actual.y - expected.y) > 0.000001) {
    throw new Error(`expected (${expected.x}, ${expected.y}), got (${actual.x}, ${actual.y})`)
  }
}

const point = clientPointToImagePoint({
  clientX: 500,
  clientY: 250,
  overlayRect: { left: 0, top: 0, width: 1000, height: 500 },
  imageSize: { width: 800, height: 600 },
})

assertPoint(point, { x: 400, y: 300 })

const clamped = clientPointToImagePoint({
  clientX: 50,
  clientY: 250,
  overlayRect: { left: 0, top: 0, width: 1000, height: 500 },
  imageSize: { width: 800, height: 600 },
})

assertPoint(clamped, { x: 0, y: 300 })
