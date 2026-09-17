-- Defense-in-depth tenant isolation for a production database role.
-- Apply only after the API sets these transaction-local values:
--   SET LOCAL app.current_hospital_id = '<uuid>';
--   SET LOCAL app.is_platform_admin = 'false';
-- The table owner/service role may bypass RLS; use a restricted runtime role.

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'users', 'patients', 'encounters', 'discharges', 'protocols',
    'knowledge_resources', 'campaigns', 'outreach_tasks', 'call_records',
    'escalations', 'events', 'ehr_records', 'notifications', 'ai_usage',
    'audit_logs'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (
         current_setting(''app.is_platform_admin'', true) = ''true''
         OR hospital_id = nullif(
           current_setting(''app.current_hospital_id'', true), ''''
         )::uuid
       ) WITH CHECK (
         current_setting(''app.is_platform_admin'', true) = ''true''
         OR hospital_id = nullif(
           current_setting(''app.current_hospital_id'', true), ''''
         )::uuid
       )',
      table_name
    );
  END LOOP;
END $$;