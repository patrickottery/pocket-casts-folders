import os
from pathlib import Path


def load_dotenv_if_present(path: Path | None = None) -> None:
    """Minimal .env loader (KEY=VALUE per line). No external dependency.

    Existing environment variables always win over .env values.
    """
    env_path = path or Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
