# DBLP Local Search

独立内网 DBLP 检索服务：**FastAPI + SQLite FTS5 + 流式 XML 导入 + Docker Compose 周更**。
不依赖 `literature_search` SDK，SDK 的远程 Provider 后续单独接入。

## 1. 部署前提

- Linux 服务器，安装 Docker Engine 与 Docker Compose v2。
- 能访问 `https://dblp.org/xml/dblp.xml.gz` 和 `https://dblp.org/xml/dblp.dtd`，镜像构建时能下载 Python 包。
- 推荐使用 SSD；全量数据库、FTS、作者关联表及更新临时文件可能占用大量空间。
- 初步可预留 8 GiB 内存、100 GiB 以上空闲磁盘用于验证，但**不是全量资源保证**，必须结合当前 dump 大小实测。
- 首次初始化会完整建库；后续更新复制当前数据库到临时文件，只修改新增、变化和删除的记录，校验后替换。
- 更新时同时存在：唯一正式库 + 临时数据库副本 + 下载的 gzip；成功后只有 `/data/dblp.sqlite`，不保留历史库。不要按压缩包大小估算磁盘。
- API 启动必须配置 Bearer Token；仅建议部署在可信内网，跨不可信网络需反向代理 HTTPS。

## 2. 首次部署

把整个 `dblp_local_search/` 目录复制到服务器：

```bash
cd dblp_local_search
cp .env.example .env
chmod 600 .env
```

编辑 `.env`：

```dotenv
DBLP_API_TOKEN=请替换成长随机字符串
DBLP_BIND_ADDRESS=192.168.1.100
DBLP_PORT=8000
TZ=Asia/Shanghai
DBLP_UPDATE_CRON=0 3 * * 0
DBLP_QUERY_TIMEOUT=15
DBLP_MIN_RECORD_RATIO=0.8
```

- `DBLP_BIND_ADDRESS` 填服务器**实际内网 IP**；默认 `127.0.0.1` 仅允许本机访问。
- 不建议设 `0.0.0.0` 后直接暴露公网；用防火墙限制访问来源。
- Token 可本地生成，例如 `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`。
- `.env` 不提交版本库，镜像构建也不复制它。

```bash
# 构建同一个 API/updater 镜像
# Dockerfile 使用非 root 用户，命名数据卷持久化存储。
docker compose build

# 首次初始化：下载完整 XML/DTD，建库、索引、校验后发布。
# 首次执行可能很慢，建议放 tmux/screen 内运行。
docker compose run --rm updater update --force

# 初始化成功后，启动查询和定时更新两个容器。
docker compose up -d

docker compose ps
docker compose logs --tail=100 api updater
```

不要对首次初始化设置“一小时必须完成”的假设，完整导入时间要在服务器上测量。

> 新建命名卷会复制镜像 `/data` 的 app 用户权限。若改成宿主目录挂载，需要先将目录属主设为 UID/GID 10001，API 仍应只读挂载。

## 3. 每周自动更新

`updater` 是独立常驻调度进程，默认：

```text
每周日 03:00，Asia/Shanghai（北京时间）
检查 XML 是否变化 → 下载 XML/DTD → 流式建库 → 校验 → 发布
```

- `03:00` 是开始时间，不保证 `04:00` 完成。
- 标准 cron 的 `0`/`7` 在本项目明确映射为周日，不会误用 APScheduler 的 Monday=0。
- 任务单实例执行，另外有文件锁阻止手动更新与定时更新同时运行。
- 启动 updater **不会立即下载**；正常重启等待下一个计划时间。
- 服务器/容器必须保持运行。停机期间的计划任务**不补跑**；恢复后等待下一次或手动执行。
- 通过 ETag/Last-Modified 条件请求判断是否变化；上游返回 304 时跳过更新。无缓存头时可能每周重新下载。
- 首次没有数据库时执行完整建库；之后解析新 XML，与数据库中的 `content_hash` 比较，只更新新增、变化和删除的记录。
- **不需要保存旧的 dblp.xml**：数据库本身保存上一条记录的内容哈希，比保留完整 XML 更省磁盘。
- 如果没有任何记录变化，不替换正式数据库。
- 官方下载失败/反爬时直接失败，不尝试绕过。
- 文件锁持有期间构建临时新库，API 继续读取正式库；校验通过后原子替换 `/data/dblp.sqlite`。
- 记录数、构建时间、ETag/Last-Modified 等元数据全部保存在 SQLite 内，随数据一起替换。不生成数据版本号。
- 不原地写入正式库，不保留历史版本，也不提供历史回滚。Linux 中已打开的旧连接可完成当前请求，关闭后释放旧文件空间；新请求读取新库。
- 异常缩减到旧库 80% 以下会拒绝发布。`--force` 只强制下载，不绕过完整性检查。
- Windows 开发环境若仍有连接占用正式文件，原子替换可能失败；失败时旧库保持不变。生产建议 Linux Docker。

手动更新：

```bash
docker compose run --rm updater update
# 无视 HTTP 条件缓存，重新下载：
docker compose run --rm updater update --force
# 不读取旧数据库，完整重建（排查或强制刷新）：
docker compose run --rm updater update --full
```

变更调度后：

```bash
docker compose up -d --force-recreate updater
```

## 4. 健康检查与更新状态

```bash
curl http://192.168.1.100:8000/health/live
curl http://192.168.1.100:8000/health/ready

# 建议在当前 shell 设置 API_TOKEN，避免把 Token 直接写进命令历史。
curl -H "Authorization: Bearer $API_TOKEN" \
  http://192.168.1.100:8000/v1/dataset
```

- `live`：进程存活。
- `ready`：已发布数据库可读，未初始化时返回 503。
- `/v1/dataset`：论文/作者数量、构建时间、最近更新状态，不返回数据版本。
- 更新失败会记录在 `/data/update-status.json`，旧数据仍服务。
- 更新状态包含 `mode`（`full` 或 `incremental`）以及新增、更新、未变化、删除数量。
- Docker 健康检查只读，不触发下载或建库。API 文档在 `/docs`，业务接口需 Bearer Token。

## 5. 搜索接口

### 论文结构化搜索

```bash
curl -X POST http://192.168.1.100:8000/v1/papers/search \
  -H "Authorization: Bearer $API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "all_of": [{"text":"graph learning","field":"title","phrase":false}],
      "any_of": [],
      "none_of": [{"text":"survey","field":"title"}]
    },
    "year_from": 2020,
    "year_to": 2025,
    "venues": [],
    "page_size": 20,
    "include_total": true
  }'
```

支持字段：`all / title / authors / venue`，**没有摘要和全文检索**。

- 普通多词是 AND，`phrase=true` 是分词后连续词组匹配。
- all_of 全部满足；any_of 至少一个满足；两组之间 AND；none_of 排除。
- 每组最多 12 项，每项最多 300 字符。
- `year_from/year_to` 是出版年份范围，包含两端，不是提交时间。
- `venues` 为**精确书目名称列表的 OR**，如 `ICSE`；不是别名识别。需要宽泛会议搜索可用 `field=venue` 的文本条件。
- 默认 page_size=100，最大 100。
- 默认计算 total；宽泛查询计数可能慢，可设 `include_total=false`，此时 total=null。
- 排序为当前数据集内稳定 ID 顺序，不是相关性排序。
- 总查询预算默认 15 秒，超出返回 503；JSON 请求体上限 64 KiB。
- 使用受控 FTS 表达式、参数绑定 SQL，不执行用户原始查询语言。

响应示意：

```json
{
  "items": [{"dblp_key":"conf/icse/example","title":"...","authors":["..."],"year":2024,"venue":"ICSE","doi":null,"record_url":"...","external_urls":[]}],
  "total": 123,
  "next_cursor": "...",
  "warnings": []
}
```

下一页将 `next_cursor` 原样放进相同请求的 `cursor`；其他字段不变，包括 page_size/include_total。
游标只绑定查询条件和最后记录位置，不绑定数据库版本；更新后不会因为数据切换拒绝旧游标。如果正好跨周更翻页，允许出现重复或遗漏，客户端可重新开始查询。
游标不是认证令牌，也不是加密载荷；访问授权由 Bearer Token 独立处理。

### DBLP Key / DOI 查询

```bash
curl -G http://192.168.1.100:8000/v1/papers/lookup \
  -H "Authorization: Bearer $API_TOKEN" --data-urlencode 'key=conf/icse/example'

curl -G http://192.168.1.100:8000/v1/papers/lookup \
  -H "Authorization: Bearer $API_TOKEN" --data-urlencode 'doi=10.1234/example'
```

key/doi 二选一，DOI 使用不含 URL 前缀的标准值。未命中返回 items=[]，不报网络错误。每次最多返回 100 条（极少数同 DOI 多记录场景）。

### 作者搜索及作者论文

```bash
curl -G http://192.168.1.100:8000/v1/authors/search \
  -H "Authorization: Bearer $API_TOKEN" --data-urlencode 'name=Alice Smith'
```

返回作者候选、author_id 和可用 PID，不需要数据版本参数。

**注意**：dump 的出版物作者通常没有 PID。此时按照姓名生成的是“未验证姓名标签”，不是已经消歧的真实人物；同名作品可能混合，`identity_verified=false`。不要声称本地服务实现了 DBLP 在线作者 PID 消歧。

```bash
curl http://192.168.1.100:8000/v1/authors/123/papers \
  -H "Authorization: Bearer $API_TOKEN"
```

作者数字 ID 属于当前数据库，不建议长期缓存；更新后应重新搜索作者。本版不检测跨更新使用旧 ID 的情况。

## 6. 离线文件导入与备份

如果服务器不能直接下载，可手动准备官方 `dblp.xml.gz` 和 `dblp.dtd`，放进服务器目录 `/srv/dblp-input`：

```bash
docker compose run --rm -v /srv/dblp-input:/input:ro updater \
  update --xml /input/dblp.xml.gz --dtd /input/dblp.dtd
```

首次导入完整建库；后续导入复制正式库为临时副本，增量修改并校验后替换。XML 仅用于可信官方数据；解析器允许指定本地 DBLP DTD 的字符实体，拒绝其他网络/本地实体资源。

数据目录：

```text
/data/
├── dblp.sqlite           # 唯一正式库，包含数据及元数据
├── update-status.json    # 最近更新状态
├── update.lock           # 更新任务互斥锁
└── staging/              # 固定的临时工作目录，任务结束后整个删除
```

数据存在 Compose 命名卷 `dblp_data`（实际名称带项目名前缀），删除容器不丢数据。
**不要执行 `docker compose down -v`，它会删除数据卷。** 备份至少包括 `dblp.sqlite` 和 `update-status.json`；备份期间停止 updater，确保没有正在执行的手动更新。

更新被强制中断时 staging 可能留下临时文件；下次任务获取更新锁后会自动删除并重建固定的 staging 目录。不要把本地导入的 XML/DTD 放在 staging 内，否则会拒绝执行，避免清理时删除源文件。

## 7. 本地开发与测试

```bash
uv sync
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests

# 小样本初始化（不下载整个 DBLP）
DBLP_DATA_DIR=./data uv run dblp-local update \
  --xml tests/fixtures/dblp.xml --dtd tests/fixtures/dblp.dtd

DBLP_API_TOKEN=local-test-token DBLP_DATA_DIR=./data uv run dblp-local serve --host 127.0.0.1
```

Windows PowerShell 使用 `$env:DBLP_DATA_DIR=...` 设置环境变量。

## 8. 验证边界

已通过固定样本的 XML/DTD、AND/OR/NOT/短语、年份/会议、作者、认证、分页、单库原子替换、锁及失败保留旧库测试。Linux 专属的打开旧连接测试在 Windows 上跳过。
Compose 可进行静态校验；本轮未下载完整 DBLP，也未测完整数据的资源开销。当前开发机 Docker 引擎未运行，未宣称 Docker 容器运行验证通过。
服务端目前与现有 SDK 独立，不会自动切换或替代 SDK 中的在线 DBLP Provider。
