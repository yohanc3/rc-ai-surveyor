import unittest
import urllib.request
from unittest.mock import MagicMock, patch
import socket

from app.camera_http import CameraConnection, open_camera


class CameraHTTPTests(unittest.TestCase):
    def test_local_camera_uses_ipv4_without_address_synthesis(self):
        sock = MagicMock()
        with patch('app.camera_http.socket.socket', return_value=sock) as create, \
             patch('socket.getaddrinfo', side_effect=AssertionError('must not resolve')):
            conn = CameraConnection('10.5.5.9', timeout=4)
            conn.connect()
        create.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect.assert_called_once_with(('10.5.5.9', 80))
        sock.settimeout.assert_called_once_with(4)

    def test_failed_connect_closes_socket(self):
        sock = MagicMock()
        sock.connect.side_effect = TimeoutError('timeout')
        with patch('app.camera_http.socket.socket', return_value=sock):
            with self.assertRaises(TimeoutError):
                CameraConnection('10.5.5.9', timeout=4).connect()
        sock.close.assert_called_once()

    def test_camera_request_skips_macos_proxy_discovery(self):
        response = MagicMock()
        response.code = 200
        with patch('urllib.request.getproxies', side_effect=AssertionError('must not discover')), \
             patch('app.camera_http.CameraHandler.do_open', return_value=response) as send:
            self.assertIs(open_camera(urllib.request.Request(
                'http://10.5.5.9/gp/gpControl/status'), timeout=4), response)
        self.assertIs(send.call_args.args[0], CameraConnection)
