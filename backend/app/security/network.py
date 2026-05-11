import ipaddress
import socket
from urllib.parse import urlparse

from app.config import settings


def _allowed_networks() -> list[ipaddress._BaseNetwork]:
    networks: list[ipaddress._BaseNetwork] = []
    for cidr in settings.allowed_sensor_cidrs.split(","):
        cidr = cidr.strip()
        if cidr:
            networks.append(ipaddress.ip_network(cidr, strict=False))
    return networks


def validate_sensor_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("source_url deve usar esquema http ou https")
    if parsed.username or parsed.password:
        raise ValueError("source_url não deve conter credenciais")
    if not parsed.hostname:
        raise ValueError("source_url deve conter host")

    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("source_url aponta para host local não permitido")

    allowed = _allowed_networks()
    if not allowed:
        raise ValueError("ALLOWED_SENSOR_CIDRS não configurado")

    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError(f"source_url não resolveu DNS: {exc}") from exc

    for raw_ip in resolved:
        ip = ipaddress.ip_address(raw_ip)
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise ValueError("source_url resolveu para endereço não permitido")
        if not any(ip in network for network in allowed):
            raise ValueError(f"source_url resolveu para IP fora da allowlist: {ip}")

    return source_url.rstrip("/")
