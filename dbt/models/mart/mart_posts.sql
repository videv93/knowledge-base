-- mart_posts: Enriched posts combining staging posts, summaries, and author references.
-- Primary consumption table for vault generation and newsletter systems.
-- Materialized as table for query performance (configured in dbt_project.yml).
-- Performance: index recommendations for downstream queries on category, publication_date.

with enriched_posts as (
    select
        p.id,
        p.source_id,
        p.source_name,
        p.category,
        p.title,
        p.body,
        p.url,
        p.author_name,
        a.author_id,
        p.publication_date,
        p.post_slug,
        s.summary_text,
        s.tags,
        s.difficulty_classification,
        s.is_low_quality,
        p.created_at
    from {{ ref('stg_posts') }} as p
    left join {{ ref('stg_summaries') }} as s
        on p.id = s.post_id
    left join {{ ref('stg_authors') }} as a
        on initcap(p.author_name) = a.author_name
)

select * from enriched_posts
