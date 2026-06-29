-- Tokengram self-hosted SQLite sxema.
-- license-server/schema.sql ilə uyğundur, üstəlik admin_users.

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  polar_customer_id TEXT UNIQUE,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  polar_subscription_id TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('trialing','active','past_due','cancelled','incomplete')),
  current_period_end INTEGER NOT NULL,
  plan TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS licenses (
  key TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  machine_fingerprint TEXT,
  activated_at INTEGER,
  revoked INTEGER DEFAULT 0,
  note TEXT,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Bir maşın = bir trial. Lokal faylların silinməsi reset vermir,
-- çünki qeyd fingerprint-ə bağlıdır və serverdə yaşayır.
CREATE TABLE IF NOT EXISTS trials (
  fingerprint TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  license_key TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Magic-link sign-in (parolsuz). Token birdəfəlikdir, qısa ömürlüdür.
CREATE TABLE IF NOT EXISTS magic_links (
  token TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at INTEGER,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  last_login_at INTEGER
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  admin_email TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT,
  details TEXT,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subs_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_lic_user ON licenses(user_id);
CREATE INDEX IF NOT EXISTS idx_lic_fingerprint ON licenses(machine_fingerprint);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_magic_email ON magic_links(email);
