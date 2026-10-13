# Demo 5：LangChain Deep Agents 智能体（阿里百炼 + Skills + MCP）

本实验用 [LangChain Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) 搭建一个“课程助教”智能体。
模型通过阿里百炼的 OpenAI 兼容接口调用，并接入了 Skills（技能）、MCP（模型上下文协议）、子代理、长期记忆和文件系统。

提供两种界面：网页版 `web.py` 和命令行版 `app.py`，两者共用同一个 Agent。

命令行运行效果：

```
正在初始化 Agent（加载 MCP 服务器、Skills、Memory）……
模型       qwen3.7-plus
自定义工具 get_current_time, calculator
MCP 工具   list_course_demos, get_course_demo, text_stats
Skills     code-explainer, report-writer
子代理     researcher, critic, general-purpose

你：今天星期几？另外列出课程有哪些实验，并计算 17*23+5
[主Agent] 调用工具 get_current_time {}
[主Agent] 调用工具 list_course_demos {}
[主Agent] 调用工具 calculator {"expression": "17*23+5"}
  ↳ calculator 返回：396
助教：今天是星期二……17 × 23 + 5 = 396
```

---

## 一、Deep Agents 是什么

普通的 Agent 只是“模型 + 工具”的循环。Deep Agents 在这个循环外面加了一层“线束”（harness），让 Agent 能处理长时间、多步骤的复杂任务：

| 能力 | 作用 | 本项目中的体现 |
|---|---|---|
| 任务规划 | 用 `write_todos` 把大任务拆成待办清单 | 写报告前先列计划 |
| 文件系统 | `ls / read_file / write_file / edit_file / glob / grep` | 读源码、把报告写进 `workspace/` |
| 子代理 | 用 `task` 把子任务交给独立上下文的子 Agent | `researcher` 调研、`critic` 审稿 |
| Skills | 按需加载的“操作手册”，平时只占一行描述 | `report-writer`、`code-explainer` |
| Memory | `AGENTS.md`，每次对话都注入 | 课程信息、回答偏好、项目约定 |
| MCP | 用标准协议接入外部工具服务器 | 本地 `course-info` 服务器，可选 fetch 和 filesystem |

---

## 二、目录结构

```
demo_5/
├── web.py               # 网页界面（Streamlit）
├── app.py               # 命令行界面
├── agent.py             # 组装 Deep Agent，并提供两种界面共用的 stream_events()（改能力主要改这里）
├── history.py           # 会话历史存储（SQLite），两种界面共用
├── tools.py             # 自定义 Python 工具
├── mcp_server.py        # 本地 MCP 服务器（FastMCP），被 agent 自动启动
├── mcp_servers.json     # MCP 服务器清单，可开关
├── AGENTS.md            # 长期记忆，每次对话都加载
├── skills/              # 技能目录，每个子目录一个技能
│   ├── report-writer/
│   │   ├── SKILL.md     # 技能说明（带 YAML 头）
│   │   └── template.md  # 技能附带的资源文件
│   └── code-explainer/
│       └── SKILL.md
├── workspace/           # Agent 唯一可写的目录，生成的报告都在这里
├── data/                # 运行后自动生成：checkpoints.db（Agent 状态）、sessions.db（聊天记录）
├── requirements.txt
├── .env.example         # 环境变量模板（可提交）
└── .env                 # 真实密钥（已被 .gitignore 忽略，不要提交）
```

`preview.tsx` 和 `types.ts` 是从官方文档复制来的前端示例片段，与本 Python 实验无关，可以忽略。

---

## 三、启动指南

### 1. 准备环境

需要 Python 3.10 及以上版本，推荐 3.12。在 `demo_5` 目录下执行。

**方式 A：使用 uv（推荐，速度快）**

```bash
cd demo_5
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

**方式 B：使用 pip**

```bash
cd demo_5
python -m venv .venv
.venv\Scripts\activate          # Windows CMD / PowerShell
# source .venv/Scripts/activate   # Git Bash
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

### 2. 配置 API Key

```bash
cp .env.example .env      # Windows CMD 用：copy .env.example .env
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

> **注意**：密钥只能写在 `.env` 里。不要写进代码、`.env.example` 或 README，否则提交到 Git 后就泄露了。

### 3. 运行网页版（推荐）

```bash
streamlit run web.py
# 未激活虚拟环境时：.venv\Scripts\python.exe -m streamlit run web.py
```

浏览器会自动打开 http://localhost:8501 ，页面包括：

| 区域 | 内容 |
|---|---|
| 主区域 | 对话窗口，回答逐字流式输出；首页有 4 个示例问题按钮 |
| 执行过程 | 每条回答上方可展开，实时显示工具调用、子代理步骤和返回结果 |
| 侧边栏·新会话 | 开始一个全新的上下文 |
| 侧边栏·历史会话 | 列出所有保存过的会话，点击即可切换并继续追问 |
| 侧边栏·管理当前会话 | 重命名或删除当前会话 |
| 侧边栏·工具与能力 | 当前模型、自定义工具、MCP 工具、Skills、子代理 |
| 侧边栏·任务清单 | Agent 用 `write_todos` 列出的计划及完成状态 |
| 侧边栏·产出文件 | `workspace/` 中的文件，可预览 Markdown 并下载 |

当前会话的 ID 记在网址的 `?thread=` 参数中，刷新页面或收藏网址都能回到同一个会话。
同一局域网的同学可以通过启动日志中的 Network URL 访问。

### 4. 运行命令行版

```bash
# 开始新会话（已激活虚拟环境时）
python app.py

# 继续最近一次会话
python app.py -c

# 未激活虚拟环境时，直接指定解释器
.venv\Scripts\python.exe app.py

# 只问一个问题；加 -c 则在最近一次会话里追问
python app.py -q "列出课程有哪些实验"
python app.py -c -q "刚才第 2 个实验讲什么？"
```

回答会逐字流式打印。对话中可用的命令：

| 命令 | 作用 |
|---|---|
| `/sessions` | 列出历史会话，带编号 |
| `/load 编号` | 切换到该历史会话，回放记录后可以继续追问 |
| `/history` | 回放当前会话 |
| `/new` | 开始新会话 |
| `/info` | 查看当前模型、工具、技能、子代理 |
| `/help` | 查看帮助 |
| `/exit` | 退出，会话已自动保存 |

### 历史会话说明

- 网页版和命令行版共用同一份历史，在命令行里聊过的会话，网页侧边栏也能看到并继续追问，反之亦然。
- 所有数据保存在 `demo_5/data/`，已被 `.gitignore` 忽略。删除这个目录即可清空全部历史。

### 5. 推荐体验的问题

| 问题 | 会用到的能力 |
|---|---|
| 今天星期几？计算 2**20-1 | 自定义工具 |
| 课程一共有哪些实验？demo_2 讲什么？ | MCP 工具 |
| 讲解一下 /tools.py 这个文件 | Skill：code-explainer |
| 帮我写一份 demo_5 的实验报告 | Skill + 待办规划 + 子代理 + 写文件 |
| 请修改 /agent.py | 权限拦截，只能写 `/workspace/` |

写报告这类长任务会调用十几次工具，用 qwen3.7-plus 大约需要 5 分钟，请耐心等待。

---

## 四、工作原理

```
web.py / app.py ──> agent.build_agent()
                      │
                      ├─ build_model()          ChatOpenAI(base_url=阿里百炼)
                      ├─ load_mcp_tools()       读取 mcp_servers.json，启动 MCP 服务器，拿到工具
                      ├─ build_subagents()      researcher / critic
                      ├─ build_checkpointer()   AsyncSqliteSaver -> data/checkpoints.db
                      ├─ FilesystemBackend      把 demo_5 目录映射为 Agent 眼中的 "/"
                      └─ create_deep_agent(model, tools, system_prompt, subagents,
                                           skills=["/skills/"], memory=["/AGENTS.md"],
                                           backend, permissions, middleware, checkpointer)

每轮提问 ──> agent.stream_events(agent, 问题, thread_id)
                ├─ token / thought     模型逐字输出，用于流式显示
                ├─ tool_call / tool_result   工具调用过程
                └─ answer              本轮完整回答
          ──> history.save_message()   把问答和执行步骤存入 data/sessions.db
```

**流式输出**：`stream_events()` 同时订阅 LangGraph 的两种流。`messages` 流逐 token 给出模型输出，用于打字机效果。`updates` 流在每个节点结束后给出完整的工具调用和结果。

**两个数据库**：

| 文件 | 写入者 | 保存内容 | 用途 |
|---|---|---|---|
| `data/checkpoints.db` | Deep Agents 检查点 | 完整消息、待办、文件状态 | 让模型接着上下文继续回答 |
| `data/sessions.db` | `history.py` | 会话标题、时间、问答文字、执行步骤 | 在界面上列出和回放历史 |

两者通过同一个 `thread_id` 关联。选中历史会话就是拿到它的 `thread_id`，再用它调用 Agent，模型自然能看到之前的上下文。

**网页版的特殊处理**：Agent、MCP 工具和 SQLite 检查点都是异步的，而 Streamlit 每次交互都会从头重跑脚本。
所以 `web.py` 开了一个常驻的后台事件循环线程，Agent 只创建一次并始终在这个循环里运行，页面线程通过队列接收事件并实时刷新。
修改 `agent.py` 后，需要重启 `streamlit run`，因为 Agent 被缓存了。

几个关键点：

1. **路径以 demo_5 为根。** `FilesystemBackend(root_dir=demo_5, virtual_mode=True)` 让 Agent 看到的 `/skills/` 就是 `demo_5/skills/`。`virtual_mode=True` 会阻止 Agent 用 `..` 访问 demo_5 以外的文件。
2. **Skills 是渐进式披露。** 启动时只把每个技能的 `name` 和 `description` 放进系统提示词。Agent 判断任务匹配后，才用 `read_file` 读取完整的 `SKILL.md`，因此技能再多也不会撑爆上下文。
3. **Memory 每轮都加载。** `AGENTS.md` 的全文会拼进系统提示词，适合放“每次都要知道”的信息。
4. **MCP 工具与普通工具没有区别。** `langchain-mcp-adapters` 把 MCP 服务器的工具转换成 LangChain 工具，再和自定义工具一起传给 `tools=`。
5. **子代理有独立上下文。** 主 Agent 调用 `task(子代理名, 任务描述)`，子代理做完只把结论返回，中间过程不占用主对话的上下文。
6. **多轮对话靠检查点。** `AsyncSqliteSaver` 按 `thread_id` 把对话状态存到磁盘，程序重启后仍能继续追问。新会话就是换一个新的 `thread_id`。

---

## 五、修改指南

### 1. 换模型

修改 `.env` 中的 `LLM_MODEL`，例如 `qwen3.6-plus`、`deepseek-v4-pro`、`glm-5.3`、`kimi-k3`。可用模型列表可以这样查询：

```bash
curl -s "$LLM_BASE_URL/models" -H "Authorization: Bearer $DASHSCOPE_API_KEY"
```

选型经验：

- **qwen3.7-plus**：默认，事实准确，工具调用稳定，但较慢。
- **qwen-plus**：速度快，但写长报告时容易编造日期和数据。
- **子代理换小模型**：把 `SUBAGENT_MODEL` 设为 `qwen3.7-flash` 等便宜模型，可以降低成本。

### 2. 新增自定义工具

在 `tools.py` 里写一个带类型注解和 docstring 的函数，并加入 `CUSTOM_TOOLS`：

```python
def word_count(text: str) -> int:
    """统计英文文本的单词数。

    Args:
        text: 要统计的英文文本
    """
    return len(text.split())


CUSTOM_TOOLS = [get_current_time, calculator, word_count]
```

模型完全依靠 docstring 判断何时调用，所以要写清楚“做什么”和“什么时候用”。

### 3. 新增 Skill

在 `skills/` 下新建一个目录，目录名必须和 `name` 一致，只能用小写字母、数字和连字符：

```
skills/
└── quiz-maker/
    ├── SKILL.md
    └── examples.md      # 可选：技能用到的模板、示例、脚本
```

`SKILL.md` 的格式：

```markdown
---
name: quiz-maker
description: 根据课程内容出选择题。当用户说“出题”“做测验”“生成练习题”时使用。
---

# 出题技能

## 执行步骤
1. 用 get_course_demo 获取相关实验的信息。
2. 用 read_file 读取 /skills/quiz-maker/examples.md 参考题型。
3. 生成 5 道单选题，写入 /workspace/quiz.md。
```

重启程序即可生效，可以用 `/info` 确认技能已加载。`description` 最关键，它决定 Agent 能不能想到使用这个技能。

### 4. 新增或开关 MCP 服务器

编辑 `mcp_servers.json`，把 `enabled` 改为 `true` 或 `false`。文件中已预置四个示例：

| 名称 | 默认 | 前置条件 | 能力 |
|---|---|---|---|
| `course-info` | 开 | 无 | 本地 Python 服务器，查询课程信息 |
| `fetch` | 关 | 安装 uv | 抓取网页内容 |
| `filesystem` | 关 | 安装 Node.js | 官方文件系统服务器 |
| `remote-example` | 关 | 有远程地址 | 远程 HTTP MCP 服务器模板 |

本地命令型服务器（stdio）：

```json
"my-server": {
  "enabled": true,
  "transport": "stdio",
  "command": "python",
  "args": ["my_server.py"]
}
```

远程服务器（HTTP）：

```json
"my-remote": {
  "enabled": true,
  "transport": "streamable_http",
  "url": "https://your-server/mcp",
  "headers": {"Authorization": "Bearer xxx"}
}
```

说明：

- `command` 写 `python` 时，程序会自动换成当前虚拟环境的解释器。
- 某个服务器启动失败时，只会打印一条警告，其他功能照常可用。
- 给本地服务器加工具，只需在 `mcp_server.py` 中写函数并加上 `@mcp.tool()`。
- 单独调试 MCP 服务器可以用官方 Inspector：`npx @modelcontextprotocol/inspector python mcp_server.py`。
- 同一个 `mcp_server.py` 也能直接配置到 Claude Desktop、Cursor、Cherry Studio 等客户端中使用。

### 5. 新增子代理

在 `agent.py` 的 `build_subagents()` 返回列表里加一个字典：

```python
{
    "name": "translator",
    "description": "翻译员。需要把中文内容翻译成英文时使用。",
    "system_prompt": "你是专业的技术翻译，保持术语准确，只输出译文。",
    "tools": [],                 # 不写这一项则继承主 Agent 的全部工具
    "model": sub_model,          # 可选，不写则与主 Agent 相同
},
```

`description` 决定主 Agent 什么时候委派给它，要写得具体。框架还会自动提供一个名为 `general-purpose` 的通用子代理。

### 6. 修改记忆和系统提示词

- **长期记忆**：直接编辑 `AGENTS.md`，下次对话生效。
- **系统提示词**：修改 `agent.py` 中的 `SYSTEM_PROMPT`。
- **让 Agent 自己更新记忆**：默认禁止 Agent 写 `AGENTS.md`。如果希望它记住用户信息，在 `agent.py` 的 `permissions` 列表最前面加一条：

```python
FilesystemPermission(operations=["write"], paths=["/AGENTS.md"], mode="allow"),
```

### 7. 调整文件权限

`agent.py` 中的 `permissions` 按顺序匹配，第一条命中即生效：

```python
permissions = [
    FilesystemPermission(operations=["read", "write"], paths=["/.env", "/.venv/**"], mode="deny"),
    FilesystemPermission(operations=["write"], paths=["/workspace/**"], mode="allow"),
    FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
]
```

`mode` 有三种取值：

- **`allow`**：允许执行。
- **`deny`**：拒绝，并把错误返回给模型。
- **`interrupt`**：暂停等待人工审批。使用它需要在 `app.py` 中处理中断和恢复，详见官方文档的 Human-in-the-loop 章节。

### 8. 其他常见改动

| 想做的事 | 修改位置 |
|---|---|
| 换历史存储位置 | `agent.py` 中的 `DATA_DIR`；多人部署可把检查点换成 `langgraph-checkpoint-postgres` |
| 会话标题规则 | `history.py` 中 `save_message()`，默认取第一个问题的前 30 个字 |
| 流式显示的内容 | `agent.py` 中 `stream_events()`，例如也展示子代理的文字 |
| 修改网页布局 | `web.py`，例如在 `EXAMPLES` 中增删示例问题 |
| 最多允许多少步 | `app.py` 中 `recursion_limit` |
| 关闭子代理过程输出 | `app.py` 中把 `subgraphs=True` 改成 `False` |
| 接入 LangSmith 追踪 | `.env` 中设置 `LANGSMITH_TRACING=true` 和 `LANGSMITH_API_KEY` |

---

## 六、常见问题

| 现象 | 原因与解决 |
|---|---|
| `缺少 DASHSCOPE_API_KEY` | 没有创建 `.env`，按第三节第 2 步操作 |
| `401` 或 `Invalid API-key` | Key 填错或已失效，到阿里百炼控制台重新生成 |
| `model not found` | 该地址没有开通此模型，用第五节的 curl 命令查询可用模型 |
| `MCP 服务器 [xxx] 加载失败` | 缺少 `npx` 或 `uvx` 等命令，安装后重试，或把它的 `enabled` 改为 `false` |
| 网页端口被占用 | `streamlit run web.py --server.port 8502` |
| 想清空所有历史会话 | 停止程序后删除 `demo_5/data/` 目录 |
| 改了 agent.py 网页没变化 | Agent 被缓存，按 Ctrl+C 停止后重新 `streamlit run` |
| 中文乱码 | 在 Windows Terminal 中运行，或先执行 `chcp 65001` |
| 回答编造日期或数据 | 换用更强的模型，并在 Skill 中要求“只用工具结果中的事实” |
| `permission denied for write` | 权限规则生效，Agent 只能写 `/workspace/` |

## 参考资料

- Deep Agents 文档：https://docs.langchain.com/oss/python/deepagents/overview
- Deep Agents 源码：https://github.com/langchain-ai/deepagents
- MCP 适配器：https://github.com/langchain-ai/langchain-mcp-adapters
- Agent Skills 规范：https://agentskills.io
- 阿里百炼 OpenAI 兼容接口：https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope
