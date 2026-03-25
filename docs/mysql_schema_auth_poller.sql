-- PyPNM / PyPNMGui MySQL schema
-- Covers:
--   1) GUI auth/users/api keys
--   2) Poller settings/jobs/decision logs
--   3) Inventory and RF snapshot tables

CREATE DATABASE IF NOT EXISTS pypnm_auth
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE pypnm_auth;

-- -----------------------------
-- Auth tables (GUI users + API keys)
-- -----------------------------
CREATE TABLE IF NOT EXISTS users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(16) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  language_preference VARCHAR(16) NOT NULL DEFAULT 'en-US',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS api_keys (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(128) NOT NULL,
  key_hash VARCHAR(255) NOT NULL,
  key_prefix VARCHAR(16) NOT NULL,
  role VARCHAR(16) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  description VARCHAR(255),
  created_by BIGINT,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------
-- Poller core tables
-- -----------------------------
CREATE TABLE IF NOT EXISTS modem_inventory_current (
  mac VARCHAR(17) NOT NULL,
  ip VARCHAR(45) NULL,
  cmts VARCHAR(128) NOT NULL,
  cmts_ip VARCHAR(45) NULL,
  fiber_node VARCHAR(128) NULL,
  cable_mac VARCHAR(128) NULL,
  status VARCHAR(64) NULL,
  docsis_version VARCHAR(32) NULL,
  vendor VARCHAR(64) NULL,
  model VARCHAR(128) NULL,
  upstream_interface VARCHAR(128) NULL,
  ofdm_enabled BOOLEAN NULL,
  ofdma_enabled BOOLEAN NULL,
  partial_service BOOLEAN NULL,
  first_seen_at DATETIME NOT NULL,
  last_seen_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  source_poller VARCHAR(64) NULL,
  PRIMARY KEY (mac)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS poller_setting (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(64) NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  scope_type VARCHAR(16) NOT NULL DEFAULT 'all_cmts',
  scope_json JSON NULL,
  collect_identity BOOLEAN NOT NULL DEFAULT TRUE,
  collect_scqam BOOLEAN NOT NULL DEFAULT FALSE,
  collect_rxmer BOOLEAN NOT NULL DEFAULT FALSE,
  interval_minutes INT NOT NULL DEFAULT 1440,
  run_window_start TIME NULL,
  run_window_end TIME NULL,
  max_concurrency INT NOT NULL DEFAULT 1,
  max_agent_queue_depth INT NOT NULL DEFAULT 20,
  retention_days INT NOT NULL DEFAULT 30,
  heavy_window_start TIME NULL,
  heavy_window_end TIME NULL,
  heavy_max_modems INT NOT NULL DEFAULT 300,
  heavy_delay_ms INT NOT NULL DEFAULT 0,
  max_runtime_sec INT NOT NULL DEFAULT 3600,
  last_target_offset INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uk_poller_setting_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS poller_job (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  poller_id BIGINT NOT NULL,
  trigger_type VARCHAR(24) NOT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'queued',
  rows_collected INT NOT NULL DEFAULT 0,
  modems_attempted INT NOT NULL DEFAULT 0,
  modems_succeeded INT NOT NULL DEFAULT 0,
  modems_failed INT NOT NULL DEFAULT 0,
  requested_by VARCHAR(64) NULL,
  request_payload JSON NULL,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  error_text TEXT NULL,
  cmts_breakdown JSON NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_job_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS scheduler_decision_log (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tick_at DATETIME NOT NULL,
  poller_id BIGINT NULL,
  poller_name VARCHAR(64) NULL,
  decision VARCHAR(16) NOT NULL,
  reason VARCHAR(64) NULL,
  effective_load INT NULL,
  threshold INT NULL,
  detail VARCHAR(255) NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_scheduler_tick (tick_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS modem_rf_snapshot (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  mac VARCHAR(17) NOT NULL,
  cmts VARCHAR(128) NOT NULL,
  collected_at DATETIME NOT NULL,
  scqam_json JSON NULL,
  rxmer_json JSON NULL,
  poller_name VARCHAR(64) NOT NULL,
  INDEX idx_snapshot_collected (collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
