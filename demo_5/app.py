"""
Demo 5：LangChain Deep Agents + 阿里百炼 命令行助手
==================================================

启动：
    python app.py                  # 开始新会话
    python app.py -c               # 继续最近一次会话
    python app.py -q "你的问题"     # 只问一个问题后退出（可与 -c 组合）
    streamlit run web.py           # 网页界面

对话中的命令：
    /sessions   列出历史会话        /load 编号   切换到某个历史会话继续追问
    /history    回放当前会话        /new         开始新会话
    /info       查看模型和能力      /help        查看帮助
    /exit       退出

所有会话自动保存在 data/ 目录，重启后可以继续追问。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import history
from agent import build_agent, close_agent, stream_events

# Windows 终端默认 GBK，统一改成 UTF-8，避免中文乱码
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

GRAY, CYAN, YELLOW, GREEN, RED, RESET = "\033[90m", "\033[36m", "\033[33m", "\033[32m", "\033[31m", "\033[0m"


def _short(value, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


async def ask(agent, question: str, thread_id: str) -> str:
    """把问题发给 Agent，流式打印回答和工具调用过程，并保存到历史记录。"""
    history.save_message(thread_id, "user", question)
    answer, steps = "", []
    streaming = False  # 当前是否正在流式打印文字

    print(f"{GREEN}助教：{RESET}", end="", flush=True)
    async for ev in stream_events(agent, question, thread_id):
        kind = ev["type"]
        if kind == "token":
            print(ev["content"], end="", flush=True)
            streaming = True
            continue
        if streaming:  # 一段流式文字结束，换行后再打印其他内容
            print()
            streaming = False
        indent = "    " * ev.get("depth", 0)
        who = "子代理" if ev.get("depth") else "主Agent"
        if kind == "tool_call":
            steps.append(ev)
            print(f"{indent}{YELLOW}[{who}] 调用工具 {ev['name']}{RESET} {GRAY}{_short(ev['args'])}{RESET}")
        elif kind == "tool_result":
            steps.append(ev)
            print(f"{indent}{GRAY}  ↳ {ev['name']} 返回：{_short(ev['content'])}{RESET}")
        elif kind == "answer":
            answer = ev["content"]
    if streaming:
        print()
    history.save_message(thread_id, "assistant", answer, steps)
    return answer


def print_info(info: dict) -> None:
    print(f"{CYAN}模型      {RESET}{info['model']}")
    print(f"{CYAN}自定义工具{RESET} {', '.join(info['custom_tools'])}")
    print(f"{CYAN}MCP 工具  {RESET} {', '.join(info['mcp_tools']) or '（无）'}")
    print(f"{CYAN}Skills    {RESET} {', '.join(info['skills']) or '（无）'}")
    print(f"{CYAN}子代理    {RESET} {', '.join(info['subagents'])}")
    print(f"{CYAN}内置工具  {RESET} write_todos, ls, read_file, write_file, edit_file, glob, grep, task")
    for w in info["warnings"]:
        print(f"{RED}警告：{w}{RESET}")


def print_sessions(sessions: list[dict], current: str) -> None:
    if not sessions:
        print(f"{GRAY}还没有历史会话。{RESET}")
    for i, s in enumerate(sessions, 1):
        mark = f"{GREEN}*{RESET}" if s["thread_id"] == current else " "
        print(f"{mark}{i:>3}. {s['title']}  {GRAY}{s['updated_at']} · {s['n']} 条消息{RESET}")


def print_history(thread_id: str) -> None:
    msgs = history.load_messages(thread_id)
    if not msgs:
        print(f"{GRAY}当前会话还没有消息。{RESET}")
    for m in msgs:
        who = f"{GREEN}你：{RESET}" if m["role"] == "user" else f"{GREEN}助教：{RESET}"
        print(f"{who}{m['content']}\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Deep Agents + 阿里百炼 演示")
    parser.add_argument("-q", "--question", help="只问一个问题，回答后退出")
    parser.add_argument("-c", "--continue", dest="resume", action="store_true", help="继续最近一次会话")
    args = parser.parse_args()

    print(f"{GRAY}正在初始化 Agent（加载 MCP 服务器、Skills、Memory）……{RESET}")
    agent, info = await build_agent()
    print_info(info)

    thread_id = history.new_thread_id()
    if args.resume:
        recent = history.list_sessions(limit=1)
        if recent:
            thread_id = recent[0]["thread_id"]
            print(f"\n{CYAN}继续会话：{recent[0]['title']}{RESET}")
            print_history(thread_id)

    try:
        if args.question:
            print(f"\n{GREEN}你：{RESET}{args.question}")
            await ask(agent, args.question, thread_id)
            return

        print("\n输入问题开始对话，/help 查看命令。\n")
        sessions: list[dict] = []
        while True:
            try:
                question = (await asyncio.to_thread(input, f"{GREEN}你：{RESET}")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question:
                continue
            cmd, _, arg = question.partition(" ")
            if cmd in ("/exit", "/quit"):
                break
            if cmd == "/help":
                print(__doc__)
            elif cmd == "/info":
                print_info(info)
            elif cmd == "/new":
                thread_id = history.new_thread_id()
                print(f"{GRAY}已开始新会话。{RESET}")
            elif cmd == "/sessions":
                sessions = history.list_sessions()
                print_sessions(sessions, thread_id)
            elif cmd == "/history":
                print_history(thread_id)
            elif cmd == "/load":
                sessions = sessions or history.list_sessions()
                if arg.isdigit() and 1 <= int(arg) <= len(sessions):
                    s = sessions[int(arg) - 1]
                    thread_id = s["thread_id"]
                    print(f"{CYAN}已切换到：{s['title']}{RESET}\n")
                    print_history(thread_id)
                else:
                    print(f"{RED}用法：先 /sessions 查看编号，再 /load 编号{RESET}")
            elif cmd.startswith("/"):
                print(f"{RED}未知命令，/help 查看帮助。{RESET}")
            else:
                try:
                    await ask(agent, question, thread_id)
                    print()
                except Exception as exc:  # noqa: BLE001
                    print(f"\n{RED}出错了：{exc!r}{RESET}")
        print("再见！会话已保存，下次可用 python app.py -c 继续。")
    finally:
        await close_agent(agent)


if __name__ == "__main__":
    asyncio.run(main())
