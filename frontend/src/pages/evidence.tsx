import React from 'react'
import { getJson } from '../api'

interface EvidenceData {
  status: string
  milestone: string
  planned: string[]
}

export function EvidencePage() {
  const [data, setData] = React.useState<EvidenceData | null>(null)
  const [error, setError] = React.useState('')
  React.useEffect(() => {
    getJson<EvidenceData>('/api/evidence').then(setData).catch(e => setError(String(e)))
  }, [])
  if (error) return <div className="status danger">加载失败：{error}</div>
  if (!data) return <div className="empty">加载中...</div>
  return (
    <div className="card">
      <h3>证据中心 <span className="badge neutral">{data.milestone}</span></h3>
      <p className="hint">证据优先是平台第一原则：每个判断必须绑定文件、行号、符号或命令输出，证据不足显式标记 needs_review。</p>
      <h3 style={{ marginTop: 18 }}>规划能力</h3>
      <table>
        <thead><tr><th>#</th><th>能力</th></tr></thead>
        <tbody>
          {data.planned.map((p, i) => (
            <tr key={p}><td>{i + 1}</td><td>{p}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="hint" style={{ marginTop: 12 }}>分析任务产生的代码证据在 M1 入库（code_evidence 表），M2 支持调用链浏览与知识检索。</p>
    </div>
  )
}
