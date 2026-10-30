"""Shared HTTPS settings for outgoing requests (Imgflip, Twitch)."""
import ssl


def _make_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    # Python 3.13+ enables VERIFY_X509_STRICT by default. Antivirus HTTPS scanning
    # (e.g. Sophos web protection) re-signs sites with a local CA that Windows
    # trusts but that fails those extra RFC 5280 checks ("Basic Constraints of CA
    # cert not marked critical"). Certificates are still fully verified against
    # the system trust store; only the extra strictness is turned off.
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return ctx


SSL_CONTEXT = _make_context()
