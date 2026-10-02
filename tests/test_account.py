import io
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "justcaptions" / "scripts"))

from justcaptions import api, cli, transcribe  # noqa: E402

FAKE_KEY = "jc_live_" + "a" * 28 + "wxyz"


class Isolated(unittest.TestCase):
    """Each test gets its own key file and no JUSTCAPTIONS_API_KEY."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_file = Path(self.tmp.name) / "justcaptions" / "api_key"
        patches = [
            mock.patch.object(api, "KEY_FILE", self.key_file),
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(api.time, "sleep", lambda s: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("JUSTCAPTIONS_API_KEY", None)
        self.addCleanup(self.tmp.cleanup)


def http_error(status, code):
    body = json.dumps({"error": "nope", "code": code}).encode()
    return urllib.error.HTTPError("https://x", status, "err", {}, io.BytesIO(body))


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class KeyLookupTests(Isolated):
    def test_no_key(self):
        self.assertIsNone(api.api_key())

    def test_file_is_used_when_env_is_unset(self):
        api.save_key(FAKE_KEY)
        self.assertEqual(api.api_key(), FAKE_KEY)

    def test_env_wins_over_file(self):
        api.save_key(FAKE_KEY)
        os.environ["JUSTCAPTIONS_API_KEY"] = "jc_live_fromenv"
        self.assertEqual(api.api_key(), "jc_live_fromenv")

    def test_saved_key_is_private(self):
        api.save_key(FAKE_KEY)
        self.assertEqual(stat.S_IMODE(self.key_file.stat().st_mode), 0o600)

    def test_mask_hides_the_secret(self):
        masked = api.mask(FAKE_KEY)
        self.assertTrue(masked.startswith("jc_live_aaaa") and masked.endswith("wxyz"))
        self.assertNotIn("a" * 10, masked)


class SignupTests(Isolated):
    def test_signup_saves_key_and_prints_it_masked(self):
        sent = {}

        def fake_urlopen(req, timeout=0):
            sent["auth"] = req.get_header("Authorization")
            sent["body"] = json.loads(req.data)
            sent["url"] = req.full_url
            return Response(json.dumps({"id": "key_1", "key": FAKE_KEY, "plan": "free"}).encode())

        out = io.StringIO()
        with mock.patch.object(api.urllib.request, "urlopen", fake_urlopen), redirect_stdout(out):
            self.assertEqual(cli.main(["--signup", "dev@example.com"]), 0)
        self.assertEqual(sent["body"], {"email": "dev@example.com"})
        self.assertTrue(sent["url"].endswith("/v1/signup"))
        self.assertIsNone(sent["auth"])
        self.assertEqual(self.key_file.read_text().strip(), FAKE_KEY)
        self.assertNotIn(FAKE_KEY, out.getvalue())
        self.assertIn(api.mask(FAKE_KEY), out.getvalue())

    def test_signup_refuses_when_a_key_exists(self):
        api.save_key(FAKE_KEY)
        with mock.patch.object(api.urllib.request, "urlopen", side_effect=AssertionError("no request")), \
             redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--signup", "dev@example.com"]), 1)

    def test_bad_email_is_rejected_locally(self):
        with mock.patch.object(api.urllib.request, "urlopen", side_effect=AssertionError("no request")):
            with self.assertRaises(api.APIError):
                api.signup("not-an-email")


class ErrorTests(Isolated):
    def test_billing_refusals_point_to_the_account_page(self):
        for code in ["quota_exceeded", "free_tier_busy", "spend_cap_reached", "payment_required"]:
            self.assertIn(api.ACCOUNT_URL, api.explain(api.APIError(429, code, "x")), code)

    def test_refusals_are_not_retried(self):
        api.save_key(FAKE_KEY)
        calls = []

        def refuse(req, timeout=0):
            calls.append(1)
            raise http_error(429, "quota_exceeded")

        with mock.patch.object(api.urllib.request, "urlopen", refuse):
            with self.assertRaises(api.APIError) as ctx:
                api.usage()
        self.assertEqual(ctx.exception.code, "quota_exceeded")
        self.assertEqual(len(calls), 1)

    def test_rate_limit_is_retried(self):
        api.save_key(FAKE_KEY)
        calls = []

        def flaky(req, timeout=0):
            calls.append(1)
            if len(calls) == 1:
                raise http_error(429, "rate_limited")
            return Response(b'{"plan": "free"}')

        with mock.patch.object(api.urllib.request, "urlopen", flaky):
            self.assertEqual(api.usage(), {"plan": "free"})
        self.assertEqual(len(calls), 2)

    def test_account_prints_usage(self):
        api.save_key(FAKE_KEY)
        usage = {"month": "2026-10", "plan": "free", "email": "dev@example.com", "audio_seconds": 90,
                 "text_chars": 12890, "free_audio_seconds": 1800, "free_text_chars": 50000,
                 "estimated_charge_cents": 125, "spend_cap_cents": 10000}
        out = io.StringIO()
        with mock.patch.object(api, "usage", return_value=usage), redirect_stdout(out):
            self.assertEqual(cli.main(["--account"]), 0)
        text = out.getvalue()
        for expected in ["1.5 min used", "30.0 min free", "12,890", "$1.25", "$100.00", api.ACCOUNT_URL]:
            self.assertIn(expected, text)


class FallbackTests(Isolated):
    def run_transcribe(self, error, local_installed):
        with mock.patch.object(transcribe, "transcribe_api", side_effect=error), \
             mock.patch.object(transcribe, "local_available", return_value=local_installed), \
             mock.patch.object(transcribe, "transcribe_local", return_value=(["local"], "en")) as local, \
             redirect_stderr(io.StringIO()) as err:
            result = transcribe.transcribe(Path("v.mp4"), Path("."), 1.0, "api", "small", None, [])
        return result, local, err.getvalue()

    def test_refused_transcription_falls_back_to_local(self):
        result, local, err = self.run_transcribe(api.APIError(429, "free_tier_busy", "x"), True)
        self.assertEqual(result, (["local"], "en"))
        self.assertIn("falling back to local faster-whisper", err)

    def test_refusal_without_local_engine_is_raised(self):
        with self.assertRaises(api.APIError):
            self.run_transcribe(api.APIError(402, "payment_required", "x"), False)

    def test_other_errors_are_not_masked(self):
        with self.assertRaises(api.APIError):
            self.run_transcribe(api.APIError(401, "invalid_api_key", "x"), True)


if __name__ == "__main__":
    unittest.main()
