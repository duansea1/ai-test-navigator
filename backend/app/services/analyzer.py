from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from app.models.schemas import AnalysisReport, CodeEvidence, ImplementationStatus, ImpactScope, Priority, RequirementAssessment, RequirementItem, RiskLevel, TestCase, Verdict


class NavigatorAnalyzer:
    """Deterministic analyzer with a focused endpoint-review mode."""

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def analyze(self, requirement_file: Path, projects: list[str], branch: str = "integration") -> AnalysisReport:
        text = requirement_file.read_text(encoding="utf-8")
        requirements = self.parse_requirements(text, requirement_file)
        evidence: list[CodeEvidence] = []
        impacts: list[ImpactScope] = []
        cases: list[TestCase] = []
        assessments: list[RequirementAssessment] = []
        commit_info = {project: self.git_info(project, branch) for project in projects}
        for req in requirements:
            req_evidence = self.find_evidence(req, projects)
            evidence.extend(req_evidence)
            impacts.extend(self.make_impacts(req, req_evidence))
            req_cases = self.make_test_cases(req)
            cases.extend(req_cases)
            assessments.append(self.assess(req, req_evidence, req_cases))
        notes = ["已按需求类型选择分析策略：接口 URL 使用 endpoint 精确定位，普通文本使用关键词索引。"]
        return AnalysisReport(report_id=f"RPT-{uuid4().hex[:10]}", requirement_source=str(requirement_file), projects=projects, branch=branch, commit_info=commit_info, requirements=requirements, evidence=evidence, impacts=impacts, test_cases=cases, assessments=assessments, notes=notes)

    def parse_requirements(self, text: str, source: Path) -> list[RequirementItem]:
        urls = re.findall(r"https?://[^\s]+", text)
        if urls:
            url = urls[0].rstrip("，。.,)")
            parsed = urlparse(url)
            endpoint = parsed.path.rstrip("/") or "/"
            return [RequirementItem(id="REQ-001", title=f"接口逻辑审查：{endpoint}", description=text.strip(), priority=Priority.P1, acceptance_criteria=["定位接口 Controller/Facade 和请求 DTO", "追踪 Service/Business/Mapper/外部调用链", "检查参数校验、状态流转、事务、幂等和权限", "输出问题、证据和建议测试"], source=str(source))]
        headings = re.findall(r"^#{1,3}\s+(.+)$", text, re.MULTILINE)
        bullets = [x.strip() for x in re.findall(r"^[-*]\s+(.+)$", text, re.MULTILINE)]
        candidates = bullets if bullets else headings
        if not candidates:
            candidates = [line.strip() for line in text.splitlines() if line.strip()][:8]
        items = []
        for index, title in enumerate(candidates[:30], 1):
            if len(title) >= 4:
                items.append(RequirementItem(id=f"REQ-{index:03d}", title=title[:120], description=title[:500], priority=Priority.P1 if index <= 3 else Priority.P2, acceptance_criteria=[f"验证：{title[:100]}", "验证异常输入和边界条件", "验证相关数据和调用链一致"], source=str(source)))
        return items or [RequirementItem(id="REQ-001", title="需求文档未提取到结构化条目", description=text[:500], priority=Priority.P1)]

    def find_evidence(self, req: RequirementItem, projects: list[str]) -> list[CodeEvidence]:
        endpoint = re.search(r"接口逻辑审查：([^\s]+)", req.title)
        if endpoint:
            token = endpoint.group(1).split("/")[-1].lower()
            return self.find_endpoint_evidence(token, projects)
        terms = set(re.findall(r"[A-Za-z][A-Za-z0-9_/-]{3,}|[\u4e00-\u9fff]{2,}", req.title + " " + req.description))
        keywords = {x.lower() for x in terms if len(x) >= 4 and x.lower() not in {"https", "http", "payful"}}
        return self.scan_keywords(keywords, projects, 30)

    def find_endpoint_evidence(self, token: str, projects: list[str]) -> list[CodeEvidence]:
        results: list[CodeEvidence] = []
        for project in projects:
            root = self.workspace / project
            if not root.exists():
                continue
            for path in list(root.rglob("*.java")) + list(root.rglob("*.vue")) + list(root.rglob("*.js")):
                if any(part in {"target", "node_modules", ".git"} for part in path.parts):
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()
                hits = [i for i, line in enumerate(lines, 1) if token in line.lower()]
                if not hits:
                    continue
                line = hits[0]
                symbol = path.stem
                results.append(CodeEvidence(id=f"EV-{len(results)+1:03d}", project=project, path=str(path), line=line, symbol=symbol, evidence=f"精确命中接口方法/路径：{token}", relevance="接口入口或直接业务实现证据"))
                if len(results) >= 30:
                    return results
        return results

    def scan_keywords(self, keywords: set[str], projects: list[str], limit: int) -> list[CodeEvidence]:
        results = []
        for project in projects:
            root = self.workspace / project
            if not root.exists():
                continue
            for path in list(root.rglob("*.java")) + list(root.rglob("*.vue")) + list(root.rglob("*.js")):
                if any(part in {"target", "node_modules", ".git"} for part in path.parts):
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                hits = [k for k in keywords if k in content.lower()]
                if hits:
                    line = next((i for i, value in enumerate(content.splitlines(), 1) if any(k in value.lower() for k in hits)), 1)
                    results.append(CodeEvidence(id=f"EV-{len(results)+1:03d}", project=project, path=str(path), line=line, evidence=f"命中关键词：{', '.join(sorted(hits)[:8])}", relevance="规则索引命中，需结合语义审查确认"))
                if len(results) >= limit:
                    return results
        return results

    def make_impacts(self, req: RequirementItem, evidence: list[CodeEvidence]) -> list[ImpactScope]:
        grouped: dict[str, list[str]] = {}
        for item in evidence:
            grouped.setdefault(item.project, []).append(f"{item.symbol or Path(item.path).stem} ({item.path}:{item.line})")
        return [ImpactScope(id=f"IMP-{req.id[4:]}-{i:02d}", requirement_id=req.id, area=project, affected_items=paths[:12], risk_level=RiskLevel.HIGH if len(paths) > 4 else RiskLevel.MEDIUM, rationale="基于接口精确命中结果，建议继续追踪调用链、数据写入和权限。") for i, (project, paths) in enumerate(grouped.items(), 1)]

    def make_test_cases(self, req: RequirementItem) -> list[TestCase]:
        """基于需求本身生成用例，绝不假设具体业务域（如订单/配送）。

        优先用需求自带的验收标准；无则仅生成一条泛化可用性验证，不编造域特定步骤。
        """
        acs = getattr(req, "acceptance_criteria", None) or []
        if acs:
            return [TestCase(
                id=f"TC-{req.id[4:]}-{i:02d}", requirement_id=req.id,
                title=f"{req.title} - 验收点{i}", kind="functional", priority=req.priority,
                preconditions=[f"构造满足验收条件的输入：{ac[:60]}"],
                steps=["准备可控测试数据", "触发该需求对应功能", "记录请求与响应"],
                expected="系统行为符合验收标准") for i, ac in enumerate(acs, 1)]
        return [TestCase(
            id=f"TC-{req.id[4:]}-01", requirement_id=req.id,
            title=f"{req.title} - 基本可用性", kind="functional", priority=req.priority,
            preconditions=["准备合法输入"],
            steps=["触发该需求对应功能", "检查返回与副作用"],
            expected="功能可正常执行且返回符合预期")]

    def assess(self, req: RequirementItem, evidence: list[CodeEvidence], cases: list[TestCase]) -> RequirementAssessment:
        if not evidence:
            return RequirementAssessment(requirement_id=req.id, status=ImplementationStatus.NOT_FOUND, verdict=Verdict.NEEDS_REVIEW, confidence=0.55, summary="未找到接口精确实现证据，请确认项目、分支或网关路由。", gaps=["未找到 endpoint 精确命中"])
        mode = "接口精确定位" if "接口逻辑审查" in req.title else "关键词索引"
        return RequirementAssessment(requirement_id=req.id, status=ImplementationStatus.UNCERTAIN, verdict=Verdict.NEEDS_REVIEW, confidence=0.8 if mode == "接口精确定位" else 0.65, evidence_refs=[e.id for e in evidence], summary=f"通过{mode}找到 {len(evidence)} 条相关证据；当前结论还需要结合方法体、测试执行和数据库证据确认。", gaps=["需要读取完整方法体", "需要执行对应测试用例"])

    def git_info(self, project: str, branch: str) -> str:
        try:
            result = subprocess.run(["git", "-C", str(self.workspace / project), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
            return result.stdout.strip() or "unavailable"
        except (OSError, subprocess.SubprocessError):
            return "unavailable"


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()[:12]
