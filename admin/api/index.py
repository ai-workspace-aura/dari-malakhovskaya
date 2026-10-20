"""Точка входа для Vercel: все запросы к /api, /go и /hooks обрабатывает server.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import Handler  # noqa: E402


class handler(Handler):
    pass
