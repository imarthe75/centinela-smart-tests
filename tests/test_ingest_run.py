"""send_run: whole-run payload to Centinela (no network: requests.post is replaced)."""
import unittest
from unittest import mock

from centinela_core.results import CaseResult, Evidence, Status

from smart_tests import ingest


class TestSendRun(unittest.TestCase):
    def setUp(self):
        self.results = [CaseResult("CI-1", Status.PASSED, evidence=[Evidence("http", "GET / -> 200")]),
                        CaseResult("CI-2", Status.BLOCKED, reason="sin cuenta")]
        self.meta = {"project": "p", "cycle": "c", "package": "k.zip", "started": "s", "finished": "f", "planned_in_package": 3}

    def test_url_is_derived_from_the_failures_endpoint(self):
        self.assertEqual(ingest.run_url("http://centinela-backend:8000/api/ingest/smart-tests/"),
                         "http://centinela-backend:8000/api/ingest/smart-tests/run")
        self.assertEqual(ingest.run_url(""), "")

    def test_not_configured_sends_nothing(self):
        with mock.patch.object(ingest.requests, "post") as post:
            out = ingest.send_run(self.results, "a", {}, self.meta)
        post.assert_not_called()
        self.assertFalse(out["sent"])

    def test_sends_every_case_with_bearer(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"run_id": "r1", "created": True}
        with mock.patch.object(ingest.requests, "post", return_value=resp) as post:
            out = ingest.send_run(self.results, "a", {"ingest_url": "http://h/api/ingest/smart-tests", "ingest_token": "t"}, self.meta)
        self.assertEqual(out, {"sent": True, "run_id": "r1", "created": True, "detail": "ok"})
        url = post.call_args.args[0]
        body = post.call_args.kwargs["json"]
        self.assertEqual(url, "http://h/api/ingest/smart-tests/run")
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer t"})
        self.assertEqual([r["status"] for r in body["results"]], ["PASSED", "BLOCKED"])
        self.assertEqual(body["run"]["planned_in_package"], 3)

    def test_http_error_is_reported_not_raised(self):
        with mock.patch.object(ingest.requests, "post", return_value=mock.Mock(status_code=422, text="caso inválido")):
            out = ingest.send_run(self.results, "a", {"ingest_url": "http://h/x", "ingest_token": "t"}, self.meta)
        self.assertFalse(out["sent"])
        self.assertIn("422", out["detail"])


if __name__ == "__main__":
    unittest.main()
