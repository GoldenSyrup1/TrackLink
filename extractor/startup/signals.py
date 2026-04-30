"""
Startup signal models.

`StartupSignals` is the canonical intermediate representation produced by
the startup LangGraph agent.  It maps to the `signals` and `problem_space`
JSONB columns on the `startups` table.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FundingRound(BaseModel):
    round_type: str | None = None   # seed, series_a, …
    amount_usd: int | None = None
    date: str | None = None         # ISO date string
    investors: list[str] = Field(default_factory=list)


class GitHubOrgActivity(BaseModel):
    org: str | None = None
    public_repos: int = 0
    stars_total: int = 0
    top_languages: list[str] = Field(default_factory=list)
    recent_push_repos: list[str] = Field(default_factory=list)
    contributors_count: int = 0


class StartupSignals(BaseModel):
    """
    Structured signals for a startup extracted from Crunchbase + GitHub.
    """
    canonical_id: str                    # normalized domain
    name: str | None = None
    domain: str | None = None
    tagline: str | None = None
    description: str | None = None
    category: str | None = None          # e.g. "fintech", "devtools"
    maturity: str | None = None          # "idea" | "mvp" | "growth" | "scaled"
    founded_year: int | None = None
    employee_count: str | None = None    # "1-10", "11-50", …
    headquarters: str | None = None
    funding_total_usd: int | None = None
    funding_rounds: list[FundingRound] = Field(default_factory=list)
    investors: list[str] = Field(default_factory=list)
    problem_space: dict[str, Any] = Field(default_factory=dict)
    github: GitHubOrgActivity | None = None
    tech_stack: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_signals_jsonb(self) -> dict[str, Any]:
        """Shape stored in startups.signals JSONB."""
        out: dict[str, Any] = {}
        if self.funding_rounds:
            out["crunchbase"] = {
                "tagline": self.tagline,
                "description": self.description,
                "founded_year": self.founded_year,
                "employee_count": self.employee_count,
                "headquarters": self.headquarters,
                "funding_total_usd": self.funding_total_usd,
                "funding_rounds": [r.model_dump() for r in self.funding_rounds],
                "investors": self.investors,
            }
        if self.github:
            out["github"] = self.github.model_dump()
        if self.tech_stack:
            out["tech_stack"] = self.tech_stack
        if self.extra:
            out["extra"] = self.extra
        return out

    def to_problem_space_jsonb(self) -> dict[str, Any]:
        base = dict(self.problem_space)
        if self.category:
            base["category"] = self.category
        if self.description:
            base["description_excerpt"] = self.description[:500]
        return base
