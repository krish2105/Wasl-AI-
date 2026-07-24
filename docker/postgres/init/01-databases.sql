-- Runs once, on first initialisation of the postgres volume.
--
-- Why this exists: one postgres instance serves two unrelated consumers — the
-- Wasl application (which needs pgvector) and self-hosted Langfuse (which does
-- not, and which manages its own schema via Prisma migrations). Giving Langfuse
-- its own database rather than its own container keeps `docker compose up`
-- within a laptop's RAM budget while still isolating the schemas.

CREATE DATABASE langfuse;

\connect wasl
CREATE EXTENSION IF NOT EXISTS vector;
