"""mcp_server.py 纯逻辑测试：许可证信息、兼容性、文本识别、归一化、目录扫描、知识库回退。

全程离线：不启动 MCP 进程，只调用工具的底层实现函数。
"""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

import mcp_server as ms

MIT_TEXT = (
    "Permission is hereby granted, free of charge, to any person obtaining "
    "a copy of this software and associated documentation files (the "
    "\"Software\"), to deal in the Software without restriction."
)
APACHE_TEXT = "Apache License\nVersion 2.0, January 2004\nhttp://www.apache.org/licenses/"
GPL3_TEXT = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007"
BSD2_TEXT = (
    "Redistribution and use in source and binary forms, with or without "
    "modification, are permitted provided that the conditions are met."
)
BSD3_SUFFIX = "\nNeither the name of the holder nor may the names of its contributors be used to endorse."


# ----------------------------------------------------------------------
# get_license_info
# ----------------------------------------------------------------------
class TestGetLicenseInfo:
    def test_known_license(self):
        r = ms.get_license_info("MIT")
        assert r["spdx_id"] == "MIT"
        assert r["copyleft"] == "无"
        assert "note" in r

    def test_unknown_license(self):
        r = ms.get_license_info("NONEXISTENT-LICENSE")
        assert "error" in r
        assert "available" in r

    @pytest.mark.parametrize(
        "alias,expected",
        [("mit", "MIT"), ("Apache 2.0", "Apache-2.0"), ("gpl", "GPL-3.0")],
    )
    def test_alias_normalized(self, alias, expected):
        assert ms.get_license_info(alias)["spdx_id"] == expected


# ----------------------------------------------------------------------
# check_compatibility
# ----------------------------------------------------------------------
class TestCheckCompatibility:
    def test_all_permissive(self):
        r = ms.check_compatibility(["MIT", "Apache-2.0"])
        assert r["risks"] == []
        assert "MIT" in r["permissive_only"]
        assert "未见强 Copyleft" in r["conclusion"]
        assert r["dual_license_note"] is None

    def test_with_strong_copyleft(self):
        r = ms.check_compatibility(["MIT", "GPL-3.0"])
        assert any("强 Copyleft" in x for x in r["risks"])
        assert "存在传染风险" in r["conclusion"]
        assert r["dual_license_note"] is None

    def test_multiple_strong_copyleft(self):
        r = ms.check_compatibility(["GPL-3.0", "AGPL-3.0"])
        assert r["dual_license_note"], "双强 Copyleft 必须给出逐文件确认提示"
        assert "多种不同的强 Copyleft" in r["dual_license_note"]

    def test_exception_note_always_present(self):
        r = ms.check_compatibility(["MIT"])
        assert r["exception_note"]

    def test_unknown_id(self):
        assert "error" in ms.check_compatibility(["FOO-LICENSE"])


# ----------------------------------------------------------------------
# _classify_text
# ----------------------------------------------------------------------
class TestClassifyText:
    @pytest.mark.parametrize(
        "text,expected",
        [
            (MIT_TEXT, "MIT"),
            (APACHE_TEXT, "Apache-2.0"),
            (GPL3_TEXT, "GPL-3.0"),
            ("随便写的一段话，不是任何许可证。", "unknown"),
        ],
    )
    def test_basic_recognition(self, text, expected):
        assert ms._classify_text(text) == expected

    def test_bsd_2_vs_3_distinction(self):
        assert ms._classify_text(BSD2_TEXT) == "BSD-2-Clause"
        assert ms._classify_text(BSD2_TEXT + BSD3_SUFFIX) == "BSD-3-Clause"

    @pytest.mark.xfail(
        reason="已知盲区：_SIGNATURES 无 AGPL 条目，AGPL 文本会被误判为 GPL-3.0"
    )
    def test_agpl_recognition(self):
        assert ms._classify_text("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3, 19 November 2007") == "AGPL-3.0"


# ----------------------------------------------------------------------
# _normalize_spdx
# ----------------------------------------------------------------------
class TestNormalizeSpdx:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("mit", "MIT"),
            ("GPL", "GPL-3.0"),
            ("Apache 2.0", "Apache-2.0"),
            ("Apache-2.0", "Apache-2.0"),  # 本身就是合法 key，原样通过
        ],
    )
    def test_normalize(self, raw, expected):
        assert ms._normalize_spdx(raw) == expected

    def test_unknown_returns_original(self):
        assert ms._normalize_spdx("totally-unknown-lic") == "totally-unknown-lic"


# ----------------------------------------------------------------------
# _manifest_license_field
# ----------------------------------------------------------------------
class TestManifestLicenseField:
    def test_package_json_string(self, tmp_path):
        p = tmp_path / "package.json"
        p.write_text(json.dumps({"name": "x", "license": "MIT"}), encoding="utf-8")
        assert ms._manifest_license_field(p) == "MIT"

    def test_package_json_dict_type(self, tmp_path):
        p = tmp_path / "package.json"
        p.write_text(json.dumps({"license": {"type": "Apache-2.0"}}), encoding="utf-8")
        assert ms._manifest_license_field(p) == "Apache-2.0"

    def test_pyproject_string(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('[project]\nname = "x"\nlicense = "MIT"\n', encoding="utf-8")
        assert ms._manifest_license_field(p) == "MIT"

    def test_pyproject_dict_text(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('[project]\nname = "x"\nlicense = { text = "MIT License" }\n', encoding="utf-8")
        assert ms._manifest_license_field(p) == "MIT License"

    def test_missing_field_returns_none(self, tmp_path):
        p = tmp_path / "package.json"
        p.write_text(json.dumps({"name": "x"}), encoding="utf-8")
        assert ms._manifest_license_field(p) is None


# ----------------------------------------------------------------------
# scan_project_licenses
# ----------------------------------------------------------------------
class TestScanProjectLicenses:
    def test_multi_source_identification(self, tmp_path):
        """LICENSE 文本 + 连字符命名 + package.json + pyproject.toml 四种来源。"""
        (tmp_path / "LICENSE").write_text(MIT_TEXT, encoding="utf-8")
        (tmp_path / "LICENSE-MIT").write_text(MIT_TEXT, encoding="utf-8")
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "package.json").write_text(json.dumps({"license": "Apache-2.0"}), encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "pyproject.toml").write_text('[project]\nlicense = "MIT"\n', encoding="utf-8")

        r = ms.scan_project_licenses(str(tmp_path))
        assert r["total_files"] >= 4
        assert "MIT" in r["licenses"]
        assert "Apache-2.0" in r["licenses"]

    def test_nonexistent_dir(self):
        assert "error" in ms.scan_project_licenses("/nonexistent/xyz")

    def test_empty_project(self, tmp_path):
        (tmp_path / "README.md").write_text("hi", encoding="utf-8")
        r = ms.scan_project_licenses(str(tmp_path))
        assert r["licenses"] == {}

    def test_unknown_license_text(self, tmp_path):
        (tmp_path / "LICENSE").write_text("完全无关的随机文本，没有任何许可证特征。", encoding="utf-8")
        r = ms.scan_project_licenses(str(tmp_path))
        assert "unknown" in r["licenses"]

    def test_depth_limit_skips_deep_manifest(self, tmp_path):
        """package.json 在三层子目录中（rel 层级 > 1）不参与 license 字段解析。"""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "package.json").write_text(json.dumps({"license": "MIT"}), encoding="utf-8")
        r = ms.scan_project_licenses(str(tmp_path))
        assert "MIT" not in r["licenses"]

    def test_max_files_cap(self, tmp_path):
        for i in range(5):
            (tmp_path / f"L{i}").mkdir()
            (tmp_path / f"L{i}" / "LICENSE").write_text(MIT_TEXT, encoding="utf-8")
        r = ms.scan_project_licenses(str(tmp_path), max_files=2)
        assert r["total_files"] <= 2


# ----------------------------------------------------------------------
# 知识库加载与回退
# ----------------------------------------------------------------------
class TestKnowledgeBaseFallback:
    def test_full_library_has_16_entries(self):
        assert len(ms.LICENSES) == 16

    def test_fallback_without_licenses_json(self, tmp_path):
        """licenses.json 缺失时，独立加载的副本应回退到内置 3 项最小集合。"""
        copy = tmp_path / "mcp_server.py"
        shutil.copy(Path(ms.__file__), copy)
        assert not (tmp_path / "licenses.json").exists()

        spec = importlib.util.spec_from_file_location("mcp_server_fallback", copy)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.LICENSES == mod._FALLBACK_LICENSES
        assert set(mod.LICENSES) == {"MIT", "Apache-2.0", "GPL-3.0"}

    def test_fallback_tool_still_works(self, tmp_path):
        """回退模式下 get_license_info 对内置 3 项仍然可用。"""
        copy = tmp_path / "mcp_server.py"
        shutil.copy(Path(ms.__file__), copy)
        spec = importlib.util.spec_from_file_location("mcp_server_fallback2", copy)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.get_license_info("MIT")["copyleft"] == "无"
        assert "error" in mod.get_license_info("LGPL-3.0")  # 不在最小集合内
