"""Exception hierarchy for the XTB API client.

All exceptions inherit from XTBError, allowing callers to catch
any library error with a single ``except XTBError`` clause.
"""

from __future__ import annotations


class XTBError(Exception):
    """Base exception for all XTB API errors."""


class XTBConnectionError(XTBError):
    """Failed to establish or maintain a connection."""


class AuthenticationError(XTBConnectionError):
    """Authentication failed (invalid credentials, expired TGT, 2FA failure)."""


class CASError(AuthenticationError):
    """CAS-specific error with an error code from XTB servers.

    Backward-compatible with the original ``CASError`` that lived in
    ``xtb_api.types.websocket``.  The ``.code`` attribute carries the
    raw CAS error code (e.g. ``"CAS_GET_TGT_UNAUTHORIZED"``).
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ReconnectionError(XTBConnectionError):
    """Exhausted all reconnection attempts."""


class TradeError(XTBError):
    """Trade execution failed (order rejected, insufficient margin)."""


class InstrumentNotFoundError(TradeError):
    """Symbol could not be resolved to a known instrument."""


class AmbiguousOutcomeError(TradeError):
    """The send succeeded but the broker's response did not confirm the trade.

    The order may or may not have been placed. Consumers must reconcile
    via ``get_positions()`` to determine whether the trade is live.

    Typical cause: an empty gRPC-web response body after a successful HTTP
    POST. Previously surfaced as a ``ProtocolError`` whose message had to
    be string-matched.
    """


class RateLimitError(XTBError):
    """Too many requests or OTP attempts."""


class XTBTimeoutError(XTBError):
    """A request timed out waiting for a response."""


class ProtocolError(XTBError):
    """Malformed response or unexpected message format from the server."""
