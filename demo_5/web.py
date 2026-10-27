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

st.set_page_config(page_title="开源合规助手", page_icon="🛡️", layout="wide")


# ------------------------------------------------------------------
# 液态玻璃主题（Liquid Glass / Glassmorphism）
# ------------------------------------------------------------------
GLASS_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
    --glass-bg: rgba(255, 255, 255, 0.55);
    --glass-bg-dark: rgba(255, 255, 255, 0.38);
    --glass-border: rgba(255, 255, 255, 0.65);
    --glass-shadow: 0 8px 32px rgba(31, 38, 135, 0.12);
    --accent: #6C5CE7;
    --radius-xl: 24px;
    --radius-lg: 18px;
    --radius-md: 14px;
    --glass-filter: blur(18px) saturate(1.5);
}

/* ---------- 字体（文字颜色按亮/暗系统偏好分别设置） ---------- */
html, body, .stApp, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', 'Microsoft YaHei UI', 'Microsoft YaHei', sans-serif;
}
@media (prefers-color-scheme: light) {
    html, body, .stApp, [data-testid="stAppViewContainer"] {
        color: #2D3436;
    }
}

/* ---------- 液态光斑背景（挂在最外层容器上） ---------- */
[data-testid="stAppViewContainer"], [data-testid="stAppContainer"] {
    background: linear-gradient(135deg, #EEF2FF 0%, #FDF4FF 45%, #E8F9FF 100%) !important;
}
[data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stMainBlockContainer"], [data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"] {
    background: transparent !important;
}
[data-testid="stAppViewContainer"]::before,
[data-testid="stAppViewContainer"]::after {
    content: '';
    position: fixed;
    border-radius: 50%;
    filter: blur(90px);
    opacity: 0.55;
    z-index: 0;
    pointer-events: none;
    animation: blob 22s ease-in-out infinite alternate;
}
[data-testid="stAppViewContainer"]::before {
    width: 520px; height: 520px;
    background: radial-gradient(circle, #A29BFE 0%, transparent 70%);
    top: -140px; left: -120px;
}
[data-testid="stAppViewContainer"]::after {
    width: 620px; height: 620px;
    background: radial-gradient(circle, #81ECEC 0%, transparent 70%);
    bottom: -180px; right: -150px;
    animation-delay: -8s;
}
@keyframes blob {
    0%   { transform: translate(0, 0) scale(1); }
    50%  { transform: translate(60px, 40px) scale(1.12); }
    100% { transform: translate(-40px, 60px) scale(0.95); }
}

/* 主内容层抬到光斑之上，且自身透明让玻璃发光可见 */
[data-testid="stMain"], [data-testid="stMainBlockContainer"] {
    position: relative;
    z-index: 1;
}

/* ---------- 顶栏透明 ---------- */
[data-testid="stHeader"], [data-testid="stToolbar"] {
    background: transparent !important;
    backdrop-filter: none;
}

/* ---------- 隐藏英文界面元素（仅 Deploy、装饰线；页脚保留以免设置入口丢失） ---------- */
[data-testid="stDeployButton"],
[data-testid="stDecoration"],
button[aria-label="Deploy"] {
    display: none !important;
}

/* ---------- 头部状态栏（Running…/STOP）玻璃圆角 ---------- */
[data-testid="stStatus"], [data-testid="stHeaderStatusWidget"],
[data-testid="stStatusWidget"] {
    border-radius: 999px !important;
    background: var(--glass-bg-dark) !important;
    border: 1px solid var(--glass-border) !important;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    overflow: hidden;
}

/* ---------- 右上角工具栏保留（含侧边栏呼出按钮），但按钮改为半透明玻璃感 ---------- */
[data-testid="stToolbar"] [data-testid="stBaseButton-header"],
[data-testid="stToolbar"] button {
    background: var(--glass-bg-dark) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: var(--radius-md) !important;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
}

/* ---------- 页脚（含 Manage app 设置入口）玻璃化 ---------- */
[data-testid="stAppFooter"], footer {
    background: transparent !important;
    opacity: 0.6;
}
[data-testid="stAppFooter"] a, footer a {
    color: rgba(108, 92, 231, 0.8) !important;
}

/* ---------- 侧边栏：竖向玻璃面板 ---------- */
[data-testid="stSidebar"], [data-testid="stSidebarUserContent"] {
    background: var(--glass-bg) !important;
}
[data-testid="stSidebar"] {
    backdrop-filter: blur(24px) saturate(1.6) !important;
    -webkit-backdrop-filter: blur(24px) saturate(1.6) !important;
    border-right: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow);
}
@media (prefers-color-scheme: light) {
    [data-testid="stSidebar"] * {
        color: #2D3436;
    }
}

/* ---------- 通用玻璃卡片（1.65 的组件 testid） ---------- */
[data-testid="stChatMessage"],
[data-testid="stExpander"],
[data-testid="stStatusWidget"],
.stCodeBlock,
[data-testid="stAlert"],
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--glass-bg) !important;
    backdrop-filter: var(--glass-filter) !important;
    -webkit-backdrop-filter: var(--glass-filter) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: var(--radius-lg) !important;
    box-shadow: var(--glass-shadow);
}
[data-testid="stExpanderDetails"] {
    background: transparent !important;
    border: none !important;
}

/* ---------- 聊天气泡 ---------- */
[data-testid="stChatMessage"] {
    border-radius: var(--radius-xl) !important;
    padding: 14px 18px;
    margin-bottom: 14px;
    animation: rise 0.35s ease-out;
}
@keyframes rise {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}
[data-testid="stChatMessageAvatarUser"] {
    background: linear-gradient(135deg, #6C5CE7, #a29bfe);
}
[data-testid="stChatMessageAvatarAssistant"] {
    background: linear-gradient(135deg, #00CEC9, #81ECEC);
}

/* ---------- 按钮：胶囊玻璃 ---------- */
.stButton > button, .stDownloadButton > button,
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-tertiary"] {
    border-radius: 999px !important;
    border: 1px solid var(--glass-border) !important;
    background: var(--glass-bg-dark) !important;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    transition: all 0.25s ease !important;
    font-weight: 500;
}
.stButton > button:hover, .stDownloadButton > button:hover,
[data-testid="stBaseButton-secondary"]:hover {
    background: rgba(108, 92, 231, 0.14) !important;
    border-color: var(--accent) !important;
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(108, 92, 231, 0.25);
}
[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #6C5CE7, #8E7CF3) !important;
    color: #fff !important;
    border: none !important;
    box-shadow: 0 6px 18px rgba(108, 92, 231, 0.35);
}
[data-testid="stBaseButton-primary"]:hover {
    filter: brightness(1.08);
    transform: translateY(-2px);
}

/* ---------- 输入框：玻璃胶囊 ---------- */
[data-testid="stChatInput"], [data-testid="stChatInput"] > div {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
[data-testid="stChatInputTextArea"], [data-testid="stChatInput"] textarea {
    border-radius: 999px !important;
    background: rgba(255, 255, 255, 0.7) !important;
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow);
}
[data-testid="stChatInputTextArea"]:focus, [data-testid="stChatInput"] textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(108, 92, 231, 0.18);
}
.stTextInput > div > div > input {
    border-radius: 999px !important;
    background: rgba(255, 255, 255, 0.7) !important;
    border: 1px solid var(--glass-border) !important;
}

/* ---------- 执行过程状态框 ---------- */
[data-testid="stStatusWidget"] {
    border-radius: var(--radius-lg) !important;
    padding: 10px 16px;
}

/* ---------- 代码块 ---------- */
.stCodeBlock, .stCodeBlock > div {
    border-radius: var(--radius-md) !important;
    overflow: hidden;
}
.stCodeBlock code {
    font-family: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace !important;
    font-size: 0.85rem;
}

/* ---------- 滚动条 ---------- */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: rgba(108, 92, 231, 0.35);
    border-radius: 999px;
}
::-webkit-scrollbar-thumb:hover { background: rgba(108, 92, 231, 0.55); }

/* ---------- 分隔线弱化 ---------- */
hr {
    border: none !important;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(108,92,231,0.35), transparent);
}

/* ---------- 下拉框 / 输入类组件圆角补齐 ---------- */
/* Streamlit 1.65 下拉框 = react-aria-ComboBox，可视控件是其中的 <input>，
   必须直接对 input 套圆角，否则方角会盖在圆角包装层上面 */
[data-testid="stSelectbox"] > div,
.react-aria-ComboBox,
[data-testid="stSelectbox"] input,
.react-aria-ComboBox input,
[data-testid="stMultiselect"], [data-testid="stDateInput"],
[data-testid="stNumberInput"], [data-testid="stTextArea"] > div,
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label,
[data-testid="stSlider"] > div > div {
    border-radius: var(--radius-md) !important;
    overflow: hidden;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
}
[data-testid="stSelectbox"] input,
.react-aria-ComboBox input {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: 999px !important;
}
/* ComboBox 外层容器 = 玻璃胶囊，整体裁剪 input 与箭头按钮 */
[data-testid="stSelectbox"] [role="group"],
.react-aria-ComboBox > div {
    border-radius: 999px !important;
    overflow: hidden !important;
    background: rgba(255, 255, 255, 0.7) !important;
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow);
}
/* 右侧箭头按钮：透明融入胶囊 */
.react-aria-ComboBox button {
    background: transparent !important;
    border: none !important;
    border-radius: 999px !important;
}
@media (prefers-color-scheme: dark) {
    [data-testid="stSelectbox"] [role="group"],
    .react-aria-ComboBox > div {
        background: rgba(45, 45, 68, 0.7) !important;
        color: #E8E8F0;
    }
}
/* 内联代码块（如侧边栏的模型名）做成玻璃胶囊 */
code {
    border-radius: 999px !important;
    padding: 2px 8px;
}
/* 下拉选项弹出层 */
[data-baseweb="popover"], [data-testid="stSelectbox"] [data-baseweb="popover"] > ul,
[data-testid="stSelectbox"] > div [role="listbox"],
[role="listbox"] {
    border-radius: var(--radius-md) !important;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.92) !important;
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--glass-border) !important;
    box-shadow: var(--glass-shadow);
}
@media (prefers-color-scheme: dark) {
    [data-baseweb="popover"],
    [role="listbox"] {
        background: rgba(35, 35, 55, 0.95) !important;
    }
}
[data-testid="stSidebar"] [data-testid="stExpander"],
[data-testid="stSidebar"] .stButton > button {
    border-radius: var(--radius-md) !important;
}
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

/* ---------- 深色模式：暗色玻璃（Streamlit 1.65 不设 data-theme，按系统偏好） ---------- */
@media (prefers-color-scheme: dark) {
    :root {
        --glass-bg: rgba(30, 30, 48, 0.55);
        --glass-bg-dark: rgba(45, 45, 68, 0.45);
        --glass-border: rgba(255, 255, 255, 0.14);
        --glass-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
    }
    body, .stApp, [data-testid="stAppViewContainer"] {
        color: #E8E8F0;
    }
    [data-testid="stAppViewContainer"], [data-testid="stAppContainer"] {
        background: linear-gradient(135deg, #17162A 0%, #221A33 45%, #10222E 100%) !important;
    }
    [data-testid="stAppViewContainer"]::before {
        background: radial-gradient(circle, #6C5CE7 0%, transparent 70%);
        opacity: 0.4;
    }
    [data-testid="stAppViewContainer"]::after {
        background: radial-gradient(circle, #00B894 0%, transparent 70%);
        opacity: 0.35;
    }
    [data-testid="stSidebar"], [data-testid="stSidebarUserContent"] {
        background: rgba(26, 26, 42, 0.6) !important;
    }
    [data-testid="stSidebar"] * {
        color: #E8E8F0;
    }
    [data-testid="stChatMessage"], [data-testid="stExpander"],
    [data-testid="stStatusWidget"], .stCodeBlock,
    [data-testid="stAlert"], [data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--glass-bg) !important;
        color: #E8E8F0;
    }
    [data-testid="stChatMessage"] * {
        color: #E8E8F0;
    }
    .stButton > button, .stDownloadButton > button,
    [data-testid="stBaseButton-secondary"] {
        background: var(--glass-bg-dark) !important;
        border-color: rgba(255, 255, 255, 0.14) !important;
    }
    .stButton > button:hover, [data-testid="stBaseButton-secondary"]:hover {
        background: rgba(108, 92, 231, 0.3) !important;
    }
    [data-testid="stChatInputTextArea"], [data-testid="stChatInput"] textarea {
        background: rgba(45, 45, 68, 0.7) !important;
        color: #E8E8F0;
    }
    [role="listbox"] {
        background: rgba(35, 35, 55, 0.95) !important;
    }
    .stCodeBlock, .stCodeBlock > div {
        background: rgba(20, 20, 32, 0.7) !important;
    }
    code {
        background: rgba(45, 45, 68, 0.8) !important;
        color: #E8E8F0 !important;
    }
}
</style>
"""

st.markdown(GLASS_CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------
# 后台事件循环 + Agent（整个进程只创建一次，所有浏览器标签页共享）
# ------------------------------------------------------------------
@st.cache_resource
def get_loop():
    """后台事件循环线程：整个进程只创建一个，所有 provider 的 Agent 共用。"""
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True, name="agent-loop").start()
    return loop


@st.cache_resource(show_spinner="正在初始化 Agent（加载 MCP 服务器、Skills、Memory）……")
def get_runtime(provider: str = "cloud"):
    """按 provider 创建并缓存 Agent：切换模型时用新 provider 重建，旧实例保留。"""
    loop = get_loop()
    agent, info = asyncio.run_coroutine_threadsafe(build_agent(provider), loop).result()
    return loop, agent, info


def run_in_loop(coro):
    """在后台事件循环中执行协程并等待结果。"""
    loop, _, _ = get_runtime(st.session_state.get("provider", "cloud"))
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def iter_events(question: str, thread_id: str):
    """同步生成器：在后台循环里跑 stream_events，把事件通过队列交给页面线程。"""
    loop, agent, _ = get_runtime(st.session_state.get("provider", "cloud"))
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
# 模型选择器：放在侧边栏顶部，切换后按 provider 重建 Agent
PROVIDERS = {
    "云端 · qwen3.7-plus（阿里百炼）": "cloud",
    "本地 · Ollama qwen3.5:0.8B": "local",
}
with st.sidebar:
    provider = st.selectbox(
        "⚙️ 模型",
        list(PROVIDERS),
        index=0,
        help="本地模型需要先启动 Ollama（ollama serve）并拉取 qwen3.5:0.8B",
    )
st.session_state.provider = PROVIDERS[provider]

try:
    _, agent, info = get_runtime(PROVIDERS[provider])
except Exception as exc:  # noqa: BLE001
    st.error(f"Agent 初始化失败：{exc}")
    st.info("云端模式请检查 demo_5/.env 中的 DASHSCOPE_API_KEY；"
            "本地模式请确认 Ollama 已启动且已拉取 qwen3.5:0.8B。")
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
    st.header("🛡️ 开源合规助手")
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
    st.markdown(f"**模型**　`{info['model']}`（{info['provider']}）")
    if info["lite_mode"]:
        st.caption("🔶 小模型模式：子代理已关闭，回答为要点式。")
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
st.title("🛡️ 开源合规助手")
st.caption("LangChain Deep Agents ｜ 许可证查询 · 兼容性检查 · 项目扫描 · 合规报告")

EXAMPLES = [
    "MIT 和 GPL-3.0 有什么区别？能混用吗？",
    "扫描 node_modules 的许可证分布",
    "评估这个仓库的许可证合规风险，出一份报告",
    "AGPL-3.0 能用在闭源 SaaS 里吗？",
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
