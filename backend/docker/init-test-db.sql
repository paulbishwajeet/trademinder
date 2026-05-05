-- Creates the test database when Postgres container first starts
CREATE DATABASE trademinder_test;
GRANT ALL PRIVILEGES ON DATABASE trademinder_test TO trademinder;
