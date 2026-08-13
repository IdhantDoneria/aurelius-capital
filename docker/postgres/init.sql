-- Mentisrex Capital — PostgreSQL initialization
-- Runs once when the container first starts.

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for text search on symbol names

-- Separate databases for dev and test (test DB is wiped between runs)
CREATE DATABASE mentisrex_test
    WITH OWNER mentisrex
    ENCODING 'UTF8'
    LC_COLLATE 'en_US.utf8'
    LC_CTYPE 'en_US.utf8';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE mentisrex_dev TO mentisrex;
GRANT ALL PRIVILEGES ON DATABASE mentisrex_test TO mentisrex;
