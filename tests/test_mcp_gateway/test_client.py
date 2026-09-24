from mcp_gateway.client import GatewayClient
import pytest
def test_client_requires_url(): 
    c=GatewayClient(base_url='',api_key='')
    with pytest.raises(RuntimeError): c.health()
