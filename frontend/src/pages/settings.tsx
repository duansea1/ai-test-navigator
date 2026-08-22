import React from 'react'
import { getJson } from '../api'

interface Capabilities {
  vision_supported: boolean
  dsh_key_configured: boolean
  dsh_ready: boolean
  dsh_runtime: Record<string, any>
  database_url_configured: boolean
  message: string
}

interface Health {
  status: string
  mode: string
  version: string
}

export function SettingsPage() {
  const [caps, setCaps] = React.useState<Capabilities | null>(null)
  const [health, setHealth] = React.useState<Health | null>(null)
  const [error, setError] = React.useState('')
  const [checked, setChecked] = React.useState(false)

  const load = React.useCallback(() => {
    getJson<Capabilities>('/api/capabilities').then(setCaps).catch(e => setError(String(e)))
  }, [])
  React.useEffect(load, [load])

  async function runHealth() {
    setChecked(false)
    try {
      setHealth(await getJson<Health>('/api/health'))
    } catch (e) {
      setError(String(e))
    } finally {
      setChecked(true)
    }
  }

  const rt = caps?.dsh_runtime ?? {}
  if (error && !caps) return <div className="status danger">加载失败：{error}</div>
  if (!caps) return <div className="empty">加载中...</div>

  return (
    <>
      <div className="card">
        <h3>系统能力</h3>
        <dl className="kv">
          <dt>服务模式</dt><dd><span className="badge ok">{caps.message ? '商用级 FDE 双链路' : '-'}</span></dd>
          <dt>DSH 就绪</dt><dd>{caps.dsh_ready ? <span className="badge ok">就绪</span> : <span className="badge warn">未就绪（降级规则分析）</span>}</dd>
          <dt>DSH API Key</dt><dd>{caps.dsh_key_configured ? '已配置' : '未配置'}</dd>
          <dt>数据库</dt><dd>{caps.database_url_configured ? '已配置' : '未配置（SQLite 降级）'}</dd>
          <dt>视觉能力</dt><dd>{caps.vision_supported ? '支持' : '不支持'}</dd>
        </dl>
        <p className="hint" style={{ marginTop: 10 }}>{caps.message}</p>
      </div>
      <div className="card">
        <h3>DSH Runtime</h3>
        <dl className="kv">
          <dt>运行模式</dt><dd><code>{String(rt.mode ?? '-')}</code></dd>
          <dt>Provider / Model</dt><dd><code>{String(rt.provider ?? '-')} / {String(rt.model ?? '-')}</code></dd>
          <dt>源码集成</dt><dd>{rt.source_available ? '已接入' : '未找到'}</dd>
          <dt>node 载体</dt><dd>{rt.node_carrier_available ? '已构建' : '未构建'}</dd>
          <dt>运行中</dt><dd>{rt.running ? `启动于 ${String(rt.started_at ?? '').slice(0, 19).replace('T', ' ')}` : '未启动'}</dd>
          {rt.last_error ? <><dt>最近错误</dt><dd className="hint">{String(rt.last_error)}</dd></> : null}
        </dl>
      </div>
      <div className="card">
        <h3>健康检查</h3>
        <button className="ghost" onClick={runHealth}>执行检查</button>
        {checked && health ? (
          <dl className="kv" style={{ marginTop: 12 }}>
            <dt>状态</dt><dd><span className="badge ok">{health.status}</span></dd>
            <dt>模式</dt><dd><code>{health.mode}</code></dd>
            <dt>版本</dt><dd><code>{health.version}</code></dd>
          </dl>
        ) : null}
      </div>
      <div className="card">
        <h3>配置说明</h3>
        <p className="hint">密钥与环境配置通过项目根目录 <code>.env</code> 注入（参考 <code>.env.example</code>）：DSH_REPO、DSH_RUNTIME_MODE、DEEPSEEK_API_KEY、AI_NAVIGATOR_DB 等。权限、工单/IM/SSO 集成为后续迭代预留。</p>
      </div>
    </>
  )
}
