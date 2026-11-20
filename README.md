# 教育智能客服 v2

沿用课堂参考项目的 API → Service → Repository 分层和 `DialogueEngine → TurnPlanner → TurnPlanValidator` 主线。配置在启动时加载，运行中的任务固定流程版本；会话、轮次和消息使用已有 MySQL 三表。

## 后端目录

| 路径 | 职责 |
| --- | --- |
| `main.py` | 启动入口，仅导出 FastAPI 应用。 |
| `edu_assistant/api/` | 应用装配、路由、请求契约、身份注入与 SSE。 |
| `edu_assistant/service/dialogue_service.py` | 会话操作与对话轮次编排。 |
| `edu_assistant/repository/` | 三表映射、事务和持久化。 |
| `edu_assistant/engine/`、`edu_assistant/plan/` | 对话执行、模型规划与校验。 |
| `edu_assistant/task/` | 流程目录和中台业务动作。 |
| `edu_assistant/conf/`、`edu_assistant/domain/` | 配置和共享类型。 |

## 本地启动

1. 按 `edu-data` 原有方式启动中台，默认地址为 `http://127.0.0.1:8000`。
2. 在 v2 的 `.env` 本地填写 `CHAT_DATABASE_URL`，格式为 `mysql+pymysql://账号:密码@主机:3306/库名`；密码有 URL 保留字符时需编码。设置 `CHAT_DEMO_AUTH_ENABLED=true`，仅用于本机演示。填写 `MODEL_NAME`、`MODEL_API_KEY`，需要自定义 OpenAI 兼容接口时填写 `MODEL_BASE_URL`（如服务的 `/v1` 根路径）。模型留空时仍可创建和读取会话，但不能规划普通消息。
3. 在 v2 目录运行 `uv sync`，再运行 `uv run uvicorn main:app --host 127.0.0.1 --port 8001`。
4. 在 `edu-web` 的 `.env` 设置 `VITE_ASSISTANT_ENABLED=true`、`ASSISTANT_API_TARGET=http://127.0.0.1:8001`。运行 `npm run dev`，连接有效学习账号后进入智能客服。

会话表按已有映射使用 `chat_session`、`chat_turn`、`chat_message`。服务不建表、不迁移，不兼容的旧快照只查看历史，请另开 v2 会话；不要让两版服务同时向同一会话写入。演示身份不是真实认证，不对外暴露。

## 业务与恢复

- 课程、订单和学习进度读取中台接口；订单不展示中台未提供的报名明细。
- 新发起的退款任务在核验本人订单后返回「前往退款」。点击后打开订单页的申请退款弹窗，并带入核验过的订单 ID。选择商品后，弹窗按该明细的应付金额预填申请金额，允许填写大于零且不超此金额的值。用户在弹窗核对并提交，接口成功后自动回到原客服会话；退款资格由中台判断。
- 退款流程继续通过 YAML 的 `guard` 拦截 `cancelled`，此时提示重新选择订单。客服使用 `ORDER_ITEMS_BASE_URL`（默认 `http://127.0.0.1:8002`）核验本人订单是否已有待审核或已审核未完成的退款申请。处理中时提示查看进度或换单。旧卡片点击后及客服跳转的弹窗提交前同样核验。已开始的旧版退款任务继续使用原流程，可取消旧任务后重新发起。工单仍通过「前往服务工单」进入业务页面办理。
- 手动验收可从客服提交本人订单编号或选择订单，检查入口、单明细预选和多明细选择、金额预填与超限提示，再核对已取消订单、已有退款处理中时不发新入口、历史入口拒绝跳转、接口拒绝时弹窗保留，以及成功后回到原会话。
- 消息支持 JSON 与 POST SSE。断流时按原 `clientMessageId` 查询历史，必要时保留原 ID、正文和状态版本重放；不会自动生成新轮。连续 60 分钟无有效交互后开启新会话，旧历史仍可读取。
- 聊天页可二次确认清空当前 v2 会话。服务端删除该会话的全部消息和轮次，清除任务槽位并推进状态版本，保留标题和原有过期时间；处理中或只读旧版会话不能清空，不影响业务申请。
- 「删除会话」在二次确认后连同标题、消息和轮次一起永久删除；其他会话和中台业务申请不受影响。旧版会话不必迁移即可删除，但处理中或仍有待核对业务提交的会话不能删除。

## 知识目录

`knowledge/releases/v1/catalog.yaml` 是空的首版目录，无命中时不会编造政策、联系方式或处理时限。发布已审核内容时新增目录（例如 `v2`），文件内声明同名 `version`，在 `entries` 中加入唯一 `id`、`title` 和 `answer`，再用 `KNOWLEDGE_VERSION` 切换并重启。

实现与启动说明待用户手动验收；未运行测试、未启动服务、未连接数据库。
