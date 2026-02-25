#!/bin/bash
set -e

# Create the knowledge_base database for pipeline data (separate from Airflow's DB)
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE knowledge_base;
EOSQL
