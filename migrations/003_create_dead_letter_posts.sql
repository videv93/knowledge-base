-- Migration 003: Create dead_letter_posts table
-- Dead letter queue for failed pipeline items across all stages.

CREATE TABLE IF NOT EXISTS dead_letter_posts (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    post_reference  TEXT NOT NULL,
    failure_stage   TEXT NOT NULL,
    failure_reason  TEXT NOT NULL,
    retry_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    last_retry_at   TIMESTAMPTZ
);
