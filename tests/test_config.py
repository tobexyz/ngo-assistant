from pathlib import Path

import pytest
from pydantic import ValidationError

from ngo_assistant.config import Tenant, load_tenant

ROOT = Path(__file__).resolve().parent.parent


def source(**overrides):
    base = {
        "id": "fixture-a",
        "title": "Fixture",
        "url": "https://example.org/a",
        "language": "en",
        "kind": "web",
        "licence": "CC BY 4.0",
        "licence_url": "https://example.org/licence",
        "redistributable": True,
        "checked_on": "2026-10-14",
    }
    return {**base, **overrides}


def tenant(sources):
    return {"slug": "t", "name": "T", "languages": ["en"], "system_prompt": "x", "sources": sources}


def test_demo_tenant_loads():
    t = load_tenant(ROOT / "tenants" / "demo.yaml")
    assert t.slug == "demo"
    assert set(t.languages) == {"de", "en"}


def test_unclear_licence_is_rejected():
    with pytest.raises(ValidationError, match="unclear"):
        Tenant.model_validate(tenant([source(licence="Unclear")]))


def test_duplicate_source_ids_are_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        Tenant.model_validate(tenant([source(), source(url="https://example.org/b")]))


def test_valid_source_is_accepted():
    t = Tenant.model_validate(tenant([source()]))
    assert t.source_ids() == {"fixture-a"}


@pytest.mark.parametrize("bad", ["../x", "a/b", "a..b", "A", "-a", ".a", "a b", "a*", "", "a\n"])
def test_unsafe_source_ids_are_rejected(bad):
    with pytest.raises(ValidationError):
        Tenant(**tenant([source(id=bad)]))


@pytest.mark.parametrize("good", ["a", "uba-co2.2024", "x_1", "0abc"])
def test_safe_source_ids_are_accepted(good):
    assert Tenant(**tenant([source(id=good)])).source_ids() == {good}


def test_demo_and_moorfunke_ids_load():
    assert load_tenant(ROOT / "tenants" / "demo.yaml").slug == "demo"
    assert len(load_tenant(ROOT / "tenants" / "moorfunke.yaml").sources) == 22
