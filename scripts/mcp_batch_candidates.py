"""Filter registry metadata for executable batch candidates; never execute metadata."""
from __future__ import annotations
import json
from pathlib import Path

def filter_executable(servers: dict) -> list[dict]:
    out=[]
    for key, item in servers.items():
        cfg=item.get('install_config') if isinstance(item.get('install_config'), dict) else {}
        method=cfg.get('install_method') or cfg.get('method')
        package=cfg.get('package')
        tools=item.get('tools') or []
        verified=bool(item.get('verified') or item.get('validated'))
        installs=int(item.get('install_count') or 0)
        credentials=bool(item.get('requires_credentials') or cfg.get('requires_credentials'))
        if method in ('npm','python','docker') and package and len(tools) >= 1 and (verified or installs > 100) and not credentials:
            out.append({'slug': key, 'name': item.get('name'), 'package': package, 'install_method': method, 'tools': len(tools), 'verified': verified, 'install_count': installs})
    return out

if __name__ == '__main__':
    data=json.loads(Path('mcp_registry_cache.json').read_text(encoding='utf-8'))
    candidates=filter_executable(data)
    Path('candidates.json').write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'TOTAL_METADATA={len(data)} CANDIDATES={len(candidates)}')
