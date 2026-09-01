PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE assessment_dimensions (
    id INTEGER NOT NULL,
    "key" VARCHAR(32) NOT NULL,
    name VARCHAR(64) NOT NULL,
    enabled BOOLEAN NOT NULL,
    weight FLOAT NOT NULL,
    description TEXT,
    PRIMARY KEY (id),
    UNIQUE ("key")
);

CREATE TABLE children (
    id INTEGER NOT NULL,
    name VARCHAR(64) NOT NULL,
    nickname VARCHAR(64),
    avatar VARCHAR(255),
    active BOOLEAN NOT NULL,
    deactivated_at DATETIME,
    PRIMARY KEY (id)
);

CREATE TABLE ducks (
    id INTEGER NOT NULL,
    name VARCHAR(64) NOT NULL,
    avatar VARCHAR(255),
    status VARCHAR(255),
    note TEXT,
    active BOOLEAN NOT NULL,
    deactivated_at DATETIME,
    PRIMARY KEY (id)
);

CREATE TABLE roster_requests (
    request_id VARCHAR(36) NOT NULL,
    operation VARCHAR(32) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    response_json TEXT,
    last_error_code VARCHAR(64),
    last_error_message VARCHAR(255),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (request_id)
);
CREATE INDEX ix_roster_requests_operation ON roster_requests (operation);
CREATE INDEX ix_roster_requests_status ON roster_requests (status);

CREATE TABLE teacher_credentials (
    id INTEGER NOT NULL,
    pin_salt VARCHAR(64) NOT NULL,
    pin_hash VARCHAR(128) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE teacher_sessions (
    id INTEGER NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_teacher_sessions_token_hash
    ON teacher_sessions (token_hash);

CREATE TABLE conversations (
    id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    date VARCHAR(16) NOT NULL,
    started_at DATETIME NOT NULL,
    ended_at DATETIME,
    status VARCHAR(16) NOT NULL,
    end_reason VARCHAR(32),
    revision INTEGER NOT NULL,
    pending_end_reason VARCHAR(32),
    frozen_last_message_id INTEGER,
    PRIMARY KEY (id),
    FOREIGN KEY(child_id) REFERENCES children (id)
);
CREATE UNIQUE INDEX uq_conversations_child_active
    ON conversations (child_id) WHERE status = 'active';

CREATE TABLE duck_archives (
    id INTEGER NOT NULL,
    duck_id INTEGER NOT NULL,
    summary TEXT,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(duck_id) REFERENCES ducks (id)
);

CREATE TABLE duty_rosters (
    id INTEGER NOT NULL,
    cycle VARCHAR(64) NOT NULL,
    date VARCHAR(16) NOT NULL,
    child_id INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_roster_date_child UNIQUE (date, child_id),
    FOREIGN KEY(child_id) REFERENCES children (id)
);

CREATE TABLE assessments (
    id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL,
    overall FLOAT,
    PRIMARY KEY (id),
    CONSTRAINT uq_assessment_conversation UNIQUE (conversation_id),
    FOREIGN KEY(conversation_id) REFERENCES conversations (id),
    FOREIGN KEY(child_id) REFERENCES children (id)
);

CREATE TABLE emotion_logs (
    id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    emotion VARCHAR(32) NOT NULL,
    intensity INTEGER NOT NULL,
    note TEXT,
    occurred_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_emotion_conversation UNIQUE (conversation_id),
    FOREIGN KEY(conversation_id) REFERENCES conversations (id),
    FOREIGN KEY(child_id) REFERENCES children (id)
);

CREATE TABLE feeding_logs (
    id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    duck_id INTEGER,
    category VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    occurred_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(conversation_id) REFERENCES conversations (id),
    FOREIGN KEY(child_id) REFERENCES children (id),
    FOREIGN KEY(duck_id) REFERENCES ducks (id)
);

CREATE TABLE insight_notes (
    id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_insight_conversation UNIQUE (conversation_id),
    FOREIGN KEY(conversation_id) REFERENCES conversations (id),
    FOREIGN KEY(child_id) REFERENCES children (id)
);

CREATE TABLE messages (
    id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    role VARCHAR(16) NOT NULL,
    text TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(conversation_id) REFERENCES conversations (id)
);

CREATE TABLE analysis_jobs (
    id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    frozen_last_message_id INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL,
    attempt_count INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    available_at DATETIME NOT NULL,
    lease_owner VARCHAR(64),
    lease_expires_at DATETIME,
    last_error_code VARCHAR(64),
    last_error_message VARCHAR(255),
    started_at DATETIME,
    finished_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_analysis_job_conversation UNIQUE (conversation_id),
    FOREIGN KEY(conversation_id) REFERENCES conversations (id),
    FOREIGN KEY(frozen_last_message_id) REFERENCES messages (id)
);
CREATE INDEX ix_analysis_jobs_available_at ON analysis_jobs (available_at);
CREATE INDEX ix_analysis_jobs_lease_expires_at
    ON analysis_jobs (lease_expires_at);
CREATE INDEX ix_analysis_jobs_status ON analysis_jobs (status);

CREATE TABLE assessment_scores (
    id INTEGER NOT NULL,
    assessment_id INTEGER NOT NULL,
    dimension_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    reason TEXT,
    PRIMARY KEY (id),
    CONSTRAINT uq_assessment_dimension UNIQUE (assessment_id, dimension_id),
    FOREIGN KEY(assessment_id) REFERENCES assessments (id),
    FOREIGN KEY(dimension_id) REFERENCES assessment_dimensions (id)
);

CREATE TABLE chat_requests (
    request_id VARCHAR(36) NOT NULL,
    child_id INTEGER NOT NULL,
    conversation_id INTEGER,
    base_last_message_id INTEGER,
    child_message_id INTEGER,
    diary_message_id INTEGER,
    payload_hash VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    attempt_count INTEGER NOT NULL,
    available_at DATETIME NOT NULL,
    lease_owner VARCHAR(64),
    lease_expires_at DATETIME,
    last_error_code VARCHAR(64),
    last_error_message VARCHAR(255),
    response_json TEXT,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (request_id),
    FOREIGN KEY(child_id) REFERENCES children (id),
    FOREIGN KEY(conversation_id) REFERENCES conversations (id),
    FOREIGN KEY(base_last_message_id) REFERENCES messages (id),
    FOREIGN KEY(child_message_id) REFERENCES messages (id),
    FOREIGN KEY(diary_message_id) REFERENCES messages (id)
);
CREATE INDEX ix_chat_requests_available_at ON chat_requests (available_at);
CREATE INDEX ix_chat_requests_lease_expires_at
    ON chat_requests (lease_expires_at);
CREATE INDEX ix_chat_requests_status ON chat_requests (status);

INSERT INTO teacher_credentials
    (id, pin_salt, pin_hash, created_at, updated_at)
VALUES
    (1, 'synthetic-salt', 'synthetic-hash', '2026-08-31 08:00:00', '2026-08-31 08:00:00');

INSERT INTO teacher_sessions (id, token_hash, created_at)
VALUES (1, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '2026-08-31 08:01:00');

INSERT INTO children
    (id, name, nickname, avatar, active, deactivated_at)
VALUES
    (1, '合成幼儿', '小合', NULL, 1, NULL);

INSERT INTO ducks
    (id, name, avatar, status, note, active, deactivated_at)
VALUES
    (1, '合成小鸭', NULL, '健康', '仅用于迁移测试', 1, NULL);

INSERT INTO roster_requests
    (request_id, operation, payload_hash, status, response_json,
     last_error_code, last_error_message, created_at, updated_at)
VALUES
    ('00000000-0000-4000-8000-000000000010', 'daily',
     'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
     'succeeded', '{"date":"2026-09-01"}', NULL, NULL,
     '2026-08-31 08:02:00', '2026-08-31 08:02:00');

INSERT INTO conversations
    (id, child_id, date, started_at, ended_at, status, end_reason, revision,
     pending_end_reason, frozen_last_message_id)
VALUES
    (1, 1, '2026-09-01', '2026-09-01 01:00:00', '2026-09-01 01:05:00',
     'ended', 'complete', 2, NULL, 2);

INSERT INTO duty_rosters (id, cycle, date, child_id)
VALUES (1, '2026-09月值日', '2026-09-01', 1);

INSERT INTO messages (id, conversation_id, role, text, created_at)
VALUES
    (1, 1, 'child', '我给合成小鸭添了菜叶', '2026-09-01 01:01:00'),
    (2, 1, 'diary', '你观察得很仔细', '2026-09-01 01:02:00');

INSERT INTO chat_requests
    (request_id, child_id, conversation_id, base_last_message_id,
     child_message_id, diary_message_id, payload_hash, status, attempt_count,
     available_at, lease_owner, lease_expires_at, last_error_code,
     last_error_message, response_json, started_at, finished_at, created_at,
     updated_at)
VALUES
    ('00000000-0000-4000-8000-000000000011', 1, 1, NULL, 1, 2,
     'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
     'succeeded', 1, '2026-09-01 01:00:00', NULL, NULL, NULL, NULL,
     '{"conversation_id":1}', '2026-09-01 01:00:00',
     '2026-09-01 01:03:00', '2026-09-01 01:00:00',
     '2026-09-01 01:03:00');

INSERT INTO analysis_jobs
    (id, conversation_id, frozen_last_message_id, status, attempt_count,
     max_attempts, available_at, lease_owner, lease_expires_at,
     last_error_code, last_error_message, started_at, finished_at,
     created_at, updated_at)
VALUES
    (1, 1, 2, 'succeeded', 1, 3, '2026-09-01 01:05:00', NULL, NULL,
     NULL, NULL, '2026-09-01 01:05:00', '2026-09-01 01:06:00',
     '2026-09-01 01:05:00', '2026-09-01 01:06:00');

INSERT INTO assessment_dimensions
    (id, "key", name, enabled, weight, description)
VALUES
    (1, 'language', '语言表达能力', 1, 1.0, '迁移测试维度');

INSERT INTO assessments
    (id, conversation_id, child_id, status, overall)
VALUES
    (1, 1, 1, 'confirmed', 4.0);

INSERT INTO assessment_scores
    (id, assessment_id, dimension_id, score, reason)
VALUES
    (1, 1, 1, 4, '表达清晰');

INSERT INTO feeding_logs
    (id, conversation_id, child_id, duck_id, category, content, occurred_at)
VALUES
    (1, 1, 1, 1, '喂食', '添加菜叶', '2026-09-01 01:01:00');

INSERT INTO emotion_logs
    (id, conversation_id, child_id, emotion, intensity, note, occurred_at)
VALUES
    (1, 1, 1, '开心', 4, '愿意继续分享', '2026-09-01 01:04:00');

INSERT INTO insight_notes
    (id, conversation_id, child_id, content, created_at)
VALUES
    (1, 1, 1, '能主动观察食量', '2026-09-01 01:04:00');

INSERT INTO duck_archives (id, duck_id, summary, updated_at)
VALUES (1, 1, '合成小鸭历史摘要', '2026-09-01 01:06:00');

COMMIT;
