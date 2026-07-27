-- Aurelius Capital — PostgreSQL initialization
-- Runs once when the container first starts.

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for text search on symbol names

-- Separate databases for dev and test (test DB is wiped between runs)
CREATE DATABASE aurelius_test
    WITH OWNER aurelius
    ENCODING 'UTF8'
    LC_COLLATE 'en_US.utf8'
    LC_CTYPE 'en_US.utf8';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE aurelius_dev TO aurelius;
GRANT ALL PRIVILEGES ON DATABASE aurelius_test TO aurelius;
