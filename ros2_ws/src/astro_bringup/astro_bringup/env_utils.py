"""Shared helpers for locating and loading the ASTRO repo-root .env file."""
import os
from typing import Optional


def find_env_file() -> Optional[str]:
    """Walk up from CWD and this module's location to find astr1/.env."""
    candidates = []
    cwd = os.getcwd()
    if cwd:
        candidates.append(cwd)

    here = os.path.dirname(os.path.abspath(__file__))
    if here not in candidates:
        candidates.append(here)

    seen = set()
    for start in candidates:
        current = start
        for _ in range(10):
            if current in seen:
                break
            seen.add(current)
            env_path = os.path.join(current, ".env")
            if os.path.isfile(env_path):
                return env_path
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    return None


def load_astro_env() -> Optional[str]:
    """Load repo-root .env into os.environ. Returns the path if found."""
    env_path = find_env_file()
    if not env_path:
        return None

    try:
        from dotenv import load_dotenv
    except ImportError:
        return env_path

    load_dotenv(env_path, override=False)
    return env_path
