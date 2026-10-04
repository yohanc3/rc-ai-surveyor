"""Offline checks for TLS setup and free ElevenLabs diagnostics."""

import contextlib
import io
import ssl
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from app.tls import verified_context
from test import check_connection


class ConnectivityTests(unittest.TestCase):
    def test_mac_without_python_cas_loads_system_bundle(self):
        context = MagicMock()
        context.get_ca_certs.return_value = []
        with patch("app.tls.ssl.create_default_context", return_value=context), \
             patch("app.tls.sys.platform", "darwin"), \
             patch("app.tls.Path.is_file", return_value=True):
            self.assertIs(verified_context(), context)
        context.load_verify_locations.assert_called_once_with(cafile="/etc/ssl/cert.pem")

    def test_existing_certificate_store_is_preserved(self):
        context = MagicMock()
        context.get_ca_certs.return_value = [{"subject": "CA"}]
        with patch("app.tls.ssl.create_default_context", return_value=context):
            verified_context()
        context.load_verify_locations.assert_not_called()

    def test_certificate_validation_stays_enabled(self):
        context = verified_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_check_makes_only_read_only_request(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch("test.urllib.request.urlopen", return_value=response) as request, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_connection("test-key"), 0)
        sent = request.call_args.args[0]
        self.assertEqual(sent.get_method(), "GET")
        self.assertEqual(sent.full_url, "https://api.elevenlabs.io/v1/user/subscription")
        self.assertNotIn("test-key", sent.full_url)

    def test_tls_reset_is_not_reported_as_bad_key(self):
        output = io.StringIO()
        with patch("test.urllib.request.urlopen", side_effect=ConnectionResetError(54, "reset")), \
             contextlib.redirect_stdout(output):
            self.assertEqual(check_connection("test-key"), 1)
        self.assertIn("Key validity is unknown", output.getvalue())
        self.assertNotIn("test-key", output.getvalue())

    def test_forbidden_is_distinct_from_transport_failure(self):
        output = io.StringIO()
        error = urllib.error.HTTPError("https://api.elevenlabs.io", 403, "Forbidden", {}, None)
        with patch("test.urllib.request.urlopen", side_effect=error), \
             contextlib.redirect_stdout(output):
            self.assertEqual(check_connection("test-key"), 1)
        self.assertIn("reachable (HTTP 403)", output.getvalue())
        self.assertIn("permissions", output.getvalue())
