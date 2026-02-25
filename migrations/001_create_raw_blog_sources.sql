-- Migration 001: Create raw_blog_sources table
-- Stores curated blog source metadata for RSS feed ingestion.

CREATE TABLE IF NOT EXISTS raw_blog_sources (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rss_feed_url    TEXT NOT NULL,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    quality_rating  INTEGER NOT NULL,
    status          VARCHAR(20) DEFAULT 'active',
    last_checked_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
