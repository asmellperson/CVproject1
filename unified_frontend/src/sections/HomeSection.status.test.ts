// 文件说明：包含`HomeSection.status.test` 模块的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { getRecognitionAbilityText, getServiceStatusText } from './HomeSection.status'

/**
 * 功能：实现 `assertEqual` 对应的`HomeSection.status.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `actual`（unknown）：`actual` 对应的业务输入值
 *   - `expected`（unknown）：`expected` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Error`。
 * 副作用/注意事项：校验或请求失败时会主动抛出异常。
 */
function assertEqual(actual: unknown, expected: unknown) {
  if (actual !== expected) {
    throw new Error(`expected ${expected}, got ${actual}`)
  }
}

assertEqual(
  getServiceStatusText({
    online: true,
    running: false,
    hasError: true,
    cameraCount: 2,
  }),
  '服务在线，状态获取异常',
)

assertEqual(
  getServiceStatusText({
    online: true,
    running: false,
    hasError: false,
    cameraCount: 2,
  }),
  '已连接，未开始检测',
)

assertEqual(getRecognitionAbilityText({ modelLoaded: true, running: true }), '已启用')

assertEqual(getRecognitionAbilityText({ modelLoaded: true, running: false }), '已就绪')

assertEqual(getRecognitionAbilityText({ modelLoaded: false, running: true }), '待确认')
