"""Transport and SSRF policy for federated MCP upstreams."""
from __future__ import annotations
import ipaddress
from urllib.parse import urlparse
ALLOWED_TRANSPORTS=frozenset({'stdio','http','sse'})
def validate_transport(transport: str) -> str:
    t=(transport or '').strip().lower()
    if t not in ALLOWED_TRANSPORTS: raise ValueError('transport tidak diizinkan')
    return t
def validate_http_url(url: str) -> str:
    p=urlparse((url or '').strip())
    if p.scheme not in ('http','https') or not p.hostname: raise ValueError('URL harus http/https')
    host=p.hostname.lower().rstrip('.')
    if host in {'localhost','metadata.google.internal','metadata.amazonaws.com'}: raise ValueError('SSRF: host metadata/localhost diblokir')
    try:
        info = ipaddress.ip_address(host)
    except ValueError:
        info = None
    if info is not None and (info.is_private or info.is_loopback or info.is_link_local or info.is_reserved or info.is_multicast): raise ValueError('SSRF: alamat jaringan privat diblokir')
    return url
def validate_upstream(transport: str, url: str | None = None) -> dict:
    t=validate_transport(transport)
    if t in ('http','sse') and not url: raise ValueError('URL wajib untuk transport remote')
    if url: validate_http_url(url)
    return {'transport':t,'url':url or ''}
