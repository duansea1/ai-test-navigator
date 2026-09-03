import React from 'react'
import { getJson, postForm, streamSse, postFormSse, delJson, patchForm } from '../api'
import { ModelModal } from '../components/ModelDrawer'
import { toast as showToast } from '../components/ui'

/* ── 类型 ──────────────────────────────────────────────────────────── */
interface TaskItem {
  task_id: string; title: string; source_text?: string; projects: string; branch: string
  status: string; stage: string; progress: number; message: string | null
  report_id: string | null; error: string | null; created_at: string
}
interface ConvItem { conv_id: string; title: string; created_at: string; updated_at: string }
interface ConvMessage {
  role: string; content: string; intent?: string | null; task_id?: string | null
  created_at: string
  /** 模型被调了但失败（404/配额/超时等）——气泡展示错误样式 + 重试入口 */
  model_error?: string | null
}
interface ActItem {
  seq: number; time: string; agent: string; agent_name: string; kind: string
  tool?: string; detail?: string; text?: string; ok?: boolean; summary?: string
  preview?: string; model?: string; provider?: string; stage?: string; progress?: number
}
interface ReqItem { id: string; title: string; description: string; priority: string; acceptance_criteria: string[] }
interface EvidenceItem { project: string; path: string; line_no: number | null; symbol: string; summary: string; relevance: string; req_ref?: string | null }
interface ImpactItem { project: string; area: string; risk_level: string; steps: Array<{ project?: string; component?: string; call?: string }> }
interface TestCaseItem { req_ref: string; case_type: string; title: string; steps: string[]; expected: string }
interface AssessmentItem { req_ref: string; verdict: string; risk: string; confidence: number | null; evidence_refs: string[]; gaps: string[] }
interface AgentSessionItem { agent_id: string; session_id: string; status: string; turns: number; created_at: string }
interface Analysis {
  task: TaskItem; requirements: ReqItem[]; evidence: EvidenceItem[]; impacts: ImpactItem[]
  test_cases: TestCaseItem[]; assessments: AssessmentItem[]
  views: { dev?: string; qa?: string; product?: string }; agent_sessions: AgentSessionItem[]
}
interface ProjectOption { name: string; is_git: boolean; branch: string }
interface RuntimeStatus { ready: boolean; callable?: boolean; provider: string; model: string; mode: string; api_key_configured: boolean; provider_key?: string }
interface ModelOption { id: string; label: string }

const PRIORITY_CLS: Record<string, string> = { P0: 'bad', P1: 'warn', P2: 'neutral', P3: 'neutral' }
const RISK_CLS: Record<string, string> = { high: 'bad', medium: 'warn', low: 'ok' }
const VERDICT_CLS: Record<string, string> = { pass: 'ok', fail: 'bad', blocked: 'bad', needs_review: 'warn' }
const STATUS_CLS: Record<string, string> = { completed: 'ok', failed: 'bad', running: 'warn', pending: 'neutral' }
const MODE_LABEL: Record<string, string> = { auto: '自动识别', qa: '问答', analyze: '需求分析', full: '全流程+报告' }

/** 流程轨道：8 Agent（id → 图标/短名/全名）。 */
const RAIL: Array<{ id: string; icon: string; short: string }> = [
  { id: 'requirement-analyst', icon: '📋', short: '需求' },
  { id: 'project-scout', icon: '🧭', short: '侦察' },
  { id: 'code-locator', icon: '🔍', short: '定位' },
  { id: 'call-chain', icon: '🔗', short: '链路' },
  { id: 'impl-reviewer', icon: '⚖️', short: '审查' },
  { id: 'test-designer', icon: '🧪', short: '用例' },
  { id: 'quality-judge', icon: '🎯', short: '裁决' },
  { id: 'report-writer', icon: '📝', short: '报告' },
]
const AGENT_ICON: Record<string, string> = Object.fromEntries(RAIL.map(r => [r.id, r.icon]))

const TABS = [
  ['requirements', '需求条目'], ['evidence', '代码证据'], ['impacts', '影响范围'],
  ['test_cases', '测试用例'], ['assessments', '裁决结论'], ['views', '报告摘要'], ['agents', 'Agent 会话'],
] as const

/** ISO/空格时间 → 相对时间（修复 created_at 带 T 导致的截断乱码）。 */
function relTime(raw?: string): string {
  if (!raw) return ''
  const d = new Date(raw.replace(' ', 'T'))
  if (isNaN(d.getTime())) return raw
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const hm = d.toTimeString().slice(0, 5)
  if (d >= today) return `今天 ${hm}`
  const yest = new Date(today); yest.setDate(yest.getDate() - 1)
  if (d >= yest) return `昨天 ${hm}`
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${hm}`
}

/** 分析耗时（创建 → 完成）。 */
function fmtDuration(startIso?: string): string {
  if (!startIso) return '-'
  const s = new Date(startIso.replace(' ', 'T')).getTime()
  if (isNaN(s)) return '-'
  const sec = Math.max(1, Math.round((Date.now() - s) / 1000))
  return sec < 90 ? `${sec} 秒` : sec < 5400 ? `${Math.round(sec / 60)} 分钟` : `${(sec / 3600).toFixed(1)} 小时`
}

function fileSize(n: number): string {
  return n < 1024 ? `${n}B` : n < 1048576 ? `${(n / 1024).toFixed(0)}KB` : `${(n / 1048576).toFixed(1)}MB`
}


/* ── 会话时间分组：今天 / 昨天 / 近 7 天 / 更早 ─────────────────────── */
function groupConvs(convs: ConvItem[]): Array<[string, ConvItem[]]> {
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const yest = new Date(today); yest.setDate(yest.getDate() - 1)
  const week = new Date(today); week.setDate(week.getDate() - 7)
  const groups: Array<[string, ConvItem[]]> = [['今天', []], ['昨天', []], ['近 7 天', []], ['更早', []]]
  const byKey: Record<string, ConvItem[]> = Object.fromEntries(groups)
  for (const c of convs) {
    const d = new Date((c.updated_at || '').replace(' ', 'T'))
    if (isNaN(d.getTime())) { byKey['更早'].push(c); continue }
    if (d >= today) byKey['今天'].push(c)
    else if (d >= yest) byKey['昨天'].push(c)
    else if (d >= week) byKey['近 7 天'].push(c)
    else byKey['更早'].push(c)
  }
  return groups.filter(([, items]) => items.length > 0)
}


/* ── 项目选择 chip + 弹层（多选 + 高级选项收进弹层底部） ────────────── */
function ProjectPicker({ options, value, onChange, workspace, branch,
  onWorkspace, onBranch }: {
  options: ProjectOption[]; value: string[]; onChange: (v: string[]) => void
  workspace: string; branch: string
  onWorkspace: (v: string) => void; onBranch: (v: string) => void
}) {
  const [open, setOpen] = React.useState(false)
  const [q, setQ] = React.useState('')
  const [advOpen, setAdvOpen] = React.useState(false)
  const ref = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])
  const kw = q.trim().toLowerCase()
  const filtered = kw ? options.filter(o => o.name.toLowerCase().includes(kw)) : options
  const label = value.length === 0 ? '自动侦察'
    : value.length === 1 ? value[0] : `${value[0]} 等 ${value.length} 个`
  return (
    <div className="cx-pick" ref={ref}>
      <button className={`cx-chip ${value.length ? 'on' : ''}`} onClick={() => setOpen(o => !o)}
        title={value.length ? `已选项目：${value.join('、')}` : '不选则由侦察 Agent 自动判断涉及项目'}>
        🗂 {label} <span className="cx-caret">▾</span>
      </button>
      {open && (
        <div className="pop">
          <input className="pop-search" placeholder="搜索项目名..." value={q}
            onChange={e => setQ(e.target.value)} autoFocus />
          <div className="pop-list">
            {options.length === 0 ? <div className="empty">工作区下未发现项目目录</div> :
              filtered.length === 0 ? <div className="empty">无匹配项目</div> :
                filtered.map(o => (
                  <label key={o.name} className="pop-item">
                    <input type="checkbox" checked={value.includes(o.name)}
                      onChange={() => onChange(value.includes(o.name) ? value.filter(x => x !== o.name) : [...value, o.name])} />
                    <span>{o.name}</span>
                    {o.is_git && o.branch ? <span className="hint">{o.branch}</span> : null}
                  </label>
                ))}
          </div>
          <div className="pop-foot">
            <button className="link" onClick={() => onChange([])}>清空</button>
            <span className="hint">已选 {value.length} / {options.length}</span>
          </div>
          <div className="pop-adv">
            <button className="link" onClick={() => setAdvOpen(o => !o)}>
              {advOpen ? '收起高级选项 ▲' : '工作区 / 分支 ▼'}
            </button>
            {advOpen && (
              <div className="pop-adv-form">
                <div><label>源码工作区</label><input value={workspace} onChange={e => onWorkspace(e.target.value)} /></div>
                <div><label>分支</label><input value={branch} onChange={e => onBranch(e.target.value)} /></div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}


/* ── 模式选择 chip + 弹层（单选） ──────────────────────────────────── */
function ModePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = React.useState(false)
  const ref = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])
  return (
    <div className="cx-pick" ref={ref}>
      <button className={`cx-chip ${value !== 'auto' ? 'on' : ''}`} onClick={() => setOpen(o => !o)}
        title="自动识别：由意图分类 Agent 判断每条输入">
        🎯 {MODE_LABEL[value] ?? value} <span className="cx-caret">▾</span>
      </button>
      {open && (
        <div className="pop">
          {(['auto', 'qa', 'analyze', 'full'] as const).map(m => (
            <div key={m} className={`pop-item sel-row ${value === m ? 'sel' : ''}`}
              onClick={() => { onChange(m); setOpen(false) }}>
              <span>{MODE_LABEL[m]}</span>
              {m === 'auto' ? <span className="hint">模型判断</span> : null}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


/* ── 模型激活条（点击打开模型管理抽屉；圆点反映 DSH 状态） ──────────── */
function ModelBar({ currentModel, onOpen, ok }: {
  currentModel?: string; onOpen: () => void; ok?: boolean
}) {
  return (
    <button className="model-bar" onClick={onOpen}
      title={ok === false ? 'DSH 引擎待验证——点击管理并配置模型' : '点击管理并切换模型'}>
      <span className={`model-dot ${ok === false ? 'warn' : ''}`} />
      <span className="model-name">{currentModel || '选择模型'}</span>
      <span className="model-cfg">⚙</span>
    </button>
  )
}


/* ── 流程轨道（8-Agent 常驻进度） ───────────────────────────────────── */
function Rail({ acts, task }: { acts: ActItem[]; task: TaskItem | null }) {
  // 推导每个 Agent 状态：started/ended(result)/failed
  const state: Record<string, { started: boolean; ok?: boolean; done: boolean }> = {}
  for (const a of acts) {
    if (a.kind === 'agent_start') state[a.agent] = { started: true, done: false }
    else if (a.kind === 'agent_end') state[a.agent] = { started: true, ok: !!a.ok, done: true }
    else if (a.kind === 'result' && state[a.agent]) state[a.agent].ok = a.ok !== false
  }
  const failedTask = task?.status === 'failed'
  // 轨道是否显示：有任务即显示（欢迎页也显示，作为功能导览）
  return (
    <div className="rail">
      {RAIL.map((r, i) => {
        const st = state[r.id]
        let cls = ''
        let mark = r.icon
        if (st?.done && st.ok) { cls = 'done'; mark = '✓' }
        else if (st?.done && st.ok === false) { cls = 'err'; mark = '✗' }
        else if (st?.started) { cls = 'cur'; mark = r.icon }
        // 失败任务：未启动的节点置灰即可（不标红，只标执行中失败的）
        return (
          <div key={r.id} className={`rail-node ${cls}`} title={r.id}>
            <span className="r-icon">{mark}</span>
            <span className="r-label">{r.short}</span>
          </div>
        )
      })}
    </div>
  )
}


/* ── Agent 活动卡片 ─────────────────────────────────────────────────── */
interface AgentGroup {
  agent: string; name: string; start?: ActItem; events: ActItem[]
  end?: ActItem; result?: ActItem; running: boolean
}

function AgentCard({ g }: { g: AgentGroup }) {
  const done = !!g.end
  const ok = g.end?.ok
  const running = g.running && !done
  const err = done && !ok
  const [open, setOpen] = React.useState(true)
  React.useEffect(() => { if (done) setOpen(false) }, [done])
  const icon = AGENT_ICON[g.agent] ?? '🤖'
  return (
    <div className={`agent-card ${running ? 'running' : err ? 'err' : ''}`}>
      <div className="agent-head" onClick={() => setOpen(o => !o)}>
        <span className="a-icon">{icon}</span>
        <span className="a-name">{g.name}</span>
        {g.start?.model ? <span className="a-model">{g.start.model}</span> : null}
        <span className="a-state">
          {running ? <><span className="spinner" /> 执行中（{g.events.length} 步）</> :
            done ? (ok ? `✓ ${g.result?.summary ?? '完成'}` : `✗ ${g.result?.summary ?? g.end?.summary ?? '失败'}`) : '-'}
          <span style={{ fontSize: 11 }}>{open ? '▲' : '▼'}</span>
        </span>
      </div>
      {!open ? null : (
        <div className="agent-body">
          {g.events.length === 0 && !g.end ? <div className="hint" style={{ padding: '4px 0' }}>正在连接模型...</div> : null}
          {g.events.map(ev => (
            <div className="act" key={ev.seq}>
              <span className="t">{ev.time}</span>
              {ev.kind === 'tool' || ev.kind === 'skill' ? (
                <span className="act-tool">
                  <span className="tool-name">{ev.kind === 'skill' ? '◆skill ' : '⚙ '}{ev.tool}</span>
                  {ev.detail ? <span className="tool-args"> {ev.detail}</span> : null}
                </span>
              ) : (
                <span className="act-text">{ev.text}</span>
              )}
            </div>
          ))}
          {g.end?.preview ? <RawOutput text={g.end.preview} /> : null}
          {g.result ? <div className={`act-result ${g.result.ok === false ? 'fail' : ''}`}>▸ {g.result.summary}</div> : null}
        </div>
      )}
    </div>
  )
}

function RawOutput({ text }: { text: string }) {
  const [open, setOpen] = React.useState(false)
  return (
    <div>
      <span className="raw-toggle" onClick={() => setOpen(o => !o)}>{open ? '▾ 收起模型原始输出' : '▸ 模型原始输出'}</span>
      {open ? <div className="raw-out">{text}</div> : null}
    </div>
  )
}


/* ── 结果面板 v2：统计卡 + segmented tabs + 卡片式内容 ──────────────── */
function ResultPanel({ a }: { a: Analysis }) {
  const [tab, setTab] = React.useState<string>('requirements')
  const nReq = a.requirements.length
  const nEv = a.evidence.length
  const nImp = a.impacts.length
  const nTc = a.test_cases.length
  const nAs = a.assessments.length
  const nRisk = a.assessments.filter(s => s.risk === 'high').length
  const nReview = a.assessments.filter(s => ['needs_review', 'blocked'].includes(s.verdict)).length
  return (
    <div className="card" style={{ margin: 0 }}>
      {/* 统计卡行 */}
      <div className="result-head">
        <div className="result-stats">
          <span className="rstat"><b>{nReq}</b><span>需求</span></span>
          <span className="rstat"><b>{nEv}</b><span>证据</span></span>
          <span className="rstat"><b>{nImp}</b><span>链路</span></span>
          <span className="rstat"><b>{nTc}</b><span>用例</span></span>
          <span className="rstat"><b>{nAs}</b><span>裁决</span></span>
          {nRisk > 0 ? <span className="rstat warn"><b>{nRisk}</b><span>高风险</span></span> : null}
          {nReview > 0 ? <span className="rstat warn"><b>{nReview}</b><span>待复核</span></span> : null}
        </div>
        {a.task?.report_id ? <span className="hint">报告 <code>{a.task.report_id}</code></span> : null}
      </div>

      {/* segmented tabs */}
      <div className="seg" style={{ marginBottom: 12 }}>
        {TABS.map(([key, label]) => {
          const n = key === 'views'
            ? (a.views?.dev || a.views?.qa || a.views?.product ? 1 : 0)
            : ((a as any)[key]?.length ?? 0)
          return <button key={key} className={tab === key ? 'on' : ''} onClick={() => setTab(key)}>
            {label}{n ? <span className="n">{n}</span> : null}
          </button>
        })}
      </div>

      {/* 需求卡片 */}
      {tab === 'requirements' && (nReq === 0 ? <div className="empty">无需求条目</div> :
        a.requirements.map(r => (
          <div className="req-card" key={r.id}>
            <div className="rc-head">
              <span className="rc-id">{r.id}</span>
              <span className={`badge ${PRIORITY_CLS[r.priority] ?? 'neutral'}`}>{r.priority}</span>
              <span className="rc-title">{r.title}</span>
            </div>
            {r.description ? <div className="rc-desc">{r.description}</div> : null}
            {(r.acceptance_criteria ?? []).length > 0 ? (
              <div className="rc-ac">{r.acceptance_criteria.map((x, i) => <span key={i}>✓ {x}</span>)}</div>
            ) : null}
          </div>
        ))
      )}

      {/* 证据卡片 */}
      {tab === 'evidence' && (nEv === 0 ? <div className="empty">无代码证据</div> :
        a.evidence.map((ev, i) => (
          <div className="ev-card" key={i}>
            <span className="ev-no">{i + 1}</span>
            <div className="ev-body">
              <div>
                <span className="ev-path">{ev.path}{ev.line_no ? <span className="ln">:{ev.line_no}</span> : null}</span>
                {ev.symbol ? <span className="ev-sym">{ev.symbol}</span> : null}
              </div>
              {ev.summary ? <div className="ev-snip">{String(ev.summary).slice(0, 400)}</div> : null}
              <div className="ev-meta">
                <span>{ev.project}</span>
                {ev.relevance ? <span className={`badge ${RISK_CLS[ev.relevance] ?? 'neutral'}`}>{ev.relevance}</span> : null}
              </div>
            </div>
          </div>
        ))
      )}

      {/* 影响链路 */}
      {tab === 'impacts' && (nImp === 0 ? <div className="empty">无影响链路</div> :
        a.impacts.map((im, i) => (
          <div className="req-card" key={i}>
            <div className="rc-head">
              <span className="rc-title">{im.area}</span>
              <span className={`badge ${RISK_CLS[im.risk_level] ?? 'neutral'}`}>{im.risk_level || '未评估'}</span>
              {im.project ? <span className="hint">{im.project}</span> : null}
            </div>
            {(im.steps ?? []).length > 0 ? (
              <div className="tc-steps" style={{ marginTop: 8 }}>
                {(im.steps ?? []).map((s, j) => (
                  <li key={j}><span className="s-no">{j + 1}.</span>
                    <span>{[s.project, s.component, s.call].filter(Boolean).join(' → ')}</span></li>
                ))}
              </div>
            ) : null}
          </div>
        ))
      )}

      {/* 测试用例卡片 */}
      {tab === 'test_cases' && (nTc === 0 ? <div className="empty">无测试用例</div> :
        a.test_cases.map((c, i) => (
          <div className="tc-card" key={i}>
            <div className="tc-head">
              <span className="tc-no">#{i + 1}</span>
              <span className={`tc-type ${c.case_type || 'functional'}`}>{c.case_type || 'functional'}</span>
              <span className="tc-title">{c.title}</span>
              {c.req_ref ? <code style={{ fontSize: 11, color: '#98a2b3' }}>{c.req_ref}</code> : null}
            </div>
            {(c.steps ?? []).length > 0 ? (
              <ul className="tc-steps">
                {(c.steps ?? []).map((s, j) => <li key={j}><span className="s-no">{j + 1}</span><span>{s}</span></li>)}
              </ul>
            ) : null}
            {c.expected ? <div className="tc-exp"><b>预期</b>{c.expected}</div> : null}
          </div>
        ))
      )}

      {/* 裁决 */}
      {tab === 'assessments' && (nAs === 0 ? <div className="empty">无裁决结论</div> :
        a.assessments.map((s, i) => (
          <div className="req-card" key={i}>
            <div className="rc-head">
              <span className="rc-id">{s.req_ref}</span>
              <span className={`badge ${VERDICT_CLS[s.verdict] ?? 'neutral'}`}>{s.verdict || '-'}</span>
              <span className={`badge ${RISK_CLS[s.risk] ?? 'neutral'}`}>{s.risk || '-'}</span>
              {s.confidence != null ? <span className="hint">置信度 {s.confidence}</span> : null}
            </div>
            {(s.gaps ?? []).length > 0 ? (
              <div className="rc-desc" style={{ margin: '7px 0 0' }}>
                <b style={{ color: '#b54708' }}>缺口：</b>{(s.gaps ?? []).join('；')}
              </div>
            ) : null}
            {(s.evidence_refs ?? []).length > 0 ? (
              <div className="ev-meta" style={{ marginTop: 7 }}>依据：{(s.evidence_refs ?? []).join(' · ')}</div>
            ) : null}
          </div>
        ))
      )}

      {/* 三视角 */}
      {tab === 'views' && (!a.views?.dev && !a.views?.qa && !a.views?.product ? <div className="empty">无报告摘要</div> : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12 }}>
          {[['👨‍💻 研发视角', a.views?.dev], ['🧪 测试视角', a.views?.qa], ['📊 产品视角', a.views?.product]].map(([label, content]) => (
            <div className="view-card" key={label as string}>
              <div className="v-head">{label as string}</div>
              <div className="v-body">{(content as string) ?? '（无）'}</div>
            </div>
          ))}
        </div>
      ))}

      {/* Agent 会话 */}
      {tab === 'agents' && (a.agent_sessions.length === 0 ? <div className="empty">无 Agent 会话</div> : (
        <table>
          <thead><tr><th>Agent</th><th>会话</th><th>状态</th><th>回合</th><th>时间</th></tr></thead>
          <tbody>
            {a.agent_sessions.map((s, i) => (
              <tr key={i}>
                <td>{AGENT_ICON[s.agent_id] ?? ''} <code>{s.agent_id}</code></td>
                <td className="hint"><code style={{ fontSize: 11 }}>{s.session_id?.slice(0, 24)}</code></td>
                <td><span className={`badge ${STATUS_CLS[s.status] ?? 'neutral'}`}>{s.status}</span></td>
                <td>{s.turns}</td>
                <td><span className="rel-time">{relTime(s.created_at)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </div>
  )
}


/* ── 主页面 ────────────────────────────────────────────────────────── */

/** 欢迎页示例（点击只填入输入框，不自动发送）。 */
const EXAMPLES: Array<[string, string, string]> = [
  ['📋', '分析登录需求', '帮我分析一个登录需求：手机号+验证码登录，连续输错 5 次锁定 60 分钟'],
  ['🔍', '基于项目提问', '这个项目的登录逻辑该怎么测？'],
  ['📝', '全流程出报告', '分析上面的需求并生成测试报告'],
  ['💬', '测试方法论', '幂等性测试怎么设计用例？'],
]

export function RequirementsPage() {
  // 基础数据
  const [projectOpts, setProjectOpts] = React.useState<ProjectOption[]>([])
  const [dsh, setDsh] = React.useState<RuntimeStatus | null>(null)
  const [models, setModels] = React.useState<ModelOption[]>([])
  const [drawerOpen, setDrawerOpen] = React.useState(false)
  const [history, setHistory] = React.useState<TaskItem[]>([])
  const [convs, setConvs] = React.useState<ConvItem[]>([])
  // 当前会话与任务
  const [convId, setConvId] = React.useState('')
  const [messages, setMessages] = React.useState<ConvMessage[]>([])  // 会话消息流（多轮）
  const [activeId, setActiveId] = React.useState('')
  const [task, setTask] = React.useState<TaskItem | null>(null)
  const [acts, setActs] = React.useState<ActItem[]>([])
  const [analysis, setAnalysis] = React.useState<Analysis | null>(null)
  // composer
  const [text, setText] = React.useState('')
  const [selProjects, setSelProjects] = React.useState<string[]>([])
  const [workspace, setWorkspace] = React.useState('')
  const [branch, setBranch] = React.useState('')
  const [files, setFiles] = React.useState<File[]>([])  // 粘贴/拖拽的附件
  const [dragOver, setDragOver] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [formErr, setFormErr] = React.useState('')
  const [mode, setMode] = React.useState<string>('auto')
  const [detected, setDetected] = React.useState('')
  const [intentReason, setIntentReason] = React.useState('')
  const [editingId, setEditingId] = React.useState('')  // 正在重命名的会话 id（双击进入）

  const msgsRef = React.useRef<HTMLDivElement>(null)
  const inputRef = React.useRef<HTMLTextAreaElement>(null)
  const fileRef = React.useRef<HTMLInputElement>(null)
  const composerRef = React.useRef<HTMLDivElement>(null)
  const stickRef = React.useRef(true)
  const doneRef = React.useRef(false)
  const streamingRef = React.useRef(false)  // 问答流进行中（finish 时勿刷新消息列表防打断）

  const showToastMsg = (msg: string) => showToast(msg, 'info')

  React.useEffect(() => {
    getJson<{ workspace: string; default_branch: string; projects: ProjectOption[] }>('/api/projects')
      .then(d => {
        setProjectOpts(d.projects ?? [])
        setWorkspace(w => w || d.workspace)
        setBranch(b => b || d.default_branch)
      }).catch(() => {})
    getJson<RuntimeStatus>('/api/agents/runtime/status').then(setDsh).catch(() => {})
    getJson<{ models: ModelOption[] }>('/api/agents/runtime/config')
      .then(d => setModels(d.models ?? [])).catch(() => {})
  }, [])

  const refreshHistory = React.useCallback(() => {
    getJson<{ tasks: TaskItem[] }>('/api/requirements/tasks?limit=30').then(d => setHistory(d.tasks)).catch(() => {})
    getJson<{ conversations: ConvItem[] }>('/api/conversations?limit=30').then(d => setConvs(d.conversations)).catch(() => {})
  }, [])
  React.useEffect(() => { refreshHistory() }, [refreshHistory])

  React.useEffect(() => {
    if (stickRef.current && msgsRef.current) msgsRef.current.scrollTop = msgsRef.current.scrollHeight
  }, [acts, analysis, messages])

  // composer textarea 自动长高（2 行起步，最高 200px）
  React.useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }, [text])

  function loadAnalysis(id: string) {
    getJson<Analysis>(`/api/requirements/tasks/${id}/analysis`).then(d => {
      setAnalysis(d)
      // 终态任务打开时自动滚到结果区（完成横幅），过程详情往上翻
      window.setTimeout(() => {
        const box = msgsRef.current
        const banner = box?.querySelector('.done-banner') as HTMLElement | null
        if (box && banner) box.scrollTop = banner.offsetTop - box.offsetTop - 8
        else if (box) stickRef.current = true
      }, 120)
    }).catch(() => {})
  }

  function finish(id: string) {
    if (doneRef.current) return
    doneRef.current = true
    setBusy(false)
    loadAnalysis(id)
    refreshHistory()
    // 任务结论已由后端回写会话（_notify_conversation）——空闲时同步消息流，
    // 让「分析任务完成」任务块出现在当前会话；问答流进行中则跳过（防覆盖流式气泡）
    if (convId && !streamingRef.current) {
      getJson<{ messages: ConvMessage[] }>(`/api/conversations/${convId}/messages`)
        .then(d => { if (d.messages?.length) setMessages(d.messages) }).catch(() => {})
    }
    getJson<TaskItem>(`/api/requirements/tasks/${id}`).then(t => { setTask(t); setHistory(h => h.map(x => (x.task_id === id ? t : x))) }).catch(() => {})
  }

  function openTask(id: string) {
    // 只切到这个任务的活动流/结果；绝不清当前会话（任务就在会话里，清了会话
    // 第二次发送就会新建会话——这是 2026-08-27 报的「第2次发送新增会话」的根因）。
    setActiveId(id)
    setTask(null)
    setActs([])
    setAnalysis(null)
    setBusy(false)
    doneRef.current = false
    stickRef.current = true
    getJson<TaskItem>(`/api/requirements/tasks/${id}`).then(t => {
      setTask(t)
      setBusy(t.status === 'pending' || t.status === 'running')
      if (t.status === 'completed' || t.status === 'failed') {
        doneRef.current = true
        loadAnalysis(id)
      }
    }).catch(() => {})
    streamSse(`/api/requirements/tasks/${id}/activity`, ev => {
      const items: ActItem[] = ev.items ?? []
      if (items.length === 0) return
      setActs(prev => {
        const maxSeq = prev.length ? prev[prev.length - 1].seq : 0
        const add = items.filter(x => x.seq > maxSeq)
        return add.length ? [...prev, ...add] : prev
      })
      if (items.some(x => x.stage === 'completed' || x.stage === 'failed')) finish(id)
    }).catch(() => {}).finally(() => finish(id))
  }

  React.useEffect(() => {
    if (!activeId || !busy) return
    const timer = window.setInterval(() => {
      getJson<TaskItem>(`/api/requirements/tasks/${activeId}`).then(t => {
        setTask(t)
        setHistory(h => h.map(x => (x.task_id === activeId ? t : x)))
        if (t.status === 'completed' || t.status === 'failed') finish(activeId)
      }).catch(() => {})
    }, 3000)
    return () => window.clearInterval(timer)
  }, [activeId, busy])

  /** 新建会话：清空视图 + 聚焦输入框 + 闪烁提示。 */
  function newSession() {
    setConvId(''); setMessages([])
    setActiveId(''); setTask(null); setActs([]); setAnalysis(null)
    setBusy(false); doneRef.current = false
    setText(''); setFiles([])
    setDetected(''); setIntentReason('')
    inputRef.current?.focus()
    const el = composerRef.current
    if (el) { el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash') }
    showToastMsg('已开启新会话，输入需求开始分析')
  }

  /** 打开会话：回放消息流，最新任务块自动展开跟踪。 */
  function openConversation(id: string) {
    setConvId(id)
    setMessages([])
    setActiveId(''); setTask(null); setActs([]); setAnalysis(null)
    setBusy(false); doneRef.current = false
    stickRef.current = true
    getJson<{ messages: ConvMessage[] }>(`/api/conversations/${id}/messages`).then(d => {
      setMessages(d.messages ?? [])
      // 会话内最新任务自动挂载（活动流 + 结果面板）
      const lastTask = [...(d.messages ?? [])].reverse().find(m => m.task_id)
      if (lastTask?.task_id) openTask(lastTask.task_id)
    }).catch(() => {})
  }

  /** 删除会话：连带删 chat_messages + 会话内全部任务及其衍生数据。
  删当前会话 → 切回新会话视图；删别的 → 只刷新列表。二次确认防误删。 */
  async function deleteConversation(id: string, title: string) {
    const label = title || id
    if (!window.confirm(`确定删除会话「${label}」？\n该会话内的所有任务和消息将一并删除，且不可恢复。`)) return
    try {
      const r = await delJson<{ deleted: boolean; deleted_tasks: string[] }>(`/api/conversations/${id}`)
      const n = r?.deleted_tasks?.length ?? 0
      showToast(`已删除会话「${label}」${n ? `（含 ${n} 个任务）` : ''}`, 'ok')
      // 删的是当前会话：切回新会话视图
      if (id === convId) {
        newSession()
      } else {
        // 删别的会话：只刷新会话/任务列表
        refreshHistory()
      }
    } catch (e) {
      setFormErr(`删除会话失败：${e}`)
    }
  }

  /** 重命名会话：双击会话名进入编辑，Enter/blur 提交、Esc 取消。
  提交 PATCH /api/conversations/{id}；失败回滚并 toast。 */
  async function saveRename(id: string, newTitle: string) {
    const t = (newTitle || '').trim()
    const cur = convs.find(c => c.conv_id === id)
    const oldTitle = cur?.title || ''
    setEditingId('')
    if (!t || t === oldTitle) return  // 空或未改：静默退出
    // 乐观更新
    setConvs(prev => prev.map(c => c.conv_id === id ? { ...c, title: t } : c))
    try {
      const fd = new FormData()
      fd.append('title', t)
      await patchForm<{ conversation_id: string; title: string }>(`/api/conversations/${id}`, fd)
      showToast(`已重命名为「${t}」`, 'ok')
    } catch (e) {
      // 回滚
      setConvs(prev => prev.map(c => c.conv_id === id ? { ...c, title: oldTitle } : c))
      showToast(`重命名失败：${e}`, 'err')
    }
  }

  /** 切换模型（运行时热切换）。 */
  /** 切换模型/供应商后刷新引擎状态（即时对新任务生效）。 */
  async function refreshRuntime() {
    try {
      const s = await getJson<RuntimeStatus>('/api/agents/runtime/status')
      setDsh(s)
      const c = await getJson<{ models: ModelOption[] }>('/api/agents/runtime/config')
      setModels(c.models ?? [])
    } catch { /* 忽略刷新失败 */ }
  }

  /** 粘贴/拖拽附件。 */
  function addFiles(list: FileList | File[]) {
    const arr = Array.from(list)
    if (arr.length === 0) return
    setFiles(prev => [...prev, ...arr])
    showToastMsg(`已添加 ${arr.length} 个附件`)
  }
  function onPaste(e: React.ClipboardEvent) {
    const fs = e.clipboardData?.files
    if (fs && fs.length > 0) {
      e.preventDefault()
      addFiles(fs)
    }
  }
  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files)
  }

  async function run() {
    setFormErr('')
    if (!text.trim() && files.length === 0) {
      setFormErr('请输入需求描述，或粘贴/拖入文档与图片')
      inputRef.current?.focus()
      return
    }
    setBusy(true)
    try {
      // 多轮会话主链路（流式版）：/api/chat/stream 逐段推送意图 + 回答增量
      // projects 必须带上：用户选了项目，问答就要基于该项目回答
      // 附件统一进流：文本附件后端并入提问；图片/二进制后端终帧返回
      // intent=analyze（模型读不了像素），前端据此转建任务——不再本地按
      // 扩展名二分（本地判断和后端 _TEXT_SUFFIXES 双头维护易漂移）
      const cf = new FormData()
      cf.append('text', text.trim())
      if (convId) cf.append('conversation_id', convId)
      if (mode !== 'auto') cf.append('mode', mode)
      if (selProjects.length) cf.append('projects', selProjects.join(' '))
      files.forEach(f => cf.append('attachments', f))
      // 本地即时追加 user 消息（后端已落库；文本附件内容后端会并入）
      const askText = text.trim()
      setMessages(prev => [...prev, { role: 'user', content: askText || '（附件提问）', created_at: '' }])
      let streamConvId = ''
      let intent = ''
      let reason = ''
      let streamAnswer = ''
      let modelError = ''
      // 占位气泡：发送即插入空 assistant 气泡，delta 到达前显示"正在思考…"
      // ——此前等首帧 delta 才建气泡，期间用户看不到任何反馈，以为"卡住没反应"
      let streamMsgIdx = -1
      setMessages(prev => {
        streamMsgIdx = prev.length
        return [...prev, { role: 'assistant', content: '', intent: 'qa', created_at: '' }]
      })
      streamingRef.current = true
      await postFormSse('/api/chat/stream', cf, ev => {
        if (ev.error) { setFormErr(ev.error); return }
        if (ev.conversation_id && !streamConvId) {
          streamConvId = ev.conversation_id
          if (!convId) setConvId(ev.conversation_id)
        }
        if (ev.intent) { intent = ev.intent; reason = ev.reason || '' }
        if (typeof ev.delta === 'string') {
          // 打字机：占位气泡已在，直接累加内容（不再"首帧才建气泡"）
          streamAnswer += ev.delta
          setMessages(prev => {
            if (streamMsgIdx < 0) {
              streamMsgIdx = prev.length
              return [...prev, { role: 'assistant', content: streamAnswer, intent: 'qa', created_at: '' }]
            }
            const next = [...prev]
            next[streamMsgIdx] = { ...next[streamMsgIdx], content: streamAnswer }
            return next
          })
        }
        if (ev.done) {
          if (ev.model_error) modelError = ev.model_error
          // 以终帧完整回答为准（防丢段）；model_error 时气泡标记错误样式 + 重试入口
          setMessages(prev => {
            const patch = { content: ev.answer || streamAnswer, model_error: ev.model_error || null }
            if (streamMsgIdx < 0) return [...prev, { role: 'assistant', intent: 'qa', created_at: '', ...patch }]
            const next = [...prev]
            next[streamMsgIdx] = { ...next[streamMsgIdx], ...patch }
            return next
          })
        }
      })
      setDetected(intent)
      setIntentReason(reason)
      streamingRef.current = false
      if (modelError) {
        // 模型被调了但失败（如切了不可用的模型）：保留输入供换模型后重发，
        // toast 明示真因——不再「页面什么都没有」；历史仍刷新（新会话要进侧栏）
        showToast(`模型调用失败：${modelError.slice(0, 80)}。输入已保留，换模型后可重试`, 'err')
        refreshHistory()
        inputRef.current?.focus()
        return
      }
      setText('')
      setFiles([])
      if (intent === 'qa') {
        refreshHistory()
        return
      }
      // analyze/full（含图片附件场景）：建任务（带会话 ID），任务块进入消息流
      await runTask(askText, intent === 'analyze' ? 'analyze' : 'full', streamConvId || convId)
    } catch (e) {
      streamingRef.current = false
      setFormErr(`发送失败：${e}`)
    } finally {
      setBusy(false)
    }
  }

  /** 建分析任务并挂载活动流（run 的 analyze/full 分支；图片附件也走这里）。 */
  async function runTask(askText: string, resolved: string, useConvId?: string) {
    const fd = new FormData()
    if (askText) fd.append('text', askText)
    const docExt = /\.(md|txt|csv|json|xml|ya?ml|log)$/i
    const doc = files.find(f => docExt.test(f.name))
    if (doc) fd.append('requirement', doc)
    files.filter(f => f !== doc).forEach(f => fd.append('attachments', f))
    fd.append('mode', resolved)
    fd.append('projects', selProjects.join(' '))
    if (workspace.trim()) fd.append('workspace', workspace)
    if (branch.trim()) fd.append('branch', branch)
    const cid = useConvId || convId
    if (cid) fd.append('conversation_id', cid)
    try {
      const created = await postForm<{ task_id: string }>('/api/requirements/tasks', fd)
      setMessages(prev => [...prev, {
        role: 'assistant', content: `已创建分析任务，8-Agent 流水线执行中。`,
        intent: resolved, task_id: created.task_id, created_at: '',
      }])
      setText('')
      setFiles([])
      refreshHistory()
      openTask(created.task_id)
    } catch (e) {
      setFormErr(`任务创建失败：${e}`)
    }
  }

  // 活动流 → 渲染序列
  const renderSeq: Array<{ type: 'sys'; item: ActItem } | { type: 'group'; g: AgentGroup }> = []
  for (const it of acts) {
    if (it.kind === 'stage') {
      renderSeq.push({ type: 'sys', item: it })
      continue
    }
    let last = renderSeq[renderSeq.length - 1]
    if (!last || last.type === 'sys' || last.g.agent !== it.agent) {
      last = { type: 'group', g: { agent: it.agent, name: it.agent_name, events: [], running: true } }
      renderSeq.push(last)
    }
    const g = last.g
    if (it.kind === 'agent_start') g.start = it
    else if (it.kind === 'agent_end') g.end = it
    else if (it.kind === 'result') g.result = it
    else g.events.push(it)
  }
  const running = busy || (!!task && (task.status === 'pending' || task.status === 'running'))
  const doneStats = analysis ? [
    ['需求', analysis.requirements.length], ['证据', analysis.evidence.length],
    ['链路', analysis.impacts.length], ['用例', analysis.test_cases.length], ['裁决', analysis.assessments.length],
  ] : null

  return (
    <div className="req-layout">
      {/* ── 左侧：会话列表（z.ai 式：新建按钮 + 按时间分组） ─────────── */}
      {/* 任务不单列：任务挂在会话消息流里（📦 块可点击），最近任务 Ctrl+K 直达 */}
      <div className="chat-side">
        <button className="new-chat-btn" onClick={newSession}>＋ 新建会话</button>
        <div className="side-list">
          {convs.length === 0 ? <div className="empty" style={{ padding: 18 }}>暂无会话，输入内容开始对话</div> :
            groupConvs(convs).map(([g, items]) => (
              <div key={g} className="conv-group">
                <div className="conv-glabel">{g}</div>
                {items.map(c => (
                  <div key={c.conv_id} className={`conv-item ${c.conv_id === convId ? 'active' : ''}`}
                    onClick={() => editingId !== c.conv_id && openConversation(c.conv_id)}>
                    {editingId === c.conv_id ? (
                      <input className="c-edit" defaultValue={c.title || c.conv_id} autoFocus
                        onClick={e => e.stopPropagation()}
                        onKeyDown={e => {
                          if (e.key === 'Enter') { e.preventDefault(); saveRename(c.conv_id, (e.target as HTMLInputElement).value) }
                          else if (e.key === 'Escape') { e.preventDefault(); setEditingId('') }
                        }}
                        onBlur={e => saveRename(c.conv_id, e.target.value)} />
                    ) : (
                      <span className="c-title"
                        onDoubleClick={e => { e.stopPropagation(); setEditingId(c.conv_id) }}
                        title="双击重命名">{c.title || c.conv_id}</span>
                    )}
                    <span className="t-del" title="删除会话"
                      onClick={e => { e.stopPropagation(); deleteConversation(c.conv_id, c.title) }}>×</span>
                  </div>
                ))}
              </div>
            ))}
        </div>
      </div>

      {/* ── 右侧：聊天主区 ─────────────────────────────────────────── */}
      <div className="chat-main">
        {/* 流程轨道：仅在有任务时显示（欢迎页/纯问答不占位） */}
        {task ? <Rail acts={acts} task={task} /> : null}

        <div className="chat-msgs" ref={msgsRef}
          onScroll={() => {
            const el = msgsRef.current
            if (el) stickRef.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 60
          }}>
          <div className="chat-col">
          {/* 会话消息流（多轮）：user / assistant 问答气泡 + 任务块 */}
          {messages.map((m, i) => m.task_id ? (
            <div className="msg-sys" key={i}>
              <span className={`pill ${m.task_id === activeId ? 'on' : 'neutral'}`}
                style={{ cursor: 'pointer' }}
                onClick={() => m.task_id && openTask(m.task_id)}>
                📦 {m.content}{m.task_id === activeId ? '（当前）' : ' · 点击查看'}
              </span>
            </div>
          ) : m.role === 'user' ? (
            <div className="msg-user" key={i}>
              <div className="bubble">
                <div style={{ whiteSpace: 'pre-wrap' }}>{m.content.slice(0, 600)}</div>
                {m.created_at ? <div className="b-meta"><span className="rel-time">{relTime(m.created_at)}</span></div> : null}
              </div>
            </div>
          ) : (
            <div className={`msg-assistant ${busy && i === messages.length - 1 && m.content === '' ? 'pending' : ''}`} key={i}>
              <div className={`bubble-a${m.model_error ? ' err' : ''}`}>
                <div style={{ whiteSpace: 'pre-wrap' }}>
                  {m.content === '' && busy && i === messages.length - 1 ? (
                    <span className="thinking-hint"><span className="spinner" style={{ width: 12, height: 12, marginRight: 7, verticalAlign: -1 }} />正在思考…</span>
                  ) : (
                    <>
                      {m.content}{busy && i === messages.length - 1 && !m.task_id ? <span className="caret" /> : null}
                    </>
                  )}
                </div>
                {m.model_error ? (
                  <div className="b-meta">
                    <button className="link" onClick={() => {
                      if (busy) return
                      // 重试前移除失败的这对气泡（user + 错误 assistant），
                      // run() 会重新追加——否则重试一次多两条重复消息
                      setMessages(prev => {
                        const last = prev[prev.length - 1]
                        const before = prev[prev.length - 2]
                        if (last?.model_error && before?.role === 'user') return prev.slice(0, -2)
                        if (last?.model_error) return prev.slice(0, -1)
                        return prev
                      })
                      run()
                    }}>↻ 重试</button>
                    <span className="badge bad">模型调用失败</span>
                  </div>
                ) : m.intent ? <div className="b-meta"><span className="badge neutral">{MODE_LABEL[m.intent] ?? m.intent}</span></div> : null}
              </div>
            </div>
          ))}

          {/* 当前任务详情块（打开/执行中的任务展开活动流与结果） */}
          {task ? (
            <>
              {/* 用户消息 */}
              {messages.every(m => m.task_id !== activeId) ? (
                <div className="msg-user">
                  <div className="bubble">
                    <div style={{ whiteSpace: 'pre-wrap' }}>{(task.source_text || task.title || '').slice(0, 600)}</div>
                    <div className="b-meta">
                      {task.projects ? <span>项目：{task.projects}</span> : <span>项目：自动侦察</span>}
                      {task.branch ? <span>分支：{task.branch}</span> : null}
                      <span className="rel-time">{relTime(task.created_at)}</span>
                    </div>
                  </div>
                </div>
              ) : null}

              {/* 活动流 */}
              {renderSeq.map((r, i) => r.type === 'sys' ? (
                <div className="msg-sys" key={i}>
                  <span className={`pill ${r.item.stage === 'completed' ? 'ok' : r.item.stage === 'failed' ? 'bad' : ''}`}>
                    {r.item.text ?? r.item.stage}
                  </span>
                </div>
              ) : (
                <AgentCard g={r.g} key={i} />
              ))}

              {/* 失败提示 */}
              {task.status === 'failed' && task.error ? (
                <div className="msg-sys"><span className="pill bad">失败：{task.error.slice(0, 300)}</span></div>
              ) : null}

              {/* 完成横幅（PM 视角总览） */}
              {analysis && doneStats ? (
                <div className={`done-banner ${task.status === 'failed' ? 'fail' : ''}`}>
                  <span className="db-title">{task.status === 'failed' ? '✗ 分析结束（部分降级）' : '✓ 分析完成'}</span>
                  <span className="db-stats">
                    {doneStats.map(([l, v]) => <span key={l as string}>{l as string} <b>{v as number}</b></span>)}
                  </span>
                  {task.report_id ? <span className="hint">报告 <code>{task.report_id}</code></span> : null}
                  <span className="hint">耗时 {fmtDuration(task.created_at)}</span>
                </div>
              ) : null}

              {/* 结果面板 */}
              {analysis ? <ResultPanel a={analysis} /> :
                running ? <div className="msg-sys"><span className="pill"><span className="spinner" style={{ width: 10, height: 10, marginRight: 6, verticalAlign: -1 }} />{task.message || '分析中...'}</span></div> : null}
            </>
          ) : messages.length === 0 ? (
            <div className="welcome">
              <div className="w-icon">🧭</div>
              <h4>AI 测试导航 · 需求分析</h4>
              <p>粘贴需求描述或接口 URL（支持<b>直接粘贴/拖入文档和图片</b>），
                8 个 FDE Agent 协同完成分析，全程实时可见。<br />
                问答、分析、追问都在同一个会话里连续进行。</p>
              <div className="w-examples">
                {EXAMPLES.map(([icon, title, ex]) => (
                  <button key={title} className="w-card"
                    onClick={() => { setText(ex); inputRef.current?.focus() }}>
                    <span className="wc-icon">{icon}</span>
                    <b>{title}</b>
                    <span className="wc-text">{ex}</span>
                  </button>
                ))}
              </div>
              <p className="hint" style={{ marginTop: 16 }}>点击示例快速开始 · 模型管理在输入框下方的模型按钮</p>
            </div>
          ) : null}
          </div>
        </div>

        {/* ── composer：一个大盒子（选项全部收成 chip，z.ai 式） ─────── */}
        <div className="composer-wrap">
          <div className={`composer ${dragOver ? 'drag' : ''}`} ref={composerRef}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}>
            {dragOver ? <div className="drop-hint">松开以添加附件（文档/图片）</div> : null}
            {/* 附件 chips */}
            {files.length > 0 ? (
              <div className="attach-bar">
                {files.map((f, i) => (
                  <span key={i} className="attach-chip">
                    {f.type.startsWith('image/') ? (
                      <img src={URL.createObjectURL(f)} alt={f.name} />
                    ) : (
                      <span>📄</span>
                    )}
                    {f.name}
                    <span className="a-size">{fileSize(f.size)}</span>
                    <i onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}>×</i>
                  </span>
                ))}
              </div>
            ) : null}
            <textarea ref={inputRef} value={text} onChange={e => setText(e.target.value)} rows={2}
              onPaste={onPaste}
              placeholder="输入需求描述、接口 URL 或直接提问…（Enter 发送 · Shift+Enter 换行）"
              onKeyDown={e => {
                // Ctrl+Enter 兼容旧习惯；Enter 直接发送（中文输入法选词回车不发送）
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault(); if (!busy) run(); return
                }
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                  e.preventDefault(); if (!busy) run()
                }
              }} />
            <div className="cx-row">
              <div className="cx-left">
                <button className="cx-icon" title="添加附件（也可直接粘贴 / 拖入）"
                  onClick={() => fileRef.current?.click()}>📎</button>
                <input ref={fileRef} type="file" multiple hidden
                  onChange={e => { addFiles(e.target.files ?? []); e.target.value = '' }} />
                <ProjectPicker options={projectOpts} value={selProjects} onChange={setSelProjects}
                  workspace={workspace} branch={branch}
                  onWorkspace={setWorkspace} onBranch={setBranch} />
                <ModePicker value={mode} onChange={setMode} />
                <ModelBar currentModel={dsh?.model} onOpen={() => setDrawerOpen(true)} ok={dsh?.ready} />
              </div>
              <button className="cx-send" onClick={run}
                disabled={busy || !(text.trim() || files.length)}>发送</button>
            </div>
          </div>
          {/* 状态行：错误 / 运行中 / 意图识别反馈（"模型思考中"提示已移到消息区占位气泡） */}
          <div className="c-note">
            {formErr ? <span style={{ color: '#b42318' }}>{formErr}</span> :
              running ? '当前任务分析中，完成后可继续提问' :
                files.length > 0 ? `${files.length} 个附件待提交` :
                  selProjects.length > 0 ? `已指定 ${selProjects.length} 个项目` :
                    detected ? `识别：${MODE_LABEL[detected] ?? detected}${intentReason ? ` · ${intentReason}` : ''}` : ''}
          </div>
          <ModelModal open={drawerOpen} currentKey={dsh?.provider_key} currentModel={dsh?.model}
            onClose={() => setDrawerOpen(false)} onChanged={refreshRuntime} />
        </div>
      </div>
    </div>
  )
}
