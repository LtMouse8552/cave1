"""
自定义工具
==========

Deep Agents 的工具就是普通 Python 函数（或 LangChain 的 @tool）。
函数名 = 工具名，docstring = 工具说明，类型注解 = 参数 schema。
模型依靠 docstring 判断何时调用，所以 docstring 要写清楚。

新增工具：在这里写一个函数，然后加入文件末尾的 CUSTOM_TOOLS 列表。
"""

import ast
import operator
from datetime import datetime


def get_current_time() -> str:
    """获取当前的本地日期、时间和星期。回答与“今天/现在/几号/星期几”有关的问题时使用。"""
    now = datetime.now()
    weekday = "一二三四五六日"[now.weekday()]
    return now.strftime("%Y-%m-%d %H:%M:%S") + f" 星期{weekday}"


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node):
    """只允许数字和算术运算的安全求值，避免直接 eval 带来的代码执行风险。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("只支持数字和 + - * / // % ** 运算")


def calculator(expression: str) -> str:
    """精确计算数学表达式，例如 "(3 + 5) * 2 ** 10"。涉及数值计算时务必使用，不要心算。

    Args:
        expression: 只包含数字、括号和 + - * / // % ** 的表达式
    """
    try:
        return str(_eval(ast.parse(expression, mode="eval").body))
    except Exception as exc:  # noqa: BLE001
        return f"计算失败：{exc}"


# 在这里登记要交给 Agent 的自定义工具
CUSTOM_TOOLS = [get_current_time, calculator]
