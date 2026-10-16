"""
features/face_recognition/library/：人员底库与特征索引

这个目录管理识别所需的人员资料、授权、注册照片特征和内存索引。
人员同步、照片特征生成、实时匹配是三个不同阶段，成功完成前一阶段不代表后续已可用。
本入口仅定义 HIKVISION_SOURCES 和 PersonSyncError，不执行同步、推理或后台任务。

一、先分清来源、照片和特征

    HIKVISION_SOURCES：one、two 两个外部来源，外部人员标识需要结合来源理解。
    人员资料：姓名、工号、照片引用等本地快照；通行授权按事业部独立保存。
    注册特征：从有效单人照片提取的向量，关联模型名称和照片签名。
    FaceIndex：供实时匹配使用的内存索引，刷新时读取数据库，匹配时不逐脸查库。
    PersonSyncError：完整性或生成流程中的业务异常，错误内容避免包含完整人员字段。

二、每个文件负责什么

    constants.py：特征模型标识、匹配与刷新等公共参数。
    orm.py：FacePerson、FaceEmbedding 及 FacePersonAuthorization 事业部授权表。
    service.py：FaceLibraryService，人员查询、授权修改、特征候选和特征保存。
        apply_snapshot() 以单个来源的完整人员快照为输入，在一个事务中更新。
        get_allowed_person_ids(department) 提供指定事业部授权集合，供识别 Consumer 使用。
    sync.py：海康来源配置、全量分页核验和手动同步入口。
        fetch_persons() 检查页码、总数、缺页和重复 ID，完整获取后再提交快照。
        HikvisionSyncSettings 分别读取 HIKVISION_ONE_ / HIKVISION_TWO_ 配置。
    embedding.py：增量读取待生成项、下载照片、解码并要求恰好检测到一张人脸，
        复用 InsightFaceRecognizer 提取特征；模型与照片签名未变化的项可以跳过。
    index.py：照片签名、特征字节编解码和 FaceIndex。
        refresh() 整体替换索引，match() 在内存中进行相似度匹配。

三、从外部人员到实时识别的流程

    海康人员分页 → 完整性检查 → apply_snapshot() → 本地人员资料
        → 下载有效注册照片 → 单脸检查 → 生成并保存特征
        → Worker 刷新 FaceIndex → 摄像头人脸匹配 → Consumer 判断是否授权。
    两个来源各自处理同步结果，失败来源不能把未完整获取的列表当作正式快照。
    注册照片的单脸要求不同于摄像头实时画面，实时画面允许同时识别多张人脸。

四、手动任务入口

    在项目根目录、已配置依赖和环境的 Python 中执行：
        python -m AiVision.features.face_recognition.library.sync
        python -m AiVision.features.face_recognition.library.embedding
    前者会读取外部平台并写人员数据；后者还会加载模型、读取照片并写特征。
    它们是实际运维任务，不是检查 __init__.py 注释的命令；包导入不会自动执行。

五、修改与验证

    修改来源和人员键时检查完整快照、停用规则、照片引用、特征关联和历史记录。
    更换特征格式或模型时同步生成端与匹配端，避免把不同模型向量放在一起比较。
    覆盖缺页、重复 ID、事务失败、无脸/多脸照片、增量跳过、索引刷新和授权更新。
    仅改本说明时保留来源常量和异常类，检查语法与除文档字符串外的 AST 一致性。
"""

HIKVISION_SOURCES = ("one", "two")


class PersonSyncError(RuntimeError):
    """不含人员字段的完整性检查错误。"""
