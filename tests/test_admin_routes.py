from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None

from api.main import create_app
from tests.helpers import make_services, make_test_root


@unittest.skipIf(TestClient is None, "fastapi stack is not installed")
class AdminRoutesTests(unittest.TestCase):
    def _client_and_services(self):
        services = make_services(make_test_root("admin-routes"))
        services.settings.api_auth_enabled = False
        services.settings.api_embedded_worker = False
        services.settings.api_rate_limit_per_minute = 0
        patches = [
            patch("api.main.get_services", return_value=services),
            patch("api.routes.jobs.get_services", return_value=services),
            patch("api.routes.admin.get_services", return_value=services),
        ]
        for item in patches:
            item.start()

        def stop_patches() -> None:
            for item in reversed(patches):
                item.stop()

        self.addCleanup(stop_patches)
        return TestClient(create_app()), services

    def test_admin_dashboard_html(self) -> None:
        client, _services = self._client_and_services()

        response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_admin_jobs_returns_list(self) -> None:
        client, services = self._client_and_services()
        job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash")

        response = client.get("/admin/jobs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["id"], job.id)

    def test_admin_jobs_filter_status(self) -> None:
        client, services = self._client_and_services()
        done_job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash-done")
        pending_job = services.job_manager.create_job(pipeline_type="dubbing", source_sha256="hash-pending")
        services.job_manager.complete_job(done_job.id, "output.mp4")

        response = client.get("/admin/jobs", params={"status": "done"})

        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.json()["items"]}
        self.assertEqual(ids, {done_job.id})
        self.assertNotIn(pending_job.id, ids)

    def test_admin_job_assets_empty(self) -> None:
        client, _services = self._client_and_services()

        response = client.get("/admin/jobs/job-1/assets")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": []})

    def test_admin_events_empty(self) -> None:
        client, _services = self._client_and_services()

        response = client.get("/admin/events")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": []})

    def test_admin_cleanup_removes_dirs(self) -> None:
        client, services = self._client_and_services()
        job = services.job_manager.create_job(
            pipeline_type="dubbing",
            source_sha256="hash",
            payload={"output_name": "final-output"},
        )
        temp_dir = services.settings.temp_dir / job.id
        output_dir = services.settings.output_dir / "final-output"
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        response = client.delete(f"/admin/jobs/{job.id}/cleanup")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted_temp"])
        self.assertTrue(response.json()["deleted_output"])
        self.assertFalse(temp_dir.exists())
        self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
