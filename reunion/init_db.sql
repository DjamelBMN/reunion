-- init_db.sql
DROP TABLE IF EXISTS submissions;
DROP TABLE IF EXISTS final_choice; -- Nouvelle table

CREATE TABLE submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_name TEXT NOT NULL, -- Maintenant NOT NULL
    day_of_week TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    comment TEXT,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_day_time ON submissions (day_of_week, time_slot);
CREATE INDEX IF NOT EXISTS idx_teacher_name ON submissions (teacher_name); -- Utile pour la suppression

CREATE TABLE final_choice (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    votes INTEGER NOT NULL,
    chosen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_tie_breaker BOOLEAN DEFAULT FALSE -- Indique si c'était un départage
);