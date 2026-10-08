"""
connectors/hikvision/：海康人员数据连接器

这个目录负责 iSecure Center 人员查询和照片下载，使用 Artemis 签名完成请求认证。
返回的是外部平台数据，本地人员同步、特征生成及身份识别由 face_recognition/ 负责。
本入口保留客户端、签名器和数据类型的公开导出，导入本包不执行人员同步。

一、每个文件负责什么

    signer.py：ArtemisSigner，按 Artemis 协议组织签名。
        app_key、app_secret 由配置提供，签名生成不负责发送 HTTP 请求。
    client.py：连接配置、HTTP 传输、业务错误检查和图片下载。
        HikvisionConfig：平台地址、凭据、TLS、超时、响应大小和图片主机约束。
        HikvisionClient：维护连接，支持上下文管理器和 close() 释放资源。
        post_json()：发送并校验 JSON 响应；download_picture()：下载受限图片资源。
        HikvisionError：向业务层提供脱敏错误，并保留 HTTP 状态或海康业务错误码。
        HikvisionPicture：承载下载结果，供调用方继续校验和处理。
    persons.py：HikvisionPersons 人员协议门面。
        list_persons() 查询一页，get_person() 查询单人，get_picture() 获取人员照片。
        HikvisionPerson、PersonPhoto、PersonPage 对外部字段进行结构校验。

二、一次人员查询怎么走

    调用方构造 HikvisionConfig → HikvisionClient → HikvisionPersons
        → 人员接口参数 → Artemis 签名 → HTTP 响应 → 状态与数据校验 → 人员对象。
    list_persons() 返回分页结果，不代表整个来源已经同步完成。
    全量分页的总数、重复人员等完整性核对在人员库同步模块中完成。

三、图片下载和多来源要注意什么

    图片地址来自外部响应，客户端检查主机和跳转范围，并限制响应大小。
    独立图片服务器通过配置允许，不应直接取消地址校验。
    不同平台分别实例化客户端，调用方管理生命周期，不能混用来源与凭据。
    face_recognition/library/sync.py 为 one、two 来源准备各自配置并汇总同步结果。

四、如果我要增加外部接口

    复用现有 client 和 signer，在协议层定义参数与响应模型，避免复制签名逻辑。
    服务返回成功状态后仍要核对业务错误码和字段结构。
    本地入库和删除策略放人员库服务，连接器不直接修改人员数据库。

五、修改后怎么验证

    检查签名、分页参数、异常响应、照片跳转/大小限制及客户端关闭。
    日志与异常不得泄露凭据或完整人员字段；仅改包说明不需要连接真实海康平台。
"""

from .client import HikvisionClient, HikvisionConfig, HikvisionError, HikvisionPicture
from .persons import HikvisionPerson, HikvisionPersons, PersonPage, PersonPhoto
from .signer import ArtemisSigner

__all__ = [
    "ArtemisSigner",
    "HikvisionClient",
    "HikvisionConfig",
    "HikvisionError",
    "HikvisionPerson",
    "HikvisionPersons",
    "HikvisionPicture",
    "PersonPage",
    "PersonPhoto",
]
