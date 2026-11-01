"""tools.py 纯逻辑测试：表达式求值、安全拒绝、时间格式、工具注册表。

零依赖、全程离线，不调用任何模型。
"""

from datetime import datetime

import pytest

from tools import CUSTOM_TOOLS, calculator, get_current_time


class TestCalculator:
    """calculator：合法表达式求值。"""

    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("2 + 3 * 4", "14"),          # 优先级
            ("(3 + 5) * 2 ** 10", "8192"),  # 括号 + 幂
            ("1 / 2", "0.5"),             # 真除法
            ("10 // 3", "3"),             # 地板除
            ("10 % 3", "1"),              # 取模
            ("-3 + 5", "2"),              # 一元负号
        ],
    )
    def test_valid_expressions(self, expr, expected):
        assert calculator(expr) == expected

    @pytest.mark.parametrize(
        "expr",
        [
            "__import__('os').system('x')",  # 代码执行
            "open('x')",                      # 文件访问
            "a",                              # 裸标识符
            "os.getcwd()",                    # 属性链调用
            "lambda: 1",                      # lambda
            "[1, 2]",                         # 列表字面量
            "{'a': 1}",                       # 字典字面量
        ],
    )
    def test_rejects_code_execution(self, expr):
        """安全关键：非纯算术输入一律返回失败信息，绝不执行。"""
        assert calculator(expr).startswith("计算失败")

    def test_statement_injection_rejected(self):
        """分号注入语句不通过 eval 模式解析，返回失败而非执行。"""
        assert calculator("1 + 1; __import__('os').listdir('.')").startswith("计算失败")


class TestGetCurrentTime:
    def test_contains_weekday_and_today(self):
        now = datetime.now()
        result = get_current_time()
        assert "星期" in result
        assert result.startswith(now.strftime("%Y-%m-%d"))

    def test_weekday_matches_today(self):
        now = datetime.now()
        assert result_weekday(get_current_time()) == "一二三四五六日"[now.weekday()]


def result_weekday(text: str) -> str:
    """从 'YYYY-MM-DD HH:MM:SS 星期X' 中取星期字符。"""
    return text.split("星期")[-1].strip()


class TestCustomToolsRegistry:
    def test_registry_complete(self):
        names = {t.__name__ for t in CUSTOM_TOOLS}
        assert {"get_current_time", "calculator"} <= names

    def test_all_callable_with_docstring(self):
        for tool in CUSTOM_TOOLS:
            assert callable(tool)
            assert tool.__doc__, f"{tool.__name__} 缺少 docstring（模型靠它判断何时调用）"
