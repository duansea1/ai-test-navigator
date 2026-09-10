import React from 'react'
import { getJson, postJson } from '../api'

interface ModelCfg {
  provider_key: string
  display_name: string
  api_key: string | null
  base_url: string | null
  protocol: string
  model_ids: string[]
  is_default: boolean
  enabled: boolean
}

const PROTOCOLS = ['openai-completions', 'openai-responses', 'anthropic', 'gemini']

/** 模型管理弹框：单选式供应商列表。
 *  交互定则（2026-09-01 重设计）：
 *  - 点整张卡片 → 切换到该供应商（模型用其目录内上次选中/首个）
 *  - 点卡片里的模型 chip → 供应商 + 该模型一步到位
 *  - 次要操作（测试/编辑/设默认/删除）收在卡片底部弱化按钮行，不抢主操作
 *  - 选择持久化在后端（重启不回默认），切换即真实探测，坏模型当场红 toast */
export function ModelModal({ open, currentKey, currentModel, onClose, onChanged }: {
  open: boolean
  currentKey?: string
  currentModel?: string
  onClose: () => void
  onChanged: () => void
}) {
  const [mounted, setMounted] = React.useState(open)
  const [closing, setClosing] = React.useState(false)
  const [formOpen, setFormOpen] = React.useState(false)
  const [formClosing, setFormClosing] = React.useState(false)
  const [configs, setConfigs] = React.useState<ModelCfg[]>([])
  const [editing, setEditing] = React.useState<string | null>(null)
  const [viewKey, setViewKey] = React.useState<string | null>(null)
  const [form, setForm] = React.useState<any>({
    provider_key: '', display_name: '', api_key: '', base_url: '',
    protocol: 'openai-completions', model_ids: '', enabled: true,
  })
  const [busy, setBusy] = React.useState(false)
  const [toast, setToast] = React.useState<{ text: string; type: string; id: number } | null>(null)
  const [discovered, setDiscovered] = React.useState<Record<string, string[]>>({})  // 按供应商缓存拉取到的网关模型
  const [q, setQ] = React.useState('')  // 模型市场搜索词
  const toastId = React.useRef(0)
  const [confirmDlg, setConfirmDlg] = React.useState<{ title: string; message: string; danger: boolean; onOk: () => void } | null>(null)
  const askConfirm = (title: string, message: string, danger: boolean, onOk: () => void) => setConfirmDlg({ title, message, danger, onOk })

  const notify = React.useCallback((text: string, type = 'info') => {
    const id = ++toastId.current
    setToast({ text, type, id })
    setTimeout(() => setToast(t => (t && t.id === id ? null : t)), 2600)
  }, [])

  const load = React.useCallback(() => {
    getJson<{ configs: ModelCfg[] }>('/api/agents/runtime/config/models')
      .then(d => setConfigs(d.configs ?? [])).catch(() => {})
  }, [])
  React.useEffect(() => {
    if (open) { setMounted(true); setClosing(false); setToast(null); setFormOpen(false); setEditing(null); setViewKey(currentKey ?? null); setQ(''); load() }
  }, [open, load, currentKey])
  React.useEffect(() => {
    if (!mounted) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [mounted])
  const requestClose = React.useCallback(() => {
    if (closing) return
    if (formOpen) { closeForm(); return }
    setClosing(true)
    setTimeout(() => { setMounted(false); setClosing(false); onClose() }, 210)
  }, [closing, onClose, formOpen])
  const closeForm = React.useCallback(() => {
    if (formClosing) return
    setFormClosing(true)
    setTimeout(() => { setFormOpen(false); setFormClosing(false) }, 180)
  }, [formClosing])
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // 新增/编辑弹框打开时，ESC 不关闭（需点击 × 或取消）
        if (!formOpen) requestClose()
      }
    }
    if (mounted) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [mounted, requestClose, formOpen])

  function blank() {
    setEditing(null); setFormOpen(true); setFormClosing(false)
    setForm({ provider_key: '', display_name: '', api_key: '', base_url: '', protocol: 'openai-completions', model_ids: '', enabled: true })
  }
  function edit(c: ModelCfg) {
    setEditing(c.provider_key); setFormOpen(true); setFormClosing(false)
    setForm({
      provider_key: c.provider_key, display_name: c.display_name, api_key: '',
      base_url: c.base_url ?? '', protocol: c.protocol,
      model_ids: (c.model_ids ?? []).join(', '), enabled: c.enabled,
    })
  }
  async function save() {
    if (!form.display_name?.trim()) { notify('请填写显示名', 'err'); return }
    const rawIds = (form.model_ids || '').split(/[,\n]/).map((s: string) => s.trim()).filter(Boolean)
    if (rawIds.length === 0) { notify('请至少填写一个模型 ID', 'err'); return }
    const key = (editing || form.provider_key || '').trim()
    if (!key) { notify('请填写供应商 Key', 'err'); return }
    setBusy(true)
    try {
      await postJson(`/api/agents/runtime/config/models/${encodeURIComponent(key)}`, {
        display_name: form.display_name.trim(),
        api_key: form.api_key || undefined,
        base_url: form.base_url.trim() || undefined,
        protocol: form.protocol,
        model_ids: rawIds,
        enabled: !!form.enabled,
      })
      closeForm(); load(); onChanged(); notify('已保存', 'ok')
    } catch (e: any) { notify('保存失败：' + e, 'err') }
    finally { setBusy(false) }
  }

  function doDel(key: string) {
    fetch(`/api/agents/runtime/config/models/${encodeURIComponent(key)}`, { method: 'DELETE' })
      .then(() => { load(); onChanged(); notify('已删除', 'ok') })
      .catch((e: any) => notify('删除失败：' + e, 'err'))
  }
  function del(key: string) {
    askConfirm('删除供应商', `确认删除供应商「${key}」？删除后不可恢复。`, true, () => doDel(key))
  }
  async function setDefault(key: string) {
    try { await postJson(`/api/agents/runtime/config/models/${encodeURIComponent(key)}/default`, {}); load(); onChanged(); notify('已设为默认', 'ok') }
    catch (e: any) { notify('设置失败：' + e, 'err') }
  }
  /** 拉取该供应商网关下全部可用模型（OpenAI 兼容 /models 端点）。
   *  后端 _http_get_models 已实现：先 /models 再回退 /v1/models。结果按供应商缓存，
   *  模型市场渲染时把「已配置 model_ids」与「网关拉取到的全部」合并去重展示。 */
  async function pullModels(key: string, baseUrl?: string, apiKey?: string) {
    setBusy(true); notify('正在拉取可用模型…', 'info')
    try {
      const payload: any = {}
      if (baseUrl) payload.base_url = baseUrl
      if (apiKey) payload.api_key = apiKey
      const d = await postJson<any>(`/api/agents/runtime/config/models/${encodeURIComponent(key)}/fetch-available`, payload)
      if (d.ok && d.model_ids?.length) {
        setDiscovered(prev => ({ ...prev, [key]: d.model_ids }))
        notify(`拉取成功，共 ${d.model_ids.length} 个可用模型`, 'ok')
      } else {
        notify('网关未返回模型列表，请检查 API Key / 地址', 'err')
      }
    } catch (e: any) { notify('拉取失败：' + e, 'err') }
    finally { setBusy(false) }
  }
  /** 把一个网关模型添加到该供应商的 model_ids 并启用（点选即用）。
   *  通过 upsert 把新模型并入 model_ids；若该供应商已是当前使用，则同步切到该模型。 */
  async function pickModel(key: string, model: string, c: ModelCfg) {
    if (busy) return
    setBusy(true)
    try {
      const exist = c.model_ids ?? []
      const merged = Array.from(new Set([...exist, model]))
      await postJson(`/api/agents/runtime/config/models/${encodeURIComponent(key)}`, {
        display_name: c.display_name, base_url: c.base_url ?? undefined,
        protocol: c.protocol, model_ids: merged, enabled: c.enabled,
      })
      // 同步切到该供应商+模型（一步到位；reconfigure 会持久化并真实探测）
      const d = await postJson<any>('/api/agents/runtime/config', { provider_key: key, model })
      onChanged(); load()
      if (d?.probe?.ok === false) {
        notify(`已选用 ${model}，但模型不可用：${d.probe.error || '探测失败'}`, 'err')
      } else {
        notify(`已选用：${model}`, 'ok')
      }
    } catch (e: any) { notify('选用失败：' + e, 'err') }
    finally { setBusy(false) }
  }
  function draftOverrides(): any {
    const o: any = {}
    if (form.api_key) o.api_key = form.api_key
    if (form.base_url.trim()) o.base_url = form.base_url.trim()
    return o
  }
  async function testConn(key: string) {
    setBusy(true); notify('连通测试中…', 'info')
    try {
      const d = await postJson<any>(`/api/agents/runtime/config/models/${encodeURIComponent(key)}/test`, draftOverrides())
      const reason = d.error || (d.data?.error) || (d.data != null ? JSON.stringify(d.data) : '服务未返回失败原因')
      notify(d.ok ? `连通成功：模型 ${d.data?.model ?? ''} 可调用` : '连通失败：' + reason, d.ok ? 'ok' : 'err')
    } catch (e: any) { notify('测试异常：' + e, 'err') }
    finally { setBusy(false) }
  }
  async function fetchAvailable(key: string) {
    setBusy(true); notify('获取可用模型…', 'info')
    try {
      const d = await postJson<any>(`/api/agents/runtime/config/models/${encodeURIComponent(key)}/fetch-available`, draftOverrides())
      if (d.ok && d.model_ids?.length) {
        const exist = (form.model_ids || '').split(/[,\n]/).map((s: string) => s.trim()).filter(Boolean)
        const merged = Array.from(new Set([...exist, ...d.model_ids]))
        setForm((f: any) => ({ ...f, model_ids: merged.join(', ') }))
        const added = merged.length - exist.length
        notify(added > 0 ? `已追加 ${added} 个新模型（共 ${merged.length} 个）` : `无新增，当前 ${merged.length} 个模型`, 'ok')
      } else notify('未获取到模型列表', 'err')
    } catch (e: any) { notify('获取失败：' + e, 'err') }
    finally { setBusy(false) }
  }
  async function connectAndPull(key: string) {
    setBusy(true); notify('连接并拉取模型中…', 'info')
    try {
      const d = await postJson<any>(`/api/agents/runtime/config/models/${encodeURIComponent(key)}/fetch-available`, draftOverrides())
      if (d.ok && d.model_ids?.length) {
        const exist = (form.model_ids || '').split(/[,\n]/).map((s: string) => s.trim()).filter(Boolean)
        const merged = Array.from(new Set([...exist, ...d.model_ids]))
        setForm((f: any) => ({ ...f, model_ids: merged.join(', ') }))
        const added = merged.length - exist.length
        notify(added > 0 ? `连接成功，已追加 ${added} 个新模型（共 ${merged.length} 个）` : `连接成功，当前 ${merged.length} 个模型`, 'ok')
      } else {
        notify('连接成功，但未获取到模型列表', 'ok')
      }
    } catch (e: any) { notify('操作异常：' + e, 'err') }
    finally { setBusy(false) }
  }
  function doRestore() {
    postJson('/api/agents/runtime/config/models/restore-defaults', {})
      .then(() => { load(); onChanged(); notify('已恢复默认', 'ok') })
      .catch((e: any) => notify('恢复失败：' + e, 'err'))
  }
  async function restore() {
    askConfirm('恢复默认模型供应商', '确认恢复默认配置？将清空所有现有配置，并重植 4 条默认 DeepSeek 供应商。', true, doRestore)
  }

  if (!mounted) return null
  const toastIcon = toast?.type === 'ok' ? '✓' : toast?.type === 'err' ? '!' : 'i'
  const view = configs.find(c => c.provider_key === viewKey) ?? configs[0]
  return (
    <>
      <div className={`modal-mask ${closing ? 'closing' : ''}`} onClick={requestClose}>
        <div className={`modal mc-modal ${closing ? 'closing' : ''}`} onClick={e => e.stopPropagation()}>
          <div className="modal-head mc-head">
            <div className="mc-head-title">
              <h3>模型管理</h3>
              <span className="hint">选择一个模型作为当前运行模型</span>
            </div>
            <div className="head-actions">
              <button className="btn sm primary" disabled={busy} onClick={blank}>＋ 添加供应商</button>
              <button className="x" onClick={requestClose} aria-label="关闭">✕</button>
            </div>
          </div>

          <div className="modal-body mc-body">
            <aside className="mc-nav">
              <div className="mc-nav-head"><b>供应商</b><span>{configs.length}</span></div>
              {configs.map(c => (
                <button key={c.provider_key}
                  className={`mc-nav-item ${view?.provider_key === c.provider_key ? 'cur' : ''} ${c.enabled ? '' : 'off'}`}
                  onClick={() => { setViewKey(c.provider_key); setQ('') }}>
                  <span className={`mc-provider-status ${c.provider_key === currentKey ? 'active' : ''}`} />
                  <span className="mc-nav-name">{c.display_name}</span>
                  <span className="mc-nav-meta">{c.is_default ? '默认' : c.enabled ? '' : '停用'}</span>
                </button>
              ))}
              {configs.length === 0 && <div className="mc-empty">暂无供应商<br />点击右上角添加</div>}
              <button className="mc-nav-add" disabled={busy} onClick={blank}>＋ 添加供应商</button>
            </aside>
            <div className="mc-detail">
              {view ? (<>
                <div className="mc-detail-head">
                  <div className="mc-summary">
                    <div className="mc-summary-title">
                      <span className="mc-summary-name">{view.display_name}</span>
                      {view.provider_key === currentKey && <span className="tag cur">使用中</span>}
                      {!view.enabled && <span className="tag">已停用</span>}
                    </div>
                    <div className="mc-summary-meta">
                      <span className="mc-summary-model">{view.provider_key === currentKey ? `当前模型：${currentModel || '未选择'}` : '未启用'}</span>
                      {view.base_url && <span className="mc-detail-url" title={view.base_url}>{view.base_url}</span>}
                    </div>
                  </div>
                  <div className="mc-ops">
                    <button className="mc-op" disabled={busy} onClick={() => testConn(view.provider_key)}>测试连接</button>
                    <button className="mc-op" disabled={busy} onClick={() => edit(view)}>编辑</button>
                    {!view.is_default && <button className="mc-op" disabled={busy} onClick={() => setDefault(view.provider_key)}>设为默认</button>}
                    {!view.is_default && <button className="mc-op danger" disabled={busy} onClick={() => del(view.provider_key)}>删除</button>}
                  </div>
                </div>
                <div className="mc-market">
                  {/* 搜索 + 一键拉取 */}
                  <div className="mc-market-bar">
                    <span className="mc-search-wrap">
                      <span className="mc-search-ico">🔍</span>
                      <input className="mc-search" placeholder="搜索模型 ID…" value={q}
                        onChange={e => setQ(e.target.value)} />
                      {q && <span className="mc-search-clr" onClick={() => setQ('')}>✕</span>}
                    </span>
                    <button className="mc-pull" disabled={busy || !view.enabled} onClick={() => pullModels(view.provider_key)}>
                      <span className="mc-pull-ico">↻</span> 拉取全部模型
                    </button>
                  </div>
                  {(() => {
                    // 合并：已配置 model_ids + 网关拉取到的全部，去重，保持拉取顺序在前（用户更关心新拉到的）
                    const pool = discovered[view.provider_key] ?? []
                    const merged = Array.from(new Set([...(view.model_ids ?? []), ...pool]))
                    const kw = q.trim().toLowerCase()
                    const list = kw ? merged.filter(m => m.toLowerCase().includes(kw)) : merged
                    if (!list.length) {
                      return <div className="mc-empty">{pool.length ? '无匹配模型' : '暂无模型，点「拉取全部模型」从网关获取'}</div>
                    }
                    return (
                      <div className="mc-models">
                        {list.map(m => {
                          const on = view.provider_key === currentKey && m === currentModel
                          const has = (view.model_ids ?? []).includes(m)
                          return (
                            <button key={m} className={`mc-model ${on ? 'on' : ''} ${!has && !on ? 'new' : ''}`}
                              disabled={busy || !view.enabled} title={!has ? '网关可用，尚未添加到配置' : ''}
                              onClick={() => { if (!on) pickModel(view.provider_key, m, view) }}>
                              <span className="mc-model-name">{m}{!has && !on ? <span className="mc-new-tag">新</span> : null}</span>
                              <span className="mc-model-state">{on ? '使用中' : has ? '选用' : '+ 添加'}</span>
                            </button>
                          )
                        })}
                      </div>
                    )
                  })()}
                </div>
              </>) : (
                <div className="mc-empty">左侧选择供应商</div>
              )}
            </div>
          </div>

          <div className="modal-foot">
            <button className="btn sm" disabled={busy} onClick={restore}>恢复默认供应商</button>
            <span className="mc-foot-hint">选择即时生效并持久保存，重启不丢失</span>
          </div>
        </div>
      </div>

      {formOpen && (
        <div className={`form-mask ${formClosing ? 'closing' : ''}`}>
          <div className={`form-modal ${formClosing ? 'closing' : ''}`}>
            <div className="form-modal-head">
              <h3>{editing ? '编辑模型供应商' : '新增模型供应商'}</h3>
              <button className="x" onClick={closeForm} aria-label="关闭">✕</button>
            </div>
            <div className="form-modal-body">
              <label>显示名
                <input value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} placeholder="如 DeepSeek V4 Chat" />
              </label>
              <label>供应商 Key
                {editing
                  ? <input value={form.provider_key} disabled />
                  : <input value={form.provider_key} onChange={e => setForm({ ...form, provider_key: e.target.value })} placeholder="唯一英文 key，如 my-provider" />}
              </label>
              <label>API Key
                {editing
                  ? <input value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} placeholder={`（脱敏：${configs.find(c => c.provider_key === editing)?.api_key ?? '未设置'}）留空不修改`} />
                  : <input value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} placeholder="sk-... 留空则沿用环境/凭据库" />}
              </label>
              <label>API 地址
                <input value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} placeholder="https://api.deepseek.com/v1（纯域名会自动补 /v1）" />
              </label>
              <label>API 协议
                <select value={form.protocol} onChange={e => setForm({ ...form, protocol: e.target.value })}>
                  {PROTOCOLS.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </label>
              <label>模型目录
                <div className="model-ids-wrap">
                  <textarea value={form.model_ids} onChange={e => setForm({ ...form, model_ids: e.target.value })} placeholder="模型 ID，逗号或换行分隔，如 deepseek-v4-chat, deepseek-coder" rows={3} />
                  <button className="icon-refresh" title="从渠道重新拉取模型" disabled={busy || !form.provider_key.trim() || !form.base_url.trim()} onClick={() => fetchAvailable(form.provider_key)}>↻</button>
                </div>
                {(() => {
                  const ids = (form.model_ids || '').split(/[,\n]/).map((s: string) => s.trim()).filter(Boolean)
                  if (!ids.length) return null
                  return (
                    <div className="model-count-hint">
                      <span>共 {ids.length} 个模型（保存后在列表点选模型即可启用）</span>
                      {ids.length <= 8 && (
                        <div className="model-chips">
                          {ids.map((m: string) => (<span key={m} className="model-chip">{m}</span>))}
                        </div>
                      )}
                    </div>
                  )
                })()}
              </label>
              <div className="mc-switches">
                <label className="chk"><input type="checkbox" checked={!!form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} /> 启用（关闭后不出现在可选列表）</label>
              </div>
            </div>
            <div className="form-modal-foot">
              <button className="btn sm" disabled={busy || !form.provider_key.trim() || !form.base_url.trim()} onClick={() => connectAndPull(form.provider_key)}>连接并拉取模型</button>
              <span className="foot-spacer" />
              <button className="btn sm primary" disabled={busy} onClick={save}>保存</button>
              <button className="btn sm" disabled={busy} onClick={closeForm}>取消</button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className={`mc-toast ${toast.type}`} key={toast.id}>
          <span className="ic">{toastIcon}</span>{toast.text}
        </div>
      )}

      {confirmDlg && (
        <div className="confirm-mask" onClick={() => setConfirmDlg(null)}>
          <div className="confirm-modal" onClick={e => e.stopPropagation()}>
            <div className={`confirm-icon ${confirmDlg.danger ? 'danger' : ''}`}>!</div>
            <h4>{confirmDlg.title}</h4>
            <p>{confirmDlg.message}</p>
            <div className="confirm-actions">
              <button className="btn sm" onClick={() => setConfirmDlg(null)}>取消</button>
              <button className={`btn sm ${confirmDlg.danger ? 'danger' : 'primary'}`} onClick={() => { const fn = confirmDlg.onOk; setConfirmDlg(null); fn() }}>确认</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
