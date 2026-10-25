"""Clean and convert LaTeX mathematical expressions into human-readable plain text."""
from __future__ import annotations

import re


def clean_math_text(text: str) -> str:
    """Convert LaTeX formulas and math syntax to clean, human-readable plain text."""
    if not text:
        return ""

    out = text

    # Handle fractions iteratively for nested expressions: \frac{a}{b} -> a/b
    frac_pattern = re.compile(r"\\(?:d|t)?frac\{([^{}]+)\}\{([^{}]+)\}")
    while frac_pattern.search(out):
        out = frac_pattern.sub(r"\1/\2", out)

    # Standard mathematical symbols and operators
    replacements = [
        (r"\\times", "×"),
        (r"\\div", "÷"),
        (r"\\cdot", "·"),
        (r"\\pm", "±"),
        (r"\\mp", "∓"),
        (r"\\leq|\\le", "≤"),
        (r"\\geq|\\ge", "≥"),
        (r"\\neq|\\ne", "≠"),
        (r"\\approx", "≈"),
        (r"\\equiv", "≡"),
        (r"\\infty", "∞"),
        (r"\\pi", "π"),
        (r"\\degree|\\circ", "°"),
        (r"\\sqrt\{([^{}]+)\}", r"√(\1)"),
        (r"\\sqrt\s*([a-zA-Z0-9]+)", r"√\1"),
        (r"\\(?:text|mathrm|mathbf|mathit|textsf)\{([^{}]+)\}", r"\1"),
        (r"\\left\(", "("),
        (r"\\right\)", ")"),
        (r"\\left\[", "["),
        (r"\\right\]", "]"),
        (r"\\left\\{", "{"),
        (r"\\right\\}", "}"),
        (r"\\,", " "),
        (r"\\;", " "),
        (r"\\quad", " "),
        (r"\\qquad", "  "),
    ]

    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out)

    # Strip math delimiters $$...$$ and $...$
    out = re.sub(r"\$\$(.*?)\$\$", r"\1", out, flags=re.DOTALL)
    out = re.sub(r"\$(.*?)\$", r"\1", out)

    # Clean up redundant spaces around fraction slashes e.g. "3 / 5" -> "3/5"
    out = re.sub(r"(\d+)\s*/\s*(\d+)", r"\1/\2", out)
    # Clean up mixed fraction spacing like "1  3/4" -> "1 3/4"
    out = re.sub(r"(\d+)\s{2,}(\d+/\d+)", r"\1 \2", out)

    return out
