# 测试与 Mock 策略

> 2026-07-21 | 面向 AI Agent

## 原则

1. **默认单测不依赖外网**：`MOCK_EXTERNAL=true`
2. 先写失败测试，再写最小实现（计划内 Task）
3. 权限、发布闸门、Agent schema、回调入库必须有测

## 目录

```
tests/
  conftest.py           # app fixture、DB、mock 开关
  test_health.py
  test_auth_login.py
  test_user_create.py
  test_kb_permission_union.py
  test_document_publish_gate.py
  test_agent_schema_rejects_tool_ids.py
  test_im_file_callback.py
  test_message_sse.py
  test_workflow_snapshot.py
  test_department_admin_scope.py
  mocks/
    openim.py
    litellm.py
    oss.py
```

## Mock 边界

| 依赖 | Mock 行为 |
|---|---|
| LiteLLM | `chat.completions` 流式返回固定 delta；可模拟 `ask_user` tool_call |
| OSS | `put_object` 记入内存 dict；`presign` 返回 fake URL |
| Celery | `task.delay` patch 为同步记录 |
| Milvus / Neo4j | P0–P3 可完全 Mock |
| OpenIM | **禁止**：不要编写 OpenIM Mock 或客户端 |

## 必须覆盖的用例（摘要）

| ID | 断言 |
|---|---|
| U1 | KB 并集：用户部门 A+B，KB 仅授 A → 有权 |
| U2 | 文档 `qa_pairs`&lt;5 → 禁止发布 42201 |
| U3 | 召回率 0.65 → 禁止发布 |
| U4 | AgentCreate 含 `tool_ids` → 422 |
| U5 | Web 上传 → 产生 document + 入队 ingest |
| U9 | `ask_user` → SSE `card`；`card-action` 后续跑 |
| U10 | 重复 `card_id` → 42210；过期 → 42211 |
| U6 | RAG 无 citation → 不展示最终答案 |
| U7 | 部门管理员启停用户 → 403 |
| U8 | 用户日调用超 500 → 42901 |

## 命令

```bash
pytest -q
pytest tests/test_kb_permission_union.py -q
MOCK_EXTERNAL=true pytest -q
```
