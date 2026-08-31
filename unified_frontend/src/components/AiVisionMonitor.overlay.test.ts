// 文件说明：包含监控展示的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { buildAiVisionMonitorOverlay } from './AiVisionMonitor.overlay'

/**
 * 功能：实现 `assertEqual` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `actual`（unknown）：`actual` 对应的业务输入值
 *   - `expected`（unknown）：`expected` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`stringify`、`Error`。
 * 副作用/注意事项：校验或请求失败时会主动抛出异常。
 */
function assertEqual(actual: unknown, expected: unknown) {
  const actualJson = JSON.stringify(actual)
  const expectedJson = JSON.stringify(expected)
  if (actualJson !== expectedJson) {
    throw new Error(`expected ${expectedJson}, got ${actualJson}`)
  }
}

assertEqual(
  buildAiVisionMonitorOverlay({
    feature: 'detect_phone',
    value: { roi_pos: [[[10, 20], [110, 20], [110, 120], [10, 120]]] },
  }),
  {
    polygons: [[{ x: 10, y: 20 }, { x: 110, y: 20 }, { x: 110, y: 120 }, { x: 10, y: 120 }]],
    lines: [],
  },
)

assertEqual(
  buildAiVisionMonitorOverlay({
    feature: 'detect_human',
    value: {
      roi_pos: [[10, 20], [110, 20], [70, 120]],
      region: [10, 20, 110, 120],
    },
  }),
  {
    polygons: [[{ x: 10, y: 20 }, { x: 110, y: 20 }, { x: 70, y: 120 }]],
    lines: [],
  },
)

assertEqual(
  buildAiVisionMonitorOverlay({
    feature: 'detect_human',
    value: { roi_pos: [], region: [10, 20, 110, 120] },
  }),
  {
    polygons: [[{ x: 10, y: 20 }, { x: 110, y: 20 }, { x: 110, y: 120 }, { x: 10, y: 120 }]],
    lines: [],
  },
)

assertEqual(
  buildAiVisionMonitorOverlay({
    feature: 'detect_logistics_single_person',
    value: { roi_pos: [[[10, 20], [110, 20], [110, 120], [10, 120]]] },
  }),
  {
    polygons: [],
    lines: [],
  },
)

assertEqual(
  buildAiVisionMonitorOverlay({
    feature: 'blocks',
    value: { line_points: [[0.25, 0.5], [0.75, 0.5]] },
    imageSize: { width: 800, height: 600 },
  }),
  {
    polygons: [],
    lines: [[{ x: 200, y: 300 }, { x: 600, y: 300 }]],
  },
)
