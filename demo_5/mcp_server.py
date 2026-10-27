"""
本地 MCP 服务器示例（FastMCP，stdio 传输）
==========================================

「license-info」服务器：开源许可证合规查询与项目扫描。
这是一个独立进程，由 agent.py 按 mcp_servers.json 中的配置自动启动，
通过标准输入输出与 Agent 通信。任何支持 MCP 的客户端
（Claude Desktop、Cursor、Cherry Studio 等）也都能直接使用它。

单独调试：
    npx @modelcontextprotocol/inspector python mcp_server.py

新增 MCP 工具：写一个函数并加上 @mcp.tool() 装饰器即可。
"""

import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("license-info", log_level="WARNING")

# ----------------------------------------------------------------------
# 离线许可证知识库（内容概括自 OSI / 各许可证官方文本，仅作教学参考）
# ----------------------------------------------------------------------
LICENSES = {
    "MIT": {
        "name": "MIT License",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "未明确授予",
        "modify_must_open": "否",
        "summary": "最宽松的常用许可证之一，保留版权声明即可自由使用、修改、再分发。",
    },
    "ISC": {
        "name": "ISC License",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "未明确授予",
        "modify_must_open": "否",
        "summary": "与 MIT 基本等价的宽松许可证，措辞更简洁，npm 生态常见。",
    },
    "0BSD": {
        "name": "BSD Zero Clause License",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "未明确授予",
        "modify_must_open": "否",
        "summary": "近似公有领域的极简许可证，连保留声明的要求都几乎省略。",
    },
    "BSD-2-Clause": {
        "name": "BSD 2-Clause License",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "未明确授予",
        "modify_must_open": "否",
        "summary": "宽松许可证，需保留版权与免责声明，不得用原作者名义做宣传。",
    },
    "BSD-3-Clause": {
        "name": "BSD 3-Clause License",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "未明确授予",
        "modify_must_open": "否",
        "summary": "在 BSD-2 基础上追加一条：未经许可不得用贡献者名义推广衍生产品。",
    },
    "Apache-2.0": {
        "name": "Apache License 2.0",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "明确授予",
        "modify_must_open": "否",
        "summary": "宽松许可证，附专利授权与商标限制；修改文件需显著标注。",
    },
    "MPL-2.0": {
        "name": "Mozilla Public License 2.0",
        "copyleft": "弱（文件级）",
        "commercial": "允许",
        "patent_grant": "明确授予",
        "modify_must_open": "仅修改过的源文件需开源",
        "summary": "文件级弱 Copyleft：改动的文件须以 MPL 开源，可与专有代码混用。",
    },
    "LGPL-3.0": {
        "name": "GNU LGPL v3",
        "copyleft": "弱（库级）",
        "commercial": "允许",
        "patent_grant": "随 GPL-3.0 授予",
        "modify_must_open": "修改库本身需开源",
        "summary": "弱 Copyleft：允许专有软件以动态链接方式调用，但库自身改动须开源。",
    },
    "GPL-3.0": {
        "name": "GNU GPL v3",
        "copyleft": "强",
        "commercial": "允许（但衍生品必须开源）",
        "patent_grant": "明确授予",
        "modify_must_open": "是",
        "summary": "强 Copyleft：分发基于 GPL 代码的软件时，整体必须以 GPL 开源。",
    },
    "AGPL-3.0": {
        "name": "GNU AGPL v3",
        "copyleft": "最强",
        "commercial": "允许（但含网络服务也必须开源）",
        "patent_grant": "明确授予",
        "modify_must_open": "是",
        "summary": "GPL 的网络服务版本：即使只通过网络提供访问，也要提供源码。商业产品应谨慎引入。",
    },
    "CC-BY-4.0": {
        "name": "CC BY 4.0",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "不适用",
        "modify_must_open": "否",
        "summary": "知识共享署名协议，适合文档/数据/图片，一般不推荐用于源代码。",
    },
    "CC-BY-3.0": {
        "name": "CC BY 3.0",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "不适用",
        "modify_must_open": "否",
        "summary": "CC BY 4.0 的旧版，同样适合非代码资源，署名即可商用。",
    },
    "CC0-1.0": {
        "name": "CC0 1.0",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "含尽力专利弃权",
        "modify_must_open": "否",
        "summary": "近似公有领域，作者放弃全部版权，任意使用。",
    },
    "Unlicense": {
        "name": "The Unlicense",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "未明确授予",
        "modify_must_open": "否",
        "summary": "把代码献入公有领域的极简许可证。",
    },
    "BlueOak-1.0.0": {
        "name": "Blue Oak Model License 1.0.0",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "明确授予",
        "modify_must_open": "否",
        "summary": "为 npm 生态重写的现代宽松许可证，意图与 MIT 相近、条款更清晰。",
    },
    "WTFPL": {
        "name": "Do What The F*ck You Want To Public License",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "未明确授予",
        "modify_must_open": "否",
        "summary": "近似公有领域的玩笑许可证，几乎没有法律约束条款，正式项目慎用。",
    },
}

# 许可证文本特征：正则 -> 识别出的 SPDX 标识符
_SIGNATURES: list[tuple[str, str]] = [
    (r"Apache License\s*Version 2\.0", "Apache-2.0"),
    (r"GNU (AFFERO )?GENERAL PUBLIC LICENSE\s*Version 3", "GPL-3.0"),
    (r"GNU LESSER GENERAL PUBLIC LICENSE\s*Version 3", "LGPL-3.0"),
    (r"Mozilla Public License\s*Version 2\.0", "MPL-2.0"),
    (r"DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE", "WTFPL"),
    (r"The Unlicense", "Unlicense"),
    (r"Creative Commons (Attribution|BY) 4\.0", "CC-BY-4.0"),
    (r"Creative Commons (Attribution|BY) 3\.0", "CC-BY-3.0"),
    (r"CC0 1\.0 Universal", "CC0-1.0"),
    (r"Blue Oak Model License", "BlueOak-1.0.0"),
    (r"ISC License|Permission to use, copy, modify, and/or distribute this software", "ISC"),
    (r"Permission is hereby granted, free of charge", "MIT"),
    (r"Redistribution and use in source and binary forms", "BSD-2-Clause"),
]


def _classify_text(text: str) -> str:
    """用特征正则粗略识别许可证全文对应的 SPDX 标识符，识别不出返回 unknown。"""
    head = text[:4000]
    for pattern, spdx in _SIGNATURES:
        if re.search(pattern, head, re.IGNORECASE):
            # BSD-2/3 区分：3-Clause 多一条“不得用贡献者名义宣传”条款
            if spdx == "BSD-2-Clause" and re.search(
                r"nor may the names of", text[:8000], re.IGNORECASE
            ):
                return "BSD-3-Clause"
            return spdx
    return "unknown"


# ----------------------------------------------------------------------
# MCP 工具
# ----------------------------------------------------------------------
@mcp.tool()
def get_license_info(spdx_id: str) -> dict:
    """查询某个开源许可证（SPDX 标识符）的合规要点：是否宽松、能否商用、有无专利授权等。

    Args:
        spdx_id: SPDX 许可证标识符，例如 "MIT"、"Apache-2.0"、"GPL-3.0"、"LGPL-3.0"
    """
    if spdx_id not in LICENSES:
        return {
            "error": f"知识库中没有 {spdx_id}。",
            "available": sorted(LICENSES),
        }
    return {"spdx_id": spdx_id, **LICENSES[spdx_id],
            "note": "以上为教学概括，正式合规判断请以许可证原文为准。"}


@mcp.tool()
def check_compatibility(spdx_ids: list[str]) -> dict:
    """检查一组许可证之间是否存在兼容性风险（强 Copyleft 污染宽松代码等）。

    Args:
        spdx_ids: 要检查的 SPDX 标识符列表，例如 ["MIT", "Apache-2.0", "GPL-3.0"]
    """
    unknown = [s for s in spdx_ids if s not in LICENSES]
    if unknown:
        return {"error": f"无法识别：{', '.join(unknown)}", "available": sorted(LICENSES)}

    risks = []
    strict_order = {"AGPL-3.0": 3, "GPL-3.0": 2, "LGPL-3.0": 1, "MPL-2.0": 1}
    strong = [s for s in spdx_ids if strict_order.get(s, 0) >= 2]
    if strong:
        risks.append(
            f"包含强 Copyleft 许可证（{', '.join(sorted(set(strong)))}）："
            "若分发包含这些代码的产品，整体通常需要按同协议开源，闭源商用有传染风险。"
        )
    weak = [s for s in spdx_ids if strict_order.get(s, 0) == 1]
    if weak:
        risks.append(
            f"包含弱 Copyleft 许可证（{', '.join(sorted(set(weak)))}）："
            "仅被修改过的文件/库需开源，可与专有代码共存，注意修改标注。"
        )
    if "CC-BY-3.0" in spdx_ids or "CC-BY-4.0" in spdx_ids:
        risks.append("包含 CC 协议：适合文档与媒体资源，不建议用于源代码。")
    if "WTFPL" in spdx_ids:
        risks.append("包含 WTFPL：法律条款不严谨，正式产品建议评估替换。")

    copyleft_free = [s for s in set(spdx_ids) if strict_order.get(s, 0) == 0]
    return {
        "checked": sorted(set(spdx_ids)),
        "risks": risks,
        "permissive_only": sorted(copyleft_free) if not strong else [],
        "conclusion": (
            "存在传染风险，需评估分发方式与产品开源策略。" if strong
            else "未见强 Copyleft 污染风险，注意保留各许可证的版权声明即可。"
        ),
    }


@mcp.tool()
def scan_project_licenses(project_path: str) -> dict:
    """扫描一个项目目录中的 LICENSE / COPYING / NOTICE 文件，识别每个子项目的许可证。

    适合扫描 node_modules、多模块仓库或带第三方代码的目录，统计许可证分布。

    Args:
        project_path: 要扫描的项目目录路径（绝对路径或相对路径）
    """
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        return {"error": f"目录不存在或不是文件夹：{root}"}

    names = {"LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE"}
    found: dict[str, list[str]] = {}
    scanned = 0
    try:
        for path in root.rglob("*"):
            # 控制深度，避免扫进超深的依赖树
            if path.is_file() and path.stem.upper().split(".")[0] in names:
                rel = path.relative_to(root).as_posix()
                if rel.count("/") > 3:
                    continue
                scanned += 1
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                spdx = _classify_text(text)
                found.setdefault(spdx, []).append(rel)
                if scanned >= 500:
                    break
    except OSError as exc:
        return {"error": f"读取目录失败：{exc}"}

    if not found:
        return {"project": str(root), "licenses": {},
                "note": "没有找到 LICENSE/COPYING/NOTICE 文件。"}

    return {
        "project": str(root),
        "total_files": scanned,
        "licenses": {k: {"count": len(v), "examples": v[:5]} for k, v in
                     sorted(found.items(), key=lambda kv: -len(kv[1]))},
        "note": "识别基于文本特征，无法识别的标为 unknown；正式合规以各许可证原文为准。",
    }


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
