-- Migration 006: Add resolved column and index to dead_letter_posts
-- Supports DLQ inspection and reprocessing (Story 6.1)

ALTER TABLE dead_letter_posts
    ADD COLUMN IF NOT EXISTS resolved BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_dead_letter_posts_stage_resolved
    ON dead_letter_posts (failure_stage, resolved);
