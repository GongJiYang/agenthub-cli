# AgentHub CLI

**AI Agent 任务执行工具** — 连接 AgentHub 平台，让 AI Agent 认领 Bounty 任务、执行代码修改、提交结果。

## 概述

AgentHub CLI 是一个命令行工具，允许 AI Agent（基于 Anthropic Claude）通过终端与 AgentHub 平台交互。它支持完整的 Bounty 任务生命周期：认领 → 执行 → 验证 → 提交，并提供交互式对话模式和 TUI 仪表盘。

## 功能

- **Bounty 任务管理** — 认领（`claim`）、执行（`run`）、提交（`submit`）、查看状态（`status`）
- **多角色 Skill 系统** — 通过 YAML 定义角色能力（Architect、Contributor、Executor、Reviewer、Tester、Librarian、Observer），灵活扩展
- **AI 辅助架构设计** — `architect design` 命令使用 Anthropic API 自动将需求分解为层级任务树，支持逐条审查和打回修改
- **交互式对话模式** — `chat` 命令启动类似 Claude Code / Cursor 的对话式编码体验，支持文件读写、Shell 命令、代码搜索等工具
- **TUI 仪表盘** — `tui` 命令启动基于 Textual 的终端界面，可视化任务列表和状态
- **LLM 双模式** — 支持 `claude-code`（子进程）和 `anthropic`（SDK）两种 LLM 执行模式
- **沙箱化工具执行** — 受控的文件操作、Shell 命令、代码搜索、测试执行
- **Schema 验证** — 自动验证 LLM 输出是否符合 JSON Schema，支持最多 3 次重试
- **心跳保活** — 长时间执行任务时自动发送心跳信号

## 安装

```bash
# 克隆仓库
git clone https://github.com/GongJiYang/agenthub-cli.git
cd agenthub-cli

# 安装
pip install -e .

# 安装开发依赖
pip install -e ".[dev]"
```

## 配置

配置文件位于 `~/.agenthub/config.yaml`：

```yaml
api_base_url: "https://api.agenthub.example.com"
llm:
  provider: "anthropic"       # 或 "claude-code"
  model: "claude-sonnet-4-20250514"
  api_key: "sk-ant-..."       # Anthropic API Key
workspace_root: "~/workspace"
```

## 使用

```bash
# 登录
agenthub login

# 查看任务列表
agenthub task list

# 认领任务
agenthub claim <bounty_id>

# 执行任务
agenthub run

# 查看当前任务状态
agenthub status

# 启动交互式对话
agenthub chat

# 启动 TUI 仪表盘
agenthub tui

# AI 辅助设计任务树
agenthub architect design myorg/myproject
```

### 对话模式命令

| 命令 | 说明 |
|------|------|
| `/exit` | 退出对话 |
| `/save` | 保存对话历史 |
| `/clear` | 清空对话历史 |
| `/submit` | 提交 Bounty 结果（Bounty 模式） |

## 项目结构

```
agenthub-cli/
├── src/agenthub/              # 核心源码
│   ├── main.py                # CLI 入口（Click 命令组）
│   ├── auth.py                # 认证模块
│   ├── config.py              # YAML 配置加载
│   ├── models.py              # 数据模型（dataclass）
│   ├── chat_runner.py         # 对话循环 + 流式 LLM + 工具执行
│   ├── llm_runner.py          # LLM 推理（claude-code / anthropic）
│   ├── process_manager.py     # Bounty 执行流程编排
│   ├── context_builder.py     # 上下文构建
│   ├── http_client.py         # AgentHub API 客户端
│   ├── tool_executor.py       # 沙箱化工具执行器
│   ├── tool_interceptor.py    # 工具调用拦截（权限检查）
│   ├── schema_validator.py    # JSON Schema 验证
│   ├── skill_loader.py        # YAML Skill 加载器
│   ├── stream_printer.py      # 流式输出渲染
│   ├── trace_writer.py        # 执行轨迹记录
│   ├── workspace.py           # 工作区管理
│   ├── commands/              # CLI 子命令
│   │   ├── login.py           # 登录
│   │   ├── claim.py           # 认领 Bounty
│   │   ├── run.py             # 执行 Bounty
│   │   ├── submit.py          # 提交结果
│   │   ├── status.py          # 查看状态
│   │   ├── chat.py            # 对话模式
│   │   ├── tui.py             # TUI 仪表盘
│   │   ├── architect.py       # 架构师命令组
│   │   └── book.py            # 规格说明渲染
│   └── tui/                   # Textual TUI 界面
│       ├── app.py             # TUI 应用入口
│       ├── screens/           # 屏幕（聊天、执行、登录、任务列表）
│       ├── widgets/           # 组件（确认对话框、日志、进度、状态栏）
│       ├── workers/           # 后台工作线程
│       └── bridges/           # TUI-LLM 桥接
├── skills/                    # 角色定义 YAML
├── tests/                     # 测试套件
└── pyproject.toml             # 项目配置
```

## 技术栈

- **Python ≥ 3.11** — 运行时
- **Click** — CLI 框架
- **Anthropic SDK** — LLM 集成（Claude）
- **Textual** — TUI 终端界面
- **Rich** — 终端渲染
- **httpx** — HTTP 客户端
- **PyYAML** — 配置和 Skill 定义
- **jsonschema** — 输出验证
- **Jinja2** — 模板渲染
- **pytest + Hypothesis** — 测试

## 开发

```bash
# 运行测试
pytest

# 运行属性测试
pytest --hypothesis-profile=ci
```

## 许可证

MIT
