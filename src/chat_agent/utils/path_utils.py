"""Path resolution utilities for flexible file path configuration."""

from pathlib import Path


def resolve_csv_path(csv_path_setting: str, project_root_fallback: Path | None = None) -> Path:
    """
    Resolve CSV path with flexible fallback strategy.

    Resolution logic:
    1. Absolute path → use directly (e.g., Docker mounts: /app/config/model_costs.csv)
    2. Relative path (contains / or \\) → resolve from cwd (e.g., ./config/costs.csv)
    3. Filename only → resolve from project_root_fallback or cwd (default: model_costs.csv)

    Args:
        csv_path_setting: Path string from config/environment variable
        project_root_fallback: Project root directory. If None, auto-detects by
            navigating up from this file's location.

    Returns:
        Resolved absolute Path object

    Examples:
        >>> # Absolute path (Docker mount)
        >>> resolve_csv_path("/app/config/model_costs.csv")
        Path("/app/config/model_costs.csv")

        >>> # Relative path from cwd
        >>> resolve_csv_path("./config/model_costs.csv")
        Path("/current/working/dir/config/model_costs.csv")

        >>> # Filename only → project root
        >>> resolve_csv_path("model_costs.csv")
        Path("/project/root/model_costs.csv")
    """
    input_path = Path(csv_path_setting)

    # Case 1: Absolute path → use directly
    if input_path.is_absolute():
        return input_path

    # Case 2: Relative path with directory separators → resolve from cwd
    if "/" in str(input_path) or "\\" in str(input_path):
        return Path.cwd() / input_path

    # Case 3: Filename only → resolve from project root
    if project_root_fallback is None:
        # Auto-detect project root by finding pyproject.toml or langgraph.json
        # Start from current file and search upward
        current_path = Path(__file__).resolve()
        project_root_fallback = current_path

        # Search upward for project markers
        for _ in range(10):  # Max 10 levels up to prevent infinite loop
            if (project_root_fallback / "pyproject.toml").exists():
                break
            if (project_root_fallback / "langgraph.json").exists():
                break
            parent = project_root_fallback.parent
            if parent == project_root_fallback:  # Reached filesystem root
                break
            project_root_fallback = parent

    return project_root_fallback / input_path
