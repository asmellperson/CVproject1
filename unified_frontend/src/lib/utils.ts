// 文件说明：实现`utils` 模块相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/**
 * 功能：实现 `cn` 对应的`utils` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `...inputs`（ClassValue[]）：`...inputs` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ui/accordion.tsx` 的 `AccordionItem`
 *         调用本符号；`unified_frontend/src/components/ui/accordion.tsx` 的 `AccordionTrigger`
 *         调用本符号；`unified_frontend/src/components/ui/accordion.tsx` 的 `AccordionContent`
 *         调用本符号；`unified_frontend/src/components/ui/alert-dialog.tsx` 的 `AlertDialogOverlay` 调用本符号；另有 253 处静态调用
 *   - 内部调用：`twMerge`、`clsx`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
