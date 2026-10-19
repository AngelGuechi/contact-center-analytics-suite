import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import Audio, { CallAudioLinks } from './Audio';

const REVIEW_STATES = ['Needs review', 'Technical issue', 'Legitimate interaction', 'Coaching follow-up', 'Escalated for authorized review'];
const EMPTY_REPORT = { synthetic: false, coverage: {}, overview: {}, import_summary: {}, annotations: [], reconciliation: [], import_issues: [] };
const number = value => value == null ? '—' : new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value);
const percent = value => value == null ? '—' : new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 }).format(value);
const businessDate = value => value ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T12:00:00Z`)) : 'Awaiting data';
const timestamp = value => {
  if (!value || Number.isNaN(Date.parse(value))) return value || 'Not supplied';
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'America/Mexico_City' }).format(new Date(value));
};
const clock = value => {
  if (!value || Number.isNaN(Date.parse(value))) return '—';
  return new Intl.DateTimeFormat('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Mexico_City' }).format(new Date(value));
};

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'X-Call-Review': '1', ...options.headers } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : data.detail ? JSON.stringify(data.detail) : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return data;
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function Icon({ name, size = 20 }) {
  const paths = {
    desk: <><path d="M4 19V9m5 10V5m5 14v-7m5 7V3" /><path d="M2 21h20" /></>,
    daily: <><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M7 8h10M7 12h6M7 16h8" /></>,
    pulse: <><path d="M2 12h5l3-8 4 16 3-8h5" /></>,
    folder: <><path d="M3 7V4h6l3 3h9v13H3Z" /><path d="M3 11h18" /></>,
    rules: <><path d="M4 6h16M4 12h16M4 18h16" /><circle cx="8" cy="6" r="2" /><circle cx="16" cy="12" r="2" /><circle cx="10" cy="18" r="2" /></>,
    arrow: <><path d="m9 5 7 7-7 7" /></>,
    refresh: <><path d="M20 7a8 8 0 1 0 1 7" /><path d="M20 2v6h-6" /></>,
    search: <><circle cx="10" cy="10" r="6" /><path d="m15 15 6 6" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    check: <><path d="m5 12 4 4L19 6" /></>,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10v.1" /></>,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 6v6l4 2" /></>,
    shield: <><path d="m12 2 8 3v6c0 5-5 9-8 11-3-2-8-6-8-11V5Z" /><path d="m8 12 3 3 5-6" /></>,
    moon: <><path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z" /></>,
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5" /></>,
    copy: <><rect x="8" y="8" width="12" height="13" rx="2" /><path d="M16 8V3H3v13h5" /></>,
    print: <><path d="M6 9V3h12v6M6 17H3V9h18v8h-3" /><rect x="6" y="14" width="12" height="7" /><path d="M17 11h1" /></>,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.info}</svg>;
}

function Badge({ children, tone = '' }) { return <span className={`badge ${tone}`}>{children}</span>; }
function Empty({ title, children }) { return <div className="empty"><Icon name="desk" size={32} /><h3>{title}</h3><p>{children}</p></div>; }
function Person({ row }) {
  const initials = (row.name || row.agent_id || '?').replace('Synthetic ', '').split(' ').slice(0, 2).map(word => word[0]).join('');
  return <div className="person"><span className="avatar">{initials}</span><span><strong>{row.name || row.agent_id}</strong><small>{row.agent_id}</small></span></div>;
}
function originalCellValue(cell) {
  if (cell.value == null) return 'Blank';
  if (cell.type === 'timedelta' && typeof cell.value === 'object') {
    const seconds = (cell.value.days || 0) * 86400 + (cell.value.seconds || 0) + (cell.value.microseconds || 0) / 1000000;
    return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 6 }).format(seconds)} seconds`;
  }
  return typeof cell.value === 'object' ? JSON.stringify(cell.value) : String(cell.value);
}

function SourceRows({ sources = [], limit = 8 }) {
  if (!sources.length) return <p className="muted">The original source row is unavailable.</p>;
  return <div className="sources">{sources.slice(0, limit).map((source, index) => <div className="source-reference" key={`${source.file}-${source.row}-${index}`}>
    <strong>{source.file?.split(/[/\\]/).pop() || 'Source workbook'}</strong><span>{source.sheet} · row {source.row}</span>
    <details className="source-details"><summary>Original cells & file details</summary><p>{source.file}</p><small>File fingerprint: {source.sha256}</small>{source.raw_cells && <div className="table-scroll"><table className="original-cells"><thead><tr><th>Column</th><th>Original value</th><th>Type / Excel format</th></tr></thead><tbody>{Object.entries(source.raw_cells).map(([name, cell]) => <tr key={name}><td>{name}</td><td>{originalCellValue(cell)}</td><td>{cell.type}<small>{cell.number_format}</small></td></tr>)}</tbody></table></div>}</details>
  </div>)}{sources.length > limit && <p className="muted">Showing {limit} of {sources.length} original rows.</p>}</div>;
}

function IncidentContext({ annotations = [] }) {
  if (!annotations.length) return null;
  return <section className="incident-context"><h3>Incident notes</h3><p className="muted">Use these notes to understand what was happening. They do not change the calculated counts.</p>{annotations.map((annotation, index) => <div className="issue" key={annotation.annotation_id || index}><Badge tone="blue">{annotation.annotation_id || 'Incident annotation'}</Badge><p>{annotation.note}</p><small>{[annotation.site, annotation.agent_id ? `Agent ${annotation.agent_id}` : '', annotation.started_at || annotation.start ? timestamp(annotation.started_at || annotation.start) : '', annotation.ended_at || annotation.end ? timestamp(annotation.ended_at || annotation.end) : ''].filter(Boolean).join(' · ')}</small></div>)}</section>;
}

const EVIDENCE_PAGE_SIZE = 25;

function findingText(evidence) {
  const row = evidence.result;
  if (evidence.kind !== 'daily') return {
    title: 'Repeated periods of low average talk time',
    happened: `${number(row.delta_calls)} additional completed records between ${clock(row.started_at)} and ${clock(row.ended_at)}. Average from snapshot totals: ${number(row.mean_talk_seconds)} seconds of talk per added record.`,
    next: 'Check the original snapshots and incident notes. This is an aggregate lead that needs human review.',
  };
  const title = row.flagged ? 'Short records are higher than usual' : row.label === 'Low sample' ? 'Too few records to identify a daily pattern' : row.label?.startsWith('Incomplete day') ? 'This day is still incomplete' : row.label === 'No qualifying daily pattern' ? 'No daily pattern found' : row.label || 'Review the available records';
  const happened = `${number(row.signals)} of ${number(row.transactions)} call records ended within ${number(row.short_handle_seconds)} seconds without a transfer (${percent(row.rate)}).`;
  const next = row.flagged ? 'Review the short records and incident notes before recording your decision.' : row.label === 'Low sample' ? 'The records are visible below. More completed records are needed before a daily pattern can qualify.' : row.label?.startsWith('Incomplete day') ? 'Complete the daily exports before drawing a conclusion.' : row.label === 'Insufficient history' ? 'Add enough comparable history before drawing a conclusion.' : 'You can inspect the source records below, even when no pattern qualifies.';
  return { title, happened, next };
}

function ComparisonChart({ row }) {
  const bars = [
    { name: 'Today', rate: row.rate, signals: row.signals, transactions: row.transactions, available: true, current: true },
    { name: 'Team history', ...row.peer_baseline },
    { name: 'Agent history', ...row.self_baseline },
  ];
  const maximum = Math.max(0.1, ...bars.filter(bar => bar.available).map(bar => Number(bar.rate) || 0));
  return <div className="comparison-chart" aria-label="Short-record rate comparison"><p className="muted">Short / total records · same call type</p>{bars.map(bar => <div className={`comparison-row ${bar.current ? 'current' : ''}`} key={bar.name}><span>{bar.name}{bar.available && <small className="comparison-counts">{number(bar.signals)} / {number(bar.transactions)}</small>}</span><strong>{bar.available ? percent(bar.rate) : 'Not enough history'}</strong><div className="comparison-track" aria-hidden="true"><div className="comparison-fill" style={{ width: `${bar.available ? Math.min(100, Math.max(0, (bar.rate || 0) / maximum * 100)) : 0}%` }} /></div>{!bar.available && <small>{bar.unavailable_reasons?.join('. ') || 'No comparable history supplied'}</small>}</div>)}<small>Scale: 0%–{percent(maximum)} · team excludes this agent</small></div>;
}

function EvidenceDrawer({ evidenceId, sourcePublicationId, currentPublicationId, initialSignalsOnly = false, reportDate, generated, onClose, onSaved, onReload, onOpenAudio, annotations = [] }) {
  const dialog = useRef(null);
  const [evidence, setEvidence] = useState(null);
  const [page, setPage] = useState(1);
  const [scope, setScope] = useState('current');
  const [signalsOnly, setSignalsOnly] = useState(initialSignalsOnly);
  const [loadingTransactions, setLoadingTransactions] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState('');
  const [copied, setCopied] = useState('');
  const [form, setForm] = useState({ state: REVIEW_STATES[0], reviewer: '', note: '' });
  const evidenceUrl = () => `/api/evidence/${encodeURIComponent(evidenceId)}?${new URLSearchParams({ scope, page: String(page), page_size: String(EVIDENCE_PAGE_SIZE), signals_only: String(signalsOnly), ...(sourcePublicationId ? { publication_id: sourcePublicationId } : {}) })}`;
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    const cancel = event => { event.preventDefault(); onClose(); };
    element?.addEventListener('cancel', cancel);
    return () => { element?.removeEventListener('cancel', cancel); element?.close(); };
  }, [onClose]);
  useEffect(() => {
    const controller = new AbortController();
    setError(''); setLoadingTransactions(true);
    api(evidenceUrl(), { signal: controller.signal }).then(data => { if (!controller.signal.aborted) setEvidence(data); }).catch(err => { if (!controller.signal.aborted) setError(err.message); }).finally(() => { if (!controller.signal.aborted) setLoadingTransactions(false); });
    return () => controller.abort();
  }, [evidenceId, sourcePublicationId, page, scope, signalsOnly, retry]);
  const row = evidence?.result || {};
  const daily = evidence?.kind === 'daily';
  const archived = !!evidence && (evidence.is_current === false || !!(sourcePublicationId && currentPublicationId && sourcePublicationId !== currentPublicationId));
  const selectedTransactionsReady = !loadingTransactions && !error && (evidence?.scope || 'current') === scope && Boolean(evidence?.signals_only) === signalsOnly && evidence?.page === page;
  const explanation = evidence ? findingText(evidence) : null;
  const changeScope = value => { setPage(1); setScope(value); };
  const changeFilter = value => { setPage(1); setSignalsOnly(value); };
  const copySummary = async () => {
    const summary = [
      `${row.name || evidence.agent_id} · ${businessDate(evidence.report_date || reportDate)} · ${daily ? row.call_type : 'Intraday review'}`,
      explanation.title, explanation.happened,
      ...(daily ? [`Team history: ${row.peer_baseline?.available ? `${percent(row.peer_baseline.rate)} (${number(row.peer_baseline.signals)}/${number(row.peer_baseline.transactions)})` : 'Not enough history'}. Agent history: ${row.self_baseline?.available ? `${percent(row.self_baseline.rate)} (${number(row.self_baseline.signals)}/${number(row.self_baseline.transactions)})` : 'Not enough history'}.`] : []),
      explanation.next, 'Source measurements require human review and do not establish intent.',
      ...(generated ? ['Origin: generated records.'] : []),
      ...(archived ? ['This is a saved report; newer data is available.'] : []),
    ].join('\n');
    try { await navigator.clipboard.writeText(summary); setCopied('Summary copied.'); }
    catch { setCopied('Clipboard access is unavailable. Use Print / save PDF instead.'); }
  };
  const save = async event => {
    event.preventDefault();
    if (archived || !selectedTransactionsReady) return;
    setSaving(true); setError(''); setSaved('');
    try {
      await post('/api/reviews', { evidence_id: evidenceId, publication_id: sourcePublicationId, ...form });
      setEvidence(await api(evidenceUrl())); setSaved('Review saved on this computer.'); onSaved();
    } catch (err) { setError(err.message); } finally { setSaving(false); }
  };
  return <dialog className="evidence-drawer" ref={dialog} aria-labelledby="evidence-title"><div className="drawer-head"><div><span className="eyebrow">Agent inspection</span><h2 id="evidence-title">{row.name || evidence?.agent_id || 'Loading evidence…'}</h2>{evidence && <small>{businessDate(evidence.report_date || reportDate)} · {daily ? row.call_type : `${clock(row.started_at)} – ${clock(row.ended_at)}`}</small>}</div><button className="icon-button" aria-label="Close evidence" onClick={onClose}><Icon name="close" /></button></div><div className="drawer-body">
    {error && <div role="alert" className="alert error"><div><strong>Evidence could not be loaded.</strong><p>{error}</p><button className="text-button" onClick={() => setRetry(value => value + 1)}>Retry evidence</button> <button className="text-button" onClick={onReload}>Reload latest report</button></div></div>}
    {!evidence ? loadingTransactions ? <p className="loading" role="status">Loading the original records…</p> : <Empty title="No evidence loaded">Retry the request or reload the latest report. Your saved reviews are preserved.</Empty> : <>
      {archived && <div className="alert warning"><Icon name="info" /><div><strong>You are viewing a saved report.</strong><p>These original records are still available. Open the latest report before saving a new decision.</p><button className="text-button" onClick={onReload}>Reload latest report</button></div></div>}
      <div className="presentation-actions"><Badge tone={daily && row.flagged ? 'amber' : 'blue'}>{daily ? row.flagged ? 'Needs review' : row.label === 'No qualifying daily pattern' ? 'No pattern' : row.label : 'Intraday lead · review needed'}</Badge><div><button className="button secondary" disabled={!selectedTransactionsReady || saving} onClick={copySummary}><Icon name="copy" size={16} />Copy summary</button><button className="button secondary" disabled={!selectedTransactionsReady || saving} onClick={() => window.print()}><Icon name="print" size={16} />Print / save PDF</button></div></div>{copied && <p className="copy-status" role="status">{copied}</p>}
      <section className="finding-summary"><div><span className="eyebrow">What happened</span><h3>{explanation.title}</h3><p>{explanation.happened}</p><p className="finding-verdict"><strong>Next step:</strong> {explanation.next}</p></div>{daily ? <ComparisonChart row={row} /> : <div className="evidence-metrics"><div><span>Consecutive periods</span><strong>{number(row.interval_count)}</strong></div><div><span>Added records</span><strong>{number(row.delta_calls)}</strong></div><div><span>Average from talk totals</span><strong>{number(row.mean_talk_seconds)}s</strong></div></div>}</section>
      {daily ? <section className="call-evidence"><div className="segmented transaction-scopes" role="group" aria-label="Transaction evidence population">{[['current', 'Today', row.transactions], ['peer', 'Team history', evidence.baseline_counts?.peer ?? row.peer_baseline?.transactions], ['self', 'Agent history', evidence.baseline_counts?.self ?? row.self_baseline?.transactions]].map(([value, label, count]) => <button key={value} className={scope === value ? 'selected' : ''} aria-pressed={scope === value} disabled={loadingTransactions || saving} onClick={() => changeScope(value)}>{label}<span>{number(count)}</span></button>)}</div>
        <div className="section-title"><h3>{scope === 'current' ? 'Today’s original records' : scope === 'peer' ? 'Team history records' : 'Agent history records'}</h3><span>{selectedTransactionsReady ? `${number(evidence.transaction_count)} ${signalsOnly ? 'short records' : 'records'}${signalsOnly ? ` of ${number(evidence.population_count)}` : ''} · showing ${number((page - 1) * EVIDENCE_PAGE_SIZE + (evidence.transactions?.length ? 1 : 0))}–${number((page - 1) * EVIDENCE_PAGE_SIZE + (evidence.transactions?.length || 0))}` : loadingTransactions ? 'Loading records…' : 'Retry to load records'}</span></div>
        <div className="evidence-toolbar"><div className="segmented call-filter" role="group" aria-label="Record filter"><button aria-pressed={!signalsOnly} className={!signalsOnly ? 'selected' : ''} disabled={loadingTransactions || saving} onClick={() => changeFilter(false)}>All records</button><button aria-pressed={signalsOnly} className={signalsOnly ? 'selected' : ''} disabled={loadingTransactions || saving} onClick={() => changeFilter(true)}>Short records only</button></div><p className="evidence-help">Short record = ≤ {number(row.short_handle_seconds)}s and no transfer. Each row shows its original file.</p></div>
        <div className="table-scroll"><table className="transaction-table"><thead><tr><th>Record / time</th><th>Duration</th><th>Why counted</th><th>Original source</th></tr></thead><tbody>{!selectedTransactionsReady ? <tr><td colSpan={4} role="status">{loadingTransactions ? 'Loading the original records…' : 'Use Retry evidence to load this selection.'}</td></tr> : !evidence.transactions?.length ? <tr><td colSpan={4} className="no-records">{signalsOnly ? 'No records in this selection meet the short-duration rule.' : 'No call records are available in this selection.'}</td></tr> : evidence.transactions.map(transaction => {
          const isSignal = evidence.signal_transaction_ids?.includes(transaction.transaction_id);
          return <tr key={transaction.transaction_id} className={isSignal ? 'signal-row' : ''}><td><strong>{transaction.transaction_id}</strong><small>{timestamp(transaction.started_at)} → {clock(transaction.ended_at)}</small>{scope !== 'current' && <small>Agent {transaction.agent_id} · {transaction.login_id}</small>}<details className="source-details technical-detail"><summary>Connection & queue</summary><small>{transaction.connection_id}</small><small>{transaction.call_type} · queue {transaction.queue_code ?? transaction.queue ?? transaction.queue_id ?? 'Not supplied'}</small></details></td><td><strong>{number(transaction.duration_seconds)}s</strong></td><td><Badge tone={isSignal ? 'amber' : 'neutral'}>{isSignal ? 'Short record' : transaction.transfers > 0 ? 'Transferred' : 'Over threshold'}</Badge><small>{transaction.transfers > 0 ? 'Excluded from short count' : isSignal ? 'Included in short count' : `Over ${number(row.short_handle_seconds)}s`} · {number(transaction.holds)} holds</small></td><td><SourceRows sources={transaction.sources} limit={10} /></td></tr>;
        })}</tbody></table></div>{selectedTransactionsReady && evidence.transaction_count > EVIDENCE_PAGE_SIZE && <div className="pagination"><button className="button secondary" disabled={page === 1 || loadingTransactions || saving} onClick={() => setPage(value => value - 1)}>Previous</button><span>Page {page} of {Math.ceil(evidence.transaction_count / EVIDENCE_PAGE_SIZE)} · {EVIDENCE_PAGE_SIZE} records per page</span><button className="button secondary" disabled={page * EVIDENCE_PAGE_SIZE >= evidence.transaction_count || loadingTransactions || saving} onClick={() => setPage(value => value + 1)}>Next</button></div>}</section> : <section className="snapshot-evidence"><h3>Original snapshot evidence</h3><p className="muted">These changes come from cumulative totals. Individual call talk times are unavailable.</p><div className="table-scroll"><table><thead><tr><th>Period · local time</th><th>Added records</th><th>Added talk / handle time</th><th>Average talk from totals</th></tr></thead><tbody>{(evidence.intervals || [row]).map((interval, index) => <tr key={interval.evidence_id || index}><td>{clock(interval.started_at)} – {clock(interval.ended_at)}</td><td>{number(interval.delta_calls)}</td><td>{number(interval.delta_talk_seconds)}s / {number(interval.delta_handle_seconds)}s</td><td>{number(interval.mean_talk_seconds)}s</td></tr>)}</tbody></table></div><SourceRows sources={evidence.sources} limit={20} /></section>}
      {daily && selectedTransactionsReady && <CallAudioLinks transactions={evidence.transactions || []} publicationId={evidence.publication_id} onOpen={onOpenAudio} />}
      <IncidentContext annotations={evidence.annotations ?? annotations} />
      <details className="source-details calculation-details"><summary>Calculation details & report reference</summary><p>{row.note || row.deterministic_note}</p>{daily && <p>{number(row.transferred_transactions)} transferred records stay in the denominator. Team comparison: {row.peer_comparison?.ratio_label}, {number(row.peer_comparison?.increase_pp)} percentage points above history. Personal comparison: {row.self_comparison?.ratio_label}, {number(row.self_comparison?.increase_pp)} percentage points above history.</p>}<small>Evidence {evidenceId} · Rules {evidence.rule_version || 'Recorded with evidence'} · Report {evidence.publication_id || sourcePublicationId}</small></details>
      <section className="review-section"><span className="eyebrow">Your decision</span><h3>Record your review</h3><p className="muted">Save what you checked and what explains the measurements. This decision applies to the inspected finding.</p>{archived && <p className="muted">Reviewing is disabled for this saved report. Reload the latest report first.</p>}{saved && <div className="alert success" role="status"><Icon name="check" />{saved}</div>}<form onSubmit={save}><div className="form-two"><label>Outcome<select disabled={archived} value={form.state} onChange={event => setForm({ ...form, state: event.target.value })}>{REVIEW_STATES.map(state => <option key={state}>{state}</option>)}</select></label><label>Your name<input required disabled={archived} maxLength={120} value={form.reviewer} onChange={event => setForm({ ...form, reviewer: event.target.value })} placeholder="Reviewer name" /></label></div><label>What did you find?<textarea required disabled={archived} maxLength={4000} rows={3} value={form.note} onChange={event => setForm({ ...form, note: event.target.value })} placeholder="Describe the source records and context you checked." /></label><button className="button primary" disabled={saving || !selectedTransactionsReady || archived}>{saving ? 'Saving review…' : 'Save local review'}<Icon name="check" size={17} /></button></form></section>
      {!!evidence.reviews?.length && <section><h3>Saved decisions for this finding</h3>{[...evidence.reviews].reverse().map(review => <div className="review-record" key={review.id}><Badge tone="green">{review.state}</Badge><small>{review.reviewer} · {timestamp(review.timestamp)}</small><p>{review.note}</p></div>)}</section>}
      {!!evidence.earlier_reviews?.length && <details className="source-details"><summary>Earlier findings · {evidence.earlier_reviews.length} saved decisions</summary>{[...evidence.earlier_reviews].reverse().map(review => <div className="review-record" key={review.id}><Badge tone="neutral">{review.state}</Badge><small>{review.reviewer} · {timestamp(review.timestamp)}</small><p>{review.note}</p></div>)}</details>}
      <p className="presentation-footer">Source measurements require human review and do not establish intent.{generated ? ' Origin: generated records.' : ''}</p>
    </>}
  </div></dialog>;
}

function Daily({ report, openEvidence }) {
  const [supervisor, setSupervisor] = useState('');
  const [manager, setManager] = useState('');
  const [callType, setCallType] = useState('');
  const [search, setSearch] = useState('');
  const [onlyPatterns, setOnlyPatterns] = useState(false);
  const agents = report.daily?.agents || [];
  const rows = agents.flatMap(agent => agent.slices?.length ? agent.slices : [{ ...agent, call_type: 'No transactions', peer_baseline: {}, self_baseline: {} }]);
  const supervisors = [...new Set(agents.map(agent => agent.supervisor))].sort();
  const managers = [...new Set(agents.map(agent => agent.manager))].sort();
  const types = [...new Set((report.daily?.slices || []).map(row => row.call_type))].sort();
  const filtered = rows.filter(row => (!supervisor || row.supervisor === supervisor) && (!manager || row.manager === manager) && (!callType || row.call_type === callType) && (!onlyPatterns || row.flagged) && `${row.name} ${row.agent_id} ${row.login_id}`.toLowerCase().includes(search.toLowerCase()));
  return <><div className="page-intro"><div><span className="eyebrow">TODAY’S CALL REVIEW</span><h1>Daily patterns</h1><p>See who needs attention and open the original records behind each finding.</p></div><div className="segmented"><button aria-pressed={!onlyPatterns} className={!onlyPatterns ? 'selected' : ''} onClick={() => setOnlyPatterns(false)}>All agents</button><button aria-pressed={onlyPatterns} className={onlyPatterns ? 'selected' : ''} onClick={() => setOnlyPatterns(true)}>Patterns <span>{report.overview?.daily_patterns || 0}</span></button></div></div>
    <Stats report={report} />
    {!report.coverage?.report_date_complete && <div className="alert warning"><Icon name="info" /><div><strong>This day is incomplete.</strong> Observed transactions are descriptive; daily flags are suppressed. Missing expected exports: {report.coverage?.missing_expected_days?.join(', ') || 'Completeness not verified'}.</div></div>}
    <section className="card daily-card"><div className="card-heading"><div><h2>Agent review queue</h2><p>Open Inspect to see the summary and original rows. History compares the same call type over the prior {report.settings?.baseline_days} calendar days.</p></div><Badge tone="neutral">{filtered.length} rows</Badge></div><div className="filters"><label className="search-field"><span className="sr-only">Search agents</span><Icon name="search" size={18} /><input placeholder="Search agent or ID…" value={search} onChange={event => setSearch(event.target.value)} /></label><label><span className="sr-only">Supervisor</span><select value={supervisor} onChange={event => setSupervisor(event.target.value)}><option value="">All supervisors</option>{supervisors.map(value => <option key={value}>{value}</option>)}</select></label><label><span className="sr-only">Manager</span><select value={manager} onChange={event => setManager(event.target.value)}><option value="">All managers</option>{managers.map(value => <option key={value}>{value}</option>)}</select></label><label><span className="sr-only">Call type</span><select value={callType} onChange={event => setCallType(event.target.value)}><option value="">All call types</option>{types.map(value => <option key={value}>{value}</option>)}</select></label></div>
      {!filtered.length ? <Empty title="No matching agents">Try another filter or view all agents.</Empty> : <div className="table-scroll"><table className="daily-table"><thead><tr><th>Agent</th><th>Call type</th><th>Short records today</th><th title="Same-call-type rates in team and agent history">History rate</th><th>Review status</th><th><span className="sr-only">Evidence</span></th></tr></thead><tbody>{filtered.map(row => { const review = report.reviews?.[row.evidence_id]; return <tr key={`${row.agent_id}-${row.call_type}`}><td><Person row={row} /><small className="team-label">{row.supervisor}</small></td><td>{row.call_type}<small>{row.manager}</small></td><td><strong className={row.flagged ? 'rate attention' : 'rate'}>{percent(row.rate)}</strong><small>{number(row.signals)} short / {number(row.transactions)} records</small></td><td><div className="baseline-pair"><span>Team <strong>{row.peer_baseline?.available ? percent(row.peer_baseline.rate) : 'Unavailable'}</strong></span><span>Agent <strong>{row.self_baseline?.available ? percent(row.self_baseline.rate) : 'Unavailable'}</strong></span></div></td><td><Badge tone={review ? 'green' : row.flagged ? 'amber' : 'neutral'}>{review?.state || (row.flagged ? 'Needs review' : row.label === 'No qualifying daily pattern' ? 'No pattern' : row.label)}</Badge>{row.flagged && <small>Possible call avoidance</small>}{review && <small>Reviewed by {review.reviewer}</small>}</td><td>{row.evidence_id ? <button className="inspect" onClick={() => openEvidence(row.evidence_id, Boolean(row.flagged))} aria-label={`Inspect evidence for ${row.name}, ${row.call_type}`}>Inspect<Icon name="arrow" size={16} /></button> : <span className="muted no-records">No records to inspect</span>}</td></tr>; })}</tbody></table></div>}
      <div className="table-foot"><Icon name="info" size={16} /><span>A short record can reflect a legitimate call. Check its context before recording a decision.</span></div></section>
    <PooledSummary report={report} />
    <div className="below-grid"><section className="card concise"><span className="eyebrow">MEASUREMENT</span><h3>What is a short record?</h3><p>A completed call record that ends within the active duration limit and has no transfer. Transferred records stay in the total but do not count as short records.</p><a href="#rules" onClick={event => { event.preventDefault(); document.querySelector('[data-nav="rules"]')?.click(); }}>View active rules<Icon name="arrow" size={15} /></a></section><section className="card concise"><span className="eyebrow">COVERAGE</span><h3>{report.coverage?.baseline_complete ? 'Complete comparison window' : 'Comparison history is incomplete'}</h3><p>{report.coverage?.baseline_complete ? 'Every required prior calendar day is present and accepted. Each comparison also needs its own minimum transaction count.' : `Missing or incomplete dates: ${report.coverage?.missing_baseline_days?.join(', ') || 'Not supplied'}. These baselines cannot create a flag.`}</p><small>Current roster applies to historical comparisons.</small></section></div>
  </>;
}

function Stats({ report }) {
  const tiles = [
    ['Records today', number(report.overview?.transactions), 'Completed call records in the source', 'daily', ''],
    ['Agents to review', number(report.overview?.daily_patterns), 'Short-record patterns needing a closer look', 'shield', 'warm'],
    ['Intraday leads', number(report.overview?.intraday_leads), 'Low talk time across snapshot periods', 'pulse', ''],
    ['History available', `${(report.coverage?.baseline_days?.length || 0) - (report.coverage?.missing_baseline_days?.length || 0)} / ${report.settings?.baseline_days || 14}`, 'Complete prior calendar days', 'check', ''],
  ];
  return <div className="stats">{tiles.map(([label, value, note, icon, tone]) => <section className={`stat card ${tone}`} key={label}><div className="stat-top"><span>{label}</span><Icon name={icon} size={20} /></div><strong>{value}</strong><small>{note}</small></section>)}</div>;
}

function PooledSummary({ report }) {
  const rollups = report.daily?.rollups || {};
  const rows = [
    { ...rollups.site, scope: 'Site' },
    ...(rollups.supervisors || []).map(row => ({ ...row, scope: 'Supervisor' })),
    ...(rollups.managers || []).map(row => ({ ...row, scope: 'Manager' })),
  ];
  return <section className="card concise pooled-summary"><details><summary><span><strong>Pooled site & leadership rates</strong><small>Descriptive totals across all call types</small></span><span className="site-pool"><strong>{percent(rollups.site?.rate)}</strong><small>{number(rollups.site?.signals)} signals / {number(rollups.site?.transactions)} transactions · site</small></span></summary><p className="muted">These rates pool signals and transactions from the full analyzed day. Queue filters do not change these site and leadership totals. All-type rates are descriptive; different call mixes can explain a difference.</p><div className="table-scroll"><table><thead><tr><th>Scope</th><th>Site / leader</th><th>Signals / transactions</th><th>Pooled rate</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.scope}-${row.name}-${index}`}><td>{row.scope}</td><td>{row.name}{row.comparison_supported === false && <small>Unmapped context · excluded from named comparisons</small>}</td><td>{number(row.signals)} / {number(row.transactions)}</td><td>{percent(row.rate)}</td></tr>)}</tbody></table></div></details></section>;
}

function Intraday({ report, openEvidence }) {
  const [showIntervals, setShowIntervals] = useState(false);
  const [search, setSearch] = useState('');
  const [supervisor, setSupervisor] = useState('');
  const [manager, setManager] = useState('');
  const agents = report.daily?.agents || [];
  const supervisors = [...new Set(agents.map(agent => agent.supervisor))].sort();
  const managers = [...new Set(agents.map(agent => agent.manager))].sort();
  const identities = Object.fromEntries(agents.map(agent => [agent.agent_id, agent]));
  const matches = row => (!supervisor || row.supervisor === supervisor) && (!manager || row.manager === manager) && `${row.name || ''} ${row.agent_id || ''} ${row.login_id || ''}`.toLowerCase().includes(search.toLowerCase());
  const leads = (report.intraday?.leads || []).filter(matches);
  const intervals = (report.intraday?.intervals || []).filter(matches);
  const issues = (report.intraday?.issues || []).filter(issue => !issue.agent_id || matches(identities[issue.agent_id] || { agent_id: issue.agent_id }));
  return <><div className="page-intro"><div><span className="eyebrow">CHECK ACTIVITY DURING THE DAY</span><h1>Intraday leads</h1><p>See repeated periods of low average talk time, then check the original snapshots.</p></div><Badge tone="blue">Weak leads · human review</Badge></div><div className="alert info"><Icon name="info" /><div>These leads use changes between cumulative snapshots. They have no per-call talk evidence, call-type comparison, or ghost-call count.</div></div><section className="card"><div className="card-heading"><div><h2>Low aggregate talk time</h2><p>{report.settings?.intraday_consecutive_intervals} consecutive qualifying intervals create one lead. Further qualifying intervals extend the same evidence.</p></div><Badge tone="neutral">{leads.length} leads</Badge></div><div className="filters"><label className="search-field"><span className="sr-only">Search intraday agents</span><Icon name="search" size={18} /><input placeholder="Search agent or ID…" value={search} onChange={event => setSearch(event.target.value)} /></label><label><span className="sr-only">Intraday supervisor</span><select value={supervisor} onChange={event => setSupervisor(event.target.value)}><option value="">All supervisors</option>{supervisors.map(value => <option key={value}>{value}</option>)}</select></label><label><span className="sr-only">Intraday manager</span><select value={manager} onChange={event => setManager(event.target.value)}><option value="">All managers</option>{managers.map(value => <option key={value}>{value}</option>)}</select></label></div>{!leads.length ? <Empty title={search || supervisor || manager ? "No matching weak leads" : "No qualifying weak leads"}>{search || supervisor || manager ? "Try another agent or leadership filter." : "The available adjacent intervals have not met the active intraday rules."}</Empty> : <div className="table-scroll"><table><thead><tr><th>Agent</th><th>Local time range</th><th>Intervals / Added records</th><th>Added talk / handle</th><th>Review</th><th><span className="sr-only">Evidence</span></th></tr></thead><tbody>{leads.map(lead => <tr key={lead.evidence_id}><td><Person row={lead} /></td><td>{clock(lead.started_at)} – {clock(lead.ended_at)}<small>America/Mexico_City</small></td><td>{number(lead.interval_count)} intervals<small>{number(lead.delta_calls)} completed-transaction increase</small></td><td>{number(lead.delta_talk_seconds)}s / {number(lead.delta_handle_seconds)}s<small>Aggregate source totals</small></td><td><Badge tone={report.reviews?.[lead.evidence_id] ? 'green' : 'blue'}>{report.reviews?.[lead.evidence_id]?.state || 'Weak lead'}</Badge></td><td><button className="inspect" onClick={() => openEvidence(lead.evidence_id)}>Inspect<Icon name="arrow" size={16} /></button></td></tr>)}</tbody></table></div>}<div className="table-foot"><Icon name="clock" size={16} /><span>The first valid snapshot establishes an anchor. Gaps, decreased totals and zero-call intervals break the streak.</span></div></section><section className="card concise interval-section"><button className="expand-button" aria-expanded={showIntervals} onClick={() => setShowIntervals(value => !value)}><span>All observed intervals <small>{intervals.length} intervals</small></span><span>{showIntervals ? 'Hide' : 'Show'}<Icon name="arrow" size={16} /></span></button>{showIntervals && <div className="table-scroll"><table><thead><tr><th>Agent</th><th>Local time range</th><th>Added records</th><th>Mean talk / handle</th><th>Data status</th></tr></thead><tbody>{intervals.map((interval, index) => <tr key={interval.evidence_id || index}><td>{interval.name}</td><td>{clock(interval.started_at)} – {clock(interval.ended_at)}</td><td>{number(interval.delta_calls)}</td><td>{number(interval.mean_talk_seconds)}s / {number(interval.mean_handle_seconds)}s</td><td><Badge tone={!interval.valid ? 'amber' : interval.qualifies ? 'blue' : 'neutral'}>{interval.label}</Badge></td></tr>)}</tbody></table></div>}</section>{!!issues.length && <IssueList title="Intraday gaps & data quality" issues={issues} />}</>;
}

function IssueList({ title, issues = [] }) {
  return <section className="card concise"><h3>{title} <Badge tone="neutral">{issues.length}</Badge></h3>{!issues.length ? <p className="muted">No import issues reported.</p> : <div className="issue-list">{issues.slice(0, 100).map((issue, index) => <div className="issue" key={index}><Badge tone={issue.severity === 'error' ? 'amber' : 'neutral'}>{issue.code || issue.type || issue.severity || 'Source issue'}</Badge><p>{issue.message || issue.reason || JSON.stringify(issue)}</p><small>{[issue.file, issue.sheet, issue.row ? `row ${issue.row}` : '', issue.agent_id].filter(Boolean).join(' · ')}</small></div>)}{issues.length > 100 && <p>Showing the first 100 issues.</p>}</div>}</section>;
}

function Imports({ report, busy, onAction }) {
  const [files, setFiles] = useState([]);
  const [localError, setLocalError] = useState('');
  const input = useRef(null);
  const normalizedPaths = files.map(file => { const name = file.webkitRelativePath || file.name; return file.webkitRelativePath ? name.split('/').slice(1).join('/') : name; });
  const upload = async event => {
    event.preventDefault(); setLocalError('');
    if (!normalizedPaths.includes('manifest.json')) { setLocalError('Select the complete input folder with manifest.json at its root. A file date alone cannot establish complete coverage.'); return; }
    const form = new FormData(); files.forEach(file => form.append('files', file)); form.append('paths', JSON.stringify(normalizedPaths));
    await onAction(() => api('/api/import', { method: 'POST', body: form }), 'Import queued. The previous report remains available during validation.');
  };
  const summary = report.import_summary || {};
  return <><div className="page-intro"><div><span className="eyebrow">ORIGINAL WORKBOOKS & LINEAGE</span><h1>Imports</h1><p>Keep source workbooks intact, with every counted record traceable.</p></div></div><div className="below-grid"><section className="card concise"><span className="upload-symbol"><Icon name="upload" size={27} /></span><h2>Import a source folder</h2><p>Select its Admin workbook, Tool 1 snapshots, Tool 2 exports and manifest together. Relative subfolders are preserved.</p><div className="alert warning"><Icon name="info" size={18} /><span>Completeness needs an explicit manifest. Missing or rejected required daily files cannot create a daily pattern.</span></div><form onSubmit={upload}><input className="folder-input" type="file" ref={input} webkitdirectory="" multiple aria-label="Select input folder" onChange={event => { setFiles([...event.target.files].filter(file => /\.xlsx$/i.test(file.name) || ['manifest.json', 'incidents.json'].includes(file.name))); setLocalError(''); }} /><button className="button secondary" type="button" disabled={busy} onClick={() => input.current?.click()}><Icon name="folder" size={18} />Choose folder</button><span className="file-count">{files.length ? `${files.length} source files selected` : 'No folder selected'}</span>{localError && <p className="field-error" role="alert">{localError}</p>}{!!files.length && <details className="source-details"><summary>Selected paths</summary><ul className="path-list">{normalizedPaths.map(path => <li key={path}>{path}</li>)}</ul></details>}<div className="form-actions"><button className="button primary" disabled={busy || !files.length}>{busy ? 'Validating sources…' : 'Validate & import'}<Icon name="arrow" size={16} /></button></div></form></section><section className="card concise"><span className="eyebrow">REHEARSAL</span><h2>Load the synthetic demo</h2><p>A dedicated 15-day fixture includes a planted daily pattern, a weak intraday lead, transfers, low samples and a zero-transaction agent.</p><div className="demo-features"><span><Icon name="check" size={16} />14 complete history days</span><span><Icon name="check" size={16} />Original Excel source drill-down</span><span><Icon name="check" size={16} />Computed, source-backed notes</span></div><button className="button secondary" disabled={busy} onClick={() => onAction(() => post('/api/demo', {}), 'The synthetic demonstration is loading. Existing review history is preserved.')}>Load demonstration<Icon name="arrow" size={16} /></button><p className="muted">Loading the demo preserves source imports and review history.</p><div className="replay-controls"><span className="eyebrow">STEP THROUGH THE SYNTHETIC DAY</span><p>Replay a starting snapshot, then watch a weak lead arrive. Daily coverage is incomplete until step 4. Active rules and previous reviews are retained.</p><div className="replay-buttons">{[[1, "Start snapshot"], [2, "Next snapshot"], [3, "Lead arrives"], [4, "Complete day"]].map(([step, label]) => <button className="button secondary replay-step" key={step} disabled={busy} aria-label={`${step} ${label}`} onClick={() => onAction(() => post(`/api/replay/${step}`, {}), `Synthetic replay step ${step} is loading. Active rules and review history are preserved.`)}><strong>{step}</strong><span>{label}</span></button>)}</div></div></section></div><section className="card"><div className="card-heading"><div><h2>Latest source coverage</h2><p>{timestamp(report.publication?.published_at)} · {number(report.publication?.import_seconds)}s import{report.publication?.reused_normalized ? ' · validated workbook cache reused' : ''}</p></div><Badge tone={report.coverage?.report_date_complete ? 'green' : 'amber'}>{report.coverage?.status}</Badge></div><div className="import-counts">{[['Files accepted', summary.files_accepted], ['Files rejected', summary.files_rejected], ['Files missing', summary.files_missing], ['Duplicate transactions', summary.duplicate_transactions], ['Blank rows skipped', summary.blank_rows], ['Snapshots accepted', summary.snapshots]].map(([label, value]) => <div key={label}><strong>{number(value)}</strong><span>{label}</span></div>)}</div></section><IssueList title="Import issues" issues={report.import_issues || report.issues || []} />{!!report.annotations?.length && <section className="card concise"><h3>Incident notes</h3>{report.annotations.map((annotation, index) => <div className="issue" key={annotation.annotation_id || index}><Badge tone="blue">{annotation.annotation_id || 'Incident annotation'}</Badge><p>{annotation.note}</p><small>{[annotation.site, annotation.started_at || annotation.start, annotation.ended_at || annotation.end].filter(Boolean).join(' · ')}</small></div>)}</section>}<Reconciliation report={report} /></>;
}

function Reconciliation({ report }) {
  return <section className="card"><div className="card-heading"><div><h2>Latest source reconciliation</h2><p>Observed Tool 2 transactions compared with the latest accepted Tool 1 snapshot. Differences show Tool 2 minus Tool 1 when the Tool 2 day is complete. Both sources stay unchanged.</p></div><Badge tone={report.coverage?.report_date_complete ? 'green' : 'neutral'}>{report.report_date ? report.coverage?.report_date_complete ? 'Tool 2 day complete' : 'Tool 2 day incomplete' : 'No source report'}</Badge></div><div className="table-scroll"><table><thead><tr><th>Agent</th><th>Status</th><th>Tool 1 / observed Tool 2 transactions</th><th>Transaction difference</th><th>Handle-time difference</th></tr></thead><tbody>{report.reconciliation?.map(row => <tr key={row.agent_id}><td>{row.name}</td><td><Badge tone={row.label === 'Matching measured totals' ? 'green' : 'neutral'}>{row.label}</Badge></td><td>{number(row.tool1_calls)} / {number(row.tool2_transactions)}<small>{timestamp(row.captured_at)}</small></td><td>{number(row.calls_difference)}</td><td>{row.handle_seconds_difference == null ? '—' : `${number(row.handle_seconds_difference)}s`}</td></tr>)}</tbody></table></div></section>;
}

const RULES = [
  ['short_handle_seconds', 'Short-handle duration', 'Inclusive upper duration in seconds; transferred transactions are excluded from signals.', 'seconds'],
  ['daily_min_transactions', 'Minimum current transactions', 'Per agent and call type. Smaller slices show Low sample.', 'transactions'],
  ['daily_min_signals', 'Minimum short-handle signals', 'Current signal count required before either comparison can qualify.', 'signals'],
  ['daily_min_rate', 'Minimum current signal rate', 'The current numerator / denominator must meet this threshold.', '%'],
  ['baseline_days', 'Prior calendar-day window', 'Every required prior date must be complete; analyzed day is excluded.', 'days'],
  ['peer_min_transactions', 'Minimum peer transactions', 'Pooled same-type history, excluding the focal agent.', 'transactions'],
  ['self_min_transactions', 'Minimum personal transactions', 'Pooled same-type personal history.', 'transactions'],
  ['self_min_active_days', 'Minimum personal active days', 'Prior days with this agent and call type represented.', 'days'],
  ['rate_increase_pp', 'Minimum absolute rate increase', 'Current rate minus comparison rate, measured in percentage points.', 'points'],
  ['rate_multiplier', 'Minimum rate multiplier', 'A positive current rate can satisfy this with a zero baseline; the absolute rule still applies.', '×'],
  ['interval_min_minutes', 'Minimum snapshot spacing', 'Inclusive lower bound between adjacent accepted snapshots.', 'minutes'],
  ['interval_max_minutes', 'Maximum snapshot spacing', 'Inclusive upper bound. Invalid spacing breaks the consecutive streak.', 'minutes'],
  ['interval_min_transactions', 'Minimum interval transactions', 'Required completed-transaction increase in each interval.', 'transactions'],
  ['interval_max_mean_talk_seconds', 'Maximum interval mean talk', 'Aggregate talk increase divided by transaction increase; inclusive.', 'seconds'],
  ['intraday_consecutive_intervals', 'Consecutive qualifying intervals', 'Number of adjacent intervals needed for one weak lead.', 'intervals'],
];

function Rules({ report, busy, onAction }) {
  const [values, setValues] = useState({});
  const [localError, setLocalError] = useState('');
  useEffect(() => { setValues(Object.fromEntries(RULES.map(([key]) => [key, key === 'daily_min_rate' ? report.settings[key] * 100 : typeof report.settings[key] === 'object' ? report.settings[key].default ?? 15 : report.settings[key]]))); }, [report.settings]);
  const save = async event => {
    event.preventDefault(); setLocalError('');
    const data = Object.fromEntries(RULES.map(([key]) => [key, key === 'daily_min_rate' ? Number(values[key]) / 100 : Number(values[key])]));
    if (Object.values(data).some(value => !Number.isFinite(value))) { setLocalError('Enter a valid number for every rule.'); return; }
    await onAction(() => post('/api/settings', data), 'Rules saved. New evidence is ready; earlier decisions remain attached to their original evidence.');
  };
  return <><div className="page-intro"><div><span className="eyebrow">NAMED DEMONSTRATION SETTINGS</span><h1>Rules</h1><p>Every flag and lead comes from these deterministic measurements.</p></div><Badge tone="blue">Active version · {report.settings?.version || 'Recorded with evidence'}</Badge></div><div className="alert warning"><Icon name="info" /><div><strong>These are synthetic demonstration choices.</strong> Thresholds and comparison cohorts need client confirmation before operational use. Saving settings recalculates evidence and preserves earlier reviews.</div></div>{typeof report.settings?.short_handle_seconds === 'object' && <div className="alert warning">Call-type duration overrides are active. This form replaces them with one common duration threshold.</div>}<form className="card rule-form" onSubmit={save}><div className="card-heading"><div><h2>Daily patterns & intraday leads</h2><p>Both the absolute increase and rate multiplier must qualify. Rates use exact counts; rounding is display only.</p></div></div><div className="rules-grid">{RULES.map(([key, label, description, unit], index) => <label className="rule-field" key={key}><span><span className="rule-number">{String(index + 1).padStart(2, '0')}</span>{label}</span><div className="unit-input"><input type="number" required min={['daily_min_rate', 'short_handle_seconds', 'rate_increase_pp', 'rate_multiplier', 'interval_min_minutes', 'interval_max_minutes', 'interval_max_mean_talk_seconds'].includes(key) ? 0 : 1} max={['daily_min_rate', 'rate_increase_pp'].includes(key) ? 100 : undefined} step={['daily_min_rate', 'rate_increase_pp', 'rate_multiplier', 'interval_min_minutes', 'interval_max_minutes', 'interval_max_mean_talk_seconds', 'short_handle_seconds'].includes(key) ? 'any' : 1} value={values[key] ?? ''} onChange={event => setValues({ ...values, [key]: event.target.value })} /><span>{unit}</span></div><small>{description}</small></label>)}</div>{localError && <p role="alert" className="field-error">{localError}</p>}<div className="rule-footer"><span>Changing rules creates new evidence for human review.</span><button className="button primary" disabled={busy}>Save & recalculate<Icon name="check" size={17} /></button></div></form><section className="card concise"><h3>Unavailable measurements</h3><p className="muted">The current exports cannot support the following signals:</p><div className="capabilities">{report.unavailable_signals?.map(signal => <Badge tone="neutral" key={signal}>{signal}</Badge>)}</div></section></>;
}

function initialTheme() {
  try {
    const saved = localStorage.getItem('call-review-theme');
    if (saved === 'light' || saved === 'dark') return saved;
  } catch { /* Theme controls still work when browser storage is blocked. */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function App() {
  const [theme, setTheme] = useState(initialTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('call-review-theme', theme); } catch { /* Keep this session usable. */ }
  }, [theme]);
  const [view, setView] = useState('daily');
  const [audioSelection, setAudioSelection] = useState(null);
  const [report, setReport] = useState(null);
  const [job, setJob] = useState({ state: 'running', message: 'Preparing the local demonstration…' });
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [acting, setActing] = useState(false);
  const [evidenceSelection, setEvidenceSelection] = useState(null);
  const closeEvidence = useCallback(() => setEvidenceSelection(null), []);
  const openEvidence = (id, signalsOnly = false) => setEvidenceSelection({ id, publicationId: report?.publication?.id, reportDate: report?.report_date, signalsOnly });
  const publicationId = useRef(null);
  const refreshSequence = useRef(0);
  const reportLoaded = useRef(false);
  const pendingAction = useRef(false);
  const refresh = async () => {
    const sequence = ++refreshSequence.current;
    const result = await api('/api/report');
    if (sequence !== refreshSequence.current) return result;
    publicationId.current = result.publication?.id; reportLoaded.current = true;
    setReport(result); setJob(result.job || { state: 'done' }); return result;
  };
  useEffect(() => {
    let stopped = false;
    let timer;
    const poll = async () => {
      try {
        const status = await api('/api/status');
        if (stopped) return;
        setJob(status.job);
        if (status.has_report && (!reportLoaded.current || status.publication?.id !== publicationId.current)) await refresh();
        if (pendingAction.current && status.job?.state !== 'running') {
          pendingAction.current = false;
          setNotice(status.job?.state === 'failed' ? '' : status.job?.message || 'The saved source report is ready.');
        }
        if (status.job?.state === 'failed') { setError(status.job.message); setNotice(''); }
      } catch (err) { if (!stopped) setError(err.message); }
      if (!stopped) timer = setTimeout(poll, 1800);
    };
    poll(); return () => { stopped = true; clearTimeout(timer); };
  }, []);
  const onAction = async (action, message) => {
    setActing(true); setError(''); setNotice('');
    try {
      const result = await action();
      const status = await api('/api/status');
      setJob(status.job);
      pendingAction.current = status.job?.state === 'running';
      if (status.job?.state === 'failed') { setError(status.job.message); setNotice(''); }
      else setNotice(pendingAction.current || result.daily ? message : status.job?.message || 'Action completed.');
      if (status.has_report && !pendingAction.current) await refresh();
    }
    catch (err) { pendingAction.current = false; setNotice(''); setError(err.message); }
    finally { setActing(false); }
  };
  const busy = acting || job?.state === 'running';
  const nav = [['daily', 'daily', 'Daily patterns'], ['intraday', 'pulse', 'Intraday leads'], ['audio', 'pulse', 'Recordings'], ['imports', 'folder', 'Imports'], ['rules', 'rules', 'Rules']];
  let content;
  if (view === 'audio') {
    content = <Audio key={audioSelection || "inventory"} report={report} initialRecording={audioSelection} onBack={() => setAudioSelection(null)} />;
  } else if (report) {
    content = view === 'daily' ? <Daily report={report} openEvidence={openEvidence} /> : view === 'intraday' ? <Intraday report={report} openEvidence={openEvidence} /> : view === 'imports' ? <Imports report={report} busy={busy} onAction={onAction} /> : <Rules report={report} busy={busy} onAction={onAction} />;
  } else if (view === 'imports' && job?.state !== 'running') {
    content = <Imports report={EMPTY_REPORT} busy={busy} onAction={onAction} />;
  } else {
    content = <section className="card first-load">{job?.state === 'running' ? <span className="loading-dot" /> : <div className="empty-dataset-icon"><Icon name="folder" size={31} /></div>}<h1>{job?.state === 'running' ? 'Preparing your review desk' : job?.state === 'failed' ? 'The first report needs attention' : 'No dataset loaded'}</h1><p>{job?.state === 'running' || job?.state === 'failed' ? job.message : 'Choose the Imports tab to add your source folder, or load the synthetic demonstration.'}</p>{job?.state !== 'running' && <div className="empty-actions"><button className="button primary" onClick={() => setView('imports')}>Open Imports<Icon name="folder" size={17} /></button><button className="button secondary" disabled={busy} onClick={() => onAction(() => post('/api/demo', {}), 'Loading the synthetic demonstration.')}>Load demonstration</button></div>}</section>;
  }
  return <><a className="skip-link" href="#main-content">Skip to content</a><div className="app-shell"><aside className="sidebar"><div className="brand"><span className="brand-symbol"><Icon name="desk" size={25} /></span><div>Call review<span>SUPERVISOR DESK</span></div></div><div className="sidebar-label">WORKSPACE</div><nav aria-label="Main navigation">{nav.map(([id, icon, label]) => <button key={id} data-nav={id} className={view === id ? 'active' : ''} aria-current={view === id ? 'page' : undefined} onClick={() => setView(id)}><Icon name={icon} /><span>{label}</span>{id === 'daily' && report?.overview?.daily_patterns > 0 && <span className="nav-count">{report.overview.daily_patterns}</span>}{id === 'intraday' && report?.overview?.intraday_leads > 0 && <span className="nav-count">{report.overview.intraday_leads}</span>}</button>)}</nav><div className="sidebar-note"><span className="local-dot" /><strong>Local session</strong><p>Source evidence and human reviews stay on this computer.</p><span className="offline-label"><Icon name="shield" size={15} />Computed explanations</span></div><div className="sidebar-footer">{!report ? "LOCAL SESSION" : report.synthetic === false ? "LOCAL IMPORTED DATA" : "GENERATED DATA"}<span>Call Avoidance Detector · 05</span></div></aside><div className="main-shell"><header className="topbar"><span className="topbar-title">Call review desk</span><div className="topbar-actions"><button className="theme-toggle" role="switch" aria-checked={theme === 'dark'} aria-label="Dark mode" title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} onClick={() => setTheme(value => value === 'dark' ? 'light' : 'dark')}><Icon name={theme === 'dark' ? 'sun' : 'moon'} size={17} /><span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span></button><Badge tone={!report ? "neutral" : report.synthetic === false ? "blue" : "amber"}>{report ? report.synthetic === false ? "Imported data" : "Generated data" : job?.state === "running" ? "Preparing sources" : "No report loaded"}</Badge><span className="topbar-date"><Icon name="clock" size={16} />{businessDate(report?.report_date)}</span><button className="icon-button refresh" aria-label="Refresh report" title="Refresh report" disabled={acting || !report} onClick={() => onAction(refresh, 'Showing the latest saved report.')}><Icon name="refresh" size={18} /></button></div></header><main id="main-content"><div className="freshness"><span><span className={job?.state === 'running' ? 'status-dot running' : 'status-dot'} />{job?.state === 'running' ? job.message : report ? `Snapshot ${timestamp(report.latest_source_time)} · Mexico City time` : job?.message}</span>{report && <span>Rules {report.settings?.version || 'recorded'} · {report.coverage?.status}</span>}</div>{error && <div role="alert" className="alert error"><Icon name="info" /><span>{error}{report && ' The last successful report remains visible with its original date.'}</span><button className="text-button" onClick={() => report ? onAction(refresh, "Latest saved report refreshed.") : setView("imports")}>{report ? "Retry" : "Open Imports"}</button><button className="icon-button" aria-label="Dismiss error" onClick={() => setError('')}><Icon name="close" size={16} /></button></div>}{notice && <div role="status" className="alert success"><Icon name="check" /><span>{notice}</span><button className="icon-button" aria-label="Dismiss message" onClick={() => setNotice('')}><Icon name="close" size={16} /></button></div>}{content}<footer className="main-footer"><Icon name="shield" size={16} /><span>Flags and leads require human review. Source measurements do not establish intent.</span><span>Local · source-backed · optional audio model</span></footer></main></div></div>{evidenceSelection && <EvidenceDrawer key={`${evidenceSelection.publicationId}-${evidenceSelection.id}`} evidenceId={evidenceSelection.id} sourcePublicationId={evidenceSelection.publicationId} currentPublicationId={report?.publication?.id} reportDate={evidenceSelection.reportDate} generated={report?.synthetic} initialSignalsOnly={evidenceSelection.signalsOnly} annotations={report?.annotations || []} onClose={closeEvidence} onOpenAudio={id => { closeEvidence(); setAudioSelection(id); setView("audio"); }} onSaved={() => refresh().catch(err => setError(err.message))} onReload={async () => { try { await refresh(); closeEvidence(); } catch (err) { setError(err.message); } }} />}</>;
}

createRoot(document.getElementById('root')).render(<App />);
