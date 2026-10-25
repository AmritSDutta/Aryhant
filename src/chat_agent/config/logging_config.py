import logging
import sys

LEVEL_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;31m",
}
RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    def format(self, record):
        color = LEVEL_COLORS.get(record.levelname.replace(RESET, ""), "")
        record.levelname = f"{color}{record.levelname}{RESET}"
        return super().format(record)


def setup_logging():
    """
    Force a clean logging environment even when Uvicorn/LangGraph
    auto-configures their own handlers.
    """
    # 0. Ensure stdout can encode emoji/status glyphs on Windows (cp1252) consoles
    try:
        if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 1. Remove existing handlers
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    LOG_FORMAT = (
        "%(asctime)s.%(msecs)03d | %(levelname)-8s | "
        "%(name)s | %(module)s.%(funcName)s:%(lineno)d | %(message)s"
    )
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    # 2. Create your colored handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorFormatter(LOG_FORMAT, DATE_FORMAT))

    # 3. Rebuild logging tree with your rules
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        force=True,  # <-- crucial to override uvicorn/langgraph setup
    )

    # 4. Silence noisy libraries
    noisy = [
        "uvicorn", "uvicorn.access",
        "httpx",
        "langgraph",
        "langgraph_runtime_inmem",
        "langchain",
        "langchain_core",
        "asyncio",
        "httpcore",
    ]
    for name in noisy:
        logging.getLogger(name).setLevel(logging.WARNING)
