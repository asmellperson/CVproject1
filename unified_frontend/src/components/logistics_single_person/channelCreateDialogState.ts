// 文件说明：实现状态管理的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

export type ChannelCreateDialogState = {
  open: boolean
  name: string
  error: string
  submitting: boolean
}

export type ChannelCreateDialogAction =
  | { type: 'open' }
  | { type: 'close' }
  | { type: 'change-name'; name: string }
  | { type: 'submit' }
  | { type: 'success' }
  | { type: 'failure'; error: string }

export const initialChannelCreateDialogState: ChannelCreateDialogState = {
  open: false,
  name: '',
  error: '',
  submitting: false,
}

/**
 * 功能：创建或构建 `channelCreateDialogReducer` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `state`（ChannelCreateDialogState）：`state` 对应的业务输入值
 *   - `action`（ChannelCreateDialogAction）：`action` 对应的业务输入值
 * 返回：ChannelCreateDialogState；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function channelCreateDialogReducer(
  state: ChannelCreateDialogState,
  action: ChannelCreateDialogAction,
): ChannelCreateDialogState {
  switch (action.type) {
    case 'open':
      return { ...state, open: true, error: '' }
    case 'close':
      return initialChannelCreateDialogState
    case 'change-name':
      return { ...state, name: action.name, error: '' }
    case 'submit':
      return { ...state, error: '', submitting: true }
    case 'success':
      return initialChannelCreateDialogState
    case 'failure':
      return { ...state, error: action.error, submitting: false }
  }
}
