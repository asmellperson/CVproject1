"""
departments/：事业部目录与功能分配

这个目录定义平台有哪些正式事业部，并管理每个事业部可以访问哪些检测功能。
事业部名称来自固定注册表，功能分配保存在数据库；二者有不同的修改方式。
本入口保留注册表对象的公开导出，不在这里查询数据库或启动后台任务。

一、先分清目录、权限和运行开关

    DepartmentSpec：事业部的固定 name、display_name，供账号、摄像头等使用。
    功能分配：某事业部被授权访问的 FeatureSpec.name 列表，管理员和 viewer 均遵守。
    检测启停：由摄像头、功能和通道/保安室配置决定，收回页面访问权限不会停止检测。
    viewer 还受账号所属事业部约束，不能借用另一个事业部的功能分配访问资源。

二、每个文件负责什么

    department_registry.py：DepartmentSpec、DEPARTMENT_SPECS、require_department()。
        提供固定目录和名称校验，不承担功能分配的数据库读写。
    orm.py：DepartmentFeatureAccess，对应 department_feature_access 表，
        保存事业部功能列表和 revision，供并发编辑校验。
    schema.py：功能选项、单事业部分配和完整配置响应的数据契约。
    service.py：DepartmentService 与 department_service 单例。
        list_departments() 返回目录；feature_access() 返回数据库中的分配。
        get_features_by_department() 返回指定事业部已分配的功能。
        feature_settings() 提供管理员编辑需要的分配和完整功能目录。
        save_feature_settings() 校验全部事业部和功能，锁定记录、检查版本后原子保存。

三、一次功能分配保存的流程

    前端功能分配页面 → api/routes/departments.py → 管理员权限与 Schema 校验
        → DepartmentService → 检查提交是否覆盖全部正式事业部、功能是否已注册
        → 数据库事务内检查 revision → 保存变化 → 返回最新分配。
    版本不一致时抛出 FeatureAssignmentConflict，避免覆盖其他管理员的修改。
    数据库缺少正式事业部分配记录时直接报错，不回退为全部功能开放。

四、和其他模块怎么联系

    features/registry.py 提供可分配的功能全集，包名不能替代功能业务标识。
    auth/feature_permissions.py 按“事业部＋功能”组合判断权限。
    认证用户信息、前端导航和平台总览消费同一份功能分配。
    本包 __all__ 仅导出固定目录对象，配置服务仍从 service.py 显式导入。

五、如果我要增加或删除事业部

    增加 DepartmentSpec 后，还要准备对应数据库分配记录并检查账号、摄像头和前端。
    只改注册表不足以完成上线，服务会检查分配记录是否与正式目录完整对应。
    删除前处理账号、摄像头、分配记录和历史数据引用，不能只删一个注册项。
    分配已有功能使用管理接口；增加新功能先完成 FeatureSpec 注册。

六、修改后怎么验证

    在项目根目录运行已配置环境中的权限回归：
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_department_feature_access.py
    并检查版本冲突、缺失分配、跨事业部访问、管理员访问及配置撤回后的页面权限。
"""
from .department_registry import DEPARTMENT_SPECS, DepartmentSpec, require_department

__all__ = [
    "DEPARTMENT_SPECS",
    "DepartmentSpec",
    "require_department",
]
