"""
auth/：账号、认证授权和访问审计

这个目录确认请求者是谁、可以访问哪些资源，并提供账号管理与平台访问记录。
API 由 AiVision 统一挂载，账号和审计数据使用 AiVision 的共享 MySQL 基础设施。
本文件只作说明，导入本包不创建账号、签发 Token 或启动独立 Web 服务。

一、先分清几种权限

    登录身份：账号启用状态、密码和 JWT/Cookie 校验。
    角色：admin 或 viewer；管理操作使用管理员权限依赖。
    事业部功能权限：按“事业部＋功能”组合判断，管理员也遵守功能分配。
    告警数据权限：由告警查询的事业部范围和事件规则决定，不能直接套用菜单过滤。
    访问审计权限：按平台负责人身份授权，通过 capability 告知前端，不等同于 admin。

二、每个文件负责什么

    auth.py：密码验证、JWT 编解码、Cookie 设置和请求身份解析。
        get_current_user_from_request() 从请求获取并校验当前用户；
        get_current_user()/require_admin() 供 FastAPI 路由依赖使用。
        读取 AUTH_SECRET 等环境配置，不把密钥写进源码。
    user_store.py：UserStore，封装用户查询、创建、修改、删除和密码哈希保存。
        在数据库事务内处理账号约束，区分校验错误、冲突和目标不存在。
    orm.py：用户及访问记录的数据表定义，复用 AiVision.core.db.Base。
    schema.py：登录、修改密码和管理员账号操作的请求模型。
    api.py：登录、退出、当前用户、修改密码、账号管理和访问审计路由。
    feature_permissions.py：feature_departments()/require_feature_access()，
        将账号事业部范围与数据库功能分配配对，避免跨事业部借用权限。
    alarm_permissions.py：告警事件类型访问规则，供记录查询层使用。
    access_audit.py：记录近期平台访问、清理过期记录、核验平台负责人并提供 capability。

三、一次登录与后续请求的流程

    登录请求 → api.py → 校验账号密码 → 生成 JWT → 写入认证 Cookie。
    后续 /api 请求 → AiVision 认证中间件 → 解析并校验用户
        → request.state.user → 业务依赖 → 角色、事业部和资源访问检查。
    前端 AuthProvider 读取当前用户，控制菜单和页面入口；后端仍独立检查权限。
    退出通过清除 Cookie 完成，认证有效期和 Cookie 行为由 auth.py 的配置逻辑决定。

四、和其他模块怎么联系

    AiVision/api/app.py 统一挂载 router 并调用请求认证。
    AiVision/departments/ 提供正式事业部和功能分配，features/registry.py 定义功能标识。
    AiVision/alarms/records/ 使用告警权限和资源归属检查保护历史记录与媒体。
    unified_frontend/src/auth/ 和账号管理页面消费公开用户字段，不应接收密码哈希。

五、修改与验证

    增加权限时明确入口、资源归属和后端检查，避免只隐藏前端按钮。
    修改用户字段时同步 ORM、Schema、公开用户结构和前端类型，并准备数据库迁移。
    验证登录失败、停用账号、无效 Token、密码修改、管理员边界、多事业部权限和审计权限。
    仅改包说明无需真实登录、改账号或连接数据库。
"""
