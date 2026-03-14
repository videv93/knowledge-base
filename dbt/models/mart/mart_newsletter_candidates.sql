-- mart_newsletter_candidates: Weekly top 20 newsletter candidates.
-- Ranks posts from the past 7 days by source quality (40%), recency (40%), and category
-- diversity (20%). Diversity score is derived from category_rank: rank 1 in its category
-- earns the full 0.20, rank 5 earns 0.04. Final rank_score is bounded 0.0-1.0.
-- Caps at 5 candidates per category to ensure topic spread across the newsletter.
-- References mart_posts and mart_sources only (never raw or staging tables directly).

with weekly_posts as (
    select
        p.id                          as post_id,
        p.title,
        p.summary_text,
        p.tags,
        p.difficulty_classification,
        p.author_name,
        p.source_name,
        p.category,
        p.publication_date,
        p.url,
        s.quality_rating
    from {{ ref('mart_posts') }} as p
    join {{ ref('mart_sources') }} as s
        on p.source_id = s.id
    where
        p.publication_date >= current_date - interval '7 days'
        and s.status = 'active'
        and p.summary_text is not null
        and s.quality_rating is not null
),

pre_ranked as (
    select
        *,
        -- Quality + recency component (used to establish category rank before diversity is added)
        (quality_rating / 5.0 * 0.4)
        + (greatest(
            1.0 - (
                extract(epoch from (current_timestamp - publication_date))
                / (7.0 * 86400)
            ),
            0.0
        ) * 0.4) as quality_recency_score,
        row_number() over (
            partition by category
            order by
                (quality_rating / 5.0 * 0.4)
                + (greatest(
                    1.0 - (
                        extract(epoch from (current_timestamp - publication_date))
                        / (7.0 * 86400)
                    ),
                    0.0
                ) * 0.4) desc
        ) as category_rank
    from weekly_posts
),

ranked as (
    select
        post_id,
        title,
        summary_text,
        tags,
        difficulty_classification,
        author_name,
        source_name,
        category,
        quality_rating,
        publication_date,
        url,
        category_rank,
        -- Final composite: quality 40% + recency 40% + diversity 20%
        -- Diversity: rank 1 in category → 0.20, rank 2 → 0.16, ..., rank 5 → 0.04
        round(
            quality_recency_score
            + (greatest(6 - category_rank, 0) / 5.0 * 0.2),
            4
        ) as rank_score
    from pre_ranked
)

select
    post_id,
    title,
    summary_text,
    tags,
    difficulty_classification,
    author_name,
    source_name,
    category,
    quality_rating,
    publication_date,
    url,
    rank_score,
    category_rank
from ranked
where category_rank <= 5
order by rank_score desc
limit 20
