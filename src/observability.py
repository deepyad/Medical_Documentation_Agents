"""Structured logging + error tracking. See Documentation/ARCHITECTURE_DECISIONS.md, J2.

LangSmith (already integrated — see src/evals.py) covers LLM/agent traces well,
but won't surface infrastructure-level failures (DB connection errors, tool
exceptions swallowed into a return value, etc.). This module fills that gap:

- Structured logging via structlog, so log lines carry queryable fields
  (action_type, resource_id, ...) instead of being plain strings.
- Error tracking via Sentry, entirely optional — a no-op if SENTRY_DSN isn't
  set, matching the pattern already used for QDRANT_API_KEY/DATABASE_URL.

Call init_observability() once at process startup (see run_agent.py,
run_evals.py, src/mcp_server.py) — deliberately not a module-level side
effect on import, so importing src.rollback/src.agent/etc. for tests doesn't
implicitly configure logging or initialize Sentry.
"""
import logging
import sys

import sentry_sdk
import structlog

from src.config import settings

_configured = False


def init_observability() -> None:
    """Configure structured logging and (optionally) error tracking. Idempotent."""
    global _configured
    if _configured:
        return

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level.upper(),
    )

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.environment == "production"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment)

    _configured = True


def get_logger(name: str):
    """Thin wrapper around structlog.get_logger — call init_observability() first."""
    return structlog.get_logger(name)
