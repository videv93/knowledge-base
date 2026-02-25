-- Migration 005: Add unique constraint on rss_feed_url for idempotent source seeding.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_raw_blog_sources_rss_feed_url'
    ) THEN
        ALTER TABLE raw_blog_sources
            ADD CONSTRAINT uq_raw_blog_sources_rss_feed_url UNIQUE (rss_feed_url);
    END IF;
END
$$;
