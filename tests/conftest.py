"""Shared pytest setup.

Pure logic tests here (rollback, context_manager, models) never call a real
API, but importing src.config requires OPENAI_API_KEY to be set — it has no
fallback by design (see Documentation/ARCHITECTURE_DECISIONS.md, I1). Set a
placeholder before any src.* module gets imported by test collection, so
these tests don't need real credentials to run.
"""
import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-not-a-real-credential")
