-- mart_sources: Source health metrics combining raw source data with post aggregates.
-- References raw_blog_sources directly for operational metadata (status, last_checked_at)
-- not surfaced through staging layer. Acceptable per architecture: raw_blog_sources is a
-- dimension table, not a fact table.
-- Powers source notes in vault (Story 3.1) and source health monitoring (Story 5.1).

with post_metrics as (
    select
        source_id,
        count(*) as total_post_count,
        max(publication_date) as latest_post_date
    from {{ ref('stg_posts') }}
    group by source_id
)

select
    s.id,
    s.name,
    s.rss_feed_url,
    s.category,
    s.quality_rating,
    s.status,
    s.last_checked_at,
    coalesce(pm.total_post_count, 0) as total_post_count,
    pm.latest_post_date,
    s.created_at,
    s.updated_at
from {{ source('raw', 'raw_blog_sources') }} as s
left join post_metrics as pm
    on s.id = pm.source_id
