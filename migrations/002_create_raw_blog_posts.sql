-- Migration 002: Create raw_blog_posts table
-- Stores ingested blog post content with URL-based deduplication.

CREATE TABLE IF NOT EXISTS raw_blog_posts (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id        BIGINT NOT NULL REFERENCES raw_blog_sources(id),
    title            TEXT NOT NULL,
    body             TEXT NOT NULL,
    url              TEXT NOT NULL,
    publication_date TIMESTAMPTZ,
    author_name      TEXT NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_raw_blog_posts_url UNIQUE (url)
);

CREATE INDEX IF NOT EXISTS idx_raw_blog_posts_source_id ON raw_blog_posts(source_id);
