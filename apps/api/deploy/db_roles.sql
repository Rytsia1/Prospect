-- Least-privilege database roles for Prospect (docs/SECURITY_P2_5.md §9).
--
-- Run once, connected as the role that owns the schema (the one that runs `alembic upgrade`),
-- after the first migration. Re-running is safe. Then create one LOGIN role per service in the
-- group, each with its own generated password, and give each service only its own DATABASE_URL:
--
--   CREATE ROLE prospect_api    LOGIN PASSWORD '<generated>' IN ROLE prospect_app;
--   CREATE ROLE prospect_worker LOGIN PASSWORD '<generated>' IN ROLE prospect_app;
--
-- The services can then read and write rows, and nothing else: no DDL (CREATE/ALTER/DROP), no
-- TRUNCATE, no role management, no schema-version changes. Migrations keep using the owner, from
-- the deploy step only. Both services need row access to the same tables (the worker's sweep
-- deletes expired workspaces), so they share the group; separate logins still mean separate
-- credentials to rotate and separate connections to audit.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'prospect_app') THEN
    CREATE ROLE prospect_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO prospect_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO prospect_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO prospect_app;
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM prospect_app;

-- Tables that future migrations create get the same grants.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO prospect_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO prospect_app;
