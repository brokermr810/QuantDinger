/*
 Navicat Premium Data Transfer

 Source Server         : quantdinger
 Source Server Type    : PostgreSQL
 Source Server Version : 160013 (160013)
 Source Host           : localhost:5432
 Source Catalog        : quantdinger
 Source Schema         : public

 Target Server Type    : PostgreSQL
 Target Server Version : 160013 (160013)
 File Encoding         : 65001

 Date: 06/06/2026 17:00:55
*/


-- ----------------------------
-- Sequence structure for pending_orders_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."pending_orders_id_seq";
CREATE SEQUENCE "public"."pending_orders_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_agent_audit_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_agent_audit_id_seq";
CREATE SEQUENCE "public"."qd_agent_audit_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_agent_jobs_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_agent_jobs_id_seq";
CREATE SEQUENCE "public"."qd_agent_jobs_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_agent_paper_orders_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_agent_paper_orders_id_seq";
CREATE SEQUENCE "public"."qd_agent_paper_orders_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_agent_tokens_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_agent_tokens_id_seq";
CREATE SEQUENCE "public"."qd_agent_tokens_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_ai_calibration_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_ai_calibration_id_seq";
CREATE SEQUENCE "public"."qd_ai_calibration_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_analysis_memory_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_analysis_memory_id_seq";
CREATE SEQUENCE "public"."qd_analysis_memory_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_analysis_tasks_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_analysis_tasks_id_seq";
CREATE SEQUENCE "public"."qd_analysis_tasks_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_backtest_equity_points_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_backtest_equity_points_id_seq";
CREATE SEQUENCE "public"."qd_backtest_equity_points_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_backtest_runs_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_backtest_runs_id_seq";
CREATE SEQUENCE "public"."qd_backtest_runs_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_backtest_trades_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_backtest_trades_id_seq";
CREATE SEQUENCE "public"."qd_backtest_trades_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_credits_log_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_credits_log_id_seq";
CREATE SEQUENCE "public"."qd_credits_log_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_exchange_credentials_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_exchange_credentials_id_seq";
CREATE SEQUENCE "public"."qd_exchange_credentials_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_indicator_codes_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_indicator_codes_id_seq";
CREATE SEQUENCE "public"."qd_indicator_codes_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_indicator_comments_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_indicator_comments_id_seq";
CREATE SEQUENCE "public"."qd_indicator_comments_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_indicator_purchases_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_indicator_purchases_id_seq";
CREATE SEQUENCE "public"."qd_indicator_purchases_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_login_attempts_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_login_attempts_id_seq";
CREATE SEQUENCE "public"."qd_login_attempts_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_manual_positions_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_manual_positions_id_seq";
CREATE SEQUENCE "public"."qd_manual_positions_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_market_symbols_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_market_symbols_id_seq";
CREATE SEQUENCE "public"."qd_market_symbols_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_membership_orders_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_membership_orders_id_seq";
CREATE SEQUENCE "public"."qd_membership_orders_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_oauth_links_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_oauth_links_id_seq";
CREATE SEQUENCE "public"."qd_oauth_links_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_position_alerts_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_position_alerts_id_seq";
CREATE SEQUENCE "public"."qd_position_alerts_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_position_monitors_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_position_monitors_id_seq";
CREATE SEQUENCE "public"."qd_position_monitors_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_quick_trades_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_quick_trades_id_seq";
CREATE SEQUENCE "public"."qd_quick_trades_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_security_logs_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_security_logs_id_seq";
CREATE SEQUENCE "public"."qd_security_logs_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_strategies_trading_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_strategies_trading_id_seq";
CREATE SEQUENCE "public"."qd_strategies_trading_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_strategy_logs_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_strategy_logs_id_seq";
CREATE SEQUENCE "public"."qd_strategy_logs_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_strategy_notifications_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_strategy_notifications_id_seq";
CREATE SEQUENCE "public"."qd_strategy_notifications_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_strategy_positions_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_strategy_positions_id_seq";
CREATE SEQUENCE "public"."qd_strategy_positions_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_strategy_trades_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_strategy_trades_id_seq";
CREATE SEQUENCE "public"."qd_strategy_trades_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_usdt_orders_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_usdt_orders_id_seq";
CREATE SEQUENCE "public"."qd_usdt_orders_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_users_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_users_id_seq";
CREATE SEQUENCE "public"."qd_users_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_verification_codes_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_verification_codes_id_seq";
CREATE SEQUENCE "public"."qd_verification_codes_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for qd_watchlist_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."qd_watchlist_id_seq";
CREATE SEQUENCE "public"."qd_watchlist_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Table structure for pending_orders
-- ----------------------------
DROP TABLE IF EXISTS "public"."pending_orders";
CREATE TABLE "public"."pending_orders" (
  "id" int4 NOT NULL DEFAULT nextval('pending_orders_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "strategy_id" int4,
  "symbol" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "signal_type" varchar(30) COLLATE "pg_catalog"."default" NOT NULL,
  "signal_ts" int8,
  "market_type" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'swap'::character varying,
  "order_type" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'market'::character varying,
  "amount" numeric(20,8) DEFAULT 0,
  "price" numeric(20,8) DEFAULT 0,
  "execution_mode" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'signal'::character varying,
  "status" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'pending'::character varying,
  "priority" int4 DEFAULT 0,
  "attempts" int4 DEFAULT 0,
  "max_attempts" int4 DEFAULT 10,
  "last_error" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "payload_json" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "dispatch_note" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "exchange_id" varchar(50) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "exchange_order_id" varchar(100) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "exchange_response_json" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "filled" numeric(20,8) DEFAULT 0,
  "avg_price" numeric(20,8) DEFAULT 0,
  "executed_at" timestamp(6),
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now(),
  "processed_at" timestamp(6),
  "sent_at" timestamp(6)
)
;

-- ----------------------------
-- Table structure for qd_agent_audit
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_agent_audit";
CREATE TABLE "public"."qd_agent_audit" (
  "id" int8 NOT NULL DEFAULT nextval('qd_agent_audit_id_seq'::regclass),
  "user_id" int4 NOT NULL,
  "agent_token_id" int4,
  "agent_name" varchar(80) COLLATE "pg_catalog"."default",
  "route" varchar(160) COLLATE "pg_catalog"."default" NOT NULL,
  "method" varchar(8) COLLATE "pg_catalog"."default" NOT NULL,
  "scope_class" varchar(4) COLLATE "pg_catalog"."default" NOT NULL,
  "status_code" int4 NOT NULL,
  "idempotency_key" varchar(120) COLLATE "pg_catalog"."default",
  "request_summary" jsonb,
  "response_summary" jsonb,
  "duration_ms" int4,
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_agent_jobs
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_agent_jobs";
CREATE TABLE "public"."qd_agent_jobs" (
  "id" int8 NOT NULL DEFAULT nextval('qd_agent_jobs_id_seq'::regclass),
  "job_id" varchar(40) COLLATE "pg_catalog"."default" NOT NULL,
  "user_id" int4 NOT NULL,
  "agent_token_id" int4,
  "kind" varchar(40) COLLATE "pg_catalog"."default" NOT NULL,
  "status" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'queued'::character varying,
  "request" jsonb NOT NULL DEFAULT '{}'::jsonb,
  "result" jsonb,
  "error" text COLLATE "pg_catalog"."default",
  "progress" jsonb,
  "idempotency_key" varchar(120) COLLATE "pg_catalog"."default",
  "created_at" timestamp(6) DEFAULT now(),
  "started_at" timestamp(6),
  "finished_at" timestamp(6)
)
;

-- ----------------------------
-- Table structure for qd_agent_paper_orders
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_agent_paper_orders";
CREATE TABLE "public"."qd_agent_paper_orders" (
  "id" int8 NOT NULL DEFAULT nextval('qd_agent_paper_orders_id_seq'::regclass),
  "order_uid" varchar(40) COLLATE "pg_catalog"."default" NOT NULL,
  "user_id" int4 NOT NULL,
  "agent_token_id" int4,
  "market" varchar(40) COLLATE "pg_catalog"."default" NOT NULL,
  "symbol" varchar(60) COLLATE "pg_catalog"."default" NOT NULL,
  "side" varchar(8) COLLATE "pg_catalog"."default" NOT NULL,
  "order_type" varchar(16) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'market'::character varying,
  "qty" numeric(28,10) NOT NULL,
  "limit_price" numeric(28,10),
  "fill_price" numeric(28,10),
  "fill_value" numeric(28,10),
  "status" varchar(16) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'filled'::character varying,
  "note" text COLLATE "pg_catalog"."default",
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_agent_tokens
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_agent_tokens";
CREATE TABLE "public"."qd_agent_tokens" (
  "id" int4 NOT NULL DEFAULT nextval('qd_agent_tokens_id_seq'::regclass),
  "user_id" int4 NOT NULL,
  "name" varchar(80) COLLATE "pg_catalog"."default" NOT NULL,
  "token_prefix" varchar(24) COLLATE "pg_catalog"."default" NOT NULL,
  "token_hash" varchar(128) COLLATE "pg_catalog"."default" NOT NULL,
  "scopes" text COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'R'::text,
  "markets" text COLLATE "pg_catalog"."default" NOT NULL DEFAULT '*'::text,
  "instruments" text COLLATE "pg_catalog"."default" NOT NULL DEFAULT '*'::text,
  "paper_only" bool NOT NULL DEFAULT true,
  "rate_limit_per_min" int4 NOT NULL DEFAULT 60,
  "status" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'active'::character varying,
  "expires_at" timestamp(6),
  "last_used_at" timestamp(6),
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_ai_calibration
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_ai_calibration";
CREATE TABLE "public"."qd_ai_calibration" (
  "id" int4 NOT NULL DEFAULT nextval('qd_ai_calibration_id_seq'::regclass),
  "market" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "buy_threshold" numeric(10,4) NOT NULL,
  "sell_threshold" numeric(10,4) NOT NULL,
  "min_consensus_abs_override" numeric(10,4) NOT NULL,
  "quality_hold_threshold" numeric(10,4) NOT NULL,
  "validated_at" timestamp(6) DEFAULT now(),
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_analysis_memory
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_analysis_memory";
CREATE TABLE "public"."qd_analysis_memory" (
  "id" int4 NOT NULL DEFAULT nextval('qd_analysis_memory_id_seq'::regclass),
  "user_id" int4,
  "market" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "symbol" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "decision" varchar(10) COLLATE "pg_catalog"."default" NOT NULL,
  "confidence" int4 DEFAULT 50,
  "price_at_analysis" numeric(24,8),
  "summary" text COLLATE "pg_catalog"."default",
  "reasons" jsonb,
  "scores" jsonb,
  "indicators_snapshot" jsonb,
  "raw_result" jsonb,
  "consensus_score" numeric(24,8),
  "consensus_abs" numeric(24,8),
  "agreement_ratio" numeric(10,6),
  "quality_multiplier" numeric(10,6),
  "created_at" timestamp(6) DEFAULT now(),
  "validated_at" timestamp(6),
  "actual_outcome" varchar(20) COLLATE "pg_catalog"."default",
  "actual_return_pct" numeric(10,4),
  "was_correct" bool,
  "user_feedback" varchar(20) COLLATE "pg_catalog"."default",
  "feedback_at" timestamp(6),
  "task_status" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'completed'::character varying,
  "task_error" text COLLATE "pg_catalog"."default",
  "updated_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_analysis_tasks
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_analysis_tasks";
CREATE TABLE "public"."qd_analysis_tasks" (
  "id" int4 NOT NULL DEFAULT nextval('qd_analysis_tasks_id_seq'::regclass),
  "user_id" int4 DEFAULT 1,
  "market" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "symbol" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "model" varchar(100) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "language" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'en-US'::character varying,
  "status" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'completed'::character varying,
  "result_json" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "error_message" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "created_at" timestamp(6) DEFAULT now(),
  "completed_at" timestamp(6)
)
;

-- ----------------------------
-- Table structure for qd_backtest_equity_points
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_backtest_equity_points";
CREATE TABLE "public"."qd_backtest_equity_points" (
  "id" int4 NOT NULL DEFAULT nextval('qd_backtest_equity_points_id_seq'::regclass),
  "run_id" int4 NOT NULL,
  "point_index" int4 DEFAULT 0,
  "point_time" varchar(64) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "point_value" float8 DEFAULT 0,
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_backtest_runs
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_backtest_runs";
CREATE TABLE "public"."qd_backtest_runs" (
  "id" int4 NOT NULL DEFAULT nextval('qd_backtest_runs_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "indicator_id" int4,
  "strategy_id" int4,
  "strategy_name" varchar(255) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "run_type" varchar(50) COLLATE "pg_catalog"."default" DEFAULT 'indicator'::character varying,
  "market" varchar(50) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "symbol" varchar(50) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "timeframe" varchar(10) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "start_date" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "end_date" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "initial_capital" numeric(20,8) DEFAULT 10000,
  "commission" numeric(10,6) DEFAULT 0.001,
  "slippage" numeric(10,6) DEFAULT 0,
  "leverage" int4 DEFAULT 1,
  "trade_direction" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'long'::character varying,
  "strategy_config" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "config_snapshot" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "engine_version" varchar(50) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "code_hash" varchar(128) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "status" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'success'::character varying,
  "error_message" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "result_json" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_backtest_trades
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_backtest_trades";
CREATE TABLE "public"."qd_backtest_trades" (
  "id" int4 NOT NULL DEFAULT nextval('qd_backtest_trades_id_seq'::regclass),
  "run_id" int4 NOT NULL,
  "user_id" int4 NOT NULL DEFAULT 1,
  "strategy_id" int4,
  "trade_index" int4 DEFAULT 0,
  "trade_time" varchar(64) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "trade_type" varchar(64) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "side" varchar(32) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "price" float8 DEFAULT 0,
  "amount" float8 DEFAULT 0,
  "profit" float8 DEFAULT 0,
  "balance" float8 DEFAULT 0,
  "reason" varchar(64) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "payload_json" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_credits_log
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_credits_log";
CREATE TABLE "public"."qd_credits_log" (
  "id" int4 NOT NULL DEFAULT nextval('qd_credits_log_id_seq'::regclass),
  "user_id" int4 NOT NULL,
  "action" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "amount" numeric(20,2) NOT NULL,
  "balance_after" numeric(20,2) NOT NULL,
  "feature" varchar(50) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "reference_id" varchar(100) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "remark" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "operator_id" int4,
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_exchange_credentials
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_exchange_credentials";
CREATE TABLE "public"."qd_exchange_credentials" (
  "id" int4 NOT NULL DEFAULT nextval('qd_exchange_credentials_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "name" varchar(100) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "exchange_id" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "api_key_hint" varchar(50) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "encrypted_config" text COLLATE "pg_catalog"."default" NOT NULL,
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_indicator_codes
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_indicator_codes";
CREATE TABLE "public"."qd_indicator_codes" (
  "id" int4 NOT NULL DEFAULT nextval('qd_indicator_codes_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "is_buy" int4 NOT NULL DEFAULT 0,
  "end_time" int8 NOT NULL DEFAULT 1,
  "name" varchar(255) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "code" text COLLATE "pg_catalog"."default",
  "description" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "publish_to_community" int4 NOT NULL DEFAULT 0,
  "pricing_type" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'free'::character varying,
  "price" numeric(10,2) NOT NULL DEFAULT 0,
  "is_encrypted" int4 NOT NULL DEFAULT 0,
  "preview_image" varchar(500) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "vip_free" bool DEFAULT false,
  "createtime" int8,
  "updatetime" int8,
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now(),
  "purchase_count" int4 DEFAULT 0,
  "avg_rating" numeric(3,2) DEFAULT 0,
  "rating_count" int4 DEFAULT 0,
  "view_count" int4 DEFAULT 0,
  "review_status" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'approved'::character varying,
  "review_note" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "reviewed_at" timestamp(6),
  "reviewed_by" int4,
  "source_indicator_id" int4,
  "source_language" varchar(16) COLLATE "pg_catalog"."default",
  "name_i18n" jsonb,
  "description_i18n" jsonb
)
;

-- ----------------------------
-- Table structure for qd_indicator_comments
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_indicator_comments";
CREATE TABLE "public"."qd_indicator_comments" (
  "id" int4 NOT NULL DEFAULT nextval('qd_indicator_comments_id_seq'::regclass),
  "indicator_id" int4 NOT NULL,
  "user_id" int4 NOT NULL,
  "rating" int4 DEFAULT 5,
  "content" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "parent_id" int4,
  "is_deleted" int4 DEFAULT 0,
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_indicator_purchases
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_indicator_purchases";
CREATE TABLE "public"."qd_indicator_purchases" (
  "id" int4 NOT NULL DEFAULT nextval('qd_indicator_purchases_id_seq'::regclass),
  "indicator_id" int4 NOT NULL,
  "buyer_id" int4 NOT NULL,
  "seller_id" int4 NOT NULL,
  "price" numeric(10,2) NOT NULL DEFAULT 0,
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_login_attempts
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_login_attempts";
CREATE TABLE "public"."qd_login_attempts" (
  "id" int4 NOT NULL DEFAULT nextval('qd_login_attempts_id_seq'::regclass),
  "identifier" varchar(100) COLLATE "pg_catalog"."default" NOT NULL,
  "identifier_type" varchar(10) COLLATE "pg_catalog"."default" NOT NULL,
  "attempt_time" timestamp(6) DEFAULT now(),
  "success" bool DEFAULT false,
  "ip_address" varchar(45) COLLATE "pg_catalog"."default",
  "user_agent" text COLLATE "pg_catalog"."default"
)
;

-- ----------------------------
-- Table structure for qd_manual_positions
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_manual_positions";
CREATE TABLE "public"."qd_manual_positions" (
  "id" int4 NOT NULL DEFAULT nextval('qd_manual_positions_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "market" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "symbol" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "name" varchar(100) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "side" varchar(10) COLLATE "pg_catalog"."default" DEFAULT 'long'::character varying,
  "quantity" numeric(20,8) NOT NULL DEFAULT 0,
  "entry_price" numeric(20,8) NOT NULL DEFAULT 0,
  "entry_time" int8,
  "notes" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "tags" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "group_name" varchar(100) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_market_symbols
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_market_symbols";
CREATE TABLE "public"."qd_market_symbols" (
  "id" int4 NOT NULL DEFAULT nextval('qd_market_symbols_id_seq'::regclass),
  "market" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "symbol" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "name" varchar(255) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "exchange" varchar(50) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "currency" varchar(10) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "is_active" int4 DEFAULT 1,
  "is_hot" int4 DEFAULT 0,
  "sort_order" int4 DEFAULT 0,
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_membership_orders
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_membership_orders";
CREATE TABLE "public"."qd_membership_orders" (
  "id" int4 NOT NULL DEFAULT nextval('qd_membership_orders_id_seq'::regclass),
  "user_id" int4 NOT NULL,
  "plan" varchar(20) COLLATE "pg_catalog"."default" NOT NULL,
  "price_usd" numeric(10,2) DEFAULT 0,
  "status" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'paid'::character varying,
  "created_at" timestamp(6) DEFAULT now(),
  "paid_at" timestamp(6)
)
;

-- ----------------------------
-- Table structure for qd_oauth_links
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_oauth_links";
CREATE TABLE "public"."qd_oauth_links" (
  "id" int4 NOT NULL DEFAULT nextval('qd_oauth_links_id_seq'::regclass),
  "user_id" int4,
  "provider" varchar(20) COLLATE "pg_catalog"."default" NOT NULL,
  "provider_user_id" varchar(100) COLLATE "pg_catalog"."default" NOT NULL,
  "provider_email" varchar(100) COLLATE "pg_catalog"."default",
  "provider_name" varchar(100) COLLATE "pg_catalog"."default",
  "provider_avatar" varchar(255) COLLATE "pg_catalog"."default",
  "access_token" text COLLATE "pg_catalog"."default",
  "refresh_token" text COLLATE "pg_catalog"."default",
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_oauth_states
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_oauth_states";
CREATE TABLE "public"."qd_oauth_states" (
  "state" varchar(128) COLLATE "pg_catalog"."default" NOT NULL,
  "provider" varchar(20) COLLATE "pg_catalog"."default" NOT NULL,
  "redirect" text COLLATE "pg_catalog"."default",
  "created_at" timestamp(6) DEFAULT now(),
  "expires_at" timestamp(6) NOT NULL
)
;

-- ----------------------------
-- Table structure for qd_position_alerts
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_position_alerts";
CREATE TABLE "public"."qd_position_alerts" (
  "id" int4 NOT NULL DEFAULT nextval('qd_position_alerts_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "position_id" int4,
  "market" varchar(50) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "symbol" varchar(50) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "alert_type" varchar(30) COLLATE "pg_catalog"."default" NOT NULL,
  "threshold" numeric(20,8) NOT NULL DEFAULT 0,
  "notification_config" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "is_active" int4 DEFAULT 1,
  "is_triggered" int4 DEFAULT 0,
  "last_triggered_at" timestamp(6),
  "trigger_count" int4 DEFAULT 0,
  "repeat_interval" int4 DEFAULT 0,
  "notes" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_position_monitors
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_position_monitors";
CREATE TABLE "public"."qd_position_monitors" (
  "id" int4 NOT NULL DEFAULT nextval('qd_position_monitors_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "name" varchar(100) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "position_ids" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "monitor_type" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'ai'::character varying,
  "config" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "notification_config" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "is_active" int4 DEFAULT 1,
  "last_run_at" timestamp(6),
  "next_run_at" timestamp(6),
  "last_result" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "run_count" int4 DEFAULT 0,
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_quick_trades
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_quick_trades";
CREATE TABLE "public"."qd_quick_trades" (
  "id" int4 NOT NULL DEFAULT nextval('qd_quick_trades_id_seq'::regclass),
  "user_id" int4 NOT NULL,
  "credential_id" int4 DEFAULT 0,
  "exchange_id" varchar(40) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "symbol" varchar(60) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "side" varchar(10) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "order_type" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'market'::character varying,
  "amount" numeric(24,8) DEFAULT 0,
  "price" numeric(24,8) DEFAULT 0,
  "leverage" int4 DEFAULT 1,
  "market_type" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'swap'::character varying,
  "tp_price" numeric(24,8) DEFAULT 0,
  "sl_price" numeric(24,8) DEFAULT 0,
  "status" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'submitted'::character varying,
  "exchange_order_id" varchar(120) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "filled_amount" numeric(24,8) DEFAULT 0,
  "avg_fill_price" numeric(24,8) DEFAULT 0,
  "error_msg" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "source" varchar(40) COLLATE "pg_catalog"."default" DEFAULT 'manual'::character varying,
  "raw_result" jsonb,
  "created_at" timestamp(6) DEFAULT now(),
  "commission" numeric(24,8) DEFAULT 0,
  "commission_ccy" varchar(16) COLLATE "pg_catalog"."default" DEFAULT ''::character varying
)
;

-- ----------------------------
-- Table structure for qd_security_logs
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_security_logs";
CREATE TABLE "public"."qd_security_logs" (
  "id" int4 NOT NULL DEFAULT nextval('qd_security_logs_id_seq'::regclass),
  "user_id" int4,
  "action" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "ip_address" varchar(45) COLLATE "pg_catalog"."default",
  "user_agent" text COLLATE "pg_catalog"."default",
  "details" text COLLATE "pg_catalog"."default",
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_strategies_trading
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_strategies_trading";
CREATE TABLE "public"."qd_strategies_trading" (
  "id" int4 NOT NULL DEFAULT nextval('qd_strategies_trading_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "strategy_name" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "strategy_type" varchar(50) COLLATE "pg_catalog"."default" DEFAULT 'IndicatorStrategy'::character varying,
  "market_category" varchar(50) COLLATE "pg_catalog"."default" DEFAULT 'Crypto'::character varying,
  "execution_mode" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'signal'::character varying,
  "notification_config" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "status" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'stopped'::character varying,
  "symbol" varchar(50) COLLATE "pg_catalog"."default",
  "timeframe" varchar(10) COLLATE "pg_catalog"."default",
  "initial_capital" numeric(20,8) DEFAULT 1000,
  "leverage" int4 DEFAULT 1,
  "market_type" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'swap'::character varying,
  "exchange_config" text COLLATE "pg_catalog"."default",
  "indicator_config" text COLLATE "pg_catalog"."default",
  "trading_config" text COLLATE "pg_catalog"."default",
  "ai_model_config" text COLLATE "pg_catalog"."default",
  "decide_interval" int4 DEFAULT 300,
  "strategy_group_id" varchar(100) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "group_base_name" varchar(255) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "strategy_mode" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'signal'::character varying,
  "strategy_code" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now(),
  "last_rebalance_at" timestamp(6)
)
;
INSERT INTO "public"."qd_strategies_trading" ("id", "user_id", "strategy_name", "strategy_type", "market_category", "execution_mode", "notification_config", "status", "symbol", "timeframe", "initial_capital", "leverage", "market_type", "exchange_config", "indicator_config", "trading_config", "ai_model_config", "decide_interval", "strategy_group_id", "group_base_name", "strategy_mode", "strategy_code", "created_at", "updated_at", "last_rebalance_at") VALUES (14, 1, 'test', 'ScriptStrategy', 'Crypto', 'live', '{"channels": ["browser", "webhook"], "targets": {}}', 'running', 'NOK/USDT', '1m', '10.00000000', 5, 'swap', '{"credential_id": 6, "exchange_id": "okx"}', '{}', '{"symbol": "NOK/USDT", "timeframe": "1m", "market_type": "swap", "leverage": 5, "trade_direction": "long", "initial_capital": 10, "stop_loss_pct": 0, "take_profit_pct": 0, "max_position": 0, "max_daily_loss": 1, "bot_type": "martingale", "bot_params": {"multiplier": 2, "maxLayers": 5, "priceDropPct": 3, "takeProfitPct": 2, "stopLossPct": 12, "direction": "long", "trailingTpEnabled": false, "trailingTpCallbackPct": 0.8, "waterfallProtection": true, "waterfallDropPct": 0.04, "initialAmount": 0.32}, "order_mode": "market", "entry_trigger_mode": "immediate", "script_runtime_state": {"last_closed_bar_ts": "", "params": {"multiplier": 2, "maxLayers": 5, "priceDropPct": 3, "takeProfitPct": 2, "stopLossPct": 12, "direction": "long", "trailingTpEnabled": false, "trailingTpCallbackPct": 0.8, "waterfallProtection": true, "waterfallDropPct": 0.04, "initialAmount": 0.32, "layer": 1, "last_entry_price": 13.29, "total_cost": 0.32, "total_qty": 0.024078254326561327, "last_order_ts": 1780736274, "peak_price": 13.29, "trailing_active": false, "adaptiveBounds": true, "adaptiveLookback": 48, "adaptiveAtrPeriod": 14, "adaptiveAtrMult": 2.0, "adaptiveMinWidthPct": 0.02, "adaptiveMaxShiftPct": 0.08, "adaptiveEdgePct": 0.12, "waterfallWindowBars": 6, "waterfallWindowSec": 300, "waterfallCooldownBars": 12, "waterfallCooldownSec": 900, "waterfallCloseOnTrigger": false, "waterfall_peak_price": 13.32, "waterfall_bar_counter": 1, "waterfall_bar_index": 1, "waterfall_pause": false, "waterfall_peak_reset_ts": 1780736274}}}', '{}', 300, '', '', 'bot', '# ---- Martingale Bot ----

', '2026-06-06 08:57:49.074797', '2026-06-06 08:57:53.429601', NULL);
-- ----------------------------
-- Table structure for qd_strategy_logs
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_strategy_logs";
CREATE TABLE "public"."qd_strategy_logs" (
  "id" int4 NOT NULL DEFAULT nextval('qd_strategy_logs_id_seq'::regclass),
  "strategy_id" int4 NOT NULL,
  "level" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'info'::character varying,
  "message" text COLLATE "pg_catalog"."default" NOT NULL,
  "timestamp" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_strategy_notifications
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_strategy_notifications";
CREATE TABLE "public"."qd_strategy_notifications" (
  "id" int4 NOT NULL DEFAULT nextval('qd_strategy_notifications_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "strategy_id" int4,
  "symbol" varchar(50) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "signal_type" varchar(30) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "channels" varchar(255) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "title" varchar(255) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "message" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "payload_json" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "is_read" int4 DEFAULT 0,
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_strategy_positions
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_strategy_positions";
CREATE TABLE "public"."qd_strategy_positions" (
  "id" int4 NOT NULL DEFAULT nextval('qd_strategy_positions_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "strategy_id" int4,
  "symbol" varchar(50) COLLATE "pg_catalog"."default",
  "side" varchar(10) COLLATE "pg_catalog"."default",
  "size" numeric(20,8),
  "entry_price" numeric(20,8),
  "current_price" numeric(20,8),
  "highest_price" numeric(20,8) DEFAULT 0,
  "lowest_price" numeric(20,8) DEFAULT 0,
  "unrealized_pnl" numeric(20,8) DEFAULT 0,
  "pnl_percent" numeric(10,4) DEFAULT 0,
  "equity" numeric(20,8) DEFAULT 0,
  "updated_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_strategy_trades
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_strategy_trades";
CREATE TABLE "public"."qd_strategy_trades" (
  "id" int4 NOT NULL DEFAULT nextval('qd_strategy_trades_id_seq'::regclass),
  "user_id" int4 NOT NULL DEFAULT 1,
  "strategy_id" int4,
  "symbol" varchar(50) COLLATE "pg_catalog"."default",
  "type" varchar(30) COLLATE "pg_catalog"."default",
  "price" numeric(20,8),
  "amount" numeric(20,8),
  "value" numeric(20,8),
  "commission" numeric(20,8) DEFAULT 0,
  "commission_ccy" varchar(20) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "profit" numeric(20,8) DEFAULT 0,
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_usdt_orders
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_usdt_orders";
CREATE TABLE "public"."qd_usdt_orders" (
  "id" int4 NOT NULL DEFAULT nextval('qd_usdt_orders_id_seq'::regclass),
  "user_id" int4 NOT NULL,
  "plan" varchar(20) COLLATE "pg_catalog"."default" NOT NULL,
  "chain" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'TRC20'::character varying,
  "amount_usdt" numeric(20,8) NOT NULL DEFAULT 0,
  "address_index" int4 NOT NULL DEFAULT 0,
  "address" varchar(120) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "status" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'pending'::character varying,
  "tx_hash" varchar(120) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "paid_at" timestamp(6),
  "confirmed_at" timestamp(6),
  "expires_at" timestamp(6),
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now(),
  "amount_suffix" numeric(20,8) NOT NULL DEFAULT 0,
  "payment_uri" text COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::text,
  "currency" varchar(10) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'USDT'::character varying,
  "matched_via" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'amount_suffix'::character varying
)
;

-- ----------------------------
-- Table structure for qd_users
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_users";
CREATE TABLE "public"."qd_users" (
  "id" int4 NOT NULL DEFAULT nextval('qd_users_id_seq'::regclass),
  "username" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "password_hash" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "email" varchar(100) COLLATE "pg_catalog"."default",
  "nickname" varchar(50) COLLATE "pg_catalog"."default",
  "avatar" varchar(255) COLLATE "pg_catalog"."default" DEFAULT '/avatar2.jpg'::character varying,
  "status" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'active'::character varying,
  "role" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'user'::character varying,
  "credits" numeric(20,2) DEFAULT 0,
  "vip_expires_at" timestamp(6),
  "vip_plan" varchar(20) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "vip_is_lifetime" bool DEFAULT false,
  "vip_monthly_credits_last_grant" timestamp(6),
  "email_verified" bool DEFAULT false,
  "referred_by" int4,
  "notification_settings" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "chart_templates" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "timezone" varchar(64) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "token_version" int4 DEFAULT 1,
  "last_login_at" timestamp(6),
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_verification_codes
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_verification_codes";
CREATE TABLE "public"."qd_verification_codes" (
  "id" int4 NOT NULL DEFAULT nextval('qd_verification_codes_id_seq'::regclass),
  "email" varchar(100) COLLATE "pg_catalog"."default" NOT NULL,
  "code" varchar(10) COLLATE "pg_catalog"."default" NOT NULL,
  "type" varchar(20) COLLATE "pg_catalog"."default" NOT NULL,
  "expires_at" timestamp(6) NOT NULL,
  "used_at" timestamp(6),
  "ip_address" varchar(45) COLLATE "pg_catalog"."default",
  "attempts" int4 DEFAULT 0,
  "last_attempt_at" timestamp(6),
  "created_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Table structure for qd_watchlist
-- ----------------------------
DROP TABLE IF EXISTS "public"."qd_watchlist";
CREATE TABLE "public"."qd_watchlist" (
  "id" int4 NOT NULL DEFAULT nextval('qd_watchlist_id_seq'::regclass),
  "user_id" int4 DEFAULT 1,
  "market" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "symbol" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "name" varchar(100) COLLATE "pg_catalog"."default" DEFAULT ''::character varying,
  "created_at" timestamp(6) DEFAULT now(),
  "updated_at" timestamp(6) DEFAULT now()
)
;

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."pending_orders_id_seq"
OWNED BY "public"."pending_orders"."id";
SELECT setval('"public"."pending_orders_id_seq"', 76, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_agent_audit_id_seq"
OWNED BY "public"."qd_agent_audit"."id";
SELECT setval('"public"."qd_agent_audit_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_agent_jobs_id_seq"
OWNED BY "public"."qd_agent_jobs"."id";
SELECT setval('"public"."qd_agent_jobs_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_agent_paper_orders_id_seq"
OWNED BY "public"."qd_agent_paper_orders"."id";
SELECT setval('"public"."qd_agent_paper_orders_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_agent_tokens_id_seq"
OWNED BY "public"."qd_agent_tokens"."id";
SELECT setval('"public"."qd_agent_tokens_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_ai_calibration_id_seq"
OWNED BY "public"."qd_ai_calibration"."id";
SELECT setval('"public"."qd_ai_calibration_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_analysis_memory_id_seq"
OWNED BY "public"."qd_analysis_memory"."id";
SELECT setval('"public"."qd_analysis_memory_id_seq"', 378, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_analysis_tasks_id_seq"
OWNED BY "public"."qd_analysis_tasks"."id";
SELECT setval('"public"."qd_analysis_tasks_id_seq"', 345, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_backtest_equity_points_id_seq"
OWNED BY "public"."qd_backtest_equity_points"."id";
SELECT setval('"public"."qd_backtest_equity_points_id_seq"', 77720, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_backtest_runs_id_seq"
OWNED BY "public"."qd_backtest_runs"."id";
SELECT setval('"public"."qd_backtest_runs_id_seq"', 245, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_backtest_trades_id_seq"
OWNED BY "public"."qd_backtest_trades"."id";
SELECT setval('"public"."qd_backtest_trades_id_seq"', 13297, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_credits_log_id_seq"
OWNED BY "public"."qd_credits_log"."id";
SELECT setval('"public"."qd_credits_log_id_seq"', 2, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_exchange_credentials_id_seq"
OWNED BY "public"."qd_exchange_credentials"."id";
SELECT setval('"public"."qd_exchange_credentials_id_seq"', 6, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_indicator_codes_id_seq"
OWNED BY "public"."qd_indicator_codes"."id";
SELECT setval('"public"."qd_indicator_codes_id_seq"', 19, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_indicator_comments_id_seq"
OWNED BY "public"."qd_indicator_comments"."id";
SELECT setval('"public"."qd_indicator_comments_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_indicator_purchases_id_seq"
OWNED BY "public"."qd_indicator_purchases"."id";
SELECT setval('"public"."qd_indicator_purchases_id_seq"', 2, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_login_attempts_id_seq"
OWNED BY "public"."qd_login_attempts"."id";
SELECT setval('"public"."qd_login_attempts_id_seq"', 322, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_manual_positions_id_seq"
OWNED BY "public"."qd_manual_positions"."id";
SELECT setval('"public"."qd_manual_positions_id_seq"', 4, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_market_symbols_id_seq"
OWNED BY "public"."qd_market_symbols"."id";
SELECT setval('"public"."qd_market_symbols_id_seq"', 6595, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_membership_orders_id_seq"
OWNED BY "public"."qd_membership_orders"."id";
SELECT setval('"public"."qd_membership_orders_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_oauth_links_id_seq"
OWNED BY "public"."qd_oauth_links"."id";
SELECT setval('"public"."qd_oauth_links_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_position_alerts_id_seq"
OWNED BY "public"."qd_position_alerts"."id";
SELECT setval('"public"."qd_position_alerts_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_position_monitors_id_seq"
OWNED BY "public"."qd_position_monitors"."id";
SELECT setval('"public"."qd_position_monitors_id_seq"', 6, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_quick_trades_id_seq"
OWNED BY "public"."qd_quick_trades"."id";
SELECT setval('"public"."qd_quick_trades_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_security_logs_id_seq"
OWNED BY "public"."qd_security_logs"."id";
SELECT setval('"public"."qd_security_logs_id_seq"', 198, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_strategies_trading_id_seq"
OWNED BY "public"."qd_strategies_trading"."id";
SELECT setval('"public"."qd_strategies_trading_id_seq"', 14, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_strategy_logs_id_seq"
OWNED BY "public"."qd_strategy_logs"."id";
SELECT setval('"public"."qd_strategy_logs_id_seq"', 445, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_strategy_notifications_id_seq"
OWNED BY "public"."qd_strategy_notifications"."id";
SELECT setval('"public"."qd_strategy_notifications_id_seq"', 139, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_strategy_positions_id_seq"
OWNED BY "public"."qd_strategy_positions"."id";
SELECT setval('"public"."qd_strategy_positions_id_seq"', 2087, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_strategy_trades_id_seq"
OWNED BY "public"."qd_strategy_trades"."id";
SELECT setval('"public"."qd_strategy_trades_id_seq"', 41, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_usdt_orders_id_seq"
OWNED BY "public"."qd_usdt_orders"."id";
SELECT setval('"public"."qd_usdt_orders_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_users_id_seq"
OWNED BY "public"."qd_users"."id";
SELECT setval('"public"."qd_users_id_seq"', 5, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_verification_codes_id_seq"
OWNED BY "public"."qd_verification_codes"."id";
SELECT setval('"public"."qd_verification_codes_id_seq"', 2, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."qd_watchlist_id_seq"
OWNED BY "public"."qd_watchlist"."id";
SELECT setval('"public"."qd_watchlist_id_seq"', 118, true);

-- ----------------------------
-- Indexes structure for table pending_orders
-- ----------------------------
CREATE INDEX "idx_pending_orders_status" ON "public"."pending_orders" USING btree (
  "status" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_pending_orders_strategy_id" ON "public"."pending_orders" USING btree (
  "strategy_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_pending_orders_user_id" ON "public"."pending_orders" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table pending_orders
-- ----------------------------
ALTER TABLE "public"."pending_orders" ADD CONSTRAINT "pending_orders_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_agent_audit
-- ----------------------------
CREATE INDEX "idx_agent_audit_class" ON "public"."qd_agent_audit" USING btree (
  "scope_class" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_agent_audit_token" ON "public"."qd_agent_audit" USING btree (
  "agent_token_id" "pg_catalog"."int4_ops" ASC NULLS LAST,
  "created_at" "pg_catalog"."timestamp_ops" DESC NULLS FIRST
);
CREATE INDEX "idx_agent_audit_user" ON "public"."qd_agent_audit" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST,
  "created_at" "pg_catalog"."timestamp_ops" DESC NULLS FIRST
);

-- ----------------------------
-- Primary Key structure for table qd_agent_audit
-- ----------------------------
ALTER TABLE "public"."qd_agent_audit" ADD CONSTRAINT "qd_agent_audit_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_agent_jobs
-- ----------------------------
CREATE UNIQUE INDEX "idx_agent_jobs_idem" ON "public"."qd_agent_jobs" USING btree (
  "agent_token_id" "pg_catalog"."int4_ops" ASC NULLS LAST,
  "kind" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
  "idempotency_key" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
) WHERE idempotency_key IS NOT NULL;
CREATE INDEX "idx_agent_jobs_kind" ON "public"."qd_agent_jobs" USING btree (
  "kind" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_agent_jobs_status" ON "public"."qd_agent_jobs" USING btree (
  "status" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_agent_jobs_user" ON "public"."qd_agent_jobs" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table qd_agent_jobs
-- ----------------------------
ALTER TABLE "public"."qd_agent_jobs" ADD CONSTRAINT "qd_agent_jobs_job_id_key" UNIQUE ("job_id");

-- ----------------------------
-- Primary Key structure for table qd_agent_jobs
-- ----------------------------
ALTER TABLE "public"."qd_agent_jobs" ADD CONSTRAINT "qd_agent_jobs_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_agent_paper_orders
-- ----------------------------
CREATE INDEX "idx_agent_paper_orders_token" ON "public"."qd_agent_paper_orders" USING btree (
  "agent_token_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_agent_paper_orders_user" ON "public"."qd_agent_paper_orders" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST,
  "created_at" "pg_catalog"."timestamp_ops" DESC NULLS FIRST
);

-- ----------------------------
-- Uniques structure for table qd_agent_paper_orders
-- ----------------------------
ALTER TABLE "public"."qd_agent_paper_orders" ADD CONSTRAINT "qd_agent_paper_orders_order_uid_key" UNIQUE ("order_uid");

-- ----------------------------
-- Primary Key structure for table qd_agent_paper_orders
-- ----------------------------
ALTER TABLE "public"."qd_agent_paper_orders" ADD CONSTRAINT "qd_agent_paper_orders_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_agent_tokens
-- ----------------------------
CREATE UNIQUE INDEX "idx_agent_tokens_hash" ON "public"."qd_agent_tokens" USING btree (
  "token_hash" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_agent_tokens_status" ON "public"."qd_agent_tokens" USING btree (
  "status" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_agent_tokens_user" ON "public"."qd_agent_tokens" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_agent_tokens
-- ----------------------------
ALTER TABLE "public"."qd_agent_tokens" ADD CONSTRAINT "qd_agent_tokens_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_ai_calibration
-- ----------------------------
CREATE INDEX "idx_ai_calibration_market_validated_at" ON "public"."qd_ai_calibration" USING btree (
  "market" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
  "validated_at" "pg_catalog"."timestamp_ops" DESC NULLS FIRST
);

-- ----------------------------
-- Primary Key structure for table qd_ai_calibration
-- ----------------------------
ALTER TABLE "public"."qd_ai_calibration" ADD CONSTRAINT "qd_ai_calibration_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_analysis_memory
-- ----------------------------
CREATE INDEX "idx_analysis_memory_created" ON "public"."qd_analysis_memory" USING btree (
  "created_at" "pg_catalog"."timestamp_ops" DESC NULLS FIRST
);
CREATE INDEX "idx_analysis_memory_symbol" ON "public"."qd_analysis_memory" USING btree (
  "market" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
  "symbol" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_analysis_memory_user" ON "public"."qd_analysis_memory" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_analysis_memory_validated" ON "public"."qd_analysis_memory" USING btree (
  "validated_at" "pg_catalog"."timestamp_ops" ASC NULLS LAST
) WHERE validated_at IS NOT NULL;

-- ----------------------------
-- Primary Key structure for table qd_analysis_memory
-- ----------------------------
ALTER TABLE "public"."qd_analysis_memory" ADD CONSTRAINT "qd_analysis_memory_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_analysis_tasks
-- ----------------------------
CREATE INDEX "idx_analysis_tasks_user_id" ON "public"."qd_analysis_tasks" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_analysis_tasks
-- ----------------------------
ALTER TABLE "public"."qd_analysis_tasks" ADD CONSTRAINT "qd_analysis_tasks_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_backtest_equity_points
-- ----------------------------
CREATE INDEX "idx_backtest_equity_points_run_id" ON "public"."qd_backtest_equity_points" USING btree (
  "run_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_backtest_equity_points
-- ----------------------------
ALTER TABLE "public"."qd_backtest_equity_points" ADD CONSTRAINT "qd_backtest_equity_points_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_backtest_runs
-- ----------------------------
CREATE INDEX "idx_backtest_runs_indicator_id" ON "public"."qd_backtest_runs" USING btree (
  "indicator_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_backtest_runs_run_type" ON "public"."qd_backtest_runs" USING btree (
  "run_type" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_backtest_runs_strategy_id" ON "public"."qd_backtest_runs" USING btree (
  "strategy_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_backtest_runs_user_id" ON "public"."qd_backtest_runs" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_backtest_runs
-- ----------------------------
ALTER TABLE "public"."qd_backtest_runs" ADD CONSTRAINT "qd_backtest_runs_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_backtest_trades
-- ----------------------------
CREATE INDEX "idx_backtest_trades_run_id" ON "public"."qd_backtest_trades" USING btree (
  "run_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_backtest_trades
-- ----------------------------
ALTER TABLE "public"."qd_backtest_trades" ADD CONSTRAINT "qd_backtest_trades_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_credits_log
-- ----------------------------
CREATE INDEX "idx_credits_log_action" ON "public"."qd_credits_log" USING btree (
  "action" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_credits_log_created_at" ON "public"."qd_credits_log" USING btree (
  "created_at" "pg_catalog"."timestamp_ops" ASC NULLS LAST
);
CREATE INDEX "idx_credits_log_user_id" ON "public"."qd_credits_log" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_credits_log
-- ----------------------------
ALTER TABLE "public"."qd_credits_log" ADD CONSTRAINT "qd_credits_log_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_exchange_credentials
-- ----------------------------
CREATE INDEX "idx_exchange_credentials_user_id" ON "public"."qd_exchange_credentials" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_exchange_credentials
-- ----------------------------
ALTER TABLE "public"."qd_exchange_credentials" ADD CONSTRAINT "qd_exchange_credentials_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_indicator_codes
-- ----------------------------
CREATE INDEX "idx_indicator_codes_source" ON "public"."qd_indicator_codes" USING btree (
  "source_indicator_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_indicator_codes_user_id" ON "public"."qd_indicator_codes" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_indicator_review_status" ON "public"."qd_indicator_codes" USING btree (
  "review_status" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_indicator_codes
-- ----------------------------
ALTER TABLE "public"."qd_indicator_codes" ADD CONSTRAINT "qd_indicator_codes_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_indicator_comments
-- ----------------------------
CREATE INDEX "idx_comments_indicator" ON "public"."qd_indicator_comments" USING btree (
  "indicator_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_comments_user" ON "public"."qd_indicator_comments" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Checks structure for table qd_indicator_comments
-- ----------------------------
ALTER TABLE "public"."qd_indicator_comments" ADD CONSTRAINT "qd_indicator_comments_rating_check" CHECK (rating >= 1 AND rating <= 5);

-- ----------------------------
-- Primary Key structure for table qd_indicator_comments
-- ----------------------------
ALTER TABLE "public"."qd_indicator_comments" ADD CONSTRAINT "qd_indicator_comments_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_indicator_purchases
-- ----------------------------
CREATE INDEX "idx_purchases_buyer" ON "public"."qd_indicator_purchases" USING btree (
  "buyer_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_purchases_indicator" ON "public"."qd_indicator_purchases" USING btree (
  "indicator_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_purchases_seller" ON "public"."qd_indicator_purchases" USING btree (
  "seller_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table qd_indicator_purchases
-- ----------------------------
ALTER TABLE "public"."qd_indicator_purchases" ADD CONSTRAINT "qd_indicator_purchases_indicator_id_buyer_id_key" UNIQUE ("indicator_id", "buyer_id");

-- ----------------------------
-- Primary Key structure for table qd_indicator_purchases
-- ----------------------------
ALTER TABLE "public"."qd_indicator_purchases" ADD CONSTRAINT "qd_indicator_purchases_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_login_attempts
-- ----------------------------
CREATE INDEX "idx_login_attempts_identifier" ON "public"."qd_login_attempts" USING btree (
  "identifier" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
  "identifier_type" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_login_attempts_time" ON "public"."qd_login_attempts" USING btree (
  "attempt_time" "pg_catalog"."timestamp_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_login_attempts
-- ----------------------------
ALTER TABLE "public"."qd_login_attempts" ADD CONSTRAINT "qd_login_attempts_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_manual_positions
-- ----------------------------
CREATE INDEX "idx_manual_positions_user_id" ON "public"."qd_manual_positions" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table qd_manual_positions
-- ----------------------------
ALTER TABLE "public"."qd_manual_positions" ADD CONSTRAINT "qd_manual_positions_user_id_market_symbol_side_group_name_key" UNIQUE ("user_id", "market", "symbol", "side", "group_name");

-- ----------------------------
-- Primary Key structure for table qd_manual_positions
-- ----------------------------
ALTER TABLE "public"."qd_manual_positions" ADD CONSTRAINT "qd_manual_positions_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_market_symbols
-- ----------------------------
CREATE INDEX "idx_market_symbols_is_hot" ON "public"."qd_market_symbols" USING btree (
  "market" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
  "is_hot" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_market_symbols_market" ON "public"."qd_market_symbols" USING btree (
  "market" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table qd_market_symbols
-- ----------------------------
ALTER TABLE "public"."qd_market_symbols" ADD CONSTRAINT "qd_market_symbols_market_symbol_key" UNIQUE ("market", "symbol");

-- ----------------------------
-- Primary Key structure for table qd_market_symbols
-- ----------------------------
ALTER TABLE "public"."qd_market_symbols" ADD CONSTRAINT "qd_market_symbols_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_membership_orders
-- ----------------------------
CREATE INDEX "idx_membership_orders_user_id" ON "public"."qd_membership_orders" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_membership_orders
-- ----------------------------
ALTER TABLE "public"."qd_membership_orders" ADD CONSTRAINT "qd_membership_orders_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_oauth_links
-- ----------------------------
CREATE INDEX "idx_oauth_links_provider" ON "public"."qd_oauth_links" USING btree (
  "provider" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_oauth_links_user_id" ON "public"."qd_oauth_links" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table qd_oauth_links
-- ----------------------------
ALTER TABLE "public"."qd_oauth_links" ADD CONSTRAINT "qd_oauth_links_provider_provider_user_id_key" UNIQUE ("provider", "provider_user_id");

-- ----------------------------
-- Primary Key structure for table qd_oauth_links
-- ----------------------------
ALTER TABLE "public"."qd_oauth_links" ADD CONSTRAINT "qd_oauth_links_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_oauth_states
-- ----------------------------
CREATE INDEX "idx_oauth_states_expires" ON "public"."qd_oauth_states" USING btree (
  "expires_at" "pg_catalog"."timestamp_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_oauth_states
-- ----------------------------
ALTER TABLE "public"."qd_oauth_states" ADD CONSTRAINT "qd_oauth_states_pkey" PRIMARY KEY ("state");

-- ----------------------------
-- Indexes structure for table qd_position_alerts
-- ----------------------------
CREATE INDEX "idx_position_alerts_position_id" ON "public"."qd_position_alerts" USING btree (
  "position_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_position_alerts_user_id" ON "public"."qd_position_alerts" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_position_alerts
-- ----------------------------
ALTER TABLE "public"."qd_position_alerts" ADD CONSTRAINT "qd_position_alerts_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_position_monitors
-- ----------------------------
CREATE INDEX "idx_position_monitors_user_id" ON "public"."qd_position_monitors" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_position_monitors
-- ----------------------------
ALTER TABLE "public"."qd_position_monitors" ADD CONSTRAINT "qd_position_monitors_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_quick_trades
-- ----------------------------
CREATE INDEX "idx_quick_trades_created" ON "public"."qd_quick_trades" USING btree (
  "created_at" "pg_catalog"."timestamp_ops" DESC NULLS FIRST
);
CREATE INDEX "idx_quick_trades_user" ON "public"."qd_quick_trades" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_quick_trades
-- ----------------------------
ALTER TABLE "public"."qd_quick_trades" ADD CONSTRAINT "qd_quick_trades_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_security_logs
-- ----------------------------
CREATE INDEX "idx_security_logs_action" ON "public"."qd_security_logs" USING btree (
  "action" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_security_logs_created_at" ON "public"."qd_security_logs" USING btree (
  "created_at" "pg_catalog"."timestamp_ops" ASC NULLS LAST
);
CREATE INDEX "idx_security_logs_user_id" ON "public"."qd_security_logs" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_security_logs
-- ----------------------------
ALTER TABLE "public"."qd_security_logs" ADD CONSTRAINT "qd_security_logs_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_strategies_trading
-- ----------------------------
CREATE INDEX "idx_strategies_group_id" ON "public"."qd_strategies_trading" USING btree (
  "strategy_group_id" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_strategies_status" ON "public"."qd_strategies_trading" USING btree (
  "status" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_strategies_user_id" ON "public"."qd_strategies_trading" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_strategies_trading
-- ----------------------------
ALTER TABLE "public"."qd_strategies_trading" ADD CONSTRAINT "qd_strategies_trading_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_strategy_logs
-- ----------------------------
CREATE INDEX "idx_strategy_logs_strategy_id" ON "public"."qd_strategy_logs" USING btree (
  "strategy_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_strategy_logs_timestamp" ON "public"."qd_strategy_logs" USING btree (
  "timestamp" "pg_catalog"."timestamp_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_strategy_logs
-- ----------------------------
ALTER TABLE "public"."qd_strategy_logs" ADD CONSTRAINT "qd_strategy_logs_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_strategy_notifications
-- ----------------------------
CREATE INDEX "idx_notifications_is_read" ON "public"."qd_strategy_notifications" USING btree (
  "is_read" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_notifications_strategy_id" ON "public"."qd_strategy_notifications" USING btree (
  "strategy_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_notifications_user_id" ON "public"."qd_strategy_notifications" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_strategy_notifications
-- ----------------------------
ALTER TABLE "public"."qd_strategy_notifications" ADD CONSTRAINT "qd_strategy_notifications_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_strategy_positions
-- ----------------------------
CREATE INDEX "idx_positions_strategy_id" ON "public"."qd_strategy_positions" USING btree (
  "strategy_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_positions_user_id" ON "public"."qd_strategy_positions" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table qd_strategy_positions
-- ----------------------------
ALTER TABLE "public"."qd_strategy_positions" ADD CONSTRAINT "qd_strategy_positions_strategy_id_symbol_side_key" UNIQUE ("strategy_id", "symbol", "side");

-- ----------------------------
-- Primary Key structure for table qd_strategy_positions
-- ----------------------------
ALTER TABLE "public"."qd_strategy_positions" ADD CONSTRAINT "qd_strategy_positions_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_strategy_trades
-- ----------------------------
CREATE INDEX "idx_trades_created_at" ON "public"."qd_strategy_trades" USING btree (
  "created_at" "pg_catalog"."timestamp_ops" ASC NULLS LAST
);
CREATE INDEX "idx_trades_strategy_id" ON "public"."qd_strategy_trades" USING btree (
  "strategy_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "idx_trades_user_id" ON "public"."qd_strategy_trades" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_strategy_trades
-- ----------------------------
ALTER TABLE "public"."qd_strategy_trades" ADD CONSTRAINT "qd_strategy_trades_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_usdt_orders
-- ----------------------------
CREATE UNIQUE INDEX "idx_usdt_orders_amount_active" ON "public"."qd_usdt_orders" USING btree (
  "chain" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST,
  "amount_usdt" "pg_catalog"."numeric_ops" ASC NULLS LAST
) WHERE status::text = ANY (ARRAY['pending'::character varying::text, 'paid'::character varying::text]);
CREATE INDEX "idx_usdt_orders_status" ON "public"."qd_usdt_orders" USING btree (
  "status" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_usdt_orders_user_id" ON "public"."qd_usdt_orders" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_usdt_orders
-- ----------------------------
ALTER TABLE "public"."qd_usdt_orders" ADD CONSTRAINT "qd_usdt_orders_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_users
-- ----------------------------
CREATE INDEX "idx_users_referred_by" ON "public"."qd_users" USING btree (
  "referred_by" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table qd_users
-- ----------------------------
ALTER TABLE "public"."qd_users" ADD CONSTRAINT "qd_users_username_key" UNIQUE ("username");
ALTER TABLE "public"."qd_users" ADD CONSTRAINT "qd_users_email_key" UNIQUE ("email");

-- ----------------------------
-- Primary Key structure for table qd_users
-- ----------------------------
ALTER TABLE "public"."qd_users" ADD CONSTRAINT "qd_users_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_verification_codes
-- ----------------------------
CREATE INDEX "idx_verification_codes_email" ON "public"."qd_verification_codes" USING btree (
  "email" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_verification_codes_expires" ON "public"."qd_verification_codes" USING btree (
  "expires_at" "pg_catalog"."timestamp_ops" ASC NULLS LAST
);
CREATE INDEX "idx_verification_codes_type" ON "public"."qd_verification_codes" USING btree (
  "type" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table qd_verification_codes
-- ----------------------------
ALTER TABLE "public"."qd_verification_codes" ADD CONSTRAINT "qd_verification_codes_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table qd_watchlist
-- ----------------------------
CREATE INDEX "idx_watchlist_user_id" ON "public"."qd_watchlist" USING btree (
  "user_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table qd_watchlist
-- ----------------------------
ALTER TABLE "public"."qd_watchlist" ADD CONSTRAINT "qd_watchlist_user_id_market_symbol_key" UNIQUE ("user_id", "market", "symbol");

-- ----------------------------
-- Primary Key structure for table qd_watchlist
-- ----------------------------
ALTER TABLE "public"."qd_watchlist" ADD CONSTRAINT "qd_watchlist_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Foreign Keys structure for table pending_orders
-- ----------------------------
ALTER TABLE "public"."pending_orders" ADD CONSTRAINT "pending_orders_strategy_id_fkey" FOREIGN KEY ("strategy_id") REFERENCES "public"."qd_strategies_trading" ("id") ON DELETE SET NULL ON UPDATE NO ACTION;
ALTER TABLE "public"."pending_orders" ADD CONSTRAINT "pending_orders_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_agent_jobs
-- ----------------------------
ALTER TABLE "public"."qd_agent_jobs" ADD CONSTRAINT "qd_agent_jobs_agent_token_id_fkey" FOREIGN KEY ("agent_token_id") REFERENCES "public"."qd_agent_tokens" ("id") ON DELETE SET NULL ON UPDATE NO ACTION;
ALTER TABLE "public"."qd_agent_jobs" ADD CONSTRAINT "qd_agent_jobs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_agent_paper_orders
-- ----------------------------
ALTER TABLE "public"."qd_agent_paper_orders" ADD CONSTRAINT "qd_agent_paper_orders_agent_token_id_fkey" FOREIGN KEY ("agent_token_id") REFERENCES "public"."qd_agent_tokens" ("id") ON DELETE SET NULL ON UPDATE NO ACTION;
ALTER TABLE "public"."qd_agent_paper_orders" ADD CONSTRAINT "qd_agent_paper_orders_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_agent_tokens
-- ----------------------------
ALTER TABLE "public"."qd_agent_tokens" ADD CONSTRAINT "qd_agent_tokens_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_analysis_tasks
-- ----------------------------
ALTER TABLE "public"."qd_analysis_tasks" ADD CONSTRAINT "qd_analysis_tasks_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_backtest_runs
-- ----------------------------
ALTER TABLE "public"."qd_backtest_runs" ADD CONSTRAINT "qd_backtest_runs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_backtest_trades
-- ----------------------------
ALTER TABLE "public"."qd_backtest_trades" ADD CONSTRAINT "qd_backtest_trades_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_credits_log
-- ----------------------------
ALTER TABLE "public"."qd_credits_log" ADD CONSTRAINT "qd_credits_log_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_exchange_credentials
-- ----------------------------
ALTER TABLE "public"."qd_exchange_credentials" ADD CONSTRAINT "qd_exchange_credentials_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_indicator_codes
-- ----------------------------
ALTER TABLE "public"."qd_indicator_codes" ADD CONSTRAINT "qd_indicator_codes_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_indicator_comments
-- ----------------------------
ALTER TABLE "public"."qd_indicator_comments" ADD CONSTRAINT "qd_indicator_comments_indicator_id_fkey" FOREIGN KEY ("indicator_id") REFERENCES "public"."qd_indicator_codes" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;
ALTER TABLE "public"."qd_indicator_comments" ADD CONSTRAINT "qd_indicator_comments_parent_id_fkey" FOREIGN KEY ("parent_id") REFERENCES "public"."qd_indicator_comments" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;
ALTER TABLE "public"."qd_indicator_comments" ADD CONSTRAINT "qd_indicator_comments_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_indicator_purchases
-- ----------------------------
ALTER TABLE "public"."qd_indicator_purchases" ADD CONSTRAINT "qd_indicator_purchases_buyer_id_fkey" FOREIGN KEY ("buyer_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;
ALTER TABLE "public"."qd_indicator_purchases" ADD CONSTRAINT "qd_indicator_purchases_indicator_id_fkey" FOREIGN KEY ("indicator_id") REFERENCES "public"."qd_indicator_codes" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;
ALTER TABLE "public"."qd_indicator_purchases" ADD CONSTRAINT "qd_indicator_purchases_seller_id_fkey" FOREIGN KEY ("seller_id") REFERENCES "public"."qd_users" ("id") ON DELETE NO ACTION ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_manual_positions
-- ----------------------------
ALTER TABLE "public"."qd_manual_positions" ADD CONSTRAINT "qd_manual_positions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_membership_orders
-- ----------------------------
ALTER TABLE "public"."qd_membership_orders" ADD CONSTRAINT "qd_membership_orders_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_oauth_links
-- ----------------------------
ALTER TABLE "public"."qd_oauth_links" ADD CONSTRAINT "qd_oauth_links_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_position_alerts
-- ----------------------------
ALTER TABLE "public"."qd_position_alerts" ADD CONSTRAINT "qd_position_alerts_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_position_monitors
-- ----------------------------
ALTER TABLE "public"."qd_position_monitors" ADD CONSTRAINT "qd_position_monitors_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_quick_trades
-- ----------------------------
ALTER TABLE "public"."qd_quick_trades" ADD CONSTRAINT "qd_quick_trades_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_strategies_trading
-- ----------------------------
ALTER TABLE "public"."qd_strategies_trading" ADD CONSTRAINT "qd_strategies_trading_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_strategy_logs
-- ----------------------------
ALTER TABLE "public"."qd_strategy_logs" ADD CONSTRAINT "qd_strategy_logs_strategy_id_fkey" FOREIGN KEY ("strategy_id") REFERENCES "public"."qd_strategies_trading" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_strategy_notifications
-- ----------------------------
ALTER TABLE "public"."qd_strategy_notifications" ADD CONSTRAINT "qd_strategy_notifications_strategy_id_fkey" FOREIGN KEY ("strategy_id") REFERENCES "public"."qd_strategies_trading" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;
ALTER TABLE "public"."qd_strategy_notifications" ADD CONSTRAINT "qd_strategy_notifications_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_strategy_positions
-- ----------------------------
ALTER TABLE "public"."qd_strategy_positions" ADD CONSTRAINT "qd_strategy_positions_strategy_id_fkey" FOREIGN KEY ("strategy_id") REFERENCES "public"."qd_strategies_trading" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;
ALTER TABLE "public"."qd_strategy_positions" ADD CONSTRAINT "qd_strategy_positions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_strategy_trades
-- ----------------------------
ALTER TABLE "public"."qd_strategy_trades" ADD CONSTRAINT "qd_strategy_trades_strategy_id_fkey" FOREIGN KEY ("strategy_id") REFERENCES "public"."qd_strategies_trading" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;
ALTER TABLE "public"."qd_strategy_trades" ADD CONSTRAINT "qd_strategy_trades_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_usdt_orders
-- ----------------------------
ALTER TABLE "public"."qd_usdt_orders" ADD CONSTRAINT "qd_usdt_orders_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- ----------------------------
-- Foreign Keys structure for table qd_watchlist
-- ----------------------------
ALTER TABLE "public"."qd_watchlist" ADD CONSTRAINT "qd_watchlist_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."qd_users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;
