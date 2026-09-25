from mcp_gateway.client import GatewayClient
import pytest

def test_client_requires_url(monkeypatch):
    monkeypatch.delenv('AGENTGATEWAY_URL', raising=False)
    with pytest.raises(RuntimeError):
        GatewayClient(url='')
