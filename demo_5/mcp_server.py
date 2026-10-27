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

import json
import logging
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("license-info")

mcp = FastMCP("license-info", log_level="WARNING")

# ----------------------------------------------------------------------
# 许可证知识库：外置为 licenses.json，缺失时回退到内置最小集合
# ----------------------------------------------------------------------
_LICENSES_FILE = Path(__file__).with_name("licenses.json")

# 内置最小集合：仅当 licenses.json 缺失或损坏时兜底
_FALLBACK_LICENSES = {
    "MIT": {
        "name": "MIT License",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "未明确授予",
        "modify_must_open": "否",
        "summary": "最宽松的常用许可证之一，保留版权声明即可自由使用、修改、再分发。",
    },
    "Apache-2.0": {
        "name": "Apache License 2.0",
        "copyleft": "无",
        "commercial": "允许",
        "patent_grant": "明确授予",
        "modify_must_open": "否",
        "summary": "宽松许可证，附专利授权与商标限制；修改文件需显著标注。",
    },
    "GPL-3.0": {
        "name": "GNU GPL v3",
        "copyleft": "强",
        "commercial": "允许（但衍生品必须开源）",
        "patent_grant": "明确授予",
        "modify_must_open": "是",
        "summary": "强 Copyleft：分发基于 GPL 代码的软件时，整体必须以 GPL 开源。",
    },
}

try:
    LICENSES = json.loads(_LICENSES_FILE.read_text(encoding="utf-8"))
    if not isinstance(LICENSES, dict) or not LICENSES:
        raise ValueError("licenses.json 内容为空或结构错误")
except (OSError, ValueError, json.JSONDecodeError) as exc:
    LICENSES = _FALLBACK_LICENSES
    log.warning("licenses.json 加载失败（%s），回退到内置 %d 项最小集合",
                exc, len(LICENSES))

# Copyleft 强度分级：数值越高传染性越强
_COPYLEFT_LEVEL = {"AGPL-3.0": 3, "GPL-3.0": 2, "LGPL-3.0": 1, "MPL-2.0": 1}

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

# 扫描默认参数：大目录可通过环境变量调整，避免漏扫或卡死
_SCAN_MAX_DEPTH = 5
_SCAN_MAX_FILES = 2000


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


def _normalize_spdx(value: str) -> str:
    """把常见许可证名写法归一到知识库中的 SPDX 标识符，归一不了返回原值。"""
    v = value.strip()
    # 去掉尾部版本号后查精确匹配，如 "Apache-2.0 license" -> "Apache-2.0"
    key = re.split(r"[\s(]", v)[0]
    for cand in (v, key, key.upper(), key.replace("-", "_")):
        if cand in LICENSES:
            return cand
    aliases = {
        "APACHE": "Apache-2.0", "APACHE2": "Apache-2.0", "APACHE 2.0": "Apache-2.0",
        "MIT LICENSE": "MIT", "MITLICENSE": "MIT", "GPL": "GPL-3.0",
        "GPLV3": "GPL-3.0", "GPL-3.0-ONLY": "GPL-3.0", "GPLV2": "GPL-3.0",
        "BSD": "BSD-2-Clause", "BSD3": "BSD-3-Clause", "BSD-3": "BSD-3-Clause",
        "ISC LICENSE": "ISC", "AGPL": "AGPL-3.0", "LGPL": "LGPL-3.0",
    }
    return aliases.get(key.upper(), aliases.get(v.upper(), key))


def _manifest_license_field(path: Path) -> str | None:
    """读取 package.json / pyproject.toml 中声明的 license 字段，没有则返回 None。"""
    try:
        if path.name == "package.json":
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            lic = data.get("license")
            if isinstance(lic, str):
                return lic
            if isinstance(lic, dict) and isinstance(lic.get("type"), str):
                return lic["type"]
        elif path.name == "pyproject.toml":
            try:
                import tomllib
            except ImportError:  # Python < 3.11
                return None
            data = tomllib.loads(path.read_text(encoding="utf-8", errors="ignore"))
            lic = (data.get("project") or {}).get("license")
            if isinstance(lic, str):
                return lic
            if isinstance(lic, dict) and isinstance(lic.get("text"), str):
                return lic["text"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    return None


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
        normalized = _normalize_spdx(spdx_id)
        if normalized in LICENSES:
            spdx_id = normalized
        else:
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
    normalized = [_normalize_spdx(s) for s in spdx_ids]
    unknown = [s for s in normalized if s not in LICENSES]
    if unknown:
        return {"error": f"无法识别：{', '.join(sorted(set(unknown)))}",
                "available": sorted(LICENSES)}

    risks = []
    strong = [s for s in normalized if _COPYLEFT_LEVEL.get(s, 0) >= 2]
    if strong:
        risks.append(
            f"包含强 Copyleft 许可证（{', '.join(sorted(set(strong)))}）："
            "若分发包含这些代码的产品，整体通常需要按同协议开源，闭源商用有传染风险。"
        )
    weak = [s for s in normalized if _COPYLEFT_LEVEL.get(s, 0) == 1]
    if weak:
        risks.append(
            f"包含弱 Copyleft 许可证（{', '.join(sorted(set(weak)))}）："
            "仅被修改过的文件/库需开源，可与专有代码共存，注意修改标注。"
        )
    if "CC-BY-3.0" in normalized or "CC-BY-4.0" in normalized:
        risks.append("包含 CC 协议：适合文档与媒体资源，不建议用于源代码。")
    if "WTFPL" in normalized:
        risks.append("包含 WTFPL：法律条款不严谨，正式产品建议评估替换。")

    notes = []
    distinct_copyleft = sorted({s for s in normalized if _COPYLEFT_LEVEL.get(s, 0) >= 2})
    if len(distinct_copyleft) > 1:
        notes.append("同时包含多种不同的强 Copyleft 许可证（GPL 与 AGPL 等）："
                     "它们互相之间的兼容性有额外限制，需逐文件确认分发义务。")
    notes.append("若个别依赖自带许可证例外条款（如 GPL exception 或 SPDX 表达式中的 "
                 "WITH 子句），其分发义务可能与标准条款不同，需单独评估。")

    copyleft_free = sorted({s for s in normalized if _COPYLEFT_LEVEL.get(s, 0) == 0})
    return {
        "checked": sorted(set(normalized)),
        "risks": risks,
        "dual_license_note": notes[0] if len(distinct_copyleft) > 1 else None,
        "exception_note": notes[-1],
        "permissive_only": copyleft_free if not strong else [],
        "conclusion": (
            "存在传染风险，需评估分发方式与产品开源策略。" if strong
            else "未见强 Copyleft 污染风险，注意保留各许可证的版权声明即可。"
        ),
    }


@mcp.tool()
def scan_project_licenses(
    project_path: str,
    max_depth: int = _SCAN_MAX_DEPTH,
    max_files: int = _SCAN_MAX_FILES,
) -> dict:
    """扫描一个项目目录中的许可证信息：LICENSE/COPYING/NOTICE 文件，以及
    package.json / pyproject.toml 中声明的 license 字段。

    Args:
        project_path: 要扫描的项目目录路径（绝对路径或相对路径）
        max_depth: 目录遍历深度上限，默认 5
        max_files: 最多处理的许可证文件数，默认 2000
    """
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        return {"error": f"目录不存在或不是文件夹：{root}"}

    # 文件名匹配：LICENSE/COPYING/NOTICE 开头，允许 .md/.txt/无后缀与
    # LICENSE-MIT 这类连字符命名
    def _is_license_file(path: Path) -> bool:
        first = re.split(r"[-_.]", path.name, maxsplit=1)[0].upper()
        return first in {"LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE"}

    found: dict[str, list[str]] = {}
    scanned = 0
    try:
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if rel.count("/") >= max_depth:
                continue
            if not path.is_file():
                continue
            if _is_license_file(path):
                scanned += 1
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                found.setdefault(_classify_text(text), []).append(rel)
            elif path.name in ("package.json", "pyproject.toml") and rel.count("/") <= 1:
                lic = _manifest_license_field(path)
                if lic:
                    scanned += 1
                    spdx = lic if lic in LICENSES else _normalize_spdx(lic)
                    found.setdefault(spdx, []).append(f"{rel}#license字段:{lic}")
            if scanned >= max_files:
                break
    except OSError as exc:
        return {"error": f"读取目录失败：{exc}"}

    if not found:
        return {"project": str(root), "total_files": scanned, "licenses": {},
                "note": "没有找到 LICENSE 类文件，package.json/pyproject.toml 中也未声明 license 字段。"}

    total = sum(len(v) for v in found.values())
    return {
        "project": str(root),
        "total_files": scanned,
        "total_identified": total,
        "licenses": {k: {"count": len(v), "examples": v[:5]} for k, v in
                     sorted(found.items(), key=lambda kv: -len(kv[1]))},
        "note": "识别基于文本特征与清单字段声明，无法识别的标为 unknown；正式合规以各许可证原文为准。",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
