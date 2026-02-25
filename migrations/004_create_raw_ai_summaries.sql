-- Migration 004: Create raw_ai_summaries table
-- Stores AI-generated summaries, topic tags, and difficulty classifications for blog posts.

CREATE TABLE IF NOT EXISTS raw_ai_summaries (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    post_id         BIGINT NOT NULL REFERENCES raw_blog_posts(id),
    summary_text    TEXT NOT NULL,
    tags            JSONB NOT NULL DEFAULT '[]',
    difficulty_classification TEXT NOT NULL,
    raw_api_response JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_raw_ai_summaries_post_id UNIQUE (post_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_ai_summaries_post_id ON raw_ai_summaries(post_id);
