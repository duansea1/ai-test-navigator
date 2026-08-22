import React from 'react'
import { getJson } from '../api'

interface TaskRow {
  task_id: string
  title: string
  projects: string
  branch: string
  status: string
  stage: string
  progress: number
  message: string | null
  report_id: string | null
  created_at: string
}

interface TrendRow { day: string; tasks: number }

interface Dash {
  totals: Record<string, number>
  tasks: TaskRow[]
  trend: TrendRow[]
  recent_reports: Array<{ report_id: string; generated_at: string; branch: string; summary: Record<string, number> }>
  dsh: Record<string, any>
  source: string
}

const STATUS_CLS: Record<string, string> = { completed: 'ok', failed: 'bad', running: 'warn', pending: 'neutral' }

export function DashboardPage() {
  const [data, setData] = React.useState<Dash | null>(null)
  const [error, setError] = React.useState('')
  const load = React.useCallback(() => {
    getJson<Dash>('/api/dashboard').then(setData).catch(e => setError(String(e)))
  }, [])
  React.useEffect(() => {
    load()
    const timer = setInterval(load, 10000) // 任务进行中自动刷新
    return () => clearInterval(timer)
  }, [load])
  if (error) return <div className="status danger">加载失败：{error}</div>
  if (!data) return <div className="empty">加载中...</div>
  const t = data.totals
  const dsh = data.dsh ?? {}
  const maxTasks = Math.max(1, ...(data.trend ?? []).map(x => x.tasks))
  return (
    <>
      <div className="grid cols-4">
        {[
          ['分析任务', t.tasks_total], ['需求条目', t.requirements], ['进行中', t.tasks_running], ['已完成', t.reports],
        ].map(([label, value]) => (
          <div className="stat" key={label as string}><b>{value as number}</b><span>{label as string}</span></div>
        ))}
      </div>
      <div className="grid cols-2">
        <div className="card">
          <h3>近 14 天任务趋势{data.source === 'files' ? <span className="badge warn" style={{ marginLeft: 8 }}>DB 降级·文件统计</span> : null}</h3>
          {(data.trend ?? []).length === 0 ? <div className="empty">暂无任务数据</div> : (
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 120, padding: '8px 0' }}>
              {data.trend.map(x => (
                <div key={x.day} style={{ flex: 1, textAlign: 'center' }} title={`${x.day}：${x.tasks} 个任务`}>
                  <div style={{
                    height: `${Math.max(6, (x.tasks / maxTasks) * 90)}px`,
                    background: '#0091ff', borderRadius: 4, margin: '0 auto', width: '70%',
                  }} />
                  <div className="hint" style={{ fontSize: 11, marginTop: 4 }}>{x.day.slice(5)}</div>
                  <div className="hint" style={{ fontSize: 11 }}>{x.tasks}</div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <h3>DSH Runtime 状态</h3>
          <dl className="kv">
            <dt>就绪</dt><dd>{dsh.ready ? <span className="badge ok">就绪</span> : <span className="badge warn">未就绪</span>}</dd>
            <dt>运行模式</dt><dd><code>{String(dsh.mode ?? '-')}</code></dd>
            <dt>源码集成</dt><dd>{dsh.source_available ? '已接入' : '未找到'}</dd>
            <dt>node 载体</dt><dd>{dsh.node_carrier_available ? '已构建' : '未构建'}</dd>
            <dt>API Key</dt><dd>{dsh.api_key_configured ? '已配置' : '未配置'}</dd>
            <dt>运行中</dt><dd>{dsh.running ? `会话 ${dsh.active_sessions} 个` : '未启动'}</dd>
            {dsh.last_error ? <><dt>最近错误</dt><dd className="hint">{String(dsh.last_error)}</dd></> : null}
          </dl>
        </div>
      </div>
      <div className="card">
        <h3>最近任务</h3>
        {(data.tasks ?? []).length === 0 ? <div className="empty">暂无任务，先到需求分析创建任务</div> : (
          <table>
            <thead><tr><th>任务</th><th>状态</th><th>阶段</th><th>进度</th><th>报告</th><th>创建时间</th></tr></thead>
            <tbody>
              {data.tasks.map(t2 => (
                <tr key={t2.task_id}>
                  <td><code>{t2.task_id}</code><div className="hint">{t2.title}</div></td>
                  <td><span className={`badge ${STATUS_CLS[t2.status] ?? 'neutral'}`}>{t2.status}</span></td>
                  <td>{t2.stage || '-'}</td>
                  <td>{t2.progress}%</td>
                  <td>{t2.report_id ? <code>{t2.report_id}</code> : '-'}</td>
                  <td>{t2.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
