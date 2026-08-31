// 文件说明：包含接口访问的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { guardRoomSiteCameraFrameUrl, guardRoomSitesPath } from './api'

/**
 * 功能：实现 `assertEndsWith` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `actual`（string）：`actual` 对应的业务输入值
 *   - `expected`（string）：`expected` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`endsWith`、`Error`。
 * 副作用/注意事项：校验或请求失败时会主动抛出异常。
 */
function assertEndsWith(actual: string, expected: string) {
  if (!actual.endsWith(expected)) {
    throw new Error(`expected ${actual} to end with ${expected}`)
  }
}

assertEndsWith(
  guardRoomSiteCameraFrameUrl(12, 'cam2', 123),
  '/api/sites/12/cameras/cam2/frame.jpg?t=123',
)

assertEndsWith(
  guardRoomSiteCameraFrameUrl(12, 'cam 2'),
  '/api/sites/12/cameras/cam%202/frame.jpg',
)

if (guardRoomSitesPath('electronics_electrician') !== '/sites?department=electronics_electrician') {
  throw new Error('expected electronics department site path to include department query')
}
