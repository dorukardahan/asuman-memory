"""NoldoMem MemoryProvider adapter for Hermes Agent."""

from __future__ import annotations

import json
import math
import os
import signal
import threading
import time
import urllib.error
import urllib.request

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from agent.memory_provider import MemoryProvider
except Exception:  # pragma: no cover - used only outside Hermes tests
    class MemoryProvider:  # type: ignore
        pass

try:
    from agent.memory_manager import sanitize_context
except Exception:  # pragma: no cover - Hermes supplies this at runtime
    def sanitize_context(text: str) -> str:
        return text.replace("<memory-context>", "").replace("</memory-context>", "")


VALID_MEMORY_TYPES = {"fact", "preference", "rule", "conversation", "lesson", "other"}
DEFAULT_BASE_URL = "http://127.0.0.1:8787"
# NoldoMem API rejects recall queries longer than 2000 chars (HTTP 422).
# Truncate well below that to leave room for safe UTF-8 boundaries.
RECALL_QUERY_MAX_CHARS = 1950
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_RECALL_CACHE_TTL_SECONDS = 300.0
DEFAULT_RECALL_CACHE_MAX_ENTRIES = 128
READINESS_MAX_BYTES = 16 * 1024
READINESS_MAX_TIMEOUT_SECONDS = 2.0
SHUTDOWN_TIMEOUT_SECONDS = 5.0


@dataclass
class NoldoMemConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    agent: str = "hermes"
    namespace: str = "default"
    recall_limit: int = 5
    recall_max_chars: int = 3500
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    prefetch_enabled: bool = True
    sync_prefetch_on_miss: bool = True
    sync_turns_enabled: bool = False
    tools_enabled: bool = True
    non_primary_writes_enabled: bool = False
    recall_cache_ttl_seconds: float = DEFAULT_RECALL_CACHE_TTL_SECONDS
    recall_cache_max_entries: int = DEFAULT_RECALL_CACHE_MAX_ENTRIES


class NoldoMemHTTPClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self.api_key,
            },
        )
        try:
            response = urllib.request.urlopen(req, timeout=self.timeout_seconds)
            try:
                raw = response.read().decode("utf-8")
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            return json.loads(raw or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.reason or f"HTTP {exc.code}"
            raise RuntimeError(f"NoldoMem API request failed: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("NoldoMem API is unavailable") from exc
        except TimeoutError as exc:
            raise RuntimeError("NoldoMem API timed out") from exc

    def recall(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/v1/recall", body)

    def store(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/v1/store", body)

    def pin(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/v1/pin", body)


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _as_float(value: Any, default: float, *, minimum: float = 0.1, maximum: float = 10.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(minimum, min(maximum, parsed))


def _read_text_file(path: str) -> str:
    if not path:
        return ""
    try:
        return Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _load_json_file(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _default_hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 15)].rstrip() + " ...[truncated]"


class _ReadinessPayloadTooLarge(ValueError):
    pass


class _ReadinessDeadlineExceeded(TimeoutError):
    pass


class _ReadinessDeadlineUnavailable(RuntimeError):
    pass


class NoldoMemProvider(MemoryProvider):
    @property
    def name(self) -> str:
        return "noldomem"

    def __init__(self) -> None:
        self._config = NoldoMemConfig()
        self._client: Optional[NoldoMemHTTPClient] = None
        self._session_id = ""
        self._initialized = False
        self._writes_enabled = False
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._session_generation = 0
        self._closing = False
        self._shutdown_deadline: Optional[float] = None
        self._lock = threading.Lock()
        self._operation_lock = threading.Lock()

    def load_config(self, hermes_home: Optional[str] = None, **overrides: Any) -> NoldoMemConfig:
        home = Path(hermes_home).expanduser() if hermes_home else _default_hermes_home()
        config_path = (
            os.environ.get("NOLDOMEM_CONFIG_FILE")
            or os.environ.get("NOLDOMEM_CONFIG")
            or str(home / "noldomem.json")
        )
        raw = _load_json_file(Path(config_path))
        raw.update({k: v for k, v in overrides.items() if v is not None})

        key = (
            os.environ.get("NOLDOMEM_API_KEY")
            or _read_text_file(os.environ.get("NOLDOMEM_API_KEY_FILE", ""))
            or _read_text_file(str(raw.get("api_key_file", "")))
            or _read_text_file(str(home / "noldomem-api-key"))
            or _read_text_file(str(Path.home() / ".noldomem" / "memory-api-key"))
        )

        return NoldoMemConfig(
            base_url=str(os.environ.get("NOLDOMEM_BASE_URL") or raw.get("base_url") or DEFAULT_BASE_URL),
            api_key=key,
            agent=str(os.environ.get("NOLDOMEM_AGENT") or raw.get("agent") or "hermes"),
            namespace=str(os.environ.get("NOLDOMEM_NAMESPACE") or raw.get("namespace") or "default"),
            recall_limit=_as_int(
                os.environ.get("NOLDOMEM_RECALL_LIMIT") or raw.get("recall_limit"),
                5,
                minimum=1,
                maximum=20,
            ),
            recall_max_chars=_as_int(
                os.environ.get("NOLDOMEM_RECALL_MAX_CHARS") or raw.get("recall_max_chars"),
                3500,
                minimum=500,
                maximum=12000,
            ),
            timeout_seconds=_as_float(
                os.environ.get("NOLDOMEM_TIMEOUT_SECONDS") or raw.get("timeout_seconds"),
                DEFAULT_TIMEOUT_SECONDS,
                minimum=0.2,
                maximum=10.0,
            ),
            prefetch_enabled=_as_bool(
                os.environ.get("NOLDOMEM_PREFETCH_ENABLED") or raw.get("prefetch_enabled"),
                True,
            ),
            sync_prefetch_on_miss=_as_bool(
                os.environ.get("NOLDOMEM_SYNC_PREFETCH_ON_MISS") or raw.get("sync_prefetch_on_miss"),
                True,
            ),
            sync_turns_enabled=_as_bool(
                os.environ.get("NOLDOMEM_SYNC_TURNS_ENABLED") or raw.get("sync_turns_enabled"),
                False,
            ),
            tools_enabled=_as_bool(
                os.environ.get("NOLDOMEM_TOOLS_ENABLED") or raw.get("tools_enabled"),
                True,
            ),
            non_primary_writes_enabled=_as_bool(
                os.environ.get("NOLDOMEM_NON_PRIMARY_WRITES_ENABLED") or raw.get("non_primary_writes_enabled"),
                False,
            ),
            recall_cache_ttl_seconds=_as_float(
                os.environ.get("NOLDOMEM_RECALL_CACHE_TTL_SECONDS") or raw.get("recall_cache_ttl_seconds"),
                DEFAULT_RECALL_CACHE_TTL_SECONDS,
                minimum=0.1,
                maximum=3600.0,
            ),
            recall_cache_max_entries=_as_int(
                os.environ.get("NOLDOMEM_RECALL_CACHE_MAX_ENTRIES") or raw.get("recall_cache_max_entries"),
                DEFAULT_RECALL_CACHE_MAX_ENTRIES,
                minimum=1,
                maximum=4096,
            ),
        )

    def is_available(self) -> bool:
        cfg = self.load_config()
        self._config = cfg
        return bool(cfg.base_url and cfg.api_key)

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        agent_override = kwargs.get("agent_identity")
        cfg = self.load_config(kwargs.get("hermes_home"))
        if cfg.agent in {"", "auto"} and agent_override:
            cfg.agent = str(agent_override)
        self._config = cfg
        self._client = NoldoMemHTTPClient(cfg.base_url, cfg.api_key, cfg.timeout_seconds)
        with self._lock:
            self._session_id = session_id
            self._session_generation += 1
            self._cache.clear()
        self._initialized = bool(cfg.api_key)

        agent_context = str(kwargs.get("agent_context") or "primary")
        self._writes_enabled = cfg.sync_turns_enabled and (
            agent_context == "primary" or cfg.non_primary_writes_enabled
        )

    def system_prompt_block(self) -> str:
        if not self._initialized:
            return ""
        return (
            "NoldoMem external memory is active. Use noldomem_recall for prior "
            "project/user facts, noldomem_store for durable facts, preferences, "
            "rules, lessons, and decisions, and noldomem_pin only for critical "
            "memories. Prefer these tools over Hermes built-in memory when both "
            "appear."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not (self._initialized and self._config.prefetch_enabled and query.strip()):
            return ""
        effective_session_id, _ = self._session_snapshot(session_id)
        key = self._cache_key(query, effective_session_id)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        if not self._config.sync_prefetch_on_miss:
            return ""
        return self._recall_context(query, session_id=session_id)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        if not (self._initialized and self._config.prefetch_enabled and query.strip()):
            return
        self._recall_context(query, session_id=session_id)

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        if not (self._initialized and self._writes_enabled and user_content and assistant_content):
            return
        text = _truncate(
            f"User: {user_content.strip()}\nAssistant: {assistant_content.strip()}",
            3000,
        )
        body = self._base_body(session_id=session_id)
        body.update(
            {
                "text": text,
                "memory_type": "conversation",
                "source": "hermes-sync-turn",
            }
        )
        self._safe_store(body)

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs: Any,
    ) -> None:
        if not new_session_id:
            return
        reason = str(kwargs.get("reason") or "").strip().lower()
        rewound = kwargs.get("rewound") is True
        with self._lock:
            previous_session_id = self._session_id
            self._session_id = new_session_id
            if reset or rewound or new_session_id != previous_session_id or reason in {"compression", "rewind"}:
                self._session_generation += 1
                self._cache.clear()

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        if not self._config.tools_enabled:
            return []
        return [
            {
                "name": "noldomem_recall",
                "description": "Recall relevant long-term memories from NoldoMem.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                        "namespace": {"type": "string"},
                        "memory_type": {"type": "string", "enum": sorted(VALID_MEMORY_TYPES)},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "noldomem_store",
                "description": "Store a durable memory in NoldoMem.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Memory text to store."},
                        "memory_type": {"type": "string", "enum": sorted(VALID_MEMORY_TYPES)},
                        "namespace": {"type": "string"},
                        "source": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "noldomem_pin",
                "description": "Pin a critical NoldoMem memory by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string", "description": "Memory ID to pin."},
                    },
                    "required": ["memory_id"],
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs: Any) -> str:
        if not self._client:
            return self._json_error("NoldoMem is not configured")
        try:
            if tool_name == "noldomem_recall":
                body = self._base_body(session_id=kwargs.get("session_id", ""))
                body["query"] = _truncate(str(args.get("query") or "").strip(), RECALL_QUERY_MAX_CHARS)
                body["limit"] = _as_int(args.get("limit"), self._config.recall_limit, minimum=1, maximum=20)
                if args.get("namespace"):
                    body["namespace"] = str(args["namespace"])
                if args.get("memory_type"):
                    body["memory_type"] = self._memory_type(args["memory_type"])
                return json.dumps({"success": True, "data": self._client.recall(body)}, ensure_ascii=False)

            if tool_name == "noldomem_store":
                body = self._base_body(session_id=kwargs.get("session_id", ""))
                body["text"] = str(args.get("text") or "").strip()
                body["memory_type"] = self._memory_type(args.get("memory_type") or "other")
                body["source"] = str(args.get("source") or "hermes-tool")
                if args.get("namespace"):
                    body["namespace"] = str(args["namespace"])
                return json.dumps({"success": True, "data": self._client.store(body)}, ensure_ascii=False)

            if tool_name == "noldomem_pin":
                memory_id = str(args.get("memory_id") or "").strip()
                if not memory_id:
                    return self._json_error("memory_id is required")
                body = {"id": memory_id, "agent": self._config.agent}
                return json.dumps({"success": True, "data": self._client.pin(body)}, ensure_ascii=False)

            return self._json_error(f"unknown tool: {tool_name}")
        except Exception as exc:
            return self._json_error(str(exc))

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not (self._initialized and content.strip() and self._client):
            return
        with self._operation_lock:
            with self._lock:
                if self._closing:
                    return
            memory_type = "preference" if target == "user" else "fact"
            body = self._base_body()
            body.update(
                {
                    "text": content.strip(),
                    "memory_type": memory_type,
                    "category": "user" if target == "user" else "other",
                    "source": f"hermes-built-in-memory-{action}",
                }
            )
            self._safe_store(body)

    def shutdown(self) -> None:
        started_at = time.monotonic()
        with self._lock:
            if not self._closing:
                self._closing = True
                self._shutdown_deadline = started_at + SHUTDOWN_TIMEOUT_SECONDS
            deadline = self._shutdown_deadline or started_at

        remaining = max(0.0, deadline - time.monotonic())
        acquired = self._operation_lock.acquire(timeout=remaining)
        if acquired:
            self._operation_lock.release()

    def probe_readiness(self, timeout_seconds: float = READINESS_MAX_TIMEOUT_SECONDS) -> Dict[str, Any]:
        """Perform one explicit bounded health read and return allowlisted metadata."""
        cfg = self.load_config()
        if not (cfg.base_url and cfg.api_key):
            return {
                "ready": False,
                "status": "unconfigured",
                "storage_ok": None,
                "embedding_ok": None,
                "uptime_seconds": None,
                "error_type": "",
            }

        timeout = _as_float(
            timeout_seconds,
            READINESS_MAX_TIMEOUT_SECONDS,
            minimum=0.1,
            maximum=READINESS_MAX_TIMEOUT_SECONDS,
        )
        try:
            previous_signal_handler = self._install_readiness_deadline(timeout)
        except _ReadinessDeadlineUnavailable as exc:
            return self._readiness_failure(exc)

        try:
            request = urllib.request.Request(cfg.base_url.rstrip("/") + "/v1/health", method="GET")
            response = urllib.request.urlopen(request, timeout=timeout)
            try:
                raw = response.read(READINESS_MAX_BYTES + 1)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            if len(raw) > READINESS_MAX_BYTES:
                raise _ReadinessPayloadTooLarge()
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError()
            status = payload.get("status")
            if status not in {"ok", "degraded", "down"}:
                raise ValueError()
            checks = payload.get("checks")
            if not isinstance(checks, dict):
                checks = {}
            storage_ok = checks.get("storage")
            embedding_ok = checks.get("embedding")
            uptime_seconds = payload.get("uptime_seconds")
            if not isinstance(storage_ok, bool):
                storage_ok = None
            if not isinstance(embedding_ok, bool):
                embedding_ok = None
            if (
                isinstance(uptime_seconds, bool)
                or not isinstance(uptime_seconds, (int, float))
                or not math.isfinite(uptime_seconds)
            ):
                uptime_seconds = None
            return {
                "ready": status == "ok",
                "status": status,
                "storage_ok": storage_ok,
                "embedding_ok": embedding_ok,
                "uptime_seconds": uptime_seconds,
                "error_type": "",
            }
        except Exception as exc:
            return self._readiness_failure(exc)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous_signal_handler)

    def _base_body(self, *, session_id: str = "") -> Dict[str, Any]:
        body = {
            "agent": self._config.agent,
            "namespace": self._config.namespace,
        }
        sid = session_id or self._session_id
        if sid:
            body["session_id"] = sid
        return body

    def _safe_store(self, body: Dict[str, Any]) -> None:
        try:
            if self._client:
                self._client.store(body)
        except Exception:
            return

    def _recall_context(self, query: str, *, session_id: str = "") -> str:
        if not self._client:
            return ""
        try:
            effective_session_id, session_generation = self._session_snapshot(session_id)
            body = self._base_body(session_id=effective_session_id)
            body.update({"query": _truncate(query, RECALL_QUERY_MAX_CHARS), "limit": self._config.recall_limit})
            data = self._client.recall(body)
            context = self._format_recall(data)
            key = self._cache_key(query, effective_session_id)
            self._cache_put(key, context, session_generation=session_generation)
            return context
        except Exception:
            return ""

    def _cache_get(self, key: str) -> Optional[str]:
        now = time.monotonic()
        with self._lock:
            self._prune_cache_locked(now)
            cached = self._cache.get(key)
            if cached is None:
                return None
            self._cache.move_to_end(key)
            return cached[1]

    def _cache_put(self, key: str, context: str, *, session_generation: int) -> None:
        now = time.monotonic()
        with self._lock:
            if session_generation != self._session_generation:
                return
            self._prune_cache_locked(now)
            self._cache[key] = (now, context)
            self._cache.move_to_end(key)
            while len(self._cache) > self._config.recall_cache_max_entries:
                self._cache.popitem(last=False)

    def _prune_cache_locked(self, now: float) -> None:
        ttl = self._config.recall_cache_ttl_seconds
        expired = [key for key, (created_at, _) in self._cache.items() if now - created_at >= ttl]
        for key in expired:
            self._cache.pop(key, None)

    def _format_recall(self, data: Dict[str, Any]) -> str:
        results = data.get("results") or data.get("memories") or []
        if not results:
            return ""
        lines = ["NoldoMem recall:"]
        used = len(lines[0])
        for item in results:
            text = sanitize_context(str(item.get("text") or item.get("content") or "")).strip()
            if not text:
                continue
            memory_type = item.get("memory_type") or item.get("type") or "memory"
            score = item.get("rerank_score") or item.get("semantic_score") or item.get("score")
            score_text = f" score={score:.3f}" if isinstance(score, (float, int)) else ""
            line = f"- [{memory_type}{score_text}] {text}"
            remaining = self._config.recall_max_chars - used - 1
            if remaining <= 0:
                break
            line = _truncate(line, remaining)
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines) if len(lines) > 1 else ""

    def _cache_key(self, query: str, session_id: str) -> str:
        normalized_query = _truncate(query.strip(), RECALL_QUERY_MAX_CHARS).lower()
        return f"{session_id}:{normalized_query}"

    def _session_snapshot(self, session_id: str) -> tuple[str, int]:
        with self._lock:
            return session_id or self._session_id, self._session_generation

    @staticmethod
    def _readiness_failure(exc: Exception) -> Dict[str, Any]:
        if isinstance(exc, _ReadinessDeadlineExceeded):
            error_type = "DeadlineExceeded"
        elif isinstance(exc, _ReadinessDeadlineUnavailable):
            error_type = "DeadlineUnavailable"
        elif isinstance(exc, _ReadinessPayloadTooLarge):
            error_type = "ResponseTooLarge"
        elif isinstance(exc, urllib.error.HTTPError):
            error_type = "HTTPError"
        elif isinstance(exc, urllib.error.URLError):
            error_type = "URLError"
        elif isinstance(exc, TimeoutError):
            error_type = "TimeoutError"
        elif isinstance(exc, OSError):
            error_type = "OSError"
        elif isinstance(exc, (UnicodeDecodeError, ValueError)):
            error_type = "InvalidResponse"
        else:
            error_type = "ReadinessError"
        return {
            "ready": False,
            "status": "unavailable",
            "storage_ok": None,
            "embedding_ok": None,
            "uptime_seconds": None,
            "error_type": error_type,
        }

    @staticmethod
    def _install_readiness_deadline(timeout_seconds: float) -> Any:
        if (
            threading.current_thread() is not threading.main_thread()
            or not hasattr(signal, "SIGALRM")
            or not hasattr(signal, "ITIMER_REAL")
            or not hasattr(signal, "setitimer")
            or not hasattr(signal, "getitimer")
        ):
            raise _ReadinessDeadlineUnavailable()

        current_timer = signal.getitimer(signal.ITIMER_REAL)
        if current_timer[0] > 0.0:
            raise _ReadinessDeadlineUnavailable()

        previous_handler = signal.getsignal(signal.SIGALRM)

        def deadline_exceeded(signum: int, frame: Any) -> None:
            raise _ReadinessDeadlineExceeded()

        try:
            signal.signal(signal.SIGALRM, deadline_exceeded)
            signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
        except Exception as exc:
            signal.signal(signal.SIGALRM, previous_handler)
            raise _ReadinessDeadlineUnavailable() from exc
        return previous_handler

    def _memory_type(self, raw: Any) -> str:
        value = str(raw or "other").strip().lower()
        if value not in VALID_MEMORY_TYPES:
            raise ValueError(f"invalid memory_type: {value}")
        return value

    @staticmethod
    def _json_error(message: str) -> str:
        return json.dumps({"success": False, "error": message}, ensure_ascii=False)


def register(ctx: Any) -> None:
    ctx.register_memory_provider(NoldoMemProvider())
