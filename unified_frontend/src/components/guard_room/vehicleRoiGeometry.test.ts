// 文件说明：包含感兴趣区域、几何计算的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import {
  imagePointsToVehicleRoi,
  parseVehicleRoiText,
  vehicleRoiToImagePoints,
} from './vehicleRoiGeometry'

/**
 * 功能：实现 `assertDeepEqual` 对应的感兴趣区域、几何计算逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `actual`（unknown）：`actual` 对应的业务输入值
 *   - `expected`（unknown）：`expected` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`stringify`、`Error`。
 * 副作用/注意事项：校验或请求失败时会主动抛出异常。
 */
function assertDeepEqual(actual: unknown, expected: unknown) {
  const actualText = JSON.stringify(actual)
  const expectedText = JSON.stringify(expected)
  if (actualText !== expectedText) {
    throw new Error(`expected ${expectedText}, got ${actualText}`)
  }
}

assertDeepEqual(
  vehicleRoiToImagePoints(
    [
      [0.25, 0.5],
      [1, 1],
    ],
    { width: 1920, height: 1080 },
  ),
  [
    { x: 480, y: 540 },
    { x: 1920, y: 1080 },
  ],
)

assertDeepEqual(
  imagePointsToVehicleRoi(
    [
      { x: 480, y: 540 },
      { x: 2500, y: -10 },
    ],
    { width: 1920, height: 1080 },
  ),
  [
    [0.25, 0.5],
    [1, 0],
  ],
)

assertDeepEqual(
  parseVehicleRoiText('0.1,0.2\nbad\n1.2,0.3\n0.4, 0.5'),
  [
    [0.1, 0.2],
    [0.4, 0.5],
  ],
)
