import pytest
from pydantic import ValidationError

from ngo_assistant.config import Source, Tenant


def source(**overrides):
    base = {
        "id": "synthetic-about",
        "title": "About the fictional NGO",
        "url": "data/synthetic/about.md",
        "language": "en",
        "kind": "synthetic",
        "licence": "CC BY 4.0 (own work)",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "redistributable": True,
        "checked_on": "2026-10-14",
    }
    return {**base, **overrides}


def test_synthetic_source_kind_is_accepted():
    s = Source.model_validate(source())
    assert s.kind == "synthetic"


def test_tenant_with_synthetic_and_real_sources_loads():
    t = Tenant.model_validate(
        {"slug": "t", "name": "T", "languages": ["en"], "system_prompt": "x",
         "sources": [source(), source(id="real-web", kind="web", url="https://example.org/a")]}
    )
    assert {s.kind for s in t.sources} == {"synthetic", "web"}


def test_unknown_source_kind_is_still_rejected():
    with pytest.raises(ValidationError, match="kind"):
        Source.model_validate(source(kind="blog"))
