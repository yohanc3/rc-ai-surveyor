"""Verified HTTPS for Python installations without a default CA bundle."""

import ssl
import sys
import os
from pathlib import Path


def configure_macos_certificates() -> None:
    """Select trusted roots before cloud SDKs create their HTTP clients."""
    if sys.platform != "darwin" or os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
        bundle = Path(certifi.where())
    except ImportError:
        bundle = Path("/etc/ssl/cert.pem")
    if bundle.is_file():
        os.environ["SSL_CERT_FILE"] = str(bundle)


def verified_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if not context.get_ca_certs() and sys.platform == "darwin":
        # python.org's macOS installation can lack its optional CA symlink.
        # Use the system bundle instead; certificate/hostname checks stay on.
        bundle = Path("/etc/ssl/cert.pem")
        if bundle.is_file():
            context.load_verify_locations(cafile=str(bundle))
    return context
