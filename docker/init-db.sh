#!/bin/bash
set -e

# Create the knowledge_base database for pipeline data (separate from Airflow's DB)
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE knowledge_base;
EOSQL

# Run migrations against the knowledge_base database
for f in /opt/airflow/migrations/*.sql; do
    echo "Running migration: $(basename "$f")"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname knowledge_base -f "$f"
done

# Seed blog sources from CSV if available
SEED_CSV="/opt/airflow/data/blog_sources.csv"
if [ -f "$SEED_CSV" ]; then
    echo "Seeding blog sources from $SEED_CSV"
    # Use a single psql session: create staging table, copy CSV, insert, drop
    tail -n +2 "$SEED_CSV" | psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname knowledge_base \
        -c "CREATE TABLE _seed_staging (name TEXT, rss_feed_url TEXT, blog_url TEXT, category TEXT, quality_rating INTEGER);" \
        -c "\COPY _seed_staging FROM STDIN WITH CSV" \
        -c "INSERT INTO raw_blog_sources (name, rss_feed_url, category, quality_rating) SELECT name, rss_feed_url, category, quality_rating FROM _seed_staging ON CONFLICT (rss_feed_url) DO NOTHING;" \
        -c "DROP TABLE _seed_staging;"
    echo "Seeded $(psql -t --username "$POSTGRES_USER" --dbname knowledge_base -c "SELECT count(*) FROM raw_blog_sources") sources"
fi
