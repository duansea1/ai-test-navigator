-- ============================================================
-- AI Test Navigator · 新建 model_configs 表（MySQL，带 COMMENT）
-- 适用场景：MySQL 库 ai-navigator 中尚不存在 model_configs 表
--   （该表为本轮「模型供应商管理」新增，老库未包含）。
-- 执行后：后端下次启动会向此表种入 4 条默认供应商（幂等）。
-- 若不慎重复执行（表已存在），会报 1050，可忽略或用 DROP 后重建。
-- 用法：mysql -uroot -p ai-navigator < db-create-model-configs.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS model_configs (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  provider_key VARCHAR(64) NOT NULL UNIQUE COMMENT '供应商唯一 key（英文）',
  display_name VARCHAR(128) NOT NULL COMMENT '显示名',
  api_key TEXT COMMENT 'API Key（明文，本地存储）',
  base_url VARCHAR(512) COMMENT 'API 地址（Base URL）',
  protocol VARCHAR(32) NOT NULL DEFAULT 'openai-completions' COMMENT 'API 协议：openai-completions/openai-responses/anthropic/gemini',
  model_ids TEXT NOT NULL COMMENT '模型 ID 列表（JSON 数组）',
  is_custom TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否自定义：0/1',
  is_default TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认供应商：0/1',
  enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：0/1',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  updated_at DATETIME NOT NULL COMMENT '更新时间',
  INDEX idx_mc_default (is_default),
  INDEX idx_mc_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模型供应商配置表';
