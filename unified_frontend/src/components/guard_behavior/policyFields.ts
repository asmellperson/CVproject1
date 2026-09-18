import type { SitePolicyValues } from './types'

export type NumericKey = { [K in keyof SitePolicyValues]: SitePolicyValues[K] extends number ? K : never }[keyof SitePolicyValues]
export type PolicyTone = 'green' | 'blue' | 'purple' | 'amber'
export type PolicyField = {
  key: NumericKey; label: string; description: string; min: number; max?: number; sliderMax: number
  step: number; integer?: boolean; exclusiveMin?: boolean; advanced?: boolean
}
// 控件展示范围与 API 校验边界分开，现有配置超出滑块常用范围时仍可精确编辑。
export const POLICY_GROUPS: Array<{ title: string; tone: PolicyTone; fields: PolicyField[] }> = [
  { title: '离岗检测', tone: 'green', fields: [
    { key: 'absent_alarm_seconds', label: '离岗触发时间（秒）', description: '所有参与检测的摄像头均有有效结果且未见保安，持续达到该时间后报警。', min: 0, sliderMax: 600, step: .1, exclusiveMin: true },
    { key: 'guard_hold_seconds', label: '保安短暂丢失宽限时间（秒）', description: '保安被遮挡或制服短暂漏识别时，继续保留身份的时间，减少离岗误报。', min: 0, sliderMax: 10, step: .1 },
    { key: 'person_confidence_threshold', label: '人体检测置信度', description: '低于该置信度的人体检测结果将被过滤。', min: 0, max: 1, sliderMax: 1, step: .01, advanced: true },
    { key: 'uniform_confidence_threshold', label: '制服识别置信度', description: '制服分类达到此概率后，才将人员识别为保安。', min: 0, max: 1, sliderMax: 1, step: .01, advanced: true },
    { key: 'person_phone_imgsz', label: '人体检测输入尺寸', description: '较大的输入尺寸保留更多细节，也会增加推理耗时。', min: 32, max: 4096, sliderMax: 1280, step: 1, integer: true, advanced: true },
  ] },
  { title: '手机检测', tone: 'blue', fields: [
    { key: 'phone_seconds', label: '持续玩手机多久报警（秒）', description: '疑似玩手机状态持续达到该时间后，才触发报警。', min: 0, sliderMax: 600, step: .1, exclusiveMin: true },
    { key: 'phone_window_seconds', label: '统计最近几秒内的手机命中', description: '只统计最近这段时间内的手机命中次数，过滤偶发误检。', min: 0, sliderMax: 20, step: .1, exclusiveMin: true },
    { key: 'phone_min_hits_in_window', label: '统计窗口内至少识别到几次手机', description: '命中次数达到该值后，才认为手机证据有效。', min: 1, sliderMax: 30, step: 1, integer: true },
    { key: 'phone_grace_seconds', label: '短暂漏检宽限时间（秒）', description: '手机被遮挡或短暂漏检时，在该时间内保留计时。', min: 0, sliderMax: 10, step: .1 },
    { key: 'phone_near_person_px', label: '手机靠近身体判定范围（px）', description: '手机与人体的关联范围，数值越大越宽松。', min: 0, sliderMax: 400, step: 1, advanced: true },
    { key: 'phone_near_head_px', label: '手机靠近头部判定范围（px）', description: '手机与头部估计位置的距离，用于辅助判断手机使用行为。', min: 0, sliderMax: 300, step: 1, advanced: true },
    { key: 'phone_confidence_threshold', label: '手机检测置信度', description: '过滤低可信度的手机识别结果。', min: 0, max: 1, sliderMax: 1, step: .01, advanced: true },
    { key: 'phone_crop_imgsz', label: '手机裁图输入尺寸', description: '手机区域进入模型时的图像尺寸。', min: 32, max: 4096, sliderMax: 1280, step: 1, integer: true, advanced: true },
  ] },
  { title: '趴睡检测', tone: 'purple', fields: [
    { key: 'prone_sleep_seconds', label: '持续趴睡多久报警（秒）', description: '疑似趴睡状态持续达到该时间后，才触发报警。', min: 0, sliderMax: 1200, step: .1, exclusiveMin: true },
    { key: 'prone_consecutive_frames', label: '连续低头确认帧数', description: '连续识别到低头达到该帧数后，才认为低头证据有效。', min: 1, sliderMax: 30, step: 1, integer: true },
    { key: 'prone_head_down_ratio_threshold', label: '低头判定灵敏度', description: '数值越小越容易判定为低头，数值越大越严格。', min: 0, max: 1, sliderMax: 1, step: .01, advanced: true },
    { key: 'prone_bbox_height_ratio_threshold', label: '伏桌／趴下判定灵敏度', description: '判断人体框是否明显变矮，数值越大越容易认为处于伏桌或趴下状态。', min: 0, max: 1, sliderMax: 1, step: .01, advanced: true },
    { key: 'pose_imgsz', label: '姿态检测输入尺寸', description: '姿态模型使用的图像尺寸，影响细节与推理耗时。', min: 32, max: 4096, sliderMax: 1280, step: 1, integer: true, advanced: true },
  ] },
  { title: '车辆出厂检查', tone: 'amber', fields: [
    { key: 'vehicle_occlusion_seconds', label: '车辆离开确认时间（秒）', description: '车辆消失达到该时间后确认离场，避免短暂遮挡提前结束检查。', min: 0, sliderMax: 60, step: .1, exclusiveMin: true },
    { key: 'vehicle_near_px', label: '保安靠近车辆范围（px）', description: '保安与车辆距离小于该范围时，作为车辆检查的接近证据。', min: 0, sliderMax: 500, step: 1 },
    { key: 'vehicle_direction_min_delta_ratio', label: '方向判定最小位移比例', description: '车辆移动达到此比例后，才确认其运动方向。', min: 0, max: 1, sliderMax: 1, step: .01 },
    { key: 'vehicle_reassociate_seconds', label: '已检查车辆重关联窗口（秒）', description: '车辆短暂丢失后，在此时间内允许重新关联已有检查记录。', min: 0, sliderMax: 120, step: .1 },
    { key: 'vehicle_confidence_threshold', label: '车辆检测置信度', description: '过滤低可信度的车辆检测结果。', min: 0, max: 1, sliderMax: 1, step: .01, advanced: true },
    { key: 'vehicle_imgsz', label: '车辆检测输入尺寸', description: '车辆模型使用的图像尺寸。', min: 32, max: 4096, sliderMax: 1280, step: 1, integer: true, advanced: true },
  ] },
  { title: '识别稳定性参数', tone: 'amber', fields: [
    { key: 'static_motion_threshold', label: '静止判定灵敏度', description: '人体移动小于该范围时认为基本静止，用于辅助趴睡判断。', min: 0, sliderMax: 20, step: .1 },
    { key: 'state_ttl_seconds', label: '目标短暂消失保留时间（秒）', description: '目标短暂丢失后保留跟踪状态的时间，超过后按新目标处理。', min: 0, sliderMax: 120, step: .1, exclusiveMin: true },
    { key: 'cap_interval', label: '处理间隔（秒）', description: '相邻感知处理的调度间隔，实际帧率还受模型耗时影响。', min: 0, sliderMax: 5, step: .01, exclusiveMin: true },
    { key: 'model_iou_threshold', label: '模型 IoU 阈值', description: '控制重叠检测框的去重程度。', min: 0, max: 1, sliderMax: 1, step: .01 },
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
