from mcp_gateway.policy import validate_upstream, validate_http_url
import pytest
@pytest.mark.parametrize('url',['http://127.0.0.1/x','http://localhost/x','http://10.0.0.1/x','http://172.16.0.1/x','http://192.168.1.1/x','http://169.254.169.254/x','http://[::1]/x','http://metadata.google.internal/x','http://metadata.amazonaws.com/x','http://[fd00::1]/x'])
def test_ssrf_blocked(url):
    with pytest.raises(ValueError): validate_http_url(url)
def test_transport_allowlist():
    assert validate_upstream('http','https://example.com')['transport']=='http'
    with pytest.raises(ValueError): validate_upstream('binary')
