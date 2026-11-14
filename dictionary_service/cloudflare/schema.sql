CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY,
    word TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed TEXT,
    reviewer TEXT
);
CREATE INDEX IF NOT EXISTS proposals_status_id ON proposals(status, id);
CREATE TABLE IF NOT EXISTS rate_limits (
    address TEXT NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY(address, day)
);
CREATE INDEX IF NOT EXISTS rate_limits_day ON rate_limits(day);
