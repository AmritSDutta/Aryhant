from __future__ import annotations

import ast
import logging
import math
import operator
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

_SAFE_OPERATORS: dict[type, Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_SAFE_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": pow,
    "sqrt": math.sqrt,
    "isqrt": math.isqrt,
    "gcd": math.gcd,
    "lcm": math.lcm,
    "factorial": math.factorial,
    "floor": math.floor,
    "ceil": math.ceil,
}


def _safe_math_eval(node: ast.AST) -> Any:
    """Recursively evaluate an AST node safely without using eval."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")

    if isinstance(node, ast.BinOp):
        op_func = _SAFE_OPERATORS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported binary operator: {type(node.op).__name__}")
        left = _safe_math_eval(node.left)
        right = _safe_math_eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 500 or abs(left) > 10000):
            raise ValueError("Exponent or base exceeds safe bounds")
        return op_func(left, right)

    if isinstance(node, ast.UnaryOp):
        op_func = _SAFE_OPERATORS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_func(_safe_math_eval(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        fn_name = node.func.id.lower()
        fn = _SAFE_FUNCTIONS.get(fn_name)
        if fn is None:
            raise ValueError(f"Function '{fn_name}' is not allowed")
        args = [_safe_math_eval(arg) for arg in node.args]
        return fn(*args)

    raise ValueError(f"Unsupported expression element: {type(node).__name__}")


def calculate_math(expression: str) -> Dict[str, Any]:
    """Evaluate a math expression safely using AST parsing (no eval)."""
    expr = str(expression or "").strip()
    if not expr:
        return {"status": "error", "message": "expression is required"}
    if len(expr) > 1000:
        return {"status": "error", "message": "expression too long (max 1000 chars)"}

    try:
        tree = ast.parse(expr, mode="eval")
        result = _safe_math_eval(tree.body)
        logger.info("calculate_math: %s = %s", expr, result)
        return {"status": "ok", "result": f"The result is {result}", "value": result}
    except ZeroDivisionError:
        return {"status": "ok", "result": "Division by zero is not defined, so that has no result."}
    except Exception as exc:
        logger.error("calculate_math error on %r: %s", expr, exc)
        return {"status": "error", "message": f"Math error: {exc}"}
