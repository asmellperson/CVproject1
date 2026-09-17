import type { SitePolicyValues } from './types'

type NumericKey = { [K in keyof SitePolicyValues]: SitePolicyValues[K] extends number ? K : never }[keyof SitePolicyValues]
export type PolicyField = { key: NumericKey; label: string; min: number; max?: number; step: number; integer?: boolean; exclusiveMin?: boolean }
// 这里只描述控件边界；新建策略的默认值始终由服务端提供。
export const POLICY_GROUPS: Array<{ title: string; fields: PolicyField[] }> = [
  { title: '人体与制服', fields: [
    { key: 'cap_interval', label: '处理间隔（秒）', min: 0, step: .01, exclusiveMin: true },
    { key: 'person_confidence_threshold', label: '人体置信度', min: 0, max: 1, step: .01 },
    { key: 'uniform_confidence_threshold', label: '制服正类概率阈值', min: 0, max: 1, step: .01 },
    { key: 'model_iou_threshold', label: '模型 IoU 阈值', min: 0, max: 1, step: .01 },
    { key: 'person_phone_imgsz', label: '人体检测输入尺寸', min: 32, max: 4096, step: 1, integer: true },
    { key: 'guard_hold_seconds', label: '保安身份保持（秒）', min: 0, step: .1 },
    { key: 'absent_alarm_seconds', label: '离岗持续阈值（秒）', min: 0, step: .1, exclusiveMin: true },
    { key: 'state_ttl_seconds', label: '轨迹状态保留（秒）', min: 0, step: .1, exclusiveMin: true },
  ] },
  { title: '手机使用', fields: [
    { key: 'phone_confidence_threshold', label: '手机置信度', min: 0, max: 1, step: .01 },
    { key: 'phone_crop_imgsz', label: '手机裁图输入尺寸', min: 32, max: 4096, step: 1, integer: true },
    { key: 'phone_seconds', label: '手机使用持续阈值（秒）', min: 0, step: .1, exclusiveMin: true },
    { key: 'phone_window_seconds', label: '手机命中窗口（秒）', min: 0, step: .1, exclusiveMin: true },
    { key: 'phone_min_hits_in_window', label: '窗口最少命中次数', min: 1, step: 1, integer: true },
    { key: 'phone_grace_seconds', label: '手机漏检宽限（秒）', min: 0, step: .1 },
    { key: 'phone_near_person_px', label: '手机与人体距离（像素）', min: 0, step: 1 },
    { key: 'phone_near_head_px', label: '手机与头部距离（像素）', min: 0, step: 1 },
  ] },
  { title: '趴睡识别', fields: [
    { key: 'pose_imgsz', label: '姿态输入尺寸', min: 32, max: 4096, step: 1, integer: true },
    { key: 'prone_sleep_seconds', label: '趴睡持续阈值（秒）', min: 0, step: .1, exclusiveMin: true },
    { key: 'static_motion_threshold', label: '静止位移阈值', min: 0, step: .1 },
    { key: 'prone_head_down_ratio_threshold', label: '低头比例阈值', min: 0, max: 1, step: .01 },
    { key: 'prone_bbox_height_ratio_threshold', label: '人体框高度比例阈值', min: 0, max: 1, step: .01 },
    { key: 'prone_consecutive_frames', label: '趴睡连续帧数', min: 1, step: 1, integer: true },
  ] },
  { title: '车辆出厂检查', fields: [
    { key: 'vehicle_confidence_threshold', label: '车辆置信度', min: 0, max: 1, step: .01 },
    { key: 'vehicle_imgsz', label: '车辆输入尺寸', min: 32, max: 4096, step: 1, integer: true },
    { key: 'vehicle_occlusion_seconds', label: '车辆消失确认（秒）', min: 0, step: .1, exclusiveMin: true },
    { key: 'vehicle_near_px', label: '保安靠近车辆距离（像素）', min: 0, step: 1 },
    { key: 'vehicle_direction_min_delta_ratio', label: '离场方向最小位移比例', min: 0, max: 1, step: .01 },
    { key: 'vehicle_reassociate_seconds', label: '已检查车辆重关联窗口（秒）', min: 0, step: .1 },
  ] },
]

export function hasInvalidPolicyNumber(value: SitePolicyValues): boolean {
  return POLICY_GROUPS.some((group) => group.fields.some((field) => {
    const number = value[field.key]
    return !Number.isFinite(number) || number < field.min
      || (field.exclusiveMin === true && number === field.min)
      || (field.max !== undefined && number > field.max)
      || (field.integer === true && !Number.isInteger(number))
  }))
}
