# 报警处置分页接口

本接口读取已保存的处置状态。报警页面仍通过 `/api/alarms` 获取报警及对应处置状态，页面布局和保存流程不变；该接口拼接状态时只读取返回报警的处置记录。前端 `getAlarmDispositions(options, signal)` 返回下面的分页对象，不自动获取所有页。

## 查询契约

`GET /api/alarm-dispositions?limit=50&cursor=<上次返回的 next_cursor>`，需要正常登录。

- `limit` 默认 50，范围 1–100；没有全量模式、页码模式或旧数组返回分支。
- 固定按 `alarm_id` **字符串升序**排列，不按更新时间排列，也不是数字 ID 排序。
- 返回 `items`、`next_cursor`、`stop_reason`；不返回总数，避免统计时扫描全部历史。
- `page_full`：当前页已满，使用 `next_cursor` 继续。
- `scan_limit`：已达到单次工作量上限；当前页可能不足 `limit`，也可能为空，必须保留 `next_cursor` 供继续查询。
- `end`：已检查到当前快照的末尾，`next_cursor` 为 `null`。只有这个状态表示结束。游标非空表示还有候选记录可检查，不保证后续候选中存在有权访问的记录。

```json
{
  "items": [],
  "next_cursor": "<opaque-token>",
  "stop_reason": "scan_limit"
}
```

游标只在服务端保存位置，不包含未授权报警 ID。绑定当前用户身份、角色、事业部权限、认证版本和处置存储版本，有效期 15 分钟，单进程最多保留 2048 个游标。每次继续查询获得新的游标；可在有效期内用原游标重试失败请求。

任意处置写入成功都会使旧快照失效，返回 **409**，调用方应清空已累计结果、从第一页重新查询；查询期间发生写入也返回 409，不混用前后快照。身份或权限不匹配同样返回 409。游标过期、被容量淘汰或服务重启后返回 **410**，应重新开始。当前存储和游标均为单进程机制，不支持无粘性的多 worker 部署。

`GET /api/alarm-dispositions/{alarm_id}` 返回 `{"item": ...}`；合法报警尚无保存的处置状态时为 404。`POST /api/alarm-dispositions` 仍接收 `alarm_id`、`status`、`note`，返回 `{"success": true, "item": ...}`。单条读取和写入使用与分页相同的授权方式。

## 权限和工作量

普通用户的 AiVision 处置候选 ID 通过新接口 `POST /api/alarms/access-check` 批量授权，请求体只能包含 `{"alarm_ids": [1, 2]}`，最多 100 个正整数（MySQL BIGINT UNSIGNED 范围）。AiVision 使用真实登录凭据重新读取认证数据库中的用户；客户端提交的事业部、角色或授权结果不能作为权限依据。查询直接按主键查整个报警历史，基于**报警归属快照**和沿用的报警类型权限过滤，只返回 `{"allowed_ids": [...]}`，不返回报警内容、归属等元数据；不存在和无权访问的 ID 都不在结果内。未登录返回 401。

事业部报警类型清单由 `auth/alarm_permissions.py` 提供，统一后端与批量接口共用。处置只接受 `aivision:<正整数 ID>`；其他来源和非法 ID 对所有账号均不可见，单条读取与写入返回 403。管理员可维护全部正式 AiVision 处置（包括失去原报警的处置），无需远程授权。

每个分页请求最多读取 **500 个候选 ID**，分 **5 批、每批最多 100 个**；逐批授权后累计有权记录，凑满页立即停止。继续位置是最后消费的候选位置，未消费的预取记录会在下一次重新检查，不会跳过。只复制最多 100 条有权记录，不遍历全量处置或为总数扫描历史。

普通用户每页最多发出 5 次授权请求，全部候选有权时一批就能生成默认 50 条的一页。单条读取或修改最多 1 次；管理员不发授权请求。

独立 `httpx.AsyncClient` 在 FastAPI lifespan 创建、关闭，连接上限 4；分页及单条授权共用最多 4 个并发名额，各请求串行发批次，不使用 `_OVERVIEW_EXECUTOR`。容量不足立即 503（`Retry-After: 1`），不堆积等待任务。单批整体等待上限 2 秒（连接 0.5 秒、连接池等待 0.1 秒），分页授权整体预算 6 秒；响应最多读取 8 KiB。内存索引读锁最多等待 50 毫秒，繁忙时 503。这些是应用层预算，不是进程被操作系统暂停等情况下的实时保证。

上游网络/响应异常返回 **502**，超时返回 **504**；上游认证拒绝返回 401/403。不会放行、吞掉失败或返回部分成功页；调用方应保留原游标重试，不能把错误当成 `end`。无权或不存在的报警不允许普通用户处置，统一返回 403，拒绝时不写 JSON。

## 存储边界与部署

`alarm_dispositions.json` 只接受 `{"items": [...]}` 格式；每条记录包含 `alarm_id`、`status`、`note`、`updated_at`、`updated_by` 和 `history`，历史项包含状态、备注、时间和操作人。文件不存在时初始化空存储；JSON 损坏、字段非法或 ID 重复时启动失败，不能当成空数据覆盖。启动时读取并建立排序 ID 索引：启动开销约 O(N log N)，内存 O(N)；分页不重新读取文件、不重复全量排序。写入仍需 O(N) 序列化并原子替换整个 JSON，新 ID 插入索引也是 O(N)。磁盘写入期间不占查询索引锁；写入失败不发布内存更改。频繁写入、极大文件、多进程共享写入仍是该存储的边界，本次没有重构为数据库或支持外部热修改文件。

部署时先提供 AiVision 批量接口，再更新统一后端和前端资源；两端应使用同一个认证数据源和正常登录凭据。本次不执行部署、服务重启或生产迁移。旧 AiVision 尚未提供接口时，普通用户处置查询/修改会明确失败，不回退逐条请求。部署后应以通用电气、皓达和管理员账号检查分页、旧报警处置及权限拒绝，并在慢上游条件下检查首页状态响应。

## 自动化验证

从仓库根目录执行（以下均为测试占位配置；测试使用临时 SQLite/JSON 和内存 HTTP 传输，不连接生产数据库）：

```bash
env MYSQL_DB_URL=127.0.0.1 MYSQL_DB_USER=disposition_test MYSQL_DB_PASSWORD=test-only-unused MYSQL_DB_NAME=disposition_test DATA_PATH=/tmp/disposition-tests-media AUTH_USERS_DB=/tmp/disposition-tests-auth.sqlite UNIFIED_BACKEND_DATA_DIR=/tmp/disposition-tests-data python -m pytest AiVision/tests/test_alarm_access_batch.py AiVision/tests/test_alarm_api.py unified_backend/tests -q
cd unified_frontend
node --test tests/*.test.mjs
npm run build
```

覆盖真实认证依赖和临时用户数据库、事业部/类型过滤、交错分页、旧报警、20,000 条历史的扫描及请求上限、超时/异常、游标失效、共享客户端身份隔离、首页执行资源隔离和生命周期释放。测试不等于生产 MySQL 压测，也不替代真实反向代理、部署进程和浏览器联调。
