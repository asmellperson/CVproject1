"""
供多个服务复用的公共模块。

auth/：统一登录认证、用户存储与角色授权

这个包回答“当前请求是谁发来的、账号是否有效、是否具备管理员身份”。
用户资料保存在独立的 SQLite 用户库中；浏览器通过 Cookie 携带 JWT 身份凭证。
摄像头、Feature、物流通道和告警仍由各自的业务模块管理，不保存在用户库中。

一、包内文件及职责边界

    __init__.py：本文件是包说明，不重新导出函数，不创建数据库、不签发 Token。
        单独 import auth 不会导入 auth.py / user_store.py，也不启动服务或线程。
        业务代码显式使用 from auth.auth import get_current_user, require_admin 等接口。

    auth.py：认证与授权的公共函数。
        负责登录密码验证、JWT 签发与校验、Cookie 读写、当前用户查询、管理员依赖，
        以及管理员管理用户和用户自行改密的服务入口。
        本文件没有 FastAPI 路由；HTTP 路径和响应结构由调用它的服务注册。

    user_store.py：UserStore 用户存储与数据约束。
        负责 SQLite 连接、建表和旧库迁移、用户 CRUD、部门规范化、密码哈希生成，
        以及保护当前管理员、保护最后一个有效管理员等数据库操作规则。
        它不解析 HTTP 请求、不读写 Cookie、不判断请求调用者是否通过了管理员认证。

    两者的关系：API → auth.py → UserStore → SQLite。
        require_admin() 在 API 入口验证调用者身份；UserStore 在事务中验证数据和业务约束。
        单独调用 create_auth_user() 等普通 Python 函数，不会自动执行 FastAPI 的权限依赖。

二、user_store.py：账号具体保存什么、怎样读写

    default_database_path()：优先读取 AUTH_USERS_DB。
        未设置时，使用项目根目录下 runtime/auth/auth_users.db。
        这是认证用户库，与 AiVision 保存摄像头、检测配置和告警的 MySQL 数据库分开。

    auth_users 表的主要字段：
        employee_id：工号，用户主键，也是 JWT 的 sub；更新资料接口不修改这个主键。
        name：姓名/显示名称，要求唯一；当前登录查询也支持用姓名匹配用户。
        role：admin 或 viewer；enabled 表示账号是否允许登录和访问受保护接口。
        departments：用户可以查看哪些事业部，以 JSON 数组字符串存入 SQLite TEXT。
        department：旧单部门兼容列，写入时同步保存 departments 的第一个值。
            当前权限对象使用 departments 列表，不能把旧 department 列当成唯一授权来源。
        password_hash：带算法、迭代次数和随机盐的密码哈希，不保存用户输入的明文密码。
        auth_version：登录凭证版本，初始为 1；修改密码时递增，用于拒绝旧 JWT。
        created_at / updated_at：用户创建和修改时间。

    UserStore.__init__()：记录数据库路径和初始化锁，不立即连接或创建数据库。
    _connect()：建立 SQLite 连接，设置 Row 访问方式、锁等待时间和外键检查。
    initialize()：首次实际读写前，在初始化锁保护下创建目录、开启 WAL、执行建表/迁移。
        初始化事务使用 BEGIN IMMEDIATE；成功 commit，失败 rollback，最后关闭连接。
        缺少 departments / password_hash 的旧表会补列；旧单部门或别名会规范化。
        旧用户缺少 password_hash 时，使用 _legacy_default_password() 生成迁移用哈希。
            该值取自 AUTH_DEFAULT_PASSWORD 或代码中的历史默认值，仅用于旧账号迁移；
            新建用户必须通过上层服务明确传入密码，不能把迁移默认值理解成新用户默认密码。
        初始化不会自动创建一个管理员账号。首次查询也可能触发这一步迁移写入，
            所以排查真实用户库时，不能把第一次 list_users() 简单理解成纯 SELECT。

    规范化与密码工具：
        _normalize_required()：清理工号、姓名等输入两端空白，并拒绝空值。
        _normalize_role_departments()：校验角色、转换部门别名、去重并检查固定部门白名单。
            admin 统一保存为 ["all"]；viewer 必须选择至少一个有效的固定事业部。
        ALLOWED_VIEWER_DEPARTMENTS：直接来自 AiVision 的 DEPARTMENT_SPECS 注册表。
        DEPARTMENT_ALIASES：旧称、中文名和简称到正式部门编码的转换，不是第二份部门注册表。
        _encode_departments() / _decode_departments()：在 Python 列表与 SQLite JSON 文本之间转换。
        hash_password()：使用随机盐和 PBKDF2-HMAC-SHA256，默认 PASSWORD_HASH_ITERATIONS 次迭代。
            哈希串包含算法、迭代次数、盐和摘要，认证时可用相同参数重新计算并比较。

    查询：
        list_users()：按工号返回所有用户，包含启用状态，不返回 password_hash。
        get_user_record()：按工号取内部完整记录，包含密码哈希；不存在时抛 UserNotFoundError。
        find_enabled_user()：只匹配 enabled=1 的用户，支持工号或姓名，返回内部记录或 None。
        _public_user() / _public_without_password()：生成不含密码哈希的公开字典。
        _user_record()：在公开字段上补回 password_hash，仅供内部认证等流程使用。

    写入：
        create_user()：检查工号、姓名唯一性和部门合法性，新用户默认启用、auth_version=1。
        update_user()：修改姓名、角色、部门、启用状态；拒绝重名，不能禁用当前登录管理员，
            也不能通过停用或降级移除最后一个已启用管理员。
        update_password_hash()：更新哈希并将 auth_version 加 1，两者在同一事务中提交。
        delete_user()：物理删除用户记录；不能删除当前登录管理员或最后一个已启用管理员。
        _enabled_admin_count()：在当前事务内统计有效管理员，用于上述保护。
        写操作成功后提交，失败回滚；连接在完成后关闭，不在后台维持用户管理线程。

    异常：UserStoreError 是公共基类；UserValidationError 表示输入不合法，
        UserConflictError 表示工号/姓名重复或管理员保护冲突，UserNotFoundError 表示用户不存在。
        HTTP 状态码由 API 层转换，存储层本身不直接返回 HTTP 响应。

三、auth.py：从登录到每一次请求的身份检查

    请求模型与用户对象：
        LoginRequest：employee_id、password；ChangePasswordRequest：current_password、new_password。
        _public_user()：生成认证使用的 employee_id、name、role、departments、auth_version。
            这里不返回 password_hash，也不带管理列表中的 enabled 等字段。
        AuthError：认证失败的公共异常；get_current_user() 将它转换为 HTTP 401。

    用户库访问：
        get_auth_users_database_path()：使用 user_store.default_database_path() 的同一条路径规则。
        get_user_store()：按数据库路径缓存 UserStore 对象，路径变化时重新创建，使用锁保护。
            缓存的是存储对象，不是全部用户资料；请求认证仍会重新查询当前用户记录。
        load_auth_users() / list_auth_users()：读取公开用户列表，分别供认证相关调用和管理入口使用。
        _find_enabled_user_record()：读取包含哈希的内部启用用户记录。
        find_enabled_user()：再经过 _public_user()，提供不含哈希的当前用户对象。

    登录验证：
        verify_login() → _find_enabled_user_record() → _verify_password() → 公开用户对象。
        找不到启用账号或密码不正确时返回 None，由登录 API 返回登录失败。
        _verify_password() 拆解已保存哈希，用相同盐和迭代次数重新计算，
            使用 hmac.compare_digest() 比较摘要，不通过普通字符串相等来验证密码。

    JWT：
        create_token()：用 employee_id 作为 sub，写入 name、role、departments、auth_version、iat；
            配置了有效期时再写 exp，使用 AUTH_SECRET 和 HS256 签名。
        _json_b64()、_b64url_encode()、_b64url_decode()：负责 JWT 的 JSON/Base64URL 格式转换。
            JWT 内容是编码后签名，不是加密，不能把密码或密码哈希加入 Payload。
        decode_token()：校验签名、算法和可选过期时间，成功返回 Payload；失败抛 AuthError。
        get_auth_secret()：读取 AUTH_SECRET；未设置时使用开发兜底值并记录一次警告。
        get_token_expire_hours()：读取 AUTH_TOKEN_EXPIRE_HOURS，正整数表示小时数；
            空值、0、never、permanent、forever 表示 Token 不主动过期，不生成 exp。
        get_auth_cookie_max_age_seconds()：有限期时与 Token 时长对应；不主动过期时，
            Cookie 使用 PERSISTENT_COOKIE_MAX_AGE_SECONDS 定义的长期保存时间。

    每次请求：
        token_from_request()：优先取 Authorization: Bearer，其次取 aicv_auth_token Cookie。
        get_current_user_from_request()：验 Token → 用 sub 重新查启用用户 → 比较 auth_version。
            返回数据库当前的角色与部门，不直接拿 JWT 中旧的 role/departments 做最终授权。
            用户已删除、被停用、凭证版本不匹配或 Token 过期时，拒绝访问。
        get_current_user()：FastAPI 登录依赖，把 AuthError 转成 401。
        require_admin()：先通过 get_current_user()，再要求 role="admin"，否则返回 403。
            这里仅检查管理员身份；摄像头、告警、站点等部门数据范围由各业务接口继续检查。

    Cookie：
        cookie_secure_for_request()：AUTH_COOKIE_SECURE 优先，否则根据 HTTPS / X-Forwarded-Proto 判断。
        set_auth_cookie()：设置 HttpOnly、SameSite=Lax、Path=/ 的认证 Cookie，并设置保存时长。
        clear_auth_cookie()：按相同路径和相关属性删除浏览器 Cookie。
            登出不增加 auth_version，也不建立服务端 Token 黑名单；不能理解成全部设备强制下线。

    管理与改密：
        create_auth_user()：检查初始密码至少 6 位，生成哈希后调用 UserStore.create_user()。
        update_auth_user() / delete_auth_user()：传递目标工号和当前管理员工号给存储层。
        reset_auth_user_password()：管理员重置，不需要目标用户旧密码；新密码至少 6 位。
        change_own_password()：检查账号启用、旧密码正确、新密码至少 6 位，然后更新哈希。
        两种改密最终都调用 update_password_hash()，使旧版本 JWT 在后续请求中失效。
        修改姓名、角色、部门本身不会增加 auth_version；权限变化通过下次请求重新查库生效。

四、和统一后端、AiVision、前端的连接

    unified_backend/app.py：注册统一站点的认证和用户管理路由。
        POST /api/auth/login：验证账号密码，签发 JWT，写 Cookie，返回公开用户资料。
        GET /api/auth/me：返回当前有效用户；POST /api/auth/logout：清除 Cookie。
        POST /api/auth/password：本人改密；当前接口不重新签发 JWT，改密后需要重新登录。
        GET /api/admin/users、POST /api/admin/users：管理员查询、新增用户。
        PATCH /api/admin/users/{employee_id}、DELETE /api/admin/users/{employee_id}：修改、删除。
        POST /api/admin/users/{employee_id}/reset-password：管理员重置密码。
        用户管理路由统一使用 require_admin()，并把存储层异常转换为接口错误。
        登录/查询当前用户时的访问记录和额外能力字段由统一后端补充，不是本包的用户表字段。

    AiVision/api/app.py：认证中间件调用 get_current_user_from_request()；
        受保护的 API 路由再按需要使用 get_current_user() / require_admin() 和部门范围校验。
        哪些健康检查或公开资源可免登录，由应用中间件自己的公开路径规则决定。
    AiVision/integrations/guard_room/src/server.py：直接使用本包的登录、Cookie、改密和认证函数。
        不要再按旧说明去寻找服务内部单独维护的 auth.py 实现。
    多个服务共享身份时，需要读取同一份用户数据库并使用一致的 JWT 签名密钥；
        仅仅导入同一个 Python 包，不代表不同进程的 AUTH_USERS_DB / AUTH_SECRET 自动一致。

    unified_frontend/src/auth/AuthContext.tsx：调用 login/me/password/logout，使用 credentials=include，
        保存公开用户状态，响应未认证事件；不需要由前端 JavaScript 读取 HttpOnly Cookie。
    unified_frontend/src/sections/UserManagementSection.tsx → src/lib/admin-users.ts
        → /api/admin/users → auth.py 管理入口 → UserStore。
        前端权限控制决定界面操作是否显示或可用，后端依赖负责最终检查。

五、部门授权与设备归属不要混淆

    用户 departments：这个用户可以查看哪些事业部，可以选择多个固定部门。
    Camera.department：这台摄像头的单个归属部门，由 AiVision 摄像头配置模块负责。
    FeatureSpec.departments：这项检测功能允许属于哪些部门，由 Feature 定义负责。
    DEPARTMENT_SPECS：固定部门编码与显示名称的唯一注册表；本包只引用其编码白名单。
    管理员的 ["all"] 是授权标记，不是可创建的新事业部，也不能写成 Camera 的归属。
    修改用户可查看部门不会移动摄像头、启停 Feature，或改写已有告警的 department。

六、后续维护从哪里入手

    新增/停用/删除用户：使用现有管理员用户管理入口，保持事务约束与密码哈希流程。
    改密码规则：检查 auth.py 的创建、本人改密、管理员重置三个入口，以及哈希验证流程。
    改登录有效期或 Cookie 策略：检查 auth.py 中对应环境变量、Token 与 Cookie 函数。
    加用户字段：同步检查 user_store.py 建表/迁移、公开/内部字典、统一后端请求模型和前端类型。
    加固定部门：修改 Department 注册表；Feature 归属在 FeatureSpec 中声明，用户管理只负责选择。
    仅修改此包说明时，不需要调用 UserStore.initialize()，也不应访问真实用户库验证注释。

    在项目根目录的 Python 环境中，相关既有测试可以这样运行：
        python -m pytest -q -c AiVision/pyproject.toml unified_backend/tests/test_auth_database.py
        python -m pytest -q -c AiVision/pyproject.toml unified_backend/tests/test_user_store.py
        python -m pytest -q -c AiVision/pyproject.toml unified_backend/tests/test_admin_users_api.py
    前两组覆盖密码、JWT、用户存储与旧库迁移；第三组检查管理员 API 权限和用户管理约束。
    这些测试使用临时用户数据库，不应为测试而修改现场 AUTH_USERS_DB 指向的真实账号资料。
"""
