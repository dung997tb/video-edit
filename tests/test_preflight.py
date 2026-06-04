from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.preflight import verify_services_preflight, verify_supabase_jobs_schema


class _RpcCall:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return SimpleNamespace(data=self._data)


class _Client:
    def __init__(self, data):
        self._data = data
        self.calls = []

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        return _RpcCall(self._data)


class PreflightTests(unittest.TestCase):
    def test_verify_supabase_jobs_schema_returns_payload(self) -> None:
        client = _Client(
            [
                {
                    "ok": True,
                    "table_exists": True,
                    "trigger_exists": True,
                    "missing_rpcs": [],
                }
            ]
        )

        result = verify_supabase_jobs_schema(client)

        self.assertTrue(result["ok"])
        self.assertEqual(client.calls[0][0], "verify_jobs_schema_requirements")
        payload = client.calls[0][1]
        self.assertIn("priority", payload["p_required_columns"])
        self.assertIn("error_detail", payload["p_required_columns"])
        self.assertIn("terminal_notified", payload["p_required_columns"])
        self.assertIn("webhook_attempts", payload["p_required_columns"])
        self.assertIn("last_webhook_error", payload["p_required_columns"])
        self.assertIn("jobs_priority_claim_idx", payload["p_required_indexes"])

    def test_verify_supabase_jobs_schema_populates_default_keys(self) -> None:
        client = _Client([{}])

        result = verify_supabase_jobs_schema(client)

        self.assertIn("ok", result)
        self.assertIn("missing_rpcs", result)
        self.assertIn("missing_columns", result)
        self.assertIn("missing_indexes", result)

    def test_verify_services_preflight_rejects_non_supabase_backend(self) -> None:
        services = SimpleNamespace(
            settings=SimpleNamespace(job_backend="memory", supabase_url=None, supabase_key=None),
            job_manager=SimpleNamespace(repository=SimpleNamespace(client=None)),
        )

        with self.assertRaises(RuntimeError):
            verify_services_preflight(services)
