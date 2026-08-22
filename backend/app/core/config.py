"""集中配置：环境变量 + .env，所有模块从这里读取。"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # backend/app/core/config.py → 项目根


def _load_env_file(path: Path) -> None:
    """极简 .env 解析（KEY=VALUE，# 注释），已存在的环境变量不覆盖。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(PROJECT_ROOT / ".env")


def _dsh_credentials() -> dict[str, str]:
    """解析 DSH 凭据库 ~/.dsh/.credentials.yaml（CredentialRef → 密钥 的简单映射）。"""
    cred_file = Path.home() / ".dsh" / ".credentials.yaml"
    try:
        content = cred_file.read_text(encoding="utf-8")
        return dict(re.findall(r"^([A-Z0-9_]+):\s*(\S+)\s*$", content, re.MULTILINE))
    except OSError:
        return {}


def _dsh_credential_available() -> bool:
    """DSH 凭据库兜底：~/.dsh/.credentials.yaml 存在 DEEPSEEK_API_KEY 时，
    无需在环境变量重复配置（SDK Runtime 未挂载 credentials-local 插件，
    由本平台读取后经子进程环境注入）。"""
    return "DEEPSEEK_API_KEY" in _dsh_credentials()


class Settings:
    def __init__(self) -> None:
        self.project_root = PROJECT_ROOT
        self.workspace = Path(os.getenv("AI_NAVIGATOR_WORKSPACE", r"C:\Akua"))
        self.branch = os.getenv("AI_NAVIGATOR_BRANCH", "integration")
        self.report_dir = PROJECT_ROOT / os.getenv("AI_NAVIGATOR_REPORT_DIR", "reports")
        self.frontend_dist = PROJECT_ROOT / "frontend" / "dist"
        self.frontend_index = PROJECT_ROOT / "frontend" / "index.html"
        # 数据库：MySQL 优先，AI_NAVIGATOR_DB=sqlite:///dev.db 可降级（dev/CI）
        self.database_url = os.getenv(
            "AI_NAVIGATOR_DB",
            os.getenv("DATABASE_URL", "mysql://root:root@127.0.0.1:3306/ai-navigator"),
        )
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "").strip()
        # DSH 源码集成路径（零安装：sys.path 注入源码 src 目录）
        self.dsh_repo = Path(os.getenv("DSH_REPO", r"C:\AppsAi\deepseek-harness"))
        self.dsh_sdk_src = self.dsh_repo / "python" / "sdk" / "src"
        self.dsh_runtime_src = self.dsh_repo / "python" / "sdk-runtime" / "src"
        self.dsh_node_carrier = self.dsh_repo / "python" / "sdk-runtime" / "src" / "deepseek_harness_runtime" / "runtime" / "node"
        # Windows 原生走 node 载体；Linux/macOS 自动解析官方 exe
        self.dsh_mode = os.getenv("DSH_RUNTIME_MODE", "node" if os.name == "nt" else "exe")
        # 满血 Runtime 组合（相对内置 jsonrpc-agent 最小组合）：
        # 原生 subagent/fork + Claude Code 子代理 + workflow + skills + fs 全套
        self.dsh_cordis = PROJECT_ROOT / os.getenv("DSH_CORDIS", "config") / "cordis.yml"
        # 平台 Skills 目录（DSH customSkillDirs，分号分隔）
        self.dsh_skill_dirs = os.getenv("DSH_SKILL_DIRS", str(PROJECT_ROOT / "skills"))
        self.dsh_provider = os.getenv("DSH_PROVIDER", "deepseek-official")
        self.dsh_model = os.getenv("DSH_MODEL", "deepseek-v4-flash")
        self.dsh_session_root = PROJECT_ROOT / ".dsh-sessions"

    @property
    def dsh_source_available(self) -> bool:
        return (self.dsh_sdk_src / "deepseek_harness").exists() and (self.dsh_runtime_src / "deepseek_harness_runtime").exists()

    @property
    def dsh_node_carrier_available(self) -> bool:
        return (self.dsh_node_carrier / "node_modules" / "@deepseek-ai" / "dsh-sdk-jsonrpc-demo" / "lib" / "packaged-bin.js").exists()

    @property
    def dsh_resolved_api_key(self) -> str:
        """实际生效的 API Key：环境变量优先，DSH 凭据库兜底。"""
        if self.deepseek_api_key:
            return self.deepseek_api_key
        return _dsh_credentials().get("DEEPSEEK_API_KEY", "")

    @property
    def dsh_credential_configured(self) -> bool:
        """凭据来源：环境变量/.env 或 DSH 凭据库（~/.dsh/.credentials.yaml）。"""
        return bool(self.dsh_resolved_api_key)

    @property
    def dsh_ready(self) -> bool:
        if not self.dsh_source_available or not self.dsh_credential_configured:
            return False
        return self.dsh_mode != "node" or self.dsh_node_carrier_available


@lru_cache
def get_settings() -> Settings:
    return Settings()
