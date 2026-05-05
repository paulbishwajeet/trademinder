-- Creates the test database idempotently
SELECT 'CREATE DATABASE trademinder_test'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'trademinder_test'
)\gexec
GRANT ALL PRIVILEGES ON DATABASE trademinder_test TO trademinder;
