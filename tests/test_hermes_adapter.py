import json
import signal
import sys
import threading
import time
import types
from pathlib import Path


class _MemoryProvider:
    pass


def _sanitize_context(text):
    return text.replace("<memory-context>", "").replace("</memory-context>", "")


agent_module = types.ModuleType("agent")
memory_provider_module = types.ModuleType("agent.memory_provider")
memory_provider_module.MemoryProvider = _MemoryProvider
memory_manager_module = types.ModuleType("agent.memory_manager")
memory_manager_module.sanitize_context = _sanitize_context
sys.modules.setdefault("agent", agent_module)
sys.modules.setdefault("agent.memory_provider", memory_provider_module)
sys.modules.setdefault("agent.memory_manager", memory_manager_module)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "adapters" / "hermes"))

from noldomem import DEFAULT_TIMEOUT_SECONDS, NoldoMemHTTPClient, NoldoMemProvider  # noqa: E402
from noldomem import doctor as noldomem_doctor  # noqa: E402


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        pass


def _configured_provider(monkeypatch, tmp_path, **config):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    (tmp_path / "noldomem.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))
    monkeypatch.delenv("NOLDOMEM_CONFIG_FILE", raising=False)
    monkeypatch.delenv("NOLDOMEM_CONFIG", raising=False)

    provider = NoldoMemProvider()
    provider.initialize("session-1", hermes_home=str(tmp_path))
    return provider


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_http_client_uses_x_api_key_header(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["api_key"] = req.get_header("X-api-key")
        return _Response({"ok": True})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = NoldoMemHTTPClient("http://127.0.0.1:8787", "test-api-key", 1.25)
    assert client.pin({"id": "mem_1", "agent": "hermes"}) == {"ok": True}
    assert captured == {
        "url": "http://127.0.0.1:8787/v1/pin",
        "timeout": 1.25,
        "body": {"id": "mem_1", "agent": "hermes"},
        "api_key": "test-api-key",
    }


def test_provider_exposes_stable_tool_names(monkeypatch, tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))

    provider = NoldoMemProvider()
    names = [schema["name"] for schema in provider.get_tool_schemas()]

    assert names == ["noldomem_recall", "noldomem_store", "noldomem_pin"]
    assert provider.is_available() is True


def test_provider_default_timeout_allows_hosted_reranker_latency(monkeypatch, tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))

    provider = NoldoMemProvider()
    cfg = provider.load_config(str(tmp_path))

    assert cfg.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert cfg.timeout_seconds >= 8.0


def test_provider_pin_tool_uses_id_payload(monkeypatch, tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))

    captured = {}

    class FakeClient:
        def pin(self, body):
            captured.update(body)
            return {"pinned": True}

    provider = NoldoMemProvider()
    provider.initialize("session-1", hermes_home=str(tmp_path))
    provider._client = FakeClient()

    result = json.loads(provider.handle_tool_call("noldomem_pin", {"memory_id": "mem_1"}))

    assert result["success"] is True
    assert captured == {"id": "mem_1", "agent": "hermes"}


def test_prefetch_formats_recall_without_memory_context_tags(monkeypatch, tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))

    class FakeClient:
        def recall(self, body):
            return {
                "results": [
                    {
                        "text": "<memory-context>Use BGE-M3 for embeddings.</memory-context>",
                        "memory_type": "rule",
                        "semantic_score": 0.91,
                    }
                ]
            }

    provider = NoldoMemProvider()
    provider.initialize("session-1", hermes_home=str(tmp_path))
    provider._client = FakeClient()

    context = provider.prefetch("embedding model?", session_id="session-1")

    assert "NoldoMem recall:" in context
    assert "Use BGE-M3 for embeddings." in context
    assert "<memory-context>" not in context


def test_store_rejects_invalid_memory_type(monkeypatch, tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))

    provider = NoldoMemProvider()
    provider.initialize("session-1", hermes_home=str(tmp_path))
    result = json.loads(
        provider.handle_tool_call(
            "noldomem_store",
            {"text": "hello", "memory_type": "deployment"},
        )
    )

    assert result["success"] is False
    assert "invalid memory_type" in result["error"]


def test_session_switch_updates_default_tool_session(monkeypatch, tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))

    captured = {}

    class FakeClient:
        def store(self, body):
            captured.update(body)
            return {"stored": True}

    provider = NoldoMemProvider()
    provider.initialize("session-1", hermes_home=str(tmp_path))
    provider._client = FakeClient()

    provider.on_session_switch(
        "session-2",
        parent_session_id="session-1",
        reset=False,
        reason="compression",
    )
    result = json.loads(
        provider.handle_tool_call("noldomem_store", {"text": "rotated session memory"})
    )

    assert result["success"] is True
    assert captured["session_id"] == "session-2"


def test_session_switch_reset_clears_prefetch_cache(monkeypatch, tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))

    provider = NoldoMemProvider()
    provider.initialize("session-1", hermes_home=str(tmp_path))
    provider._cache["session-1:query"] = (1.0, "old result")

    provider.on_session_switch("session-2", parent_session_id="session-1", reset=True)

    assert provider._session_id == "session-2"
    assert provider._cache == {}


def test_queue_prefetch_runs_in_the_host_lane_without_provider_threads(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    caller_thread = threading.get_ident()
    calls = []
    lock = threading.Lock()

    class FakeClient:
        def recall(self, body):
            with lock:
                calls.append((body["query"], threading.get_ident()))
            return {"results": []}

    provider._client = FakeClient()

    for index in range(40):
        provider.queue_prefetch(f"query-{index}", session_id="session-1")

    assert _wait_until(lambda: len(calls) == 40)
    assert {thread_id for _, thread_id in calls} == {caller_thread}
    assert not hasattr(provider, "_threads")
    assert not hasattr(provider, "_fallback")


def test_sync_turn_runs_once_in_the_host_lane(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path, sync_turns_enabled=True)
    caller_thread = threading.get_ident()
    calls = []

    class FakeClient:
        def store(self, body):
            calls.append((body, threading.get_ident()))
            return {"stored": True}

    provider._client = FakeClient()

    provider.sync_turn("hello", "hi", session_id="session-1")

    assert _wait_until(lambda: len(calls) == 1)
    assert calls[0][1] == caller_thread
    assert calls[0][0]["source"] == "hermes-sync-turn"
    assert not hasattr(provider, "_threads")
    assert not hasattr(provider, "_fallback")


def test_memory_write_runs_once_synchronously_without_provider_owned_work(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    caller_thread = threading.get_ident()
    calls = []

    class FakeClient:
        def store(self, body):
            calls.append((body, threading.get_ident()))
            return {"stored": True}

    provider._client = FakeClient()
    provider.on_memory_write("create", "user", "Use compact replies")

    assert len(calls) == 1
    assert calls[0][0]["source"] == "hermes-built-in-memory-create"
    assert calls[0][1] == caller_thread
    assert not hasattr(provider, "_threads")
    assert not hasattr(provider, "_fallback")


def test_memory_write_returns_only_after_provider_operation_finishes(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    call_returned = threading.Event()

    class FakeClient:
        def store(self, body):
            started.set()
            release.wait(1.0)
            completed.set()
            return {"stored": True}

    provider._client = FakeClient()
    worker = threading.Thread(
        target=lambda: (provider.on_memory_write("create", "user", "Remember this"), call_returned.set())
    )
    worker.start()
    assert started.wait(1.0)
    assert call_returned.is_set() is False

    release.set()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert call_returned.is_set()
    assert completed.is_set()
    assert not hasattr(provider, "_threads")
    assert not hasattr(provider, "_fallback")


def test_shutdown_is_immediate_and_idempotent_without_provider_owned_operations(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    provider.shutdown()
    provider.shutdown()

    assert not hasattr(provider, "_threads")
    assert not hasattr(provider, "_fallback")


def test_shutdown_does_not_return_while_synchronous_memory_write_is_running(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    operation_started = threading.Event()
    release_operation = threading.Event()
    shutdown_started = threading.Event()
    shutdown_returned = threading.Event()

    class FakeClient:
        def store(self, body):
            operation_started.set()
            release_operation.wait(1.0)
            return {"stored": True}

    provider._client = FakeClient()
    operation_thread = threading.Thread(
        target=provider.on_memory_write,
        args=("create", "project", "in-flight write"),
    )
    operation_thread.start()
    assert operation_started.wait(1.0)

    def run_shutdown():
        shutdown_started.set()
        provider.shutdown()
        shutdown_returned.set()

    shutdown_thread = threading.Thread(target=run_shutdown)
    shutdown_thread.start()
    assert shutdown_started.wait(1.0)
    assert shutdown_returned.wait(0.05) is False

    release_operation.set()
    operation_thread.join(timeout=1.0)
    shutdown_thread.join(timeout=1.0)

    assert not operation_thread.is_alive()
    assert not shutdown_thread.is_alive()
    assert shutdown_returned.is_set()


def test_shutdown_rejects_late_memory_writes(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    calls = []

    class FakeClient:
        def store(self, body):
            calls.append(body)
            return {"stored": True}

    provider._client = FakeClient()
    provider.shutdown()
    provider.on_memory_write("create", "project", "late write")

    assert calls == []
    assert not hasattr(provider, "_threads")
    assert not hasattr(provider, "_fallback")


def test_shutdown_marks_closing_before_waiting_and_rejects_queued_memory_writes(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    active_started = threading.Event()
    release_active = threading.Event()
    queued_attempted = threading.Event()
    shutdown_started = threading.Event()
    calls = []

    class FakeClient:
        def store(self, body):
            calls.append(body["text"])
            if body["text"] == "active":
                active_started.set()
                release_active.wait()
            return {"stored": True}

    provider._client = FakeClient()
    active_thread = threading.Thread(
        target=provider.on_memory_write,
        args=("create", "project", "active"),
    )

    def queue_write():
        queued_attempted.set()
        provider.on_memory_write("create", "project", "queued")

    queued_thread = threading.Thread(target=queue_write)

    def run_shutdown():
        shutdown_started.set()
        provider.shutdown()

    shutdown_thread = threading.Thread(target=run_shutdown)
    try:
        active_thread.start()
        assert active_started.wait(1.0)
        queued_thread.start()
        assert queued_attempted.wait(1.0)
        shutdown_thread.start()
        assert shutdown_started.wait(1.0)

        assert _wait_until(lambda: provider._closing, timeout=0.1)
        assert calls == ["active"]
    finally:
        release_active.set()
        active_thread.join(timeout=1.0)
        queued_thread.join(timeout=1.0)
        shutdown_thread.join(timeout=1.0)

    assert all(not thread.is_alive() for thread in (active_thread, queued_thread, shutdown_thread))
    assert calls == ["active"]


def test_shutdown_uses_one_monotonic_total_deadline(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    timeouts = []

    class RecordingLock:
        def acquire(self, *, timeout):
            timeouts.append(timeout)
            return False

        def release(self):
            raise AssertionError("an unacquired lock must not be released")

        def __enter__(self):
            raise AssertionError("shutdown attempted an unbounded lock wait")

        def __exit__(self, exc_type, exc, traceback):
            return False

    provider._operation_lock = RecordingLock()
    clock = iter([100.0, 100.25])
    monkeypatch.setattr("noldomem.SHUTDOWN_TIMEOUT_SECONDS", 1.0, raising=False)
    monkeypatch.setattr("noldomem.time.monotonic", lambda: next(clock))

    provider.shutdown()

    assert provider._closing is True
    assert timeouts == [0.75]


def test_concurrent_shutdown_callers_share_the_same_wait(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    operation_started = threading.Event()
    release_operation = threading.Event()
    shutdown_returned = [threading.Event(), threading.Event()]

    class FakeClient:
        def store(self, body):
            operation_started.set()
            release_operation.wait()
            return {"stored": True}

    provider._client = FakeClient()
    operation_thread = threading.Thread(
        target=provider.on_memory_write,
        args=("create", "project", "in-flight write"),
    )
    shutdown_threads = [
        threading.Thread(target=lambda event=event: (provider.shutdown(), event.set()))
        for event in shutdown_returned
    ]
    try:
        operation_thread.start()
        assert operation_started.wait(1.0)
        shutdown_threads[0].start()
        assert _wait_until(lambda: provider._closing)
        shutdown_threads[1].start()

        assert shutdown_returned[1].wait(0.05) is False
    finally:
        release_operation.set()
        operation_thread.join(timeout=1.0)
        for thread in shutdown_threads:
            thread.join(timeout=1.0)

    assert not operation_thread.is_alive()
    assert all(not thread.is_alive() for thread in shutdown_threads)
    assert all(event.is_set() for event in shutdown_returned)


def test_explicit_store_is_synchronous_exactly_once_and_not_backgrounded(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    calls = []

    class FakeClient:
        def store(self, body):
            calls.append(body)
            return {"stored": True, "id": "memory-id"}

    provider._client = FakeClient()

    result = json.loads(provider.handle_tool_call("noldomem_store", {"text": "A durable decision"}))

    assert result == {"success": True, "data": {"stored": True, "id": "memory-id"}}
    assert len(calls) == 1
    assert calls[0]["source"] == "hermes-tool"
    assert not hasattr(provider, "_threads")
    assert not hasattr(provider, "_fallback")


def test_each_store_path_submits_only_its_own_write(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path, sync_turns_enabled=True)
    sources = []

    class FakeClient:
        def store(self, body):
            sources.append(body["source"])
            return {"stored": True}

    provider._client = FakeClient()

    provider.handle_tool_call("noldomem_store", {"text": "explicit"})
    provider.sync_turn("turn", "response")
    provider.on_memory_write("create", "project", "built-in")

    assert sources == [
        "hermes-tool",
        "hermes-sync-turn",
        "hermes-built-in-memory-create",
    ]
    provider.shutdown()


def test_config_validates_cache_bounds(monkeypatch, tmp_path):
    provider = _configured_provider(
        monkeypatch,
        tmp_path,
        recall_cache_ttl_seconds=-10,
        recall_cache_max_entries=999999,
    )

    assert provider._config.recall_cache_ttl_seconds == 0.1
    assert provider._config.recall_cache_max_entries == 4096


def test_config_rejects_non_finite_cache_ttl(monkeypatch, tmp_path):
    provider = _configured_provider(
        monkeypatch,
        tmp_path,
        recall_cache_ttl_seconds=float("nan"),
    )

    assert provider._config.recall_cache_ttl_seconds == 300.0


def test_recall_cache_honors_configured_ttl(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path, recall_cache_ttl_seconds=1.0)
    clock = [1000.0]
    calls = []

    class FakeClient:
        def recall(self, body):
            calls.append(body["query"])
            return {"results": [{"text": body["query"]}]}

    provider._client = FakeClient()
    monkeypatch.setattr("noldomem.time.monotonic", lambda: clock[0])

    provider.prefetch("ttl-query")
    clock[0] += 0.9
    provider.prefetch("ttl-query")
    clock[0] += 0.2
    provider.prefetch("ttl-query")

    assert calls == ["ttl-query", "ttl-query"]


def test_recall_cache_is_bounded_lru(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path, recall_cache_max_entries=2)
    calls = []

    class FakeClient:
        def recall(self, body):
            calls.append(body["query"])
            return {"results": [{"text": body["query"]}]}

    provider._client = FakeClient()

    provider.prefetch("a")
    provider.prefetch("b")
    provider.prefetch("a")
    provider.prefetch("c")
    provider.prefetch("b")

    assert calls == ["a", "b", "c", "b"]
    assert len(provider._cache) == 2


def test_recall_cache_does_not_collide_distinct_long_queries(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    calls = []
    shared_prefix = "x" * 500
    first_query = shared_prefix + "-first"
    second_query = shared_prefix + "-second"

    class FakeClient:
        def recall(self, body):
            calls.append(body["query"])
            return {"results": [{"text": body["query"]}]}

    provider._client = FakeClient()

    first_context = provider.prefetch(first_query)
    second_context = provider.prefetch(second_query)

    assert calls == [first_query, second_query]
    assert first_query in first_context
    assert second_query in second_context


def test_recall_cache_remains_bounded_under_concurrency(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path, recall_cache_max_entries=8)

    class FakeClient:
        def recall(self, body):
            return {"results": [{"text": body["query"]}]}

    provider._client = FakeClient()
    threads = [
        threading.Thread(target=provider._recall_context, args=(f"query-{index}",))
        for index in range(40)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1.0)

    assert all(not thread.is_alive() for thread in threads)
    assert len(provider._cache) <= 8


def test_session_boundaries_invalidate_recall_cache(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)

    provider._cache["session-1:query"] = (1.0, "old result")
    provider.on_session_switch("session-2", parent_session_id="session-1", reset=False)
    assert provider._cache == {}

    provider._cache["session-2:query"] = (1.0, "old result")
    provider.on_session_switch("session-2", reset=False, reason="compression")
    assert provider._cache == {}

    provider._cache["session-2:query"] = (1.0, "old result")
    provider.on_session_switch("session-2", reset=False, reason="rewind")
    assert provider._cache == {}


def test_same_session_rewound_flag_invalidates_recall_cache(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    provider._cache["session-1:query"] = (time.monotonic(), "old result")
    previous_generation = provider._session_generation

    provider.on_session_switch("session-1", reset=False, rewound=True)

    assert provider._cache == {}
    assert provider._session_generation == previous_generation + 1


def test_inflight_old_session_recall_cannot_repopulate_cache_after_switch(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    started = threading.Event()
    release = threading.Event()
    requested_sessions = []

    class FakeClient:
        def recall(self, body):
            requested_sessions.append(body["session_id"])
            if len(requested_sessions) == 1:
                started.set()
                release.wait(1.0)
            return {"results": [{"text": f"context-{body['session_id']}"}]}

    provider._client = FakeClient()
    worker = threading.Thread(target=provider._recall_context, args=("same-query",))
    worker.start()
    assert started.wait(1.0)

    provider.on_session_switch("session-2", parent_session_id="session-1", reset=False)
    release.set()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert requested_sessions == ["session-1"]
    assert provider._cache == {}

    context = provider.prefetch("same-query")

    assert "context-session-2" in context
    assert requested_sessions == ["session-1", "session-2"]
    assert list(provider._cache) == ["session-2:same-query"]


def test_availability_and_tool_discovery_are_network_free(monkeypatch, tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))

    def forbidden_network(*args, **kwargs):
        raise AssertionError("discovery attempted a network call")

    monkeypatch.setattr("noldomem.urllib.request.urlopen", forbidden_network)
    provider = NoldoMemProvider()

    assert provider.is_available() is True
    assert [schema["name"] for schema in provider.get_tool_schemas()] == [
        "noldomem_recall",
        "noldomem_store",
        "noldomem_pin",
    ]


def test_doctor_default_is_network_free_and_redacts_private_config(monkeypatch, tmp_path, capsys):
    key_file = tmp_path / "key"
    key_file.write_text("KEY_MARKER", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("NOLDOMEM_BASE_URL", "https://PRIVATE_ENDPOINT_MARKER.invalid/private/path?query=marker")
    monkeypatch.setenv("NOLDOMEM_AGENT", "AGENT_MARKER")
    monkeypatch.setenv("NOLDOMEM_NAMESPACE", "NAMESPACE_MARKER")

    def forbidden_network(*args, **kwargs):
        raise AssertionError("default doctor attempted a network call")

    monkeypatch.setattr("noldomem.urllib.request.urlopen", forbidden_network)

    assert noldomem_doctor.main([]) == 0
    output = capsys.readouterr().out
    assert "provider_configured=true" in output
    assert "api_key_present=true" in output
    assert "readiness_probe=skipped" in output
    assert "KEY_MARKER" not in output
    assert "PRIVATE_ENDPOINT_MARKER" not in output
    assert "private/path" not in output
    assert "AGENT_MARKER" not in output
    assert "NAMESPACE_MARKER" not in output


def test_doctor_live_probe_is_opt_in_bounded_and_allowlisted(monkeypatch, tmp_path, capsys):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("NOLDOMEM_BASE_URL", "http://PRIVATE_ENDPOINT_MARKER.invalid/private")
    captured = {}

    class LiveResponse:
        def read(self, size=-1):
            captured["read_size"] = size
            return json.dumps(
                {
                    "status": "ok",
                    "checks": {"storage": True, "embedding": False, "private_check": "DETAIL_MARKER"},
                    "uptime_seconds": 12.5,
                    "private_detail": "DETAIL_MARKER",
                }
            ).encode("utf-8")

        def close(self):
            pass

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        return LiveResponse()

    monkeypatch.setattr("noldomem.urllib.request.urlopen", fake_urlopen)

    assert noldomem_doctor.main(["--live", "--timeout", "99"]) == 0
    output = capsys.readouterr().out
    assert captured["timeout"] == 2.0
    assert 0 < captured["read_size"] <= 65536
    assert "readiness_probe=completed" in output
    assert "readiness_ready=true" in output
    assert "readiness_status=ok" in output
    assert "readiness_storage_ok=true" in output
    assert "readiness_embedding_ok=false" in output
    assert "PRIVATE_ENDPOINT_MARKER" not in output
    assert "DETAIL_MARKER" not in output


def test_live_probe_omits_non_finite_uptime(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)

    class NonFiniteResponse:
        def read(self, size=-1):
            return b'{"status":"ok","uptime_seconds":NaN}'

        def close(self):
            pass

    monkeypatch.setattr("noldomem.urllib.request.urlopen", lambda *args, **kwargs: NonFiniteResponse())

    health = provider.probe_readiness()

    assert health["ready"] is True
    assert health["uptime_seconds"] is None


def test_doctor_live_probe_redacts_raw_exception_text(monkeypatch, tmp_path, capsys):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))

    def unavailable(*args, **kwargs):
        raise OSError("PRIVATE_EXCEPTION_MARKER")

    monkeypatch.setattr("noldomem.urllib.request.urlopen", unavailable)

    assert noldomem_doctor.main(["--live"]) == 2
    output = capsys.readouterr().out
    assert "readiness_ready=false" in output
    assert "readiness_error_type=OSError" in output
    assert "PRIVATE_EXCEPTION_MARKER" not in output


def test_doctor_live_probe_rejects_oversized_payload_without_leaking_it(monkeypatch, tmp_path, capsys):
    key_file = tmp_path / "key"
    key_file.write_text("test-key", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("NOLDOMEM_API_KEY_FILE", str(key_file))

    class OversizedResponse:
        def read(self, size=-1):
            return (b"PRIVATE_PAYLOAD_MARKER" * 2000)[:size]

        def close(self):
            pass

    monkeypatch.setattr("noldomem.urllib.request.urlopen", lambda *args, **kwargs: OversizedResponse())

    assert noldomem_doctor.main(["--live"]) == 2
    output = capsys.readouterr().out
    assert "readiness_ready=false" in output
    assert "readiness_error_type=ResponseTooLarge" in output
    assert "PRIVATE_PAYLOAD_MARKER" not in output


def test_live_probe_enforces_outer_deadline_without_orphan_work(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)

    def delayed_urlopen(*args, **kwargs):
        time.sleep(1.0)
        return _Response({"status": "ok"})

    monkeypatch.setattr("noldomem.urllib.request.urlopen", delayed_urlopen)

    before = time.monotonic()
    health = provider.probe_readiness(timeout_seconds=0.05)
    elapsed = time.monotonic() - before

    assert elapsed < 0.5
    assert health["ready"] is False
    assert health["status"] == "unavailable"
    assert health["error_type"] == "DeadlineExceeded"


def test_live_probe_fails_closed_when_outer_deadline_cannot_be_installed(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    network_called = threading.Event()
    result = []

    def fake_urlopen(*args, **kwargs):
        network_called.set()
        return _Response({"status": "ok"})

    monkeypatch.setattr("noldomem.urllib.request.urlopen", fake_urlopen)
    worker = threading.Thread(target=lambda: result.append(provider.probe_readiness(timeout_seconds=0.1)))
    worker.start()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert network_called.is_set() is False
    assert result == [
        {
            "ready": False,
            "status": "unavailable",
            "storage_ok": None,
            "embedding_ok": None,
            "uptime_seconds": None,
            "error_type": "DeadlineUnavailable",
        }
    ]


def test_live_probe_restores_outer_deadline_when_request_construction_fails(monkeypatch, tmp_path):
    provider = _configured_provider(monkeypatch, tmp_path)
    monkeypatch.setenv("NOLDOMEM_BASE_URL", "http://[invalid")
    previous_handler = signal.getsignal(signal.SIGALRM)
    health = None
    raised = None

    try:
        try:
            health = provider.probe_readiness(timeout_seconds=0.1)
        except Exception as exc:
            raised = exc
        timer_active = signal.getitimer(signal.ITIMER_REAL)[0] > 0.0
        restored_handler = signal.getsignal(signal.SIGALRM)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)

    assert raised is None
    assert health is not None
    assert health["ready"] is False
    assert health["error_type"] == "InvalidResponse"
    assert timer_active is False
    assert restored_handler == previous_handler
