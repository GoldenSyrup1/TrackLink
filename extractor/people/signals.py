"""
Person signal models.

`PersonSignals` is the canonical intermediate representation that the
LangGraph agent produces from raw source content.  It maps 1-to-1 with
the `sources` JSONB column on the `persons` table — never add columns
for new sources, extend this model and let JSONB absorb new fields.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkExperience(BaseModel):
    title: str | None = None
    company: str | None = None
    start_year: int | None = None
    end_year: int | None = None       # None = current
    description: str | None = None


class Education(BaseModel):
    institution: str | None = None
    degree: str | None = None
    field: str | None = None
    end_year: int | None = None


class GitHubActivity(BaseModel):
    username: str | None = None
    public_repos: int = 0
    followers: int = 0
    top_languages: list[str] = Field(default_factory=list)
    recent_push_repos: list[str] = Field(default_factory=list)  # last 5 repos pushed to
    contribution_streak: int = 0     # consecutive active days (approx from events)


class TwitterActivity(BaseModel):
    username: str | None = None
    followers: int = 0
    following: int = 0
    tweet_count: int = 0
    bio: str | None = None
    recent_topics: list[str] = Field(default_factory=list)


class PersonSignals(BaseModel):
    """
    Structured signals extracted from all scraped sources for one person.
    Fields are optional because not every source will be scraped every run.
    """
    canonical_id: str
    name: str | None = None
    headline: str | None = None
    location: str | None = None
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    work_history: list[WorkExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    github: GitHubActivity | None = None
    twitter: TwitterActivity | None = None
    # Catch-all for source-specific raw fields
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_sources_jsonb(self) -> dict[str, Any]:
        """
        Flatten into the shape stored in persons.sources JSONB.
        Top-level keys are source names; never add columns for new sources.
        """
        out: dict[str, Any] = {}
        if self.work_history:
            out["linkedin"] = {
                "headline": self.headline,
                "location": self.location,
                "summary": self.summary,
                "skills": self.skills,
                "work_history": [w.model_dump() for w in self.work_history],
                "education": [e.model_dump() for e in self.education],
            }
        if self.github:
            out["github"] = self.github.model_dump()
        if self.twitter:
            out["twitter"] = self.twitter.model_dump()
        if self.extra:
            out["extra"] = self.extra
        return out
