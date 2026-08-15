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

见 [CLAUDE.md](CLAUDE.md#员工管理) 与 [AGENTS.md](AGENTS.md) 的说明——新增员工 = `backend/employees/*.yaml` + `catalog/seeds.py` 注册 + 重启；新工具在 `app/tools/` 定义后登记进 `compiler.ALL_LOCAL_TOOLS`。

## 行为准则

请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。发现安全问题请不要在公开 issue 中提交，走 [SECURITY.md](SECURITY.md) 的渠道。
