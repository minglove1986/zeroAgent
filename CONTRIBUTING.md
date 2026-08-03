# CONTRIBUTING — zeroAgent 贡献指南

> 本文件补充 `AGENTS.md` 中的硬约束，面向外部贡献者。

## 开发环境

详见 [`docs/05-开发指南/环境与密钥.md`](./docs/05-开发指南/环境与密钥.md)。

## 分支规范

```
feat/xxx          # 新功能（对应 PRD 中某个 Task）
fix/xxx           # Bug 修复
refactor/xxx      # 重构，不改行为
docs/xxx          # 文档更新
chore/xxx         # 构建、依赖、CI 变更
```

主要开发分支：`master`（现行），`main`（最终发布）。

## 提交规范（Conventional Commits）

```
feat: 新增知识库向量检索接口
fix: 修复审批过期 Celery task 异常
docs: 补充 README 技术栈说明
refactor: 将 agent 模块拆分为独立 service
```

前缀说明：`feat / fix / docs / refactor / chore / test / style`。

## 代码规范

### Python（后端）

- 版本：Python 3.11+，全部类型注解（PEP 484）
- 风格：[`ruff`](https://astral.sh/ruff) 自动格式化，`line-length=100`
- 测试：[`pytest`](https://pytest.org/)，`asyncio_mode = auto`
- 不提交 `.env`、`__pycache__/`、`.pytest_cache/`、`*.log`、`.data/`

### TypeScript（前端）

- 版本：Node 18+，TypeScript 5.7+
- 规范：Next.js App Router，禁止使用旧的 Pages Router
- 提交前运行：`npm run lint`（各前端子仓）

## 测试要求

```bash
# 后端
pytest -q

# 前端（员工端）
cd web && npm run lint

# 前端（管理端）
cd admin-web && npm run lint
```

所有 PR 必须通过 `pytest -q`，新增功能需补充对应单测。

## PR 规范

1. 描述清楚改动背景和动机
2. 列出测试覆盖情况
3. 如有 Breaking Change，在 PR 标题注明 `[BREAKING]`
4. 关联相关 Issue / Task 编号

## 文档维护

PRD 第十六章为现行唯一裁定。文档改动须同步 `docs/01-产品需求/PRD.md` 对应章节，并在 PR 描述中说明。
