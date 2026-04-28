CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  domain TEXT NOT NULL,
  source TEXT NOT NULL,
  event TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);
