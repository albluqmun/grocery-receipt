#!/bin/bash
# Creates the test database alongside the main one.
# Executed automatically by PostgreSQL on first container init.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE ${POSTGRES_DB}_test OWNER $POSTGRES_USER;
EOSQL
