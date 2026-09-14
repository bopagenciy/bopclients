"""HTTP Webhook transport implementation for integration event delivery."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import socket
import time
from typing import Optional, Dict, Any, Callable, Union
from urllib.parse import urlparse
import httpcore
from httpcore._backends.sync import SyncBackend, SyncStream
from httpcore._exceptions import ConnectError, ConnectTimeout, map_exceptions
import httpx

from bopclients.domain.integration.destination import IntegrationDestination, DestinationTransportType
from bopclients.domain.integration.delivery import (
    TransportPublishResult,
    TransportResultStatus,
    IntegrationSecretResolver,
)
from bopclients.domain.integration.transport import IntegrationTransport
from bopclients.runtime.settings import sanitize_error_message

logger = logging.getLogger("bopclients.transports.http")


class SSRFConnectionViolation(ConnectError):
    """Raised when an IP resolved at socket connection time violates SSRF safety policy."""
    pass


def normalize_ip(ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> Union[ipaddress.IPv4Address, ipaddress.IPv6Address]:
    """Extract IPv4 from IPv4-mapped IPv6 address if applicable."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def is_ip_disallowed(raw_ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
    """Check if an IP address is private, loopback, link-local, multicast, or cloud metadata."""
    ip = normalize_ip(raw_ip)

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        return True

    # Cloud metadata IP (169.254.169.254)
    if str(ip) == "169.254.169.254":
        return True

    # 0.0.0.0/8 (Current network)
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.IPv4Network("0.0.0.0/8"):
        return True

    # 100.64.0.0/10 (Carrier-Grade NAT)
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.IPv4Network("100.64.0.0/10"):
        return True

    # 198.18.0.0/15 (Network benchmark tests)
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.IPv4Network("198.18.0.0/15"):
        return True

    return False


def normalize_and_validate_hostname(host: str) -> str:
    """Validate and normalize hostname string rejecting invalid formats or control characters."""
    if not host or not host.strip():
        raise ValueError("SSRF violation: empty hostname")
    host_clean = host.strip().lower().rstrip(".")
    if not host_clean:
        raise ValueError("SSRF violation: invalid dot-only hostname")
    if any(c in host_clean for c in ("\r", "\n", "\t", " ", "@")):
        raise ValueError(f"SSRF violation: invalid characters in hostname '{host}'")
    if host_clean in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "metadata.google.internal"):
        raise ValueError(f"SSRF violation: loopback/metadata host '{host_clean}' is prohibited")
    return host_clean


def validate_url_ssrf(url: str, allow_insecure_http: bool = False) -> None:
    """Preflight validation of endpoint URL against SSRF vulnerabilities."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()

    if scheme == "http" and not allow_insecure_http:
        raise ValueError(f"SSRF violation: insecure HTTP scheme is prohibited in production ('{url}')")
    elif scheme not in ("http", "https"):
        raise ValueError(f"SSRF violation: unsupported scheme '{scheme}' in '{url}'")

    if parsed.username or parsed.password:
        raise ValueError(f"SSRF violation: credentials in URL are prohibited ('{url}')")

    host_clean = normalize_and_validate_hostname(parsed.hostname or "")

    # Check if host is direct IP literal
    try:
        ip = ipaddress.ip_address(host_clean)
        if is_ip_disallowed(ip):
            raise ValueError(f"SSRF violation: disallowed IP address '{host_clean}'")
        return
    except ValueError as ex:
        if "SSRF violation" in str(ex):
            raise
        # Not an IP literal, resolve DNS

    try:
        addr_info = socket.getaddrinfo(host_clean, None)
        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            if is_ip_disallowed(ip_obj):
                raise ValueError(f"SSRF violation: hostname '{host_clean}' resolves to disallowed IP '{ip_str}'")
    except socket.gaierror:
        # If host cannot be resolved during pre-validation, connection time will handle DNS failure
        pass


class SafeSyncBackend(SyncBackend):
    """Custom network backend eliminating SSRF DNS rebinding / TOCTOU vulnerabilities.

    Guarantees:
    - Resolves DNS at socket creation time.
    - Inspects EVERY resolved address against SSRF rules.
    - Directly connects socket to the validated IP address.
    - Preserves TLS SNI & certificate verification by retaining server_hostname in start_tls.
    """

    def __init__(self, allow_insecure_http: bool = False):
        self.allow_insecure_http = allow_insecure_http

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Optional[Any] = None,
    ) -> SyncStream:
        if socket_options is None:
            socket_options = []
        source_address = None if local_address is None else (local_address, 0)

        host_clean = normalize_and_validate_hostname(host)

        # Check if already IP literal
        try:
            direct_ip = ipaddress.ip_address(host_clean)
            if is_ip_disallowed(direct_ip):
                raise SSRFConnectionViolation(f"SSRF violation: destination IP '{host_clean}' is disallowed")
            safe_ip = host_clean
        except ValueError as ex:
            if isinstance(ex, SSRFConnectionViolation):
                raise
            # Not an IP literal: resolve via socket.getaddrinfo at connection time
            try:
                addr_info = socket.getaddrinfo(host_clean, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
            except Exception as ex_dns:
                raise ConnectError(f"Failed to resolve host '{host_clean}': {ex_dns}") from ex_dns

            if not addr_info:
                raise ConnectError(f"No address records found for host '{host_clean}'")

            # Check EVERY resolved IP address. If any address is disallowed, abort connection immediately!
            safe_ip = None
            for entry in addr_info:
                sockaddr = entry[4]
                ip_str = sockaddr[0]
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                    if is_ip_disallowed(ip_obj):
                        raise SSRFConnectionViolation(
                            f"SSRF violation: host '{host_clean}' resolved to disallowed IP '{ip_str}' at connection time"
                        )
                except ValueError as ip_ex:
                    if isinstance(ip_ex, SSRFConnectionViolation):
                        raise
                    raise SSRFConnectionViolation(f"SSRF violation: invalid resolved IP '{ip_str}'") from ip_ex

                if safe_ip is None:
                    safe_ip = ip_str

        # Connect directly to the validated IP address
        exc_map = {
            socket.timeout: ConnectTimeout,
            OSError: ConnectError,
        }
        with map_exceptions(exc_map):
            sock = socket.create_connection(
                (safe_ip, port),
                timeout,
                source_address=source_address,
            )
            for option in socket_options:
                sock.setsockopt(*option)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        return SyncStream(sock)


def sanitize_response_body(body: Optional[str], max_length: int = 500) -> Optional[str]:
    """Sanitize and truncate response body snippets to prevent credential leaks."""
    if not body:
        return None
    text = str(body).strip()
    # Mask common sensitive credential fields in json or text
    text = re.sub(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]+", r"\1***", text)
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*([:=])\s*['\"]?[^\s,'\"]+['\"]?", r"\1\2***", text)
    text = re.sub(r"(?i)(authorization|proxy-authorization)\s*[:=]\s*['\"]?[^\s,'\"]+['\"]?", r"\1: ***", text)
    text = re.sub(r"(?i)(cookie|set-cookie)\s*[:=]\s*['\"]?[^\r\n]+['\"]?", r"\1: ***", text)
    if len(text) > max_length:
        text = text[: max_length - 3] + "..."
    return text


class HttpWebhookTransport(IntegrationTransport):
    """Generic HTTP webhook transport delivering events over POST with retry & status classification."""

    def __init__(
        self,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
        client: Optional[httpx.Client] = None,
        secret_resolver: Optional[Union[Callable[[str], Optional[str]], IntegrationSecretResolver]] = None,
        allow_insecure_http: bool = False,
    ):
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self._custom_client = client
        self.secret_resolver = secret_resolver
        self.allow_insecure_http = allow_insecure_http

    @property
    def transport_type(self) -> str:
        return DestinationTransportType.HTTP.value

    def _resolve_secret(self, reference: Optional[str]) -> Optional[str]:
        if not reference or not reference.strip():
            return None
        if not self.secret_resolver:
            return None
        if isinstance(self.secret_resolver, IntegrationSecretResolver):
            return self.secret_resolver.get_secret(reference)
        elif callable(self.secret_resolver):
            return self.secret_resolver(reference.strip())
        return None

    def _parse_retry_after(self, response: httpx.Response) -> Optional[int]:
        """Parse Retry-After header safely supporting integer seconds or HTTP-date format."""
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        raw_str = raw.strip()
        try:
            # Try integer seconds
            val = int(raw_str)
            return max(1, min(val, 3600))  # Bounded between 1s and 1 hour
        except ValueError:
            pass

        # Try HTTP-date format (e.g. Wed, 21 Oct 2026 07:28:00 GMT)
        try:
            target_dt = parsedate_to_datetime(raw_str)
            now_dt = datetime.now(timezone.utc)
            diff = int((target_dt - now_dt).total_seconds())
            if diff <= 0:
                return 1
            return max(1, min(diff, 3600))
        except Exception:
            return None

    def publish(
        self,
        envelope_json: str,
        destination: IntegrationDestination,
        timeout_seconds: float = 10.0,
    ) -> TransportPublishResult:
        """Deliver envelope_json to destination HTTP endpoint.

        Guarantees:
        - envelope_json is delivered unchanged.
        - SSRF validation enforced before connection.
        - Redirection disabled (follow_redirects=False).
        - TLS certificate verification enabled by default (verify=True).
        - Idempotency and tenant headers included (X-Bop-Event-Id, X-Bop-Event-Type, X-Bop-Organization-Id).
        - Replay-resistant HMAC signing: X-Bop-Timestamp + sha256(<timestamp>.<body_bytes>).
        - Response body snippets sanitized and truncated.
        - Structured TransportPublishResult returned.
        """
        # 1. SSRF Validation
        try:
            validate_url_ssrf(destination.endpoint_url, allow_insecure_http=self.allow_insecure_http)
        except ValueError as ex:
            return TransportPublishResult(
                status=TransportResultStatus.PERMANENT_FAILURE,
                error_code="SSRF_VALIDATION_FAILURE",
                error_message=sanitize_error_message(str(ex)),
            )

        # 2. Parse minimal header fields from envelope without mutating body
        event_id = ""
        event_type = ""
        bop_org_id = destination.bop_organization_id
        try:
            parsed = json.loads(envelope_json)
            event_id = str(parsed.get("event_id", ""))
            event_type = str(parsed.get("event_type", ""))
            if "bop_organization_id" in parsed:
                bop_org_id = str(parsed["bop_organization_id"])
        except Exception:
            pass

        now_ts = str(int(time.time()))

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BopClients-Integration-Publisher/1.0",
            "X-Bop-Event-Id": event_id,
            "X-Bop-Event-Type": event_type,
            "X-Bop-Organization-Id": bop_org_id,
            "X-Bop-Timestamp": now_ts,
        }

        # Apply destination custom non-secret headers template
        custom_headers = destination.get_headers_template()
        if custom_headers:
            for k, v in custom_headers.items():
                if k.lower() not in ("content-length", "host", "x-bop-signature-256", "x-bop-timestamp"):
                    headers[k] = str(v)

        # 3. Optional Replay-Resistant HMAC-SHA256 signature if secret_key_ref is resolved
        if destination.secret_key_ref and self.secret_resolver:
            try:
                secret = self._resolve_secret(destination.secret_key_ref)
                if secret:
                    # Signing input: <timestamp>.<raw_envelope_json>
                    signing_payload = f"{now_ts}.{envelope_json}".encode("utf-8")
                    sig = hmac.new(
                        secret.encode("utf-8"),
                        signing_payload,
                        hashlib.sha256,
                    ).hexdigest()
                    headers["X-Bop-Signature-256"] = f"sha256={sig}"
            except Exception as ex:
                return TransportPublishResult(
                    status=TransportResultStatus.PERMANENT_FAILURE,
                    error_code="SECRET_RESOLUTION_FAILURE",
                    error_message=sanitize_error_message(f"Failed resolving credential reference: {ex}"),
                )

        timeout = httpx.Timeout(
            timeout=timeout_seconds,
            connect=min(self.connect_timeout, timeout_seconds),
            read=min(self.read_timeout, timeout_seconds),
        )

        try:
            if self._custom_client:
                client = self._custom_client
            else:
                backend = SafeSyncBackend(allow_insecure_http=self.allow_insecure_http)
                pool = httpcore.ConnectionPool(network_backend=backend)
                transport = httpx.HTTPTransport(verify=True, trust_env=False)
                transport._pool = pool
                client = httpx.Client(
                    transport=transport,
                    timeout=timeout,
                    follow_redirects=False,  # CRITICAL: Never blindly follow redirects
                    verify=True,              # CRITICAL: Always verify TLS certificates
                    trust_env=False,          # CRITICAL: Disable unvalidated environment proxies (HTTP_PROXY/HTTPS_PROXY/ALL_PROXY)
                )
            try:
                resp = client.post(
                    url=destination.endpoint_url,
                    content=envelope_json.encode("utf-8"),
                    headers=headers,
                )
                status_code = resp.status_code
                body_sample = sanitize_response_body(resp.text, max_length=500)
                retry_after = self._parse_retry_after(resp)

                # 2xx: Success
                if 200 <= status_code < 300:
                    return TransportPublishResult(
                        status=TransportResultStatus.SUCCESS,
                        status_code=status_code,
                        response_body_sample=body_sample,
                    )

                # 3xx: Redirection not followed -> Permanent failure / config error
                if 300 <= status_code < 400:
                    return TransportPublishResult(
                        status=TransportResultStatus.PERMANENT_FAILURE,
                        status_code=status_code,
                        response_body_sample=body_sample,
                        error_code=f"HTTP_{status_code}_REDIRECT_NOT_FOLLOWED",
                        error_message=f"Target endpoint attempted redirect to '{resp.headers.get('Location', '')}'; redirects are disabled for security",
                    )

                # 408 Request Timeout / 425 Too Early / 429 Rate Limit: Retryable
                if status_code in (408, 425, 429):
                    code_name = "RATE_LIMIT" if status_code == 429 else "TIMEOUT" if status_code == 408 else "TOO_EARLY"
                    return TransportPublishResult(
                        status=TransportResultStatus.TRANSIENT_FAILURE,
                        status_code=status_code,
                        response_body_sample=body_sample,
                        error_code=f"HTTP_{status_code}_{code_name}",
                        error_message=f"Target endpoint reported retryable status {status_code}",
                        retry_after_seconds=retry_after or (30 if status_code == 429 else None),
                    )

                # 500-599: Server errors -> Retryable transient failure
                if 500 <= status_code < 600:
                    return TransportPublishResult(
                        status=TransportResultStatus.TRANSIENT_FAILURE,
                        status_code=status_code,
                        response_body_sample=body_sample,
                        error_code=f"HTTP_{status_code}_SERVER_ERROR",
                        error_message=f"Target endpoint returned server error {status_code}",
                        retry_after_seconds=retry_after,
                    )

                # Other 4xx (400, 401, 403, 404, 409, 422, etc.): Permanent failure
                return TransportPublishResult(
                    status=TransportResultStatus.PERMANENT_FAILURE,
                    status_code=status_code,
                    response_body_sample=body_sample,
                    error_code=f"HTTP_{status_code}_CLIENT_ERROR",
                    error_message=f"Target endpoint rejected request with client error {status_code}",
                )

            finally:
                if not self._custom_client:
                    client.close()

        except httpx.ConnectTimeout as ex:
            return TransportPublishResult(
                status=TransportResultStatus.TRANSIENT_FAILURE,
                error_code="CONNECT_TIMEOUT",
                error_message=sanitize_error_message(str(ex)),
            )
        except httpx.ReadTimeout as ex:
            return TransportPublishResult(
                status=TransportResultStatus.TRANSIENT_FAILURE,
                error_code="READ_TIMEOUT",
                error_message=sanitize_error_message(str(ex)),
            )
        except (httpx.ConnectError, httpx.NetworkError) as ex:
            # Detect socket-level SSRF violations during connection
            err_msg = str(ex)
            cause = getattr(ex, "__cause__", None)
            if isinstance(cause, SSRFConnectionViolation) or "SSRF violation" in err_msg:
                return TransportPublishResult(
                    status=TransportResultStatus.PERMANENT_FAILURE,
                    error_code="SSRF_VALIDATION_FAILURE",
                    error_message=sanitize_error_message(err_msg),
                )
            return TransportPublishResult(
                status=TransportResultStatus.TRANSIENT_FAILURE,
                error_code="NETWORK_ERROR",
                error_message=sanitize_error_message(err_msg),
            )
        except Exception as ex:
            return TransportPublishResult(
                status=TransportResultStatus.PERMANENT_FAILURE,
                error_code="UNEXPECTED_TRANSPORT_ERROR",
                error_message=sanitize_error_message(str(ex)),
            )
