"""
alarms/notifications/：企业微信通知与通知图片授权

这个目录把业务告警或系统异常发到企业微信，并为人员告警卡片提供受限缩略图链接。
是否报警、发给谁、多久重复由调用方及配置决定；通知发送不负责识别违规。
本文件只作说明，不集中导入客户端，不会在包导入时发消息。

一、每个文件负责什么

    wechat.py：WeChatNotifier，封装企业微信凭据、access_token 和消息 HTTP 请求。
        _get_token() 按有效期缓存 token，并使用锁避免并发重复刷新。
        send() 发送业务告警 news 图文卡片，需要接收人、图片 URL 和详情 URL；
            标题使用 alarms/types.py 的正式报警名称，缺少必要 URL 会返回失败。
        send_text() 发送系统异常等 Markdown 文本，由运行层或 API 异常处理调用。
        构造客户端与实际联网发送是不同动作，业务和 HTTP 错误都需要检查。
    notification_image.py：人员报警通知缩略图的短期签名和图片响应。
        issue_thumbnail_token() 将报警 ID、事业部和有效期绑定到签名。
        verify_thumbnail_token() 检查有效期与签名，避免替换报警或事业部后复用。
        thumbnail_response() 读取图片、缩放并返回 JPEG，设置禁止缓存等响应头。

二、两种通知怎么进入这里

    检测规则 → AlarmDispatcher → 保存报警并获得证据与详情地址
        → 企业微信图文卡片 → 用户点击后进入平台对应报警。
    摄像头 / 模型 / Consumer / API 异常 → 调用方读取系统异常通知策略并控制冷却
        → WeChatNotifier.send_text()。
    消息发送成功只说明通知通道完成，不表示用户已经阅读或完成处置。

三、缩略图授权和登录权限的区别

    缩略图签名使用独立用途标识，虽然读取 AUTH_SECRET，也不能当登录 JWT 使用。
    签名只授权对应的通知缩略图，不授权完整图片、视频或报警详情。
    /api/public/ 由 API 的公开路由接收，路由仍需校验缩略图签名与资源归属。
    通知目标、凭据和签名不应出现在普通调试输出或源码示例中。

四、配置与模块联系

    core/settings.py 提供企业微信、站点地址和缩略图有效期等配置。
    alarms/dispatcher.py 协调业务通知，runtime/orchestrator.py 和 api/app.py
        负责各自的系统异常通知入口，记录与媒体仍由 alarms/records/ 管理。

五、修改与验证

    修改卡片时核对正式报警名称、接收人、图片和跳转地址及失败返回。
    修改签名时覆盖过期、篡改、跨事业部和无效资源；修改 token 缓存时检查并发刷新。
    验证 HTTP 行为可使用替身；仅改说明无需向真实企业微信发送测试消息。
"""
