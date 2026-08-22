"""Vercel entrypoint: the real FastAPI engine as an ASGI function."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server import app  # noqa: F401
