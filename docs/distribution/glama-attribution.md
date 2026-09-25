# Glama Attribution — Mandatory

Katalir displays MCP server metadata sourced from the
[Glama MCP directory](https://glama.ai/mcp/servers). That data is **licensed, not
public domain**, under Glama's API Data License.

## The two obligations

1. **Visible credit, on every page that shows the data.**
   A link to `https://glama.ai` (or `/mcp/servers`), crawlable, without
   `rel="nofollow"`, `rel="sponsored"` or `rel="ugc"`.
2. **A backlink on every listing shown.**
   Each server/connector card links to the exact listing URL the Glama API
   returned for it, *alongside* the other links — it does not replace them.

Attribution may be waived under a commercial licence; that conversation has not
happened yet, so the obligations above are binding today.

## Where it is implemented

| Surface | Element |
| --- | --- |
| `/integrations` | `data-testid="glama-attribution"` footer credit + `data-testid="attribution-link"` per card |
| `/` (landing) | `data-testid="landing-glama-credit"` in the footer |
| `/docs` | `data-testid="docs-glama-credit"` |
| `/pricing` | `data-testid="pricing-glama-credit"` |
| API | `GET /mcp/registry/sources` returns `attribution.glama` (label + href + note) so the frontend never invents the wording |

`scripts/sync-glama.py` stamps `source`, `source_url` and
`attribution_required: true` on every Glama record.
`tests/test_glama_registry.py` fails the build if those fields disappear.

## Rules for future changes

- **Never** add `rel="nofollow"`, `rel="sponsored"` or `rel="ugc"` to a Glama link.
- **Never** remove the credit to "clean up" a page.
- **Never** render a Glama card without its `source_url` link.
- If a new page lists Glama data, it needs the credit too — that is the rule,
  not a per-page decision.
