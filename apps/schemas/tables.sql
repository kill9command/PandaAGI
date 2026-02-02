-- Memory & Audit Schemas

CREATE TABLE IF NOT EXISTS memory (
  id TEXT PRIMARY KEY,
  title TEXT, tags TEXT, path TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  ttl_days INT, digest TEXT
);

CREATE TABLE IF NOT EXISTS memory_embedding (
  id TEXT PRIMARY KEY, memory_id TEXT, vector BLOB, dim INT, index_name TEXT
);

CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP,
  actor TEXT, tool TEXT, args_json TEXT,
  result_digest TEXT, mode TEXT, repo TEXT
);
