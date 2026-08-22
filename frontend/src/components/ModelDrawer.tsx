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

export function ModelModal({ open, currentKey, onClose, onChanged }: {
  open: boolean
  currentKey?: string
  onClose: () => void
  onChanged: () => void
}) {
  const [mounted, setMounted] = React.useState(open)
  const [closing, setClosing] = React.useState(false)
  const [formOpen, setFormOpen] = React.useState(false)
  const [formClosing, setFormClosing] = React.useState(false)
  const [configs, setConfigs] = React.useState<ModelCfg[]>([])
  const [editing, setEditing] = React.useState<string | null>(null)
  const [form, setForm] = React.useState<any>({
    provider_key: '', display_name: '', api_key: '', base_url: '',
    protocol: 'openai-completions', model_ids: '', enabled: true,
  })
  const [busy, setBusy] = React.useState(false)
  const [curIdx, setCurIdx] = React.useState(0)
  const [toast, setToast] = React.useState<{ text: string; type: string; id: number } | null>(null)
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
    if (open) { setMounted(true); setClosing(false); setToast(null); setFormOpen(false); setEditing(null); load() }
  }, [open, load, notify])
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
    setEditing(null); setFormOpen(true); setFormClosing(false); setCurIdx(0)
    setForm({ provider_key: '', display_name: '', api_key: '', base_url: '', protocol: 'openai-completions', model_ids: '', enabled: true })
  }
  function edit(c: ModelCfg) {
    setEditing(c.provider_key); setFormOpen(true); setFormClosing(false); setCurIdx(0)
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
    const ids = rawIds.slice()
    const idx = Math.max(0, Math.min(curIdx, ids.length - 1))
    if (idx > 0) { const [sel] = ids.splice(idx, 1); ids.unshift(sel) }
    const key = (editing || form.provider_key || '').trim()
    if (!key) { notify('请填写供应商 Key', 'err'); return }
    setBusy(true)
    try {
      await postJson(`/api/agents/runtime/config/models/${encodeURIComponent(key)}`, {
        display_name: form.display_name.trim(),
        api_key: form.api_key || undefined,
        base_url: form.base_url.trim() || undefined,
        protocol: form.protocol,
        model_ids: ids,
        enabled: !!form.enabled,
      })
      closeForm(); load(); onChanged(); notify('已保存', 'ok')
    } catch (e: any) { notify('保存失败：' + e, 'err') }
    finally { setBusy(false) }
  }
  async function useModel(key: string) {
    try { await postJson('/api/agents/runtime/config', { provider_key: key }); onChanged(); notify('已切换：' + key, 'ok') }
    catch (e: any) { notify('切换失败：' + e, 'err') }
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
        setCurIdx(0)
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
  return (
    <>
      <div className={`modal-mask ${closing ? 'closing' : ''}`} onClick={requestClose}>
        <div className={`modal ${closing ? 'closing' : ''}`} onClick={e => e.stopPropagation()}>
          <div className="modal-head">
            <div>
              <h3>模型供应商配置</h3>
              <span className="hint">管理 API 地址 / Key / 模型 ID，切换即时对新任务生效</span>
            </div>
            <div className="head-actions">
              <button className="btn sm primary" disabled={busy} onClick={blank}>＋ 添加模型供应商</button>
              <button className="x" onClick={requestClose} aria-label="关闭">✕</button>
            </div>
          </div>

          <div className="modal-body">
            <div className="mc-list">
              {configs.map(c => (
                <div key={c.provider_key} className={`mc-card ${c.provider_key === currentKey ? 'active' : ''}`}>
                  <div className="mc-top">
                    <span className={`mc-dot ${c.enabled ? 'on' : 'off'}`} />
                    <span className="mc-name">{c.display_name}</span>
                    {c.is_default && <span className="tag def">默认</span>}
                    {c.provider_key === currentKey && <span className="tag cur">使用中</span>}
                  </div>
                  <div className="mc-meta">
                    <span className="mc-key">{c.provider_key}</span>
                    <span className="mc-proto">{c.protocol}</span>
                  </div>
                  <div className="mc-models">{(c.model_ids || []).join('、') || '—'}</div>
                  {c.base_url && <div className="mc-url">{c.base_url}</div>}
                  <div className="mc-actions">
                    {c.provider_key !== currentKey && <button className="btn sm primary" disabled={busy} onClick={() => useModel(c.provider_key)}>使用</button>}
                    <button className="btn sm" disabled={busy} onClick={() => testConn(c.provider_key)}>测试连通</button>
                    <button className="btn sm" disabled={busy} onClick={() => edit(c)}>编辑</button>
                    {!c.is_default && <button className="btn sm" disabled={busy} onClick={() => setDefault(c.provider_key)}>设默认</button>}
                    {!c.is_default && <button className="btn sm danger" disabled={busy} onClick={() => del(c.provider_key)}>删除</button>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="modal-foot">
            <button className="btn sm" disabled={busy} onClick={restore}>恢复默认模型</button>
            <span className="mc-foot-hint">配置变更即时生效 · 无需重启</span>
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
                  : <input value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} placeholder="sk-... 留空则不修改" />}
              </label>
              <label>API 地址
                <input value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} placeholder="https://api.deepseek.com/v1" />
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
                      <span>共 {ids.length} 个模型</span>
                      {ids.length <= 8 && (
                        <div className="model-chips">
                          {ids.map((m: string, i: number) => (
                            <span key={i} className={`model-chip ${i === 0 ? 'primary' : ''}`}>{m}{i === 0 && ' · 当前'}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })()}
              </label>
              <div className="mc-switches">
                <label className="chk"><input type="checkbox" checked={!!form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} /> 启用（关闭后该供应商模型不再出现在可选列表）</label>
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
