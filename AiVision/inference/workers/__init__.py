"""
inference/workers/：模型推理的具体实现

这里的 Worker 接收业务层准备好的图片和任务参数，完成模型加载与单次推理。
队列读取、子进程生命周期和统一结果封装由上一级 BaseModelWorker 提供。
本入口保留 YoloDetectorWorker 的公开导出，实际权重在 Worker 的加载阶段读取。

一、每个文件负责什么

    yolo_detector.py：YoloDetectorWorker，加载 YOLO 检测权重。
        按逻辑模型定义和任务参数选择置信度、IoU、类别过滤及输出标签，
        返回 bbox、confidence、class_id 等检测字段。
    yolo_pose.py：YoloPoseWorker，输出输入图片像素坐标中的人体框和 COCO 17 关键点。
    uniform_classifier.py：UniformClassifierWorker，加载制服分类模型，
        对人体 crop 输出 uniform 正类概率，是否确认为保安由业务阈值判断。
    face_detector.py：FaceDetectorWorker，只做人脸检测，不访问人员底库。
        复用 ../insightface_detector.py 的 ONNX 检测实现。
    face_recognizer.py：InsightFaceRecognizer 和 FaceRecognizerWorker。
        前者提供本地人脸检测、对齐和特征提取，注册照片任务也会复用；
        后者用于实时推理，衔接人员特征索引得到匹配结果。

二、Worker 和逻辑模型是什么关系

    ../model_registry.py 将逻辑模型名绑定到 Worker 类和输出规则。
    ../model_paths.py 读取本机权重位置；RuntimeManager 管理进程及共享关系。
    同一 Worker 类可服务多个逻辑模型，共用物理权重时仍按各自任务参数推理。
    仅把类写入本目录或加入 __all__ 不会注册模型，注册表和功能依赖必须同步。

三、一次任务怎么执行

    Consumer 裁图并投递任务 → BaseModelWorker 读取队列
        → 子类 infer(model, frame, task_meta) → 原始检测或分类结果
        → contracts.build_inference_result() → 对应功能结果队列 → 业务解释。
    输入可能是全帧、ROI 或人体裁图，输出坐标相对输入图片，业务层负责还原。
    逗留时长、手机使用确认、人员授权及报警冷却不在模型 Worker 中判断。

四、如果我要增加一种模型实现

    继承 BaseModelWorker，实现 load_model() 和 infer()，明确输入与输出契约。
    在固定模型注册表绑定类、补充权重配置示例，并更新使用它的 FeatureSpec。
    不在模块导入或接口请求中加载 GPU 模型，保持由运行管理器控制生命周期。

五、修改后怎么验证

    检查类别过滤、输入坐标、空检测、输出字段、异常包装和同权重多逻辑模型任务。
    真实权重加载和设备推理需要在部署环境验证，替身测试不能证明 GPU 模型可运行。
    仅补充此说明时检查语法及现有导入、__all__ 是否保持一致。
"""
from .yolo_detector import YoloDetectorWorker

__all__ = ["YoloDetectorWorker"]
