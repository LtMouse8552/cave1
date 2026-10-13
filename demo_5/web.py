"""
Demo 5：Deep Agents 网页界面（Streamlit）
========================================

启动：
    streamlit run web.py

浏览器会自动打开 http://localhost:8501

功能：
- 流式输出：回答逐字显示，工具调用过程实时展示
- 历史会话：所有对话自动保存到 data/，侧边栏可切换任意历史会话并继续追问
- 刷新不丢：当前会话 ID 记在网址的 ?thread= 参数里，刷新或收藏网址都能回到该会话

实现要点：
- Agent、MCP 工具、SQLite 检查点都是异步的，而 Streamlit 每次交互都会从头重跑脚本。
  所以这里开一个常驻的后台事件循环线程，Agent 只创建一次，始终在这个循环里运行；
  页面线程通过队列接收执行事件，实时刷新界面。
- 命令行版 app.py 和本文件共用 agent.py 的 build_agent() / stream_events() 和 history.py。
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading

import streamlit as st

import history
from agent import BASE_DIR, build_agent, stream_events

WORKSPACE = BASE_DIR / "workspace"

st.set_page_config(page_title="Deep Agents 课程助教", page_icon="🧠", layout="wide")


# ------------------------------------------------------------------
# 后台事件循环 + Agent（整个进程只创建一次，所有浏览器标签页共享）
# ------------------------------------------------------------------
@st.cache_resource(show_spinner="正在初始化 Agent（加载 MCP 服务器、Skills、Memory）……")
def get_runtime():
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True, name="agent-loop").start()
    agent, info = asyncio.run_coroutine_threadsafe(build_agent(), loop).result()
    return loop, agent, info


def run_in_loop(coro):
    """在后台事件循环中执行协程并等待结果。"""
    loop, _, _ = get_runtime()
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def iter_events(question: str, thread_id: str):
    """同步生成器：在后台循环里跑 stream_events，把事件通过队列交给页面线程。"""
    loop, agent, _ = get_runtime()
    q: queue.Queue = queue.Queue()
    done = object()

    async def pump():
        try:
            async for ev in stream_events(agent, question, thread_id):
                q.put(ev)
        except Exception as exc:  # noqa: BLE001
            q.put({"type": "error", "content": repr(exc)})
        finally:
            q.put(done)

    asyncio.run_coroutine_threadsafe(pump(), loop)
    while (ev := q.get()) is not done:
        yield ev


async def _get_todos(agent, thread_id: str):
    """从检查点读取该会话最新的待办清单。"""
    state = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    return (state.values or {}).get("todos") or []


# ------------------------------------------------------------------
# 渲染工具
# ------------------------------------------------------------------
def _short(text, limit: int) -> str:
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, indent=2)
    return text if len(text) <= limit else text[:limit] + "\n…（已截断）"


def render_step(ev: dict) -> None:
    """渲染一条执行步骤：工具调用或工具返回。"""
    prefix = "　　↳ 子代理 · " if ev.get("depth") else ""
    if ev["type"] == "tool_call":
        icon = "🤖" if ev["name"] == "task" else "📋" if ev["name"] == "write_todos" else "🔧"
        st.markdown(f"{prefix}{icon} 调用 **`{ev['name']}`**")
        st.code(_short(ev["args"], 600), language="json")
    elif ev["type"] == "tool_result":
        st.caption(f"{prefix}↩️ `{ev['name']}` 返回")
        st.text(_short(ev["content"], 400))


def render_todos(todos: list) -> None:
    icons = {"completed": "✅", "in_progress": "⏳", "pending": "⬜"}
    for t in todos:
        st.markdown(f"{icons.get(t.get('status'), '⬜')} {t.get('content', '')}")


def switch_to(thread_id: str) -> None:
    """切换当前会话，并把会话 ID 写进网址，刷新页面也不会丢。"""
    st.session_state.thread_id = thread_id
    st.query_params["thread"] = thread_id


# ------------------------------------------------------------------
# 初始化
# ------------------------------------------------------------------
try:
    _, agent, info = get_runtime()
except Exception as exc:  # noqa: BLE001
    st.error(f"Agent 初始化失败：{exc}")
    st.info("请检查 demo_5/.env 中的 DASHSCOPE_API_KEY 和 LLM_BASE_URL。")
    st.stop()

if "thread_id" not in st.session_state:
    # 优先使用网址里的会话 ID（刷新页面或打开收藏的网址时）
    switch_to(st.query_params.get("thread") or history.new_thread_id())

thread_id = st.session_state.thread_id
sessions = history.list_sessions()
messages = history.load_messages(thread_id)


# ------------------------------------------------------------------
# 侧边栏：会话列表、能力、待办、产出文件
# ------------------------------------------------------------------
with st.sidebar:
    st.header("🧠 Deep Agent")
    if st.button("➕ 新会话", use_container_width=True, type="primary"):
        switch_to(history.new_thread_id())
        st.rerun()

    st.subheader("💬 历史会话")
    if not sessions:
        st.caption("还没有历史会话，提问后会自动保存。")
    with st.container(height=260 if len(sessions) > 6 else "content", border=False):
        for s in sessions:
            current = s["thread_id"] == thread_id
            label = f"{'▶ ' if current else ''}{s['title']}"
            if st.button(
                label,
                key=f"s-{s['thread_id']}",
                help=f"{s['updated_at']} · {s['n']} 条消息",
                use_container_width=True,
                disabled=current,
            ):
                switch_to(s["thread_id"])
                st.rerun()

    if messages:
        with st.expander("✏️ 管理当前会话"):
            title = next((s["title"] for s in sessions if s["thread_id"] == thread_id), "")
            new_title = st.text_input("会话标题", value=title)
            c1, c2 = st.columns(2)
            if c1.button("重命名", use_container_width=True):
                history.rename_session(thread_id, new_title)
                st.rerun()
            if c2.button("🗑️ 删除", use_container_width=True):
                history.delete_session(thread_id)
                run_in_loop(agent.checkpointer.adelete_thread(thread_id))  # 同时删除 Agent 的检查点
                switch_to(history.new_thread_id())
                st.rerun()

    st.divider()
    st.markdown(f"**模型**　`{info['model']}`")
    for w in info["warnings"]:
        st.warning(w)
    with st.expander("🔧 工具与能力"):
        st.markdown("**自定义工具**　" + "、".join(f"`{t}`" for t in info["custom_tools"]))
        st.markdown("**MCP 工具**　" + ("、".join(f"`{t}`" for t in info["mcp_tools"]) or "无"))
        st.markdown("**Skills**　" + ("、".join(f"`{s}`" for s in info["skills"]) or "无"))
        st.markdown("**子代理**　" + "、".join(f"`{s}`" for s in info["subagents"]))
        st.markdown("**内置工具**　`write_todos` `ls` `read_file` `write_file` `edit_file` `glob` `grep` `task`")

    st.subheader("📋 任务清单")
    todos = run_in_loop(_get_todos(agent, thread_id)) if messages else []
    if todos:
        render_todos(todos)
    else:
        st.caption("多步骤任务时，Agent 会在这里列出计划。")

    st.subheader("📁 产出文件 workspace/")
    files = sorted(p for p in WORKSPACE.rglob("*") if p.is_file() and p.name != ".gitkeep")
    if not files:
        st.caption("暂无文件。")
    for p in files:
        rel = p.relative_to(WORKSPACE).as_posix()
        with st.expander(rel):
            content = p.read_text(encoding="utf-8", errors="replace")
            st.download_button("下载", content, file_name=p.name, key=f"dl-{rel}", use_container_width=True)
            if p.suffix == ".md":
                st.markdown(content)
            else:
                st.code(content)


# ------------------------------------------------------------------
# 主区域：对话
# ------------------------------------------------------------------
st.title("🧠 Deep Agents 课程助教")
st.caption("LangChain Deep Agents ＋ 阿里百炼 ｜ 流式输出 · 历史会话 · Skills · MCP · 子代理")

EXAMPLES = [
    "今天星期几？计算 2**20-1",
    "课程一共有哪些实验？demo_2 讲什么？",
    "讲解一下 /tools.py 这个文件",
    "帮我写一份 demo_5 的实验报告",
]

for msg in messages:
    with st.chat_message(msg["role"]):
        if msg.get("steps"):
            calls = sum(e["type"] == "tool_call" for e in msg["steps"])
            with st.expander(f"🛠️ 执行过程（调用 {calls} 次工具）"):
                for ev in msg["steps"]:
                    render_step(ev)
        st.markdown(msg["content"])

question = st.chat_input("输入问题；在历史会话中可以直接继续追问")

if not messages and not question:
    st.markdown("#### 试试这些问题")
    cols = st.columns(len(EXAMPLES))
    for col, ex in zip(cols, EXAMPLES):
        if col.button(ex, use_container_width=True):
            question = ex

if question:
    history.save_message(thread_id, "user", question)
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        status = st.status("思考中……", expanded=False)
        placeholder = st.empty()
        text, steps, answer = "", [], ""

        for ev in iter_events(question, thread_id):
            kind = ev["type"]
            if kind == "token":
                text += ev["content"]
                placeholder.markdown(text + "▌")
            elif kind == "thought":
                text += "\n\n"  # 工具调用前的说明文字已显示，后续内容另起一段
            elif kind in ("tool_call", "tool_result"):
                steps.append(ev)
                with status:
                    render_step(ev)
                calls = sum(e["type"] == "tool_call" for e in steps)
                status.update(label=f"工作中……已调用 {calls} 次工具", state="running")
            elif kind == "error":
                answer = (text + "\n\n" if text else "") + f"❌ 出错了：{ev['content']}"
            elif kind == "answer":
                answer = ev["content"]

        calls = sum(e["type"] == "tool_call" for e in steps)
        if calls:
            status.update(label=f"完成，调用了 {calls} 次工具", state="complete", expanded=False)
        else:
            status.update(label="完成（未调用工具）", state="complete", expanded=False)
        answer = answer or text or "（没有生成回答）"
        placeholder.markdown(answer)

    history.save_message(thread_id, "assistant", answer, steps)
    st.rerun()  # 刷新侧边栏中的会话列表、任务清单和产出文件
