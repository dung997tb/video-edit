from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

try:
    from api.main import create_app
except Exception:  # pragma: no cover
    create_app = None

from tests.helpers import make_services, make_test_root


@unittest.skipIf(yaml is None or create_app is None, "OpenAPI dependencies are not installed")
class OpenApiContractTests(unittest.TestCase):
    def test_static_openapi_paths_match_runtime_schema(self) -> None:
        services = make_services(make_test_root("openapi-contract"))
        services.settings.metrics_enabled = False

        with patch("api.main.get_services", return_value=services):
            runtime = create_app().openapi()
        static = yaml.safe_load(Path("openapi.yaml").read_text(encoding="utf-8"))

        self.assertEqual(set(static["paths"]), set(runtime["paths"]))
        self.assertIn("/jobs/{job_id}/retry", static["paths"])
        self.assertNotIn("/metrics", static["paths"])


if __name__ == "__main__":
    unittest.main()
