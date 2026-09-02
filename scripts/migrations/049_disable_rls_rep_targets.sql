-- Disable RLS on rep_targets
--
-- The table has RLS enabled but no policies defined, which blocks
-- all non-service-role access. Since we don't have policies yet,
-- disable RLS until proper policies are written.
--
-- This is a temporary fix while we diagnose why Railway queries
-- return empty even with service_role credentials.

ALTER TABLE rep_targets DISABLE ROW LEVEL SECURITY;

COMMENT ON TABLE rep_targets IS
'Sales quota targets by period, level, and rep.
RLS disabled pending policy implementation.';
