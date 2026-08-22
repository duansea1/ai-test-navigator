-- ============================================================
-- AI Test Navigator · 为已存在的 MySQL 表补 COMMENT 备注
-- 适用场景：ai-navigator 库里 11 张表已建好（无注释），需补备注。
--   若表尚不存在：无需本脚本，init_schema() 的 CREATE 会自动带注释。
-- 注意：MODIFY 仅追加 COMMENT，不重复声明 PRIMARY KEY / UNIQUE
--   （索引已存在，重复声明会报错 1068 / 1061）。
-- 用法：mysql -uroot -p ai-navigator < db-add-comments.sql
-- ============================================================

-- ── analysis_tasks ───────────────────────────────────────────
ALTER TABLE analysis_tasks
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN task_id VARCHAR(64) NOT NULL COMMENT '任务唯一标识（对外 ID）',
  MODIFY COLUMN title VARCHAR(512) NOT NULL COMMENT '任务标题',
  MODIFY COLUMN source_text MEDIUMTEXT COMMENT '原始需求/分析输入文本',
  MODIFY COLUMN projects VARCHAR(512) NOT NULL DEFAULT '' COMMENT '涉及项目列表（逗号分隔）',
  MODIFY COLUMN branch VARCHAR(128) NOT NULL DEFAULT '' COMMENT '分析分支',
  MODIFY COLUMN workspace VARCHAR(512) NOT NULL DEFAULT '' COMMENT '工作区路径',
  MODIFY COLUMN status VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '任务状态：pending/running/completed/failed/cancelled',
  MODIFY COLUMN stage VARCHAR(64) NOT NULL DEFAULT '' COMMENT '当前分析阶段',
  MODIFY COLUMN progress INT NOT NULL DEFAULT 0 COMMENT '进度百分比 0-100',
  MODIFY COLUMN message TEXT COMMENT '进度/状态消息',
  MODIFY COLUMN report_id VARCHAR(64) COMMENT '关联报告 ID',
  MODIFY COLUMN error TEXT COMMENT '错误信息',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间',
  MODIFY COLUMN updated_at DATETIME NOT NULL COMMENT '更新时间';
ALTER TABLE analysis_tasks COMMENT='分析任务主表';

-- ── requirements ─────────────────────────────────────────────
ALTER TABLE requirements
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
  MODIFY COLUMN req_id VARCHAR(64) NOT NULL COMMENT '需求唯一标识',
  MODIFY COLUMN title VARCHAR(512) NOT NULL COMMENT '需求标题',
  MODIFY COLUMN description TEXT COMMENT '需求描述',
  MODIFY COLUMN priority VARCHAR(16) NOT NULL DEFAULT 'P1' COMMENT '优先级：P0/P1/P2/P3',
  MODIFY COLUMN acceptance_criteria TEXT COMMENT '验收标准',
  MODIFY COLUMN status VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '需求状态：pending/analyzed/verified/covered',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE requirements COMMENT='需求条目表';

-- ── code_evidence ────────────────────────────────────────────
ALTER TABLE code_evidence
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
  MODIFY COLUMN project VARCHAR(128) COMMENT '所属项目',
  MODIFY COLUMN path VARCHAR(1024) COMMENT '代码文件路径',
  MODIFY COLUMN line_no INT COMMENT '行号',
  MODIFY COLUMN symbol VARCHAR(256) COMMENT '符号名（函数/类/变量）',
  MODIFY COLUMN summary TEXT COMMENT '代码摘要',
  MODIFY COLUMN relevance VARCHAR(32) COMMENT '相关度：high/medium/low',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE code_evidence COMMENT='代码证据表';

-- ── impact_scopes ────────────────────────────────────────────
ALTER TABLE impact_scopes
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
  MODIFY COLUMN project VARCHAR(128) COMMENT '所属项目',
  MODIFY COLUMN area VARCHAR(128) COMMENT '影响范围（模块/服务）',
  MODIFY COLUMN risk_level VARCHAR(16) COMMENT '风险等级：high/medium/low',
  MODIFY COLUMN affected_items TEXT COMMENT '受影响项清单',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE impact_scopes COMMENT='影响范围表';

-- ── test_cases ───────────────────────────────────────────────
ALTER TABLE test_cases
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
  MODIFY COLUMN req_ref VARCHAR(64) COMMENT '关联需求 ID',
  MODIFY COLUMN case_type VARCHAR(32) COMMENT '用例类型：function/integration/e2e',
  MODIFY COLUMN title VARCHAR(512) COMMENT '用例标题',
  MODIFY COLUMN steps TEXT COMMENT '测试步骤',
  MODIFY COLUMN expected TEXT COMMENT '预期结果',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE test_cases COMMENT='测试用例表';

-- ── test_runs ───────────────────────────────────────────────
ALTER TABLE test_runs
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN task_id VARCHAR(64) COMMENT '关联任务 ID',
  MODIFY COLUMN command VARCHAR(1024) COMMENT '执行命令',
  MODIFY COLUMN exit_code INT COMMENT '退出码',
  MODIFY COLUMN duration_ms INT COMMENT '耗时（毫秒）',
  MODIFY COLUMN status VARCHAR(32) COMMENT '运行状态：running/passed/failed',
  MODIFY COLUMN log_excerpt TEXT COMMENT '日志摘要',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE test_runs COMMENT='测试执行记录表';

-- ── assessments ──────────────────────────────────────────────
ALTER TABLE assessments
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
  MODIFY COLUMN req_ref VARCHAR(64) COMMENT '关联需求 ID',
  MODIFY COLUMN verdict VARCHAR(32) COMMENT '评估结论：covered/gap/risk',
  MODIFY COLUMN risk VARCHAR(16) COMMENT '风险等级：high/medium/low',
  MODIFY COLUMN confidence DECIMAL(4,3) COMMENT '置信度 0-1',
  MODIFY COLUMN evidence_refs TEXT COMMENT '证据引用',
  MODIFY COLUMN gaps TEXT COMMENT '缺口说明',
  MODIFY COLUMN needs_review TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否需人工复核：0/1',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE assessments COMMENT='需求评估表';

-- ── reports ──────────────────────────────────────────────────
ALTER TABLE reports
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN task_id VARCHAR(64) COMMENT '关联任务 ID',
  MODIFY COLUMN report_id VARCHAR(64) NOT NULL COMMENT '报告唯一标识',
  MODIFY COLUMN version INT NOT NULL DEFAULT 1 COMMENT '版本号',
  MODIFY COLUMN files TEXT COMMENT '报告文件路径清单',
  MODIFY COLUMN summary TEXT COMMENT '报告摘要',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE reports COMMENT='分析报告表';

-- ── agent_sessions ───────────────────────────────────────────
ALTER TABLE agent_sessions
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN task_id VARCHAR(64) COMMENT '关联任务 ID',
  MODIFY COLUMN agent_id VARCHAR(64) COMMENT 'Agent 标识',
  MODIFY COLUMN session_id VARCHAR(128) COMMENT 'DSH 会话 ID',
  MODIFY COLUMN status VARCHAR(32) COMMENT '会话状态：running/done/error',
  MODIFY COLUMN turns INT NOT NULL DEFAULT 0 COMMENT '对话轮次',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE agent_sessions COMMENT='Agent 会话表';

-- ── dsh_events ───────────────────────────────────────────────
ALTER TABLE dsh_events
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN task_id VARCHAR(64) COMMENT '关联任务 ID',
  MODIFY COLUMN session_id VARCHAR(128) COMMENT 'DSH 会话 ID',
  MODIFY COLUMN event_type VARCHAR(64) COMMENT '事件类型（如 token/tool_call/step/error）',
  MODIFY COLUMN payload TEXT COMMENT '事件载荷（JSON）',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE dsh_events COMMENT='DSH 事件流表';

-- ── model_configs ────────────────────────────────────────────
ALTER TABLE model_configs
  MODIFY COLUMN id INT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN provider_key VARCHAR(64) NOT NULL COMMENT '供应商唯一 key（英文）',
  MODIFY COLUMN display_name VARCHAR(128) NOT NULL COMMENT '显示名',
  MODIFY COLUMN api_key TEXT COMMENT 'API Key（明文，本地存储）',
  MODIFY COLUMN base_url VARCHAR(512) COMMENT 'API 地址（Base URL）',
  MODIFY COLUMN protocol VARCHAR(32) NOT NULL DEFAULT 'openai-completions' COMMENT 'API 协议：openai-completions/openai-responses/anthropic/gemini',
  MODIFY COLUMN model_ids TEXT NOT NULL COMMENT '模型 ID 列表（JSON 数组）',
  MODIFY COLUMN is_custom TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否自定义：0/1',
  MODIFY COLUMN is_default TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认供应商：0/1',
  MODIFY COLUMN enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：0/1',
  MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间',
  MODIFY COLUMN updated_at DATETIME NOT NULL COMMENT '更新时间';
ALTER TABLE model_configs COMMENT='模型供应商配置表';
