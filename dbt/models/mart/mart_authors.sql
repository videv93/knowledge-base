-- mart_authors: Author profiles enriched with primary category derived from post distribution.
-- Powers author notes in vault generation (Story 3.1).

with category_counts as (
    select
        author_name,
        category,
        count(*) as cat_count,
        row_number() over (partition by author_name order by count(*) desc, category) as rn
    from {{ ref('stg_posts') }}
    where author_name != 'Unknown'
    group by author_name, category
),

primary_categories as (
    select author_name, category as primary_category
    from category_counts
    where rn = 1
)

select
    a.author_id,
    a.author_name,
    a.post_count,
    a.source_ids,
    a.first_seen_at,
    a.last_seen_at,
    pc.primary_category
from {{ ref('stg_authors') }} as a
left join primary_categories as pc
    on a.author_name = pc.author_name
