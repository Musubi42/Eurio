-- auth-redesign C2 : schéma RBAC + miroir users Authentik + PAT + audit.
-- Cf. DESIGN.md §4. Idempotent — appliqué via db_migrate.run_migrations() au
-- startup hook FastAPI.

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,        -- claim `sub` d'Authentik
  email         TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  created_at    INTEGER NOT NULL,        -- epoch ms
  last_login_at INTEGER,
  active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS roles (
  name TEXT PRIMARY KEY                  -- 'owner' | 'admin' | 'reviewer'
);

INSERT OR IGNORE INTO roles(name) VALUES ('owner'), ('admin'), ('reviewer');

CREATE TABLE IF NOT EXISTS user_roles (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role    TEXT NOT NULL REFERENCES roles(name),
  PRIMARY KEY (user_id, role)
);

CREATE TABLE IF NOT EXISTS pat_tokens (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  token_sha     TEXT NOT NULL UNIQUE,    -- sha256 hex du token clair
  scopes_json   TEXT NOT NULL,           -- JSON array de scopes
  created_at    INTEGER NOT NULL,
  last_used_at  INTEGER,
  revoked_at    INTEGER,
  expires_at    INTEGER                  -- nullable
);
CREATE INDEX IF NOT EXISTS pat_tokens_user_idx ON pat_tokens(user_id);
CREATE INDEX IF NOT EXISTS pat_tokens_active_idx ON pat_tokens(revoked_at) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS auth_audit (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         INTEGER NOT NULL,         -- epoch ms
  actor_id   TEXT,                     -- user.id OU NULL pour events système (break-glass CLI)
  event      TEXT NOT NULL,            -- 'login.ok' | 'login.fail' | 'token.create' | 'token.revoke' | 'role.grant' | 'role.revoke' | 'grant_owner.cli' | …
  target     TEXT,                     -- user.id / token.id concerné, contextuel
  meta_json  TEXT                      -- payload libre (IP, user-agent, scopes demandés, …)
);
CREATE INDEX IF NOT EXISTS auth_audit_ts_idx ON auth_audit(ts);
CREATE INDEX IF NOT EXISTS auth_audit_actor_idx ON auth_audit(actor_id);
