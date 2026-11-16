"""Validated HTTP contracts independent of the literature_search SDK."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")#多余字段的处理策略，禁止

#over review
class Term(Model):
    text: str = Field(min_length=1, max_length=300)
    field: Literal["all", "title", "authors", "venue"] = "all"
    phrase: bool = False

#over review
class Query(Model):
    all_of: list[Term] = Field(default_factory=list, max_length=12)
    any_of: list[Term] = Field(default_factory=list, max_length=12)
    none_of: list[Term] = Field(default_factory=list, max_length=12)

#Search的查询字段over review 
class Search(Model):
    query: Query = Field(default_factory=Query)
    year_from: int | None = Field(default=None, ge=1, le=9999)
    year_to: int | None = Field(default=None, ge=1, le=9999)
    venues: list[str] = Field(default_factory=list, max_length=10)
    author_id: int | None = Field(default=None, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=8192)#?
    include_total: bool = True

    @model_validator(mode="after")
    def validate_conditions(self) -> Self:
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must not exceed year_to")
        if any(not v.strip() or len(v) > 300 for v in self.venues):
            raise ValueError("venue must contain 1-300 characters")
        if not (
            self.query.all_of
            or self.query.any_of
            or self.venues
            or self.author_id
            or self.year_from
            or self.year_to
        ):
            raise ValueError(
                "At least one positive text/year/venue/author condition is required"
            )
        return self
