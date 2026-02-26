-- stg_authors: Deduplicated author profiles with normalized names across sources.
-- Source: raw_blog_posts (extract distinct authors by normalized name)

with normalized as (
    select
        trim(initcap(author_name)) as author_name,
        source_id,
        publication_date
    from {{ source('raw', 'raw_blog_posts') }}
    where author_name is not null
      and trim(author_name) != ''
),

aggregated as (
    select
        md5(author_name) as author_id,
        author_name,
        count(*) as post_count,
        array_agg(distinct source_id order by source_id) as source_ids,
        min(publication_date) as first_seen_at,
        max(publication_date) as last_seen_at
    from normalized
    group by author_name
)

select * from aggregated
