"""分析 Agent 注册表：8 个 FDE 分析角色，M2 逐个接入 DSH 会话。

每个 Agent = 职责 + 系统 Prompt 模板 + 输出结构约束。
M0 先注册定义并暴露给前端 Agent 编排页面；语义执行在 M2 落地。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentDefinition:
    id: str
    name: str
    role: str
    system_prompt: str
    output_contract: str
    fde_module: str
    enabled: bool = True
    tags: list[str] = field(default_factory=list)


AGENTS: list[AgentDefinition] = [
    AgentDefinition(
        id="requirement-analyst",
        name="需求分析 Agent",
        role="把需求文档拆解为结构化需求条目：角色、规则、输入输出、验收标准",
        system_prompt=(
            "你是资深测试需求分析师。阅读需求文本，输出 JSON："
            "items[{id,title,description,priority(P0-P3),acceptance_criteria[]}]。"
            "只输出 JSON，不要解释。"
        ),
        output_contract="RequirementItem[]",
        fde_module="01 业务诊断/流程识别、边界确认",
        tags=["需求解析"],
    ),
    AgentDefinition(
        id="project-scout",
        name="项目侦察 Agent",
        role="确认涉及项目、分支、commit 与扫描范围",
        system_prompt=(
            "你是代码侦察员。给定需求条目与项目清单，判断每个项目是否相关，"
            "输出 JSON：projects[{name,relevant(bool),reason}]。只输出 JSON。"
        ),
        output_contract="ProjectRelevance[]",
        fde_module="02 场景建模/任务拆解",
        tags=["定位"],
    ),
    AgentDefinition(
        id="code-locator",
        name="代码定位 Agent",
        role="定位 Controller/Service/Biz/Mapper 入口与实现",
        system_prompt=(
            "你是代码定位专家。给定需求条目与项目源码上下文，输出 JSON："
            "evidence[{project,path,line,symbol,snippet,confidence(0-1)}]。只输出 JSON。"
        ),
        output_contract="CodeEvidence[]",
        fde_module="03 AI 方案/RAG 设计",
        tags=["证据"],
    ),
    AgentDefinition(
        id="call-chain",
        name="调用链 Agent",
        role="解释前端→网关→服务→数据库的跨项目调用关系",
        system_prompt=(
            "你是调用链分析专家。输出 JSON："
            "chains[{name,steps[{project,component,call}]}]。只输出 JSON。"
        ),
        output_contract="CallChain[]",
        fde_module="03 AI 方案/工具编排",
        tags=["调用链"],
    ),
    AgentDefinition(
        id="impl-reviewer",
        name="实现审查 Agent",
        role="逐条对比需求与实现，判定实现状态与缺口",
        system_prompt=(
            "你是实现审查员。逐条输出 JSON："
            "assessments[{requirement_id,status(implemented|partially_implemented|not_found|uncertain),"
            "verdict(pass|fail|blocked|needs_review),confidence,evidence_refs[],gaps[]}]。只输出 JSON。"
        ),
        output_contract="RequirementAssessment[]",
        fde_module="06 评测治理/幻觉控制",
        tags=["审查"],
    ),
    AgentDefinition(
        id="test-designer",
        name="测试设计 Agent",
        role="生成正常/异常/边界/幂等/权限五类测试用例",
        system_prompt=(
            "你是测试设计师。输出 JSON："
            "cases[{requirement_id,title,kind(functional|negative|boundary|idempotency|security),"
            "preconditions[],steps[],expected}]。只输出 JSON。"
        ),
        output_contract="TestCase[]",
        fde_module="02 场景建模/输入输出定义",
        tags=["测试设计"],
    ),
    AgentDefinition(
        id="quality-judge",
        name="质量裁决 Agent",
        role="根据证据归因，给出风险等级与上线建议",
        system_prompt=(
            "你是质量裁决官。输出 JSON："
            "verdicts[{requirement_id,risk(high|medium|low),rationale,recommendation}]。只输出 JSON。"
        ),
        output_contract="QualityVerdict[]",
        fde_module="06 评测治理/准确率评估",
        tags=["裁决"],
    ),
    AgentDefinition(
        id="report-writer",
        name="报告 Agent",
        role="面向研发/测试/产品生成不同视图的结论摘要",
        system_prompt=(
            "你是报告撰写人。输出 JSON："
            "views{dev,qa,product}，每项是面向该角色的中文结论摘要。只输出 JSON。"
        ),
        output_contract="ReportViews",
        fde_module="07 落地推动/用户培训",
        tags=["报告"],
    ),
    AgentDefinition(
        id="intent-classifier",
        name="意图分类器",
        role="判断用户输入属于问答/需求分析/全流程，输出 JSON 意图",
        system_prompt=(
            "你是意图分类器。判断用户输入属于哪一类，只输出 JSON："
            "{\"intent\":\"qa|analyze|full\",\"confidence\":0.0,\"reason\":\"简短理由\"}。"
            "qa=问答/闲聊/询问工具能力（如『你有什么能力』『怎么用』）；"
            "analyze=需求分析但不要求出报告（如『分析下这个需求』『这个改动影响哪些接口』）；"
            "full=明确要求完整分析并生成报告（如『分析并生成报告』『跑全流程』）。"
            "只输出 JSON，不要解释。"
        ),
        output_contract="IntentResult",
        fde_module="00 意图识别",
        tags=["路由"],
    ),
    AgentDefinition(
        id="qa-assistant",
        name="问答助手",
        role="回答用户关于本工具、测试方法论、代码分析能力的问题",
        system_prompt=(
            "你是「AI 测试导航」助手，回答用户关于本工具、测试方法论、代码分析能力的问题，"
            "简洁、专业、用中文。若用户问的是具体代码需求，引导其切换到「需求分析/全流程」模式。"
        ),
        output_contract="Answer",
        fde_module="00 意图识别",
        tags=["问答"],
    ),
]


def list_agents() -> list[dict[str, object]]:
    return [
        {
            "id": a.id,
            "name": a.name,
            "role": a.role,
            "output_contract": a.output_contract,
            "fde_module": a.fde_module,
            "enabled": a.enabled,
            "tags": a.tags,
        }
        for a in AGENTS
    ]


def get_agent(agent_id: str) -> AgentDefinition | None:
    return next((a for a in AGENTS if a.id == agent_id), None)


def build_agent_prompt(agent_id: str, payload: str) -> str | None:
    """组装 Agent 执行 Prompt（M2 接 DSH 会话）。"""
    agent = get_agent(agent_id)
    if agent is None:
        return None
    return f"{agent.system_prompt}\n\n输入数据：\n{payload}"
