"""Tenant configuration.

Everything that differs per NGO lives in one YAML file (see tenants/).
A second NGO is a new file, not new code (docs/adr/002).

The licence policy from docs/adr/001 is enforced here as code: a source
with an unclear licence cannot even be loaded.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator, model_validator

Language = Literal["de", "en"]
UNCLEAR = "unclear"
SOURCE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*")  # ids become file names (scripts/fetch_sources.py)


class Source(BaseModel):
    id: str
    title: str
    url: str
    language: Language
    kind: Literal["web", "pdf", "report", "docs", "synthetic"]
    licence: str  # exact licence name as stated by the publisher
    licence_url: str  # the page where you found the licence statement
    redistributable: bool  # may the repo contain a copy of the content?
    checked_on: date  # when you verified the licence
    contains_statistics: bool = False
    published: date | None = None  # publication date, if known

    @field_validator("id")
    @classmethod
    def id_must_be_safe(cls, v: str) -> str:
        if not SOURCE_ID_PATTERN.fullmatch(v) or ".." in v:
            raise ValueError(f"source id {v!r} must match ^[a-z0-9][a-z0-9._-]*$ and not contain '..'")
        return v

    @model_validator(mode="after")
    def licence_must_be_known(self) -> Source:
        if self.licence.strip().lower() == UNCLEAR:
            raise ValueError(f"source '{self.id}': licence is 'unclear', so it is not usable (ADR-001)")
        return self


class Tenant(BaseModel):
    slug: str
    name: str
    languages: list[Language]
    system_prompt: str
    sources: list[Source] = []

    @model_validator(mode="after")
    def source_ids_must_be_unique(self) -> Tenant:
        ids = [s.id for s in self.sources]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate source ids: {duplicates}")
        return self

    def source_ids(self) -> set[str]:
        return {s.id for s in self.sources}


def load_tenant(path: str | Path) -> Tenant:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Tenant.model_validate(data)
