"""外部接口路径及管理员凭证存储依赖。"""

from auth.external_store import external_client_store

EXTERNAL_API_PREFIX = "/api/external"


def get_external_client_store():
    return external_client_store
