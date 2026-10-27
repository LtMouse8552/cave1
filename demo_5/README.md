# 开源合规助手（LangChain Deep Agents + Skills + MCP）

帮助开发者在引入第三方开源组件时评估**许可证合规风险**：扫描项目的许可证文件、查询许可证条款、检查整组依赖之间有无 Copyleft 传染风险，并可自动生成一份可存档的合规评估报告。

- **考查路径**：路径 A（技术栈完整的智能体应用，对标 demo_5）
- **用户与场景**：准备在课程项目或个人项目中使用开源库的大学生；一句话提问即可完成「扫描 → 查条款 → 判风险 → 出报告」的多步合规评估
- **模型**：阿里百炼（OpenAI 兼容接口，默认 qwen3.7-plus）
- **界面**：Streamlit 网页版（`web.py`）与命令行版（`app.py`），共用同一个 Agent

---

## 一、与课堂 demo_5 的关系（增量说明）

本项目以课堂 demo_5（LangChain Deep Agents 课程助教实验）为骨架，允许使用课堂代码，但做了以下**可指认的增量**：

| 增量点 | 课堂 demo_5 | 本项目 |
| --- | --- | --- |
| 场景 | 课程助教问答 | 开源许可证合规评估（新场景） |
| MCP 服务器 | `course-info`：3 个课程信息查询工具 | `license-info`：3 个合规工具（`mcp_server.py`，知识库外置 `licenses.json`） |
| 工具 1 | list_course_demos | `get_license_info`：许可证合规要点知识库（外置 JSON，16 种常见 SPDX 标识符，支持名称归一化） |
| 工具 2 | get_course_demo | `check_compatibility`：整组许可证的 Copyleft 传染风险检查，含双 Copyleft 与例外条款提示 |
| 工具 3 | text_stats | `scan_project_licenses`：扫描项目目录中的 LICENSE/COPYING/NOTICE 文件（含 `.md`/`.txt`、连字符命名），并解析 `package.json` / `pyproject.toml` 的 `license` 字段；深度与文件数可配置 |
| Skills | report-writer / code-explainer | `compliance-report`（合规报告 + 模板）/ `license-qa`（许可证讲解） |
| 合规设计 | 无 | 系统提示词强制要求：不替用户做法律结论、识别不出的许可证标“待核实”、报告末尾注明以原文为准 |

保留的框架能力（来自课堂实验）：Deep Agents 任务规划、文件系统、子代理（researcher / critic）、长期记忆（`AGENTS.md`）、SQLite 检查点多轮会话、流式输出、权限隔离（只能写 `/workspace/`）。

---

## 二、总体架构

```
web.py / app.py ──> agent.build_agent()
                      │
                      ├─ build_model()          ChatOpenAI(base_url=阿里百炼)
                      ├─ load_mcp_tools()       启动 license-info MCP 服务器
                      ├─ build_subagents()      researcher（许可证调研）/ critic（审稿）
                      ├─ build_checkpointer()   AsyncSqliteSaver -> data/checkpoints.db
                      ├─ FilesystemBackend      demo_5 目录映射为 Agent 眼中的 "/"
                      └─ create_deep_agent(model, tools, system_prompt, subagents,
                                           skills=["/skills/"], memory=["/AGENTS.md"],
                                           backend, permissions, middleware, checkpointer)
```

MCP 工具链路：`get_license_info` / `check_compatibility` 是离线知识库查询；`scan_project_licenses` 会真实读取磁盘上的第三方项目目录（例如 `node_modules`），对每个许可证文件做文本特征识别。

---

## 三、目录结构

```
demo_5/
├── web.py               # 网页界面（Streamlit）
├── app.py               # 命令行界面
├── agent.py             # 组装 Deep Agent，两种界面共用的 stream_events()
├── history.py           # 会话历史存储（SQLite）
├── tools.py             # 自定义 Python 工具（get_current_time / calculator）
├── mcp_server.py        # 本地 MCP 服务器（FastMCP）：license-info，4 个合规工具
├── mcp_servers.json     # MCP 服务器清单，可开关
├── AGENTS.md            # 长期记忆，每次对话都加载
├── skills/
│   ├── compliance-report/   # 合规报告技能（SKILL.md + template.md）
│   └── license-qa/          # 许可证讲解技能（SKILL.md）
├── workspace/           # Agent 唯一可写的目录，生成的报告都在这里
├── data/                # 运行后自动生成：checkpoints.db、sessions.db（不入库）
├── requirements.txt
├── .env.example         # 环境变量模板（可提交）
└── .env                 # 真实密钥（已被 .gitignore 忽略，不要提交）
```

---

## 四、启动指南

### 0. 本地运行（Ollama，零 API 费用，可选）

没有百炼 Key 时，可用本机 Ollama 跑：

```cmd
ollama pull qwen3.5:0.8B
```

然后在 `.env` 中启用「方案二」（见 `.env.example` 注释说明）：

```ini
DASHSCOPE_API_KEY=ollama-local
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen3.5:0.8B
LITE_MODE=true
LLM_TIMEOUT=300
```

说明：

- `LITE_MODE=true` 会**关闭子代理**并改用精简系统提示词，适配 0.8B 级小模型的能力上限；报告以要点式为主。
- `DASHSCOPE_API_KEY` 只是占位（代码校验非空），本地不需要真实 Key。
- 小模型工具调用不稳定属预期现象；建议升级 `ollama pull qwen2.5:14b` 并把 `LLM_MODEL` 改为对应名称（LITE_MODE 可保持 true，或改 false 启用子代理），无需改代码。
- 切回云端：恢复「方案一」的配置并设置 `LITE_MODE=false` 即可。

### 1. 准备环境

需要 Python 3.10 及以上，推荐 3.12。在 `demo_5` 目录下执行。

**方式 A：使用 uv（推荐）**

```bash
cd demo_5
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

**方式 B：使用 pip**

```cmd
cd demo_5
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

### 2. 配置 API Key

```cmd
copy .env.example .env
```

打开 `.env`，把 `DASHSCOPE_API_KEY` 改成你的阿里百炼 API Key。其余配置项：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 阿里百炼 API Key | 必填 |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | 课程专用地址 |
| `LLM_MODEL` | 主 Agent 模型 | `qwen3.7-plus` |
| `SUBAGENT_MODEL` | 子代理模型，留空则同主模型 | 空 |
| `LLM_TEMPERATURE` | 采样温度 | `0.3` |
| `MCP_CONFIG` | MCP 配置文件 | `mcp_servers.json` |

> **注意**：密钥只能写在 `.env` 里，不要写进代码、`.env.example` 或 README，否则提交到 Git 后就泄露了。

### 3. 运行网页版（推荐）

```cmd
streamlit run web.py
```

浏览器打开 http://localhost:8501 。页面包括：主对话区（流式输出）、可展开的「执行过程」面板（实时显示工具调用）、侧边栏的会话管理 / 工具与能力 / 任务清单 / 产出文件预览。

### 4. 运行命令行版

```cmd
python app.py
python app.py -c          & :: 继续最近一次会话
python app.py -q "MIT 和 GPL 有什么区别"
```

对话中可用命令：`/sessions` `/load 编号` `/history` `/new` `/info` `/help` `/exit`。网页版与命令行版共用同一份历史会话。

---

## 五、推荐演示话术

| 话术 | 演示的能力 |
| --- | --- |
| MIT 和 GPL-3.0 有什么区别？我能把它们混着用吗？ | MCP 工具 `get_license_info` + `check_compatibility`，Skill：license-qa |
| 帮我扫描一下 node_modules，看看依赖都用什么许可证 | 真实文件扫描 `scan_project_licenses`，执行过程面板可见工具调用 |
| 评估一下这个项目的许可证风险，出一份合规报告 | 全流程：扫描 → 查条款 → 判风险 → Skill compliance-report + critic 审稿 → 写入 workspace/ |
| 引入 AGPL-3.0 的库做闭源 SaaS 有什么风险？ | Copyleft 传染分析 + 合规边界说明 |
| 今天星期几？算一下 227/314 保留一位小数 | 自定义工具 get_current_time / calculator |

> 写合规报告这类长任务会调用十几次工具，约需 3~5 分钟，请耐心等待。

---

## 六、常见问题

| 现象 | 原因与解决 |
|---|---|
| `缺少 DASHSCOPE_API_KEY` | 没有创建 `.env`，按第四节第 2 步操作 |
| `401` 或 `Invalid API-key` | Key 填错或失效，到百炼控制台重新生成 |
| `MCP 服务器 [license-info] 加载失败` | 检查 `mcp_servers.json` 中该服务器是否 `enabled: true`，路径是否正确 |
| `permission denied for write` | 权限规则生效，Agent 只能写 `/workspace/` |
| 网页端口被占用 | `streamlit run web.py --server.port 8502` |
| 想清空所有历史会话 | 停止程序后删除 `demo_5/data/` 目录 |
| 改了 agent.py / mcp_server.py 网页没变化 | Agent 与 MCP 进程被缓存，重启 `streamlit run` |

---

## 七、思政与合规说明

- **数据来源**：许可证知识库内容概括自 OSI 与各许可证官方公开文本，仅供教学；`scan_project_licenses` 只读取本机用户指定目录的 LICENSE 类文件，不采集个人信息、不上传数据。
- **使用边界**：助手只做风险提示与教学讲解，不提供法律意见；所有结论都提示「以许可证原文为准，正式合规请咨询法务」。
- **隐私**：项目中不包含任何真实密钥（`.env` 已被 `.gitignore` 忽略）、不包含真实个人信息，演示数据均为公开开源许可证信息。

## 参考资料

- Deep Agents 文档：https://docs.langchain.com/oss/python/deepagents/overview
- MCP 适配器：https://github.com/langchain-ai/langchain-mcp-adapters
- Agent Skills 规范：https://agentskills.io
- SPDX 许可证标识符列表：https://spdx.org/licenses/
- 阿里百炼 OpenAI 兼容接口：https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope
