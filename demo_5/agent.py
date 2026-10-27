"""
Deep Agent 组装模块
===================

把 Deep Agents 的几块“积木”拼在一起：

    模型      阿里百炼，OpenAI 兼容接口
    工具      tools.py 中的自定义工具 + mcp_servers.json 中 MCP 服务器提供的工具
    Skills    skills/ 目录，按需加载（渐进式披露）
    Memory    AGENTS.md，每轮都注入系统提示词
    子代理    researcher / critic，主 Agent 通过内置 task 工具委派
    后端      FilesystemBackend，Agent 看到的 "/" 就是 demo_5 目录
    权限      只允许写 /workspace/，禁止读写 .env
    检查点    AsyncSqliteSaver，对话状态存入 data/checkpoints.db，重启后仍可继续追问

app.py 只负责交互界面；要改 Agent 的能力，优先改这个文件。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents.middleware import TodoListMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import FilesystemBackend

from tools import CUSTOM_TOOLS

# demo_5 目录，所有相对路径都以它为根
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"  # 对话持久化数据（已被 .gitignore 忽略）
load_dotenv(BASE_DIR / ".env")


# ------------------------------------------------------------------
# 1. 模型：阿里百炼 OpenAI 兼容接口
# ------------------------------------------------------------------
def build_model(model_name: str | None = None) -> ChatOpenAI:
    """创建一个指向阿里百炼的聊天模型。

    阿里百炼提供 OpenAI 兼容的 /chat/completions 接口，
    所以直接用 langchain-openai 的 ChatOpenAI，改 base_url 即可。
    """
    api_key = os.getenv("DASHSCOPE_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    if not api_key or not base_url:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY 或 LLM_BASE_URL，请先复制 .env.example 为 .env 并填写。")
    return ChatOpenAI(
        model=model_name or os.getenv("LLM_MODEL") or "qwen3.7-plus",
        api_key=api_key,
        base_url=base_url,
        temperature=float(os.getenv("LLM_TEMPERATURE") or 0.3),
        timeout=120,
        max_retries=2,
    )


# ------------------------------------------------------------------
# 2. MCP：从 mcp_servers.json 读取服务器并加载工具
# ------------------------------------------------------------------
def load_mcp_config() -> dict:
    """读取 MCP 配置，返回 MultiServerMCPClient 需要的 {名称: 连接参数} 字典。

    - "enabled": false 的服务器会被跳过
    - stdio 服务器的 command 写 "python" 时，自动换成当前虚拟环境的解释器
    """
    cfg_path = BASE_DIR / (os.getenv("MCP_CONFIG") or "mcp_servers.json")
    if not cfg_path.exists():
        return {}
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    servers = {}
    for name, conn in raw.get("mcpServers", {}).items():
        conn = {k: v for k, v in conn.items() if k not in ("description", "enabled")}
        if not raw["mcpServers"][name].get("enabled", True):
            continue
        conn.setdefault("transport", "stdio")
        if conn["transport"] == "stdio":
            if conn.get("command") == "python":
                conn["command"] = sys.executable
            conn.setdefault("cwd", str(BASE_DIR))
        servers[name] = conn
    return servers


async def load_mcp_tools() -> tuple[list, list[str]]:
    """逐个连接已启用的 MCP 服务器，返回 (工具列表, 警告列表)。

    单个服务器失败（比如没装 node）只记一条警告，不影响其他服务器。
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    tools, warnings = [], []
    for name, conn in load_mcp_config().items():
        try:
            client = MultiServerMCPClient({name: conn})
            tools.extend(await client.get_tools())
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"MCP 服务器 [{name}] 加载失败：{exc!r}")
    return tools, warnings


# ------------------------------------------------------------------
# 3. 子代理：主 Agent 通过内置的 task 工具把子任务委派给它们
#    子代理有独立的上下文窗口，只把最终结果返回给主 Agent
# ------------------------------------------------------------------
def build_subagents(mcp_tools: list) -> list[dict]:
    sub_model = build_model(os.getenv("SUBAGENT_MODEL") or None)
    return [
        {
            "name": "researcher",
            "description": (
                "许可证调研员。需要查询许可证条款、扫描项目依赖、收集开源合规事实时使用。"
                "给它一个明确的调研问题，它会调用工具收集事实并返回带来源的要点总结。"
            ),
            "system_prompt": (
                "你是一名严谨的资料调研员。使用可用工具收集事实，"
                "只返回与问题相关的要点，每条要点注明来源（工具名或网址）。"
                "最终答复控制在 300 字以内，用中文。"
            ),
            # 不写 tools 时会继承主 Agent 的全部工具；这里显式只给它 MCP 工具
            "tools": mcp_tools,
            "model": sub_model,
        },
        {
            "name": "critic",
            "description": "审稿人。写完合规报告或分析文档后，用它检查错误、遗漏和可改进之处。把要审的全文放进任务描述里。",
            "system_prompt": (
                "你是一名挑剔但建设性的审稿人。阅读给定的文本，"
                "列出最多 5 条具体问题和修改建议，按严重程度排序，用中文回答。"
                "重点检查结构、逻辑、表述和前后矛盾；对技术事实只指出“需核实”，"
                "不要凭记忆断言术语含义或补充文本中没有的数据。"
            ),
            "tools": [],
            "model": sub_model,
        },
    ]


# ------------------------------------------------------------------
# 4. 系统提示词（Memory 和 Skills 列表会被框架自动追加在后面）
# ------------------------------------------------------------------
SYSTEM_PROMPT = """你是「开源合规助手」，帮助开发者在引入第三方开源组件时评估许可证风险，基于 LangChain Deep Agents 构建。

工作方式：
1. 多步骤任务先用 write_todos 列计划，完成一步更新一步。
2. 任务与某个 Skill（技能）匹配时，先用 read_file 读取它的 SKILL.md，再严格按其中的步骤执行。
3. 查询许可证信息、检查兼容性、扫描项目许可证文件时，优先使用 MCP 工具 get_license_info / check_compatibility / scan_project_licenses。
4. 需要较多查资料时，用 task 工具委派给 researcher 子代理，避免主对话上下文膨胀。
5. 产出的报告一律写到 /workspace/ 目录下。
6. 用中文回答，结论先行。合规结论必须注明“仅作教学参考，正式判断以许可证原文为准”，不要替用户做法律结论。
"""


# ------------------------------------------------------------------
# 5. 组装 Deep Agent
# ------------------------------------------------------------------
async def build_checkpointer() -> AsyncSqliteSaver:
    """创建 SQLite 检查点：每一步的完整状态（消息、待办、文件等）都按 thread_id 存盘。

    只要用同一个 thread_id 调用 Agent，就能接着之前的上下文继续对话，程序重启也不丢。
    注意：必须在之后运行 Agent 的同一个事件循环里创建。
    """
    import aiosqlite

    DATA_DIR.mkdir(exist_ok=True)
    conn = await aiosqlite.connect(DATA_DIR / "checkpoints.db")
    return AsyncSqliteSaver(conn)


async def build_agent():
    """创建 Deep Agent，返回 (agent, 信息字典)。"""
    mcp_tools, warnings = await load_mcp_tools()

    # virtual_mode=True：路径被限制在 root_dir 内，无法用 .. 或绝对路径逃逸
    backend = FilesystemBackend(root_dir=BASE_DIR, virtual_mode=True)

    # 权限规则按顺序匹配，第一条命中即生效；都不命中则允许
    permissions = [
        FilesystemPermission(operations=["read", "write"], paths=["/.env", "/.venv/**"], mode="deny"),
        FilesystemPermission(operations=["write"], paths=["/workspace/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]

    agent = create_deep_agent(
        model=build_model(),
        tools=[*CUSTOM_TOOLS, *mcp_tools],
        system_prompt=SYSTEM_PROMPT,
        subagents=build_subagents(mcp_tools),
        skills=["/skills/"],     # 相对 backend 根目录，即 demo_5/skills/
        memory=["/AGENTS.md"],   # 即 demo_5/AGENTS.md
        backend=backend,
        permissions=permissions,
        # 当前版本 deepagents 默认不带 write_todos，需要显式加入任务规划中间件
        middleware=[TodoListMiddleware()],
        checkpointer=await build_checkpointer(),
        name="license-compliance-assistant",
    )

    info = {
        "model": os.getenv("LLM_MODEL") or "qwen3.7-plus",
        "custom_tools": [t.__name__ for t in CUSTOM_TOOLS],
        "mcp_tools": [t.name for t in mcp_tools],
        "skills": sorted(p.name for p in (BASE_DIR / "skills").iterdir() if (p / "SKILL.md").exists()),
        "subagents": ["researcher", "critic", "general-purpose"],
        "warnings": warnings,
    }
    return agent, info


# ------------------------------------------------------------------
# 6. 流式运行：把 Agent 的执行过程转换成简单事件，供命令行和网页共用
# ------------------------------------------------------------------
def _iter_messages(update):
    """从 stream_mode="updates" 的单个节点更新中取出新消息。"""
    if not isinstance(update, dict) or update.get("messages") is None:
        return []
    msgs = getattr(update["messages"], "value", update["messages"])  # 兼容 Overwrite 包装
    return msgs if isinstance(msgs, list) else [msgs]


async def stream_events(agent, question: str, thread_id: str):
    """运行一轮对话，逐个产出事件字典：

    {"type": "token",       "content": "..."}     主 Agent 正在输出的文字片段（流式）
    {"type": "thought",     "content": "..."}     主 Agent 在调用工具前说的话（从流式文字中分离出来）
    {"type": "tool_call",   "depth": 0, "name": ..., "args": {...}}
    {"type": "tool_result", "depth": 0, "name": ..., "content": "..."}
    {"type": "answer",      "content": "..."}     主 Agent 本轮输出的全部文字（过程说明 + 最终回答）

    depth=0 表示主 Agent，depth>=1 表示子代理内部的步骤。
    同时订阅两种流：
      messages  模型逐 token 输出，用于打字机效果
      updates   每个节点执行完后的状态更新，用于拿到完整的工具调用和结果
    """
    from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
    final, buffer, segments = "", "", []
    async for namespace, mode, chunk in agent.astream(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
        stream_mode=["messages", "updates"],
        subgraphs=True,  # 同时输出子代理内部的步骤
    ):
        depth = len(namespace)

        if mode == "messages":
            msg, _meta = chunk
            # 只把主 Agent 模型输出的文字做流式展示；子代理的文字不展示
            if depth == 0 and isinstance(msg, AIMessageChunk) and msg.text:
                buffer += msg.text
                yield {"type": "token", "content": msg.text}
            continue

        for update in chunk.values():
            for msg in _iter_messages(update):
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    if depth == 0 and buffer.strip():
                        # 调用工具前流式输出的文字只是“过程说明”，不是最终回答
                        yield {"type": "thought", "content": buffer}
                        segments.append(buffer.strip())
                    if depth == 0:
                        buffer = ""
                    for call in msg.tool_calls:
                        yield {"type": "tool_call", "depth": depth, "name": call["name"], "args": call["args"]}
                elif isinstance(msg, ToolMessage):
                    yield {"type": "tool_result", "depth": depth, "name": msg.name, "content": msg.text}
                elif isinstance(msg, AIMessage) and depth == 0 and msg.content:
                    final = msg.text
    segments.append((final or buffer).strip())
    yield {"type": "answer", "content": "\n\n".join(x for x in segments if x)}


async def close_agent(agent) -> None:
    """程序退出前关闭 SQLite 连接，避免事件循环关闭后后台线程报错。"""
    saver = getattr(agent, "checkpointer", None)
    if isinstance(saver, AsyncSqliteSaver):
        await saver.conn.close()
