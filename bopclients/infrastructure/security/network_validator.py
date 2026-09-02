"""Network Safety and SSRF Security Validator for public web monitoring with DNS resolution pre-validation."""

import ipaddress
import socket
import urllib.parse
from typing import Tuple, List


class NetworkSafetyValidator:
    """Validator enforcing strict SSRF protections, URL safety rules, and DNS-level IP pre-validation."""

    PRIVATE_IP_RANGES = [
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),  # Link-local & AWS/Cloud IMDS metadata
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("100.64.0.0/10"),  # Carrier-grade NAT
        ipaddress.ip_network("192.0.0.0/24"),    # IETF Protocol Assignments
        ipaddress.ip_network("192.0.2.0/24"),    # TEST-NET-1
        ipaddress.ip_network("198.51.100.0/24"), # TEST-NET-2
        ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
        ipaddress.ip_network("224.0.0.0/4"),     # Multicast
        ipaddress.ip_network("240.0.0.0/4"),     # Reserved
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),        # IPv6 ULA
        ipaddress.ip_network("fe80::/10"),       # IPv6 Link-local
        ipaddress.ip_network("ff00::/8"),        # IPv6 Multicast
    ]

    DISALLOWED_SCHEMES = {"file", "ftp", "gopher", "dict", "ldap", "tftp"}

    @classmethod
    def validate_url(cls, url: str, resolve_dns: bool = True) -> Tuple[bool, str]:
        """Validate URL against SSRF vulnerabilities, illegal schemes, private IP ranges, and DNS resolution."""
        if not url or not isinstance(url, str):
            return False, "Empty or non-string URL"

        cleaned_url = url.strip()
        try:
            parsed = urllib.parse.urlparse(cleaned_url)
        except Exception as err:
            return False, f"URL parse error: {err}"

        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            return False, f"Unsupported URL scheme '{scheme}'. Only http and https allowed."

        hostname = (parsed.hostname or "").lower().strip()
        if not hostname:
            return False, "Missing hostname in URL"

        # Check explicit localhost / loopback names
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "metadata.google.internal"):
            return False, f"Access to local/internal host '{hostname}' is rejected (SSRF protection)"

        # Check internal TLDs
        if hostname.endswith((".local", ".internal", ".lan", ".home")):
            return False, f"Access to internal TLD '{hostname}' is rejected (SSRF protection)"

        # Check if hostname is direct IP address
        try:
            ip_obj = ipaddress.ip_address(hostname)
            is_valid_ip, ip_reason = cls._validate_ip_object(ip_obj)
            if not is_valid_ip:
                return False, ip_reason
            return True, "URL is safe"
        except ValueError:
            pass  # Hostname is a domain name

        # Perform DNS Resolution Pre-Validation
        if resolve_dns:
            try:
                addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                if not addr_info:
                    return False, f"DNS resolution failed for hostname '{hostname}': No addresses returned"

                for family, socktype, proto, canonname, sockaddr in addr_info:
                    raw_ip = sockaddr[0]
                    try:
                        ip_obj = ipaddress.ip_address(raw_ip)
                        is_valid_ip, ip_reason = cls._validate_ip_object(ip_obj)
                        if not is_valid_ip:
                            return False, f"DNS resolved '{hostname}' to unsafe IP '{raw_ip}': {ip_reason}"
                    except ValueError:
                        return False, f"Invalid resolved IP format '{raw_ip}' for hostname '{hostname}'"
            except socket.gaierror as gai_err:
                return False, f"DNS resolution failed for hostname '{hostname}': {gai_err}"
            except Exception as err:
                return False, f"DNS resolution error for hostname '{hostname}': {err}"

        return True, "URL is safe"

    @classmethod
    def _validate_ip_object(cls, ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> Tuple[bool, str]:
        if ip_obj.is_loopback:
            return False, f"IP '{ip_obj}' is loopback"
        if ip_obj.is_private:
            return False, f"IP '{ip_obj}' is private"
        if ip_obj.is_link_local:
            return False, f"IP '{ip_obj}' is link-local"
        if ip_obj.is_unspecified:
            return False, f"IP '{ip_obj}' is unspecified"
        if ip_obj.is_multicast:
            return False, f"IP '{ip_obj}' is multicast"
        if ip_obj.is_reserved:
            return False, f"IP '{ip_obj}' is reserved"

        for net in cls.PRIVATE_IP_RANGES:
            if ip_obj in net:
                return False, f"IP '{ip_obj}' falls within restricted range '{net}'"

        return True, "IP is public and safe"
