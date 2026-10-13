"""
本地 MCP 服务器示例（FastMCP，stdio 传输）
==========================================

这是一个独立进程，由 agent.py 按 mcp_servers.json 中的配置自动启动，
通过标准输入输出与 Agent 通信。任何支持 MCP 的客户端
（Claude Desktop、Cursor、Cherry Studio 等）也都能直接使用它。

单独调试：
    npx @modelcontextprotocol/inspector python mcp_server.py

新增 MCP 工具：写一个函数并加上 @mcp.tool() 装饰器即可。
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("course-info", log_level="WARNING")

# 演示用的“课程数据库”，实际项目中可以换成数据库或 HTTP API
COURSES = {
    "demo_1": {"title": "本地模型下载与向量检索", "keywords": ["modelscope", "embedding", "向量库"]},
    "demo_2": {"title": "Ollama API 接口实验", "keywords": ["ollama", "REST API", "流式输出"]},
    "demo_3": {"title": "LLM 应用开发", "keywords": ["streamlit", "对话应用"]},
    "demo_4": {"title": "以图搜图", "keywords": ["图像检索", "多模态"]},
    "demo_5": {"title": "Deep Agents 智能体", "keywords": ["deepagents", "skills", "mcp", "subagents"]},
}


@mcp.tool()
def list_course_demos() -> dict:
    """列出「AI 开源技术实践」课程的全部实验（demo），返回编号和标题。"""
    return {k: v["title"] for k, v in COURSES.items()}


@mcp.tool()
def get_course_demo(demo_id: str) -> dict:
    """查询某个课程实验的详细信息。

    Args:
        demo_id: 实验编号，例如 "demo_5"
    """
    if demo_id not in COURSES:
        return {"error": f"未找到 {demo_id}，可选：{', '.join(COURSES)}"}
    return {"id": demo_id, **COURSES[demo_id]}


@mcp.tool()
def text_stats(text: str) -> dict:
    """统计一段文本的字符数、中文字数、行数和段落数。写报告时可用来检查篇幅。

    Args:
        text: 要统计的文本
    """
    return {
        "chars": len(text),
        "chinese_chars": sum("一" <= c <= "鿿" for c in text),
        "lines": text.count("\n") + 1,
        "paragraphs": len([p for p in text.split("\n\n") if p.strip()]),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
