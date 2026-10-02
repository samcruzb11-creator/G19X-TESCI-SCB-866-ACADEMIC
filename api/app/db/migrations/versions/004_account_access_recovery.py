"""6C schema snapshot; only new tables. Existing revisions/data are untouched."""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE TABLE access_requests (\n\tid BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, \n\tidentifier VARCHAR(320) COLLATE utf8mb4_unicode_ci NOT NULL, \n\tnombre VARCHAR(160) NOT NULL, \n\tmotivo TEXT NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tcreated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), \n\tresolved_at DATETIME(6), \n\tresolved_by BIGINT UNSIGNED, \n\tapproved_role VARCHAR(30), \n\tadmin_reason VARCHAR(1000), \n\tusuario_id BIGINT UNSIGNED, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_access_status CHECK (status IN ('PENDING','APPROVED','REJECTED','FULFILLED')), \n\tCONSTRAINT ck_access_role CHECK (approved_role IS NULL OR approved_role IN ('ADMIN','AUDITOR_INTERNO','AUDITOR_EXTERNO','RESPONSABLE_AREA','APROBADOR')), \n\tCONSTRAINT ck_access_resolution CHECK ((status='PENDING' AND resolved_by IS NULL AND resolved_at IS NULL AND approved_role IS NULL AND usuario_id IS NULL) OR (status='REJECTED' AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL AND approved_role IS NULL AND usuario_id IS NULL) OR (status='APPROVED' AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL AND approved_role IS NOT NULL AND usuario_id IS NULL) OR (status='FULFILLED' AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL AND approved_role IS NOT NULL AND usuario_id IS NOT NULL)), \n\tFOREIGN KEY(resolved_by) REFERENCES usuarios (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(usuario_id) REFERENCES usuarios (id) ON DELETE RESTRICT\n)ENGINE=InnoDB CHARSET=utf8mb4")
    op.execute('CREATE INDEX ix_access_requests_status_created ON access_requests (status, created_at)')
    op.execute('CREATE UNIQUE INDEX uq_access_requests_identifier ON access_requests (identifier)')
    op.execute('CREATE TABLE auth_action_limits (\n\taction VARCHAR(32) NOT NULL, \n\tidentifier VARCHAR(320) COLLATE utf8mb4_unicode_ci NOT NULL, \n\twindow_start DATETIME(6) NOT NULL, \n\tcount INTEGER UNSIGNED NOT NULL, \n\texpires_at DATETIME(6) NOT NULL, \n\tPRIMARY KEY (action, identifier)\n)ENGINE=InnoDB CHARSET=utf8mb4')
    op.execute('CREATE INDEX ix_auth_action_limits_expires ON auth_action_limits (expires_at)')
    op.execute("CREATE TABLE auth_mail_jobs (\n\tid BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, \n\tkind VARCHAR(24) NOT NULL, \n\tidentifier VARCHAR(320) COLLATE utf8mb4_unicode_ci, \n\trecipient VARCHAR(320), \n\tstate_fingerprint BINARY(32), \n\ttoken_expires_at DATETIME(6), \n\tusuario_id BIGINT UNSIGNED, \n\taccess_request_id BIGINT UNSIGNED, \n\tstatus VARCHAR(16) NOT NULL, \n\tattempts INTEGER UNSIGNED NOT NULL, \n\tlease VARCHAR(32), \n\tlocked_until DATETIME(6), \n\tavailable_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), \n\tcreated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_auth_mail_kind CHECK (kind IN ('LOOKUP_RESET','PASSWORD_RESET','INITIAL_PASSWORD','PASSWORD_CHANGED')), \n\tCONSTRAINT ck_lookup_no_recipient CHECK (kind <> 'LOOKUP_RESET' OR recipient IS NULL), \n\tCONSTRAINT ck_auth_mail_subject CHECK ((kind='LOOKUP_RESET' AND identifier IS NOT NULL AND usuario_id IS NULL AND access_request_id IS NULL AND state_fingerprint IS NULL AND token_expires_at IS NULL) OR (kind IN ('PASSWORD_RESET','PASSWORD_CHANGED') AND identifier IS NULL AND usuario_id IS NOT NULL AND access_request_id IS NULL AND recipient IS NOT NULL AND state_fingerprint IS NOT NULL) OR (kind='INITIAL_PASSWORD' AND identifier IS NULL AND usuario_id IS NULL AND access_request_id IS NOT NULL AND recipient IS NOT NULL AND state_fingerprint IS NOT NULL)), \n\tCONSTRAINT ck_auth_mail_status CHECK (status IN ('PENDING','PROCESSING','DONE','CANCELLED','FAILED')), \n\tFOREIGN KEY(usuario_id) REFERENCES usuarios (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(access_request_id) REFERENCES access_requests (id) ON DELETE RESTRICT\n)ENGINE=InnoDB CHARSET=utf8mb4")
    op.execute('CREATE INDEX ix_auth_mail_jobs_created ON auth_mail_jobs (created_at)')
    op.execute('CREATE INDEX ix_auth_mail_jobs_lease ON auth_mail_jobs (status, locked_until)')
    op.execute('CREATE INDEX ix_auth_mail_jobs_lookup ON auth_mail_jobs (kind, identifier)')
    op.execute('CREATE INDEX ix_auth_mail_jobs_ready ON auth_mail_jobs (status, available_at)')
    op.execute("CREATE TABLE auth_action_tokens (\n\ttoken_hash BINARY(32) NOT NULL, \n\tpurpose VARCHAR(24) NOT NULL, \n\tmail_job_id BIGINT UNSIGNED NOT NULL, \n\tusuario_id BIGINT UNSIGNED, \n\taccess_request_id BIGINT UNSIGNED, \n\tstate_fingerprint BINARY(32) NOT NULL, \n\tcreated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), \n\texpires_at DATETIME(6) NOT NULL, \n\tconsumed_at DATETIME(6), \n\tPRIMARY KEY (token_hash), \n\tCONSTRAINT ck_action_token_subject CHECK ((purpose='PASSWORD_RESET' AND usuario_id IS NOT NULL AND access_request_id IS NULL) OR (purpose='INITIAL_PASSWORD' AND access_request_id IS NOT NULL AND usuario_id IS NULL)), \n\tFOREIGN KEY(mail_job_id) REFERENCES auth_mail_jobs (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(usuario_id) REFERENCES usuarios (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(access_request_id) REFERENCES access_requests (id) ON DELETE RESTRICT\n)ENGINE=InnoDB")
    op.execute('CREATE INDEX ix_auth_action_tokens_expires ON auth_action_tokens (expires_at)')
    op.execute('CREATE INDEX ix_auth_action_tokens_job ON auth_action_tokens (mail_job_id)')
    op.execute('CREATE INDEX ix_auth_action_tokens_request ON auth_action_tokens (access_request_id)')
    op.execute('CREATE INDEX ix_auth_action_tokens_user ON auth_action_tokens (usuario_id)')


def downgrade():
    op.drop_table('auth_action_tokens')
    op.drop_table('auth_mail_jobs')
    op.drop_table('auth_action_limits')
    op.drop_table('access_requests')
