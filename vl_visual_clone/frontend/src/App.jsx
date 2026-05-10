import { useMemo, useState } from 'react'

const API = 'http://127.0.0.1:8091'

export default function App() {
  const [form, setForm] = useState({
    inputPdf: '/u01/huzekun/data/FUNSD/pdf_test/funsd_test_0000.pdf',
    outputDir: '/u01/huzekun/data/FUNSD/test',
    apiBase: 'http://127.0.0.1:8080',
    ocrEngine: 'paddleocr-vl',
    compareAllEngines: true,
    mineruApiBase: 'http://127.0.0.1:18000',
    dotsocrApiBase: 'http://127.0.0.1:18001',
    dotsocrModel: 'model',
    dotsocrPrompt: '',
    sourceLang: 'zh',
    targetLang: 'en',
    enableTranslate: true,
    geometrySource: 'auto',
    renderBackground: true,
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [activeRun, setActiveRun] = useState(0)
  const [error, setError] = useState('')

  const pdfUrl = useMemo(() => {
    if (!result) return ''
    const run = result?.runs?.[activeRun]
    const path = run?.outputPdfPath || result?.outputPdfPath
    if (!path) return ''
    return `${API}/api/file?path=${encodeURIComponent(path)}`
  }, [result, activeRun])

  const onRun = async () => {
    setLoading(true)
    setError('')
    setResult(null)
    setActiveRun(0)
    try {
      const resp = await fetch(`${API}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data?.detail || 'Run failed')
      setResult(data)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <h1>PaddleOCR-VL 视觉一比一实验台</h1>
      <div className="grid">
        <label>输入PDF路径</label>
        <input value={form.inputPdf} onChange={(e) => setForm({ ...form, inputPdf: e.target.value })} />

        <label>输出目录</label>
        <input value={form.outputDir} onChange={(e) => setForm({ ...form, outputDir: e.target.value })} />

        <label>VL API</label>
        <input value={form.apiBase} onChange={(e) => setForm({ ...form, apiBase: e.target.value })} />

        <label>OCR引擎</label>
        <select value={form.ocrEngine} onChange={(e) => setForm({ ...form, ocrEngine: e.target.value })}>
          <option value="paddleocr-vl">paddleocr-vl</option>
          <option value="mineru">mineru</option>
          <option value="dotsocr">dotsocr</option>
        </select>

        <label>对比全部引擎</label>
        <input type="checkbox" checked={form.compareAllEngines} onChange={(e) => setForm({ ...form, compareAllEngines: e.target.checked })} />

        <label>MinerU API</label>
        <input value={form.mineruApiBase} onChange={(e) => setForm({ ...form, mineruApiBase: e.target.value })} placeholder="http://127.0.0.1:18000" />

        <label>DotsOCR API</label>
        <input value={form.dotsocrApiBase} onChange={(e) => setForm({ ...form, dotsocrApiBase: e.target.value })} placeholder="例如私有部署地址" />

        <label>DotsOCR 模型</label>
        <input value={form.dotsocrModel} onChange={(e) => setForm({ ...form, dotsocrModel: e.target.value })} />

        <label>DotsOCR Prompt</label>
        <input value={form.dotsocrPrompt} onChange={(e) => setForm({ ...form, dotsocrPrompt: e.target.value })} placeholder="可选" />

        <label>源语言</label>
        <input value={form.sourceLang} onChange={(e) => setForm({ ...form, sourceLang: e.target.value })} />

        <label>目标语言</label>
        <input value={form.targetLang} onChange={(e) => setForm({ ...form, targetLang: e.target.value })} />

        <label>几何来源</label>
        <select value={form.geometrySource} onChange={(e) => setForm({ ...form, geometrySource: e.target.value })}>
          <option value="auto">auto</option>
          <option value="parsing">parsing</option>
          <option value="layout-hybrid">layout-hybrid</option>
        </select>

        <label>启用翻译</label>
        <input type="checkbox" checked={form.enableTranslate} onChange={(e) => setForm({ ...form, enableTranslate: e.target.checked })} />

        <label>保留背景</label>
        <input type="checkbox" checked={form.renderBackground} onChange={(e) => setForm({ ...form, renderBackground: e.target.checked })} />
      </div>

      <button onClick={onRun} disabled={loading}>{loading ? '运行中...' : '运行完整流程'}</button>

      {error && <pre className="error">{error}</pre>}
      {result && (
        <div className="result">
          <h2>结果</h2>
          <pre>{JSON.stringify(result, null, 2)}</pre>
          {Array.isArray(result.runs) && result.runs.length > 0 && (
            <>
              <h3>引擎结果切换</h3>
              <select value={activeRun} onChange={(e) => setActiveRun(Number(e.target.value))}>
                {result.runs.map((r, i) => (
                  <option key={`${r.engine}-${i}`} value={i}>{r.engine}</option>
                ))}
              </select>
            </>
          )}
          <h3>PDF预览</h3>
          <iframe src={pdfUrl} title="preview" />
        </div>
      )}
    </div>
  )
}
