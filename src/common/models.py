"""Shared domain model dataclasses.

Core data shapes used across pipeline modules.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class BlogSource:
    id: Optional[int]
    rss_feed_url: str
    name: str
    category: str
    quality_rating: int
    status: str = "active"
    last_checked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class BlogPost:
    id: Optional[int]
    source_id: int
    title: str
    body: str
    url: str
    publication_date: Optional[datetime]
    author_name: str
    created_at: Optional[datetime] = None


@dataclass
class DeadLetterEntry:
    id: Optional[int]
    post_reference: str
    failure_stage: str
    failure_reason: str
    retry_count: int = 0
    created_at: Optional[datetime] = None
    last_retry_at: Optional[datetime] = None


@dataclass
class ProcessingResult:
    total_found: int
    succeeded: int
    failed: int
    skipped: int


@dataclass
class AiSummary:
    id: Optional[int]
    post_id: int
    summary_text: str
    tags: list[str]
    difficulty_classification: str
    raw_api_response: Optional[dict] = None
    created_at: Optional[datetime] = None


@dataclass
class NewsletterCandidate:
    id: Optional[int]
    source_id: int
    title: str
    url: str
    summary_text: str
    author_name: str
    source_name: str
    category: str
    publication_date: Optional[datetime]
    tags: list[str]
    difficulty_classification: str
    score: float
