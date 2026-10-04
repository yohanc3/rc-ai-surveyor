"""Direct IPv4 HTTP for a local GoPro beside an IPv6 cellular uplink."""

import http.client
import ipaddress
import socket
import urllib.request


class CameraConnection(http.client.HTTPConnection):
    def connect(self):
        # A cellular default route can synthesize NAT64 addresses even for
        # numeric IPv4 hosts. This accessory lives on local IPv4 Wi-Fi.
        address = str(ipaddress.IPv4Address(self.host))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect((address, self.port))
        except BaseException:
            sock.close()
            raise
        self.sock = sock


class CameraHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        return self.do_open(CameraConnection, request)


def open_camera(url, timeout=4):
    # Camera control is local: skip system proxy discovery and proxy routing.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), CameraHandler()
    )
    return opener.open(url, timeout=timeout)
