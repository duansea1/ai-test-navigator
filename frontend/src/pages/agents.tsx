import React from 'react'
import { getJson, postJson } from '../api'

interface AgentItem {
  id: string
  name: string
  role: string
  output_contract: string
  fde_module: string
  enabled: boolean
  tags: string[]
}

interface AgentsData {
  agents: AgentItem[]
  runtime: Record<string, any>
}

interface RunResult {
  agent_id: string
  status: string
  final_response?: string
  session_id?: string
  message?: string
  finish_reason?: string
}

export function AgentsPage() {
  const [data, setData] = React.useState<AgentsData | null>(null)
  const [error, setError] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [runAgent, setRunAgent] = React.useState<string>('')
  const [runInput, setRunInput] = React.useState('')
  const [runResult, setRunResult] = React.useState<RunResult | null>(null)

  const load = React.useCallback(() => {
    getJson<AgentsData>('/api/agents').then(setData).catch(e => setError(String(e)))
  }, [])
  React.useEffect(load, [load])

  const rt = data?.runtime ?? {}

  async function controlRuntime(action: 'start' | 'stop') {
    setBusy(true)
    try {
      await postJson(`/api/agents/runtime/${action}`, {})
      load()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function run() {
    if (!runAgent || !runInput.trim()) return
    setBusy(true)
    setRunResult(null)
    try {
      const res = await postJson<RunResult>(`/api/agents/${runAgent}/run`, { input: runInput })
      setRunResult(res)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  if (error && !data) return <div className="status danger">加载失败：{error}</div>
  if (!data) return <div className="empty">加载中...</div>

  return (
    <>
      <div className="card">
        <h3>DSH Runtime</h3>
        <dl className="kv">
          <dt>状态</dt><dd>{rt.running ? <span className="badge ok">运行中</span> : rt.ready ? <span className="badge warn">待命</span> : <span className="badge bad">未就绪</span>}</dd>
          <dt>运行模式</dt><dd><code>{String(rt.mode ?? '-')}</code></dd>
          <dt>源码集成</dt><dd>{rt.source_available ? '已接入' : '未找到'}</dd>
          <dt>node 载体</dt><dd>{rt.node_carrier_available ? '已构建' : '未构建'}</dd>
          <dt>API Key</dt><dd>{rt.api_key_configured ? '已配置' : '未配置'}</dd>
          <dt>活跃会话</dt><dd>{String(rt.active_sessions ?? 0)}</dd>
          {rt.last_error ? <><dt>最近错误</dt><dd className="hint">{String(rt.last_error)}</dd></> : null}
        </dl>
        <div style={{ marginTop: 14, display: 'flex', gap: 10 }}>
          <button disabled={busy} onClick={() => controlRuntime('start')}>启动 Runtime</button>
          <button className="ghost" disabled={busy} onClick={() => controlRuntime('stop')}>停止</button>
          <button className="ghost" disabled={busy} onClick={load}>刷新</button>
        </div>
      </div>

      <div className="card">
        <h3>Agent 注册表（{data.agents.length} 个 · M2 接入完整编排）</h3>
        <div className="agent-grid">
          {data.agents.map(a => (
            <div className="agent-card" key={a.id}>
              <h4>{a.name} <code>{a.id}</code></h4>
              <p>{a.role}</p>
              <p>输出：<code>{a.output_contract}</code></p>
              <p>FDE：<span className="hint">{a.fde_module}</span></p>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>Agent 试运行（M0 链路验证）</h3>
        <label>选择 Agent</label>
        <select value={runAgent} onChange={e => setRunAgent(e.target.value)}>
          <option value="">-- 选择 --</option>
          {data.agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <label>输入数据</label>
        <textarea value={runInput} onChange={e => setRunInput(e.target.value)} placeholder="粘贴需求文本或结构化输入（JSON）..." />
        <div style={{ marginTop: 12 }}>
          <button disabled={busy || !runAgent || !runInput.trim()} onClick={run}>{busy ? '执行中...' : '执行回合'}</button>
        </div>
        {runResult ? (
          <div className={`status ${runResult.status === 'ok' ? 'ok' : ''}`}>
            {runResult.status === 'ok'
              ? `会话 ${runResult.session_id} · ${runResult.finish_reason}\n\n${runResult.final_response ?? ''}`
              : `降级：${runResult.message ?? 'DSH 未就绪'}`}
          </div>
        ) : null}
      </div>
    </>
  )
}
