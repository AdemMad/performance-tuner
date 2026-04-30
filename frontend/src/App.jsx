import { useState, useEffect } from 'react'
import { INSIGHT_TYPES, INSIGHT_PARAMS, getInsightSql } from './queries'

// ---------------------------------------------------------------------------
// Warehouse configuration
// ---------------------------------------------------------------------------
const WAREHOUSES = {
  snowflake: {
    label: 'Snowflake',
    platform: 'snowflake',
    fields: [
      { key: 'account',   label: 'Account',   type: 'text',     placeholder: 'xy12345.eu-west-1' },
      { key: 'user',      label: 'User',       type: 'text',     placeholder: 'analytics_user' },
      { key: 'password',  label: 'Password',   type: 'password', placeholder: '' },
      { key: 'database',  label: 'Database',   type: 'text',     placeholder: 'MY_DB' },
      { key: 'schema',    label: 'Schema',     type: 'text',     placeholder: 'PUBLIC' },
      { key: 'warehouse', label: 'Warehouse',  type: 'text',     placeholder: 'COMPUTE_WH' },
    ],
  },
  databricks: {
    label: 'Databricks',
    platform: 'databricks',
    fields: [
      { key: 'server_hostname', label: 'Server Hostname', type: 'text',     placeholder: 'adb-1234.azuredatabricks.net' },
      { key: 'http_path',       label: 'HTTP Path',       type: 'text',     placeholder: '/sql/1.0/warehouses/abc123' },
      { key: 'access_token',    label: 'Access Token',    type: 'password', placeholder: 'dapi...' },
    ],
  },
  azure_sql: {
    label: 'Azure SQL',
    platform: 'azuresql',
    fields: [
      { key: 'server',   label: 'Server',   type: 'text',     placeholder: 'myserver.database.windows.net' },
      { key: 'database', label: 'Database', type: 'text',     placeholder: 'my_database' },
      { key: 'username', label: 'Username', type: 'text',     placeholder: 'admin' },
      { key: 'password', label: 'Password', type: 'password', placeholder: '' },
    ],
  },
  sqlserver: {
    label: 'SQL Server',
    platform: 'sqlserver',
    fields: [
      { key: 'server',   label: 'Server',   type: 'text',     placeholder: 'MYSERVER\\SQLEXPRESS' },
      { key: 'database', label: 'Database', type: 'text',     placeholder: 'my_database' },
      { key: 'username', label: 'Username', type: 'text',     placeholder: 'sa' },
      { key: 'password', label: 'Password', type: 'password', placeholder: '' },
    ],
  },
  postgres: {
    label: 'PostgreSQL',
    platform: 'postgres',
    fields: [
      { key: 'host',     label: 'Host',     type: 'text', placeholder: 'localhost' },
      { key: 'port',     label: 'Port',     type: 'text', placeholder: '5432' },
      { key: 'database', label: 'Database', type: 'text', placeholder: 'my_db' },
      { key: 'user',     label: 'User',     type: 'text', placeholder: 'postgres' },
      { key: 'password', label: 'Password', type: 'password', placeholder: '' },
    ],
  },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function scoreClass(s) {
  if (s >= 2.5) return 'score-high'
  if (s >= 1.5) return 'score-med'
  if (s >= 0.5) return 'score-low'
  return 'score-none'
}

function cardinalityBadge(ratio) {
  if (ratio < 0.02) return { label: 'LOW',  cls: 'card-low'  }
  if (ratio < 0.10) return { label: 'MED',  cls: 'card-med'  }
  return                    { label: 'HIGH', cls: 'card-high' }
}

function bestUse(col) {
  const map = {
    PARTITION: col.partition_score,
    CLUSTER:   col.clustering_score,
    BUCKET:    col.bucketing_score,
    INDEX:     col.indexing_score,
  }
  const [name, score] = Object.entries(map).sort((a, b) => b[1] - a[1])[0]
  if (score < 0.5) return { label: '—', cls: 'score-none' }
  const clsMap = { PARTITION: 'use-partition', CLUSTER: 'use-cluster', BUCKET: 'use-bucket', INDEX: 'use-index' }
  return { label: name, cls: clsMap[name] }
}

// ---------------------------------------------------------------------------
// Markdown renderer (no external dependency)
// ---------------------------------------------------------------------------
function MarkdownLine({ text }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**')) return <strong key={i}>{p.slice(2, -2)}</strong>
        if (p.startsWith('`')  && p.endsWith('`'))  return <code key={i}>{p.slice(1, -1)}</code>
        return p
      })}
    </>
  )
}

function MarkdownBlock({ text }) {
  const lines = text.split('\n')
  const out = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.startsWith('```')) {
      const code = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) { code.push(lines[i]); i++ }
      out.push(<pre key={i}><code>{code.join('\n')}</code></pre>)
    } else if (line.startsWith('## ') || line.startsWith('### ')) {
      const lvl = line.startsWith('## ') ? 2 : 3
      const txt = line.replace(/^#{2,3} /, '')
      out.push(lvl === 2 ? <h2 key={i}>{txt}</h2> : <h3 key={i}>{txt}</h3>)
    } else if (line.startsWith('# ')) {
      out.push(<h2 key={i}>{line.slice(2)}</h2>)
    } else if (line.match(/^[-*] /)) {
      const items = []
      while (i < lines.length && lines[i].match(/^[-*] /)) {
        items.push(<li key={i}><MarkdownLine text={lines[i].replace(/^[-*] /, '')} /></li>)
        i++
      }
      out.push(<ul key={`ul${i}`}>{items}</ul>)
      continue
    } else if (line.trim() === '') {
      out.push(<br key={i} />)
    } else {
      out.push(<p key={i}><MarkdownLine text={line} /></p>)
    }
    i++
  }
  return <div className="advice-content">{out}</div>
}

// ---------------------------------------------------------------------------
// Insight results table
// ---------------------------------------------------------------------------
function InsightTable({ result }) {
  if (!result?.rows?.length) return <p style={{ fontSize: 13, color: '#64748b', marginTop: 10 }}>No rows returned.</p>
  return (
    <div className="table-wrap" style={{ marginTop: 14 }}>
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 6 }}>
        {result.row_count} row{result.row_count !== 1 ? 's' : ''} · {result.label}
      </div>
      <table>
        <thead>
          <tr>{result.columns.map(c => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i}>
              {result.columns.map(c => (
                <td key={c} className={c.includes('query') || c.includes('text') ? 'mono' : ''}>
                  {String(row[c] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------
export default function App() {
  // -- Connection state --
  const [warehouseKey, setWarehouseKey] = useState('snowflake')
  const [auth, setAuth]                 = useState({})

  // -- Table analysis state --
  const [query, setQuery]           = useState('')
  const [sampleRows, setSampleRows] = useState(50_000)
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)
  const [profile, setProfile]       = useState(null)

  // -- Insights state --
  const [insightType, setInsightType]       = useState('most_queried_tables')
  const [insightParams, setInsightParams]   = useState({})
  const [insightSql, setInsightSql]         = useState('')
  const [insightLoading, setInsightLoading] = useState(false)
  const [insightError, setInsightError]     = useState(null)
  const [insightResults, setInsightResults] = useState([]) // list of { label, columns, rows, row_count }

  // -- Gemini state --
  const [geminiKey, setGeminiKey]         = useState('')
  const [geminiModel, setGeminiModel]     = useState('gemini-1.5-flash')
  const [advice, setAdvice]               = useState(null)
  const [adviceLoading, setAdviceLoading] = useState(false)
  const [adviceError, setAdviceError]     = useState(null)

  const wh = WAREHOUSES[warehouseKey]

  // Auto-generate SQL when insight type / params / warehouse change
  useEffect(() => {
    const paramDefs = INSIGHT_PARAMS[insightType] ?? []
    const resolved  = {}
    for (const p of paramDefs) {
      resolved[p.key] = insightParams[p.key] !== undefined ? insightParams[p.key] : p.default
    }
    setInsightSql(getInsightSql(insightType, warehouseKey, resolved))
  }, [insightType, warehouseKey, JSON.stringify(insightParams)]) // eslint-disable-line

  function changeWarehouse(key) {
    setWarehouseKey(key)
    setAuth({})
    setProfile(null)
    setAdvice(null)
    setError(null)
    setInsightResults([])
    setInsightParams({})
    setInsightError(null)
  }

  function changeInsightType(type) {
    setInsightType(type)
    setInsightParams({})
    setInsightError(null)
  }

  // -- Handlers --
  async function handleAnalyze() {
    setLoading(true)
    setError(null)
    setProfile(null)
    setAdvice(null)
    try {
      const res  = await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storage: warehouseKey, auth, query, platform: wh.platform, sample_rows: sampleRows }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Profile request failed')
      setProfile(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleRunInsight() {
    setInsightLoading(true)
    setInsightError(null)
    try {
      const res  = await fetch('/api/run-query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storage: warehouseKey, auth, query: insightSql }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Query failed')
      const label = INSIGHT_TYPES.find(t => t.id === insightType)?.label ?? insightType
      setInsightResults(prev => {
        // Replace existing result with same label, otherwise append
        const filtered = prev.filter(r => r.label !== label)
        return [...filtered, { label, ...data }]
      })
    } catch (e) {
      setInsightError(e.message)
    } finally {
      setInsightLoading(false)
    }
  }

  async function handleGetAdvice() {
    setAdviceLoading(true)
    setAdviceError(null)
    try {
      const res  = await fetch('/api/gemini-advice', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gemini_api_key:  geminiKey,
          profile:         profile ?? null,
          platform:        wh.platform,
          warehouse:       wh.label,
          model:           geminiModel,
          insight_results: insightResults.map(r => ({ label: r.label, rows: r.rows.slice(0, 15) })),
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Gemini request failed')
      setAdvice(data.advice)
    } catch (e) {
      setAdviceError(e.message)
    } finally {
      setAdviceLoading(false)
    }
  }

  const ps = profile?.platform_summary ?? {}
  const paramDefs = INSIGHT_PARAMS[insightType] ?? []
  const hasContext = !!profile || insightResults.length > 0

  return (
    <>
      {/* ── Header ── */}
      <header className="header">
        <span className="header-icon">⚡</span>
        <div>
          <h1>Data Warehouse Optimizer</h1>
          <p>Profile tables · run insight queries · get AI-powered optimization advice</p>
        </div>
      </header>

      <main className="main">

        {/* ══ 1. Connection ══ */}
        <div className="card">
          <div className="card-title">Connect</div>
          <div className="form-grid" style={{ marginBottom: 14 }}>
            <div className="field">
              <label>Warehouse</label>
              <select value={warehouseKey} onChange={e => changeWarehouse(e.target.value)}>
                {Object.entries(WAREHOUSES).map(([k, v]) => (
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-grid">
            {wh.fields.map(f => (
              <div key={f.key} className="field">
                <label>{f.label}</label>
                <input
                  type={f.type}
                  placeholder={f.placeholder}
                  value={auth[f.key] ?? ''}
                  onChange={e => setAuth(prev => ({ ...prev, [f.key]: e.target.value }))}
                />
              </div>
            ))}
          </div>
        </div>

        {/* ══ 2. Quick Insights ══ */}
        <div className="card">
          <div className="card-title">Quick Insights</div>

          {/* Insight type + params */}
          <div className="form-grid" style={{ marginBottom: 12 }}>
            <div className="field">
              <label>Query type</label>
              <select value={insightType} onChange={e => changeInsightType(e.target.value)}>
                {INSIGHT_TYPES.map(t => (
                  <option key={t.id} value={t.id}>{t.label}</option>
                ))}
              </select>
            </div>
            {paramDefs.map(p => (
              <div key={p.key} className="field">
                <label>{p.label}</label>
                <input
                  type="text"
                  placeholder={p.default}
                  value={insightParams[p.key] ?? ''}
                  onChange={e => setInsightParams(prev => ({ ...prev, [p.key]: e.target.value }))}
                />
              </div>
            ))}
          </div>

          {/* SQL preview (editable) */}
          <div className="field" style={{ marginBottom: 12 }}>
            <label>SQL — editable</label>
            <textarea
              rows={8}
              value={insightSql}
              onChange={e => setInsightSql(e.target.value)}
              style={{ fontFamily: 'monospace', fontSize: 12 }}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <button
              className="btn btn-primary"
              onClick={handleRunInsight}
              disabled={insightLoading || !insightSql.trim()}
            >
              {insightLoading ? <><span className="spinner" /> Running…</> : '▶ Run Query'}
            </button>
            {insightResults.length > 0 && (
              <span style={{ fontSize: 12, color: '#16a34a' }}>
                {insightResults.length} insight{insightResults.length > 1 ? 's' : ''} collected ✓
              </span>
            )}
          </div>

          {insightError && <div className="error-box" style={{ marginTop: 10 }}>{insightError}</div>}

          {/* Show the most recently run insight result */}
          {insightResults.length > 0 && (
            <InsightTable result={insightResults[insightResults.length - 1]} />
          )}

          {/* Tabs for older results if more than one */}
          {insightResults.length > 1 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                All collected insights
              </div>
              {insightResults.slice(0, -1).map((r, i) => (
                <details key={i} style={{ marginBottom: 6 }}>
                  <summary style={{ cursor: 'pointer', fontSize: 13, color: '#2563eb' }}>{r.label} ({r.row_count} rows)</summary>
                  <InsightTable result={r} />
                </details>
              ))}
            </div>
          )}
        </div>

        {/* ══ 3. Table Analysis ══ */}
        <div className="card">
          <div className="card-title">Analyze Table — Column Profiler</div>
          <div className="field" style={{ marginBottom: 12 }}>
            <label>SQL Query</label>
            <textarea
              placeholder="SELECT * FROM my_schema.my_table LIMIT 100000"
              value={query}
              onChange={e => setQuery(e.target.value)}
              rows={3}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div className="field" style={{ margin: 0, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <label style={{ whiteSpace: 'nowrap' }}>Sample rows</label>
              <input
                type="number"
                style={{ width: 90 }}
                value={sampleRows}
                onChange={e => setSampleRows(Number(e.target.value))}
              />
            </div>
            <button
              className="btn btn-primary"
              onClick={handleAnalyze}
              disabled={loading || !query.trim()}
            >
              {loading ? <><span className="spinner" /> Analyzing…</> : 'Analyze Table →'}
            </button>
          </div>
        </div>

        {error && <div className="error-box">{error}</div>}

        {profile && (
          <>
            {/* Summary bar */}
            <div className="card" style={{ padding: '14px 20px' }}>
              <div className="summary-bar">
                <span className="chip chip-info">
                  {profile.columns.length} columns · {profile.file_profile.num_rows?.toLocaleString() ?? '?'} rows sampled
                </span>
                {profile.partition_candidates.length  > 0 && <span className="chip chip-partition">PARTITION: {profile.partition_candidates.join(', ')}</span>}
                {profile.clustering_candidates.length > 0 && <span className="chip chip-cluster">CLUSTER: {profile.clustering_candidates.join(', ')}</span>}
                {profile.bucketing_candidates.length  > 0 && <span className="chip chip-bucket">BUCKET: {profile.bucketing_candidates.join(', ')}</span>}
                {profile.indexing_candidates.length   > 0 && <span className="chip chip-index">INDEX: {profile.indexing_candidates.join(', ')}</span>}
              </div>
            </div>

            {/* Column profiles table */}
            <div className="card">
              <div className="card-title">Column Profiles</div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Column</th>
                      <th>Type</th>
                      <th>Unique Values</th>
                      <th>Cardinality</th>
                      <th>Null %</th>
                      <th>Partition ↑</th>
                      <th>Cluster ↑</th>
                      <th>Bucket ↑</th>
                      <th>Index ↑</th>
                      <th>Best Use</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.columns.map(col => {
                      const card = cardinalityBadge(col.unique_ratio)
                      const use  = bestUse(col)
                      return (
                        <tr key={col.column}>
                          <td className="mono">{col.column}</td>
                          <td style={{ color: '#64748b', fontSize: 11 }}>{col.dtype.replace(/^DataType\.|Dtype\./i, '')}</td>
                          <td>{col.approx_unique_count.toLocaleString()}</td>
                          <td><span className={`badge ${card.cls}`}>{card.label}</span></td>
                          <td>{(col.null_ratio * 100).toFixed(1)}%</td>
                          <td><span className={`badge ${scoreClass(col.partition_score)}`}>{col.partition_score.toFixed(1)}</span></td>
                          <td><span className={`badge ${scoreClass(col.clustering_score)}`}>{col.clustering_score.toFixed(1)}</span></td>
                          <td><span className={`badge ${scoreClass(col.bucketing_score)}`}>{col.bucketing_score.toFixed(1)}</span></td>
                          <td><span className={`badge ${scoreClass(col.indexing_score)}`}>{col.indexing_score.toFixed(1)}</span></td>
                          <td><span className={`badge ${use.cls}`}>{use.label}</span></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Platform strategy */}
            {ps.recommended_primary_technique && (
              <div className="card">
                <div className="card-title">Platform Strategy — {wh.label}</div>
                <div style={{ marginBottom: 12 }}>
                  <span style={{ fontSize: 12, fontWeight: 500 }}>Primary technique: </span>
                  <span className="strategy-tag">{ps.recommended_primary_technique}</span>
                </div>
                <div className="strategy-grid">
                  {ps.recommended_partition_columns?.length > 0 && (
                    <div className="strategy-section">
                      <h3>Partition by</h3>
                      <ul>{ps.recommended_partition_columns.map(c => <li key={c}>{c}</li>)}</ul>
                    </div>
                  )}
                  {ps.recommended_cluster_columns?.length > 0 && (
                    <div className="strategy-section">
                      <h3>Cluster / sort by</h3>
                      <ul>{ps.recommended_cluster_columns.map(c => <li key={c}>{c}</li>)}</ul>
                    </div>
                  )}
                  {ps.recommended_bucket_columns?.length > 0 && (
                    <div className="strategy-section">
                      <h3>Bucket by</h3>
                      <ul>{ps.recommended_bucket_columns.map(c => <li key={c}>{c}</li>)}</ul>
                    </div>
                  )}
                  {ps.avoid_columns?.length > 0 && (
                    <div className="strategy-section">
                      <h3>Avoid optimising</h3>
                      <ul>{ps.avoid_columns.map(c => <li key={c} style={{ color: '#b91c1c' }}>{c}</li>)}</ul>
                    </div>
                  )}
                </div>
                {ps.sql_or_strategy?.length > 0 && (
                  <div className="sql-block">{ps.sql_or_strategy.join('\n')}</div>
                )}
              </div>
            )}

            {/* Anti-patterns */}
            {profile.anti_patterns?.length > 0 && (
              <div className="card">
                <div className="card-title">Anti-Patterns Detected</div>
                <ul className="anti-list">
                  {profile.anti_patterns.map((p, i) => <li key={i}>{p}</li>)}
                </ul>
              </div>
            )}
          </>
        )}

        {/* ══ 4. AI Advice ══ */}
        {hasContext && (
          <div className="card">
            <div className="card-title">AI Optimization Advice</div>

            {insightResults.length > 0 && !profile && (
              <div style={{ fontSize: 12, color: '#16a34a', marginBottom: 12 }}>
                {insightResults.length} insight result{insightResults.length > 1 ? 's' : ''} ready as AI context.
                {' '}Run table analysis above to also include column profiles.
              </div>
            )}

            <div className="advice-row">
              <div className="field">
                <label>Gemini API Key</label>
                <input
                  type="password"
                  placeholder="AIzaSy…"
                  value={geminiKey}
                  onChange={e => setGeminiKey(e.target.value)}
                />
              </div>
              <div className="field" style={{ maxWidth: 200 }}>
                <label>Model</label>
                <select value={geminiModel} onChange={e => setGeminiModel(e.target.value)}>
                  <option value="gemini-1.5-flash">gemini-1.5-flash</option>
                  <option value="gemini-1.5-pro">gemini-1.5-pro</option>
                  <option value="gemini-2.0-flash">gemini-2.0-flash</option>
                </select>
              </div>
              <button
                className="btn btn-primary"
                onClick={handleGetAdvice}
                disabled={adviceLoading || !geminiKey.trim()}
              >
                {adviceLoading ? <><span className="spinner" /> Asking Gemini…</> : 'Get AI Advice →'}
              </button>
            </div>

            {adviceError && <div className="error-box" style={{ marginBottom: 12 }}>{adviceError}</div>}
            {advice && <MarkdownBlock text={advice} />}
          </div>
        )}

      </main>
    </>
  )
}
