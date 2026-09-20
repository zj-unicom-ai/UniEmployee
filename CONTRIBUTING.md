# 参与贡献

感谢你对 UniEmployee 的关注。无论修 Bug、加功能、写文档还是提建议，都欢迎。

## 开发环境

- Python 3.12+，Node.js 18+
- 复制 `.env.example` 为 `.env` 并填入模型配置（见 [README](README.md#快速开始)）

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock.txt

# 前端依赖（仅前端开发需要）
cd frontend && npm install
```

## 代码规范

- 仓库未强制 lint/typecheck，但请保持与相邻代码一致的风格（中文注释、`app.*` 模块引用）。
- 后端代码改动必须通过测试自检：无对应测试文件的改动至少保证 `pytest tests/ -q` 通过。
- 测试在项目根目录运行，依赖 `PYTHONPATH=backend`：

```bash
PYTHONPATH=backend .venv/bin/python -m pytest tests/ -v
```

- 慢测试（联网/浏览器）用 `@pytest.mark.slow` 标记，默认跳过。
- 测试夹具（`tests/conftest.py`）会把 SQLite 库替换为临时文件，不会触碰真实数据。

## 分支与提交

1. 从 `main` 切功能分支：`git checkout -b feat/my-change`
2. 提交信息用中文或英文均可，建议遵循 Conventional Commits 风格（`feat:` / `fix:` / `docs:` / `refactor:` 等）
3. 保持提交小且聚焦，一个提交只做一件事

## 提交 PR

1. 先同步远端 `main`，解决冲突
2. 在 PR 描述里说明改动动机与验证方式（跑了哪些测试、是否手动验证过对话/审批/前端页面）
3. CI 会跑后端 pytest 与前端构建，请确保通过

## 新增数字员工 / 技能 / 工具

平台的核心扩展方式是"编排"：员工 = 人设 + 技能规程 + 工具 + 连接器的组合，多数扩展不需要动编译层。实操手册：

- [新增数字员工指南](docs/guide/add-employee.md)——yaml 字段表、种子注册、老库幂等补缺、四个必踩坑位
- [技能规程（SKILL.md）编写规范](docs/guide/skill-authoring.md)——结构模板、触发条件提取规则、看板输出约定
- [自定义工具开发](docs/guide/custom-tools.md)——三处登记、人工审批标记、运行时上下文、产物文件推送

一份改动如果新增了种子（员工/工具/连接器/自动化任务模板），请新增或更新对应的 `tests/test_catalog.py` 用例（含老库 backfill 幂等回归）。

## 发布流程（维护者）

版本号遵循语义化直觉：功能新增进位小数点后第二位（0.14.0 → 0.14.1 可承载完整新员工），修复进第三位。

1. 更新 `CHANGELOG.md`（新增版本小节，按「新增 / 修复 / 升级说明」分块）与版本号四处：`backend/app/main.py` 的 `APP_VERSION`、`frontend/package.json`、两份 README 的 APP_VERSION 表；
2. 提交 `chore(release): vX.Y.Z 版本号 + CHANGELOG` 随功能分支合入 main；
3. squash 合并后在 main 上打 tag 并创建 Release：`gh release create vX.Y.Z --target main --title "vX.Y.Z：一句话" --notes <CHANGELOG 小节改写>`。

## 行为准则

请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。发现安全问题请不要在公开 issue 中提交，走 [SECURITY.md](SECURITY.md) 的渠道。
