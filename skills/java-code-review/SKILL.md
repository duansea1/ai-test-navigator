---
name: java-code-review
description: Java 后端实现审查标准：从 Controller 到 Mapper 分层核对需求实现，缺口显式声明。
whenToUse: impl-reviewer 逐条对比需求与 Java 实现时使用（阶段 5）。
---

# Java 实现审查 Skill

目标：每条需求在 Java 代码里找到「实现了/部分实现/没实现」的可复验证据。

规则：
1. 分层核对：Controller 入口（URL/参数/权限注解）→ Service 业务规则 → Biz 编排 → Mapper SQL。
   需求的每条业务规则要么在某一层找到对应代码，要么就是缺口（gap）。
2. status 判定：
   - implemented：所有验收点都有对应代码路径；
   - partially_implemented：主路径有、异常/边界分支缺失；
   - not_found：全层检索无对应实现；
   - uncertain：找到了相似代码但语义不确定（如无法确认某 if 分支就是需求说的锁定逻辑）。
3. evidence_refs 必须指向具体证据（文件:行号 或 REQ 引用）；**fail 结论必须有证据**，无证据只能 needs_review。
4. 「未找到证据」≠「未实现」：not_found 只说明没搜到，不许直接判 fail。
5. 常见缺口模式要主动查：事务边界（@Transactional 缺失）、并发（synchronized/锁）、空指针防御、SQL 注入（拼接 SQL）、硬编码魔法值。
