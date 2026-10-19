import React, { useEffect, useRef, useState } from 'react';
import './audio.css';

async function api(path, options = {}) {
  const response = await fetch('/api/audio' + path, { ...options, headers: { 'X-Call-Review': '1', ...options.headers } });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
const post = (path, data = {}) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
const seconds = n => n == null ? '—' : `${Number(n).toFixed(1)} s`;
const states = ['Needs review', 'Technical issue', 'Legitimate interaction', 'Coaching follow-up', 'Escalated for authorized review'];

const activityColors = { speech: '#22a88a', quiet: '#8491a5', other_audio: '#e2a541' };

function VoiceActivity({ measurement, onSeek }) {
  const ref = useRef();
  useEffect(() => {
    if (!measurement || !ref.current) return;
    const canvas = ref.current, ctx = canvas.getContext('2d');
    const rows = [measurement.conversation, ...measurement.channels];
    const begin = measurement.scope.start_seconds, duration = measurement.scope.duration_seconds;
    canvas.width = 1200; canvas.height = rows.length * 28;
    rows.forEach((row, index) => {
      ctx.fillStyle = activityColors.other_audio; ctx.fillRect(0, index * 28, 1200, 22);
      ['quiet', 'speech'].forEach(kind => {
        ctx.fillStyle = activityColors[kind];
        row[kind + '_intervals'].forEach(interval => {
          ctx.fillRect((interval.start_seconds - begin) / duration * 1200, index * 28,
            (interval.end_seconds - interval.start_seconds) / duration * 1200, 22);
        });
      });
    });
  }, [measurement]);
  if (!measurement) return null;
  const begin = measurement.scope.start_seconds, end = measurement.scope.end_seconds;
  return <section className="voice-activity"><h3>Voice activity</h3><p className="muted">Speech detection across the available recording. Click a row or use the time slider to listen.</p><div className="activity-legend">{[['speech', 'Detected speech'], ['quiet', 'Quiet · no speech'], ['other_audio', 'Other sound · no speech']].map(([kind, label]) => <span key={kind}><i style={{ background: activityColors[kind] }} />{label}</span>)}</div><div className="activity-chart"><div className="activity-labels"><span>All channels</span>{measurement.channels.map(item => <span key={item.channel}>Channel {item.channel + 1}{item.role !== 'unknown' ? ' · ' + item.role : ''}</span>)}</div><canvas ref={ref} role="img" aria-label="Voice activity timeline showing detected speech, quiet and other audio for all channels and each separate channel" onClick={event => { const rect = event.currentTarget.getBoundingClientRect(); onSeek(begin + Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * (end - begin)); }} /></div><div className="audio-axis"><span>{seconds(begin)}</span><span>{seconds(end)}</span></div><label>Listen at time<input aria-label="Voice activity listening time" type="range" min={begin} max={end} step="0.1" defaultValue={begin} onChange={e => onSeek(Number(e.target.value))} /></label></section>;
}

function Spectrum({ data, onSeek }) {
  const ref = useRef();
  const [slice, setSlice] = useState(0);
  useEffect(() => { setSlice(0); }, [data]);
  useEffect(() => {
    if (!data || !ref.current) return;
    const canvas = ref.current, ctx = canvas.getContext('2d');
    const columns = data.spectrum.length, rows = data.frequencies_hz.length;
    canvas.width = columns; canvas.height = rows;
    data.spectrum.forEach((column, x) => column.forEach((db, y) => {
      const energy = Math.max(0, Math.min(1, (db + 100) / 100));
      ctx.fillStyle = `hsl(${245 - energy * 210} 75% ${8 + energy * 65}%)`;
      ctx.fillRect(x, rows - 1 - y, 1, 1);
    }));
  }, [data]);
  if (!data) return null;
  const index = Math.min(slice, data.top_k.length - 1), time = data.top_k[index]?.time_seconds;
  const fraction = (time - data.start_seconds) / (data.end_seconds - data.start_seconds);
  return <div className="audio-spectrum"><h3>Sound waves</h3><p className="muted">Wave height shows audio volume on Channel {data.channel + 1}. Click the waves to listen at that time.</p><svg viewBox="0 0 600 90" role="img" aria-label="Audio waveform showing sound amplitude over time" preserveAspectRatio="none" onClick={event => { const rect = event.currentTarget.getBoundingClientRect(); onSeek(data.start_seconds + (event.clientX - rect.left) / rect.width * (data.end_seconds - data.start_seconds)); }}><line x1="0" y1="45" x2="600" y2="45" stroke="currentColor" opacity=".25" />{data.waveform.map(([min, max], i) => <line key={i} x1={i * 600 / data.waveform.length} x2={i * 600 / data.waveform.length} y1={45 - max * 42} y2={45 - min * 42} stroke="currentColor" />)}<line x1={fraction * 600} x2={fraction * 600} y1="0" y2="90" stroke="var(--text-strong)" strokeDasharray="4 3" /></svg><div className="audio-axis"><span>{seconds(data.start_seconds)}</span><span>{seconds(data.end_seconds)}</span></div><h3>Sound spectrum</h3><canvas ref={ref} role="img" aria-label="Spectrum. Dark areas have lower audio energy; brighter areas have higher audio energy." /><div className="audio-axis"><span>0 Hz → {Math.round(data.frequencies_hz.at(-1))} Hz, bottom to top</span><span>Low energy → high energy</span></div><label>Frequency values at {seconds(time)}<input type="range" min="0" max={data.top_k.length - 1} step="1" value={index} onChange={e => setSlice(Number(e.target.value))} /></label><button className="text-button" onClick={() => onSeek(time)}>Listen from {seconds(time)}</button><div className="frequency-ranks">{[['Top K', 'Strongest frequencies', data.top_k], ['Min K', 'Weakest frequencies', data.min_k]].map(([heading, description, entries]) => { const item = entries?.[index]; return <section key={heading}><h3>{heading} · {data.k || 5}</h3><p className="muted">{description} at {seconds(time)}</p>{item?.frequencies_hz.length ? <table><thead><tr><th>Frequency</th><th>Level (dB, floor −100)</th></tr></thead><tbody>{item.frequencies_hz.map((hz, i) => <tr key={i}><td>{hz.toFixed(1)} Hz</td><td>{item.levels_db?.[i]?.toFixed(1) ?? '—'}</td></tr>)}</tbody></table> : <p>No measured energy in this slice.</p>}<p className="muted">Share of non-DC power: {item?.power_ratio == null ? 'No energy' : (100 * item.power_ratio).toFixed(2) + '%'}</p></section>; })}</div><p className="muted">{data.note} Min K lists the lowest-power frequency bins, including bins with no energy. Levels use the same Hann-window FFT scale as the spectrum and are floored at −100 dB; equal-power bins are ordered by frequency.</p></div>;
}

function Recording({ id, onClose }) {
  const [detail, setDetail] = useState(null), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [language, setLanguage] = useState('auto'), [start, setStart] = useState(0), [channel, setChannel] = useState(0), [k, setK] = useState(5);
  const [preview, setPreview] = useState(null), [previewJob, setPreviewJob] = useState(null), [busy, setBusy] = useState(false);
  const [reviewer, setReviewer] = useState(''), [note, setNote] = useState(''), [state, setState] = useState(states[0]);
  const player = useRef(), frozen = useRef(null), title = useRef(), autoPreview = useRef(false);
  const reload = async (latest = false) => {
    if (latest) frozen.current = null;
    const result = await api(`/recordings/${id}${frozen.current ? '?bundle_id=' + frozen.current : ''}`);
    if (!frozen.current && result.bundle_id) frozen.current = result.bundle_id;
    setDetail(result);
  };
  useEffect(() => {
    let stopped = false, timer;
    const poll = async () => { try { await reload(); } catch (e) { if (!stopped) setError(e.message); } if (!stopped) timer = setTimeout(poll, 2000); };
    poll(); title.current?.focus();
    return () => { stopped = true; clearTimeout(timer); };
  }, [id]);
  useEffect(() => {
    if (!previewJob) return;
    let stopped = false, timer;
    const poll = async () => { try {
      const job = await api('/jobs/' + previewJob);
      if (stopped) return;
      if (job.state === 'completed') { setPreview(job.result); setPreviewJob(null); }
      else if (['failed', 'cancelled'].includes(job.state)) { setError(job.message); setPreviewJob(null); }
      else timer = setTimeout(poll, 1000);
    } catch (e) { if (!stopped) { setError(e.message); setPreviewJob(null); } } };
    poll(); return () => { stopped = true; clearTimeout(timer); };
  }, [previewJob]);
  const action = async (fn) => { setBusy(true); setError(''); try { await fn(); await reload(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  const seek = (time, focus = true) => { if (player.current) { player.current.currentTime = time; if (focus) player.current.focus(); } };
  const recording = detail?.recording, measurement = detail?.measurement, transcript = detail?.transcript;
  const totals = measurement?.conversation?.totals;
  const requestPreview = async (from = Number(start), selectedChannel = channel, selectedK = k) => {
    const end = Math.min(from + 30, measurement.source.duration_seconds);
    const job = await api(`/recordings/${id}/preview?start=${from}&end=${end}&channel=${selectedChannel}&k=${selectedK}`);
    setPreview(null); setPreviewJob(job.id);
  };
  useEffect(() => {
    if (!measurement || autoPreview.current) return;
    autoPreview.current = true;
    const from = measurement.scope.start_seconds;
    setStart(from);
    requestPreview(from).catch(e => setError(e.message));
  }, [measurement]);
  return <section className="card audio-detail" aria-labelledby="recording-heading"><div className="audio-heading"><div><h2 id="recording-heading" tabIndex="-1" ref={title}>{recording?.filename || 'Opening recording…'}</h2><p>{recording?.transaction_ids?.join(', ') || 'Call link unresolved'} · {recording?.synthetic ? 'Generated audio' : 'Imported audio'}</p></div><button className="button secondary" onClick={onClose}>Back to recordings</button></div>{error && <p className="alert error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}{recording && <>
    <audio ref={player} controls preload="metadata" src={recording.media_url} aria-label="Retained call recording" />
    {recording.issue && <p className="alert error">{recording.issue}</p>}
    {detail.bundle_id && !detail.is_current && <div className="alert error">New evidence or a new workbook report is available. This view keeps the evidence you opened. <button className="button secondary" onClick={() => action(() => reload(true))}>Load latest evidence</button></div>}
    <div className="audio-metrics"><div><span>Available audio</span><strong>{seconds(measurement?.scope?.duration_seconds)}</strong></div><div><span>Quiet, no speech</span><strong>{seconds(totals?.quiet_seconds)}</strong></div><div><span>Longest quiet period</span><strong>{seconds(totals?.longest_quiet_seconds)}</strong></div><div><span>Other audio, no speech</span><strong>{seconds(totals?.other_audio_seconds)}</strong></div></div>
    <p>{measurement?.explanation || 'Audio measurements are queued. The original recording remains playable.'}</p><p className="muted">{measurement?.scope?.partial ? 'Partial recording: results cover only the available excerpt.' : 'Measurements describe the supplied recording; complete call coverage has not been verified.'} {measurement?.roles_verified_by_import ? 'Channel roles come from your CSV.' : 'Speaker roles are unknown.'}</p>
    {measurement?.warnings?.map((warning, i) => <p className="audio-warning" key={i}>{warning}</p>)}
    <VoiceActivity measurement={measurement} onSeek={time => seek(time, false)} />
    <h3>Quiet periods</h3><div className="audio-intervals">{measurement?.conversation?.quiet_intervals?.length ? measurement.conversation.quiet_intervals.slice(0, 50).map((interval, i) => <button className="button secondary" key={i} onClick={() => seek(interval.start_seconds)}>{seconds(interval.start_seconds)} – {seconds(interval.end_seconds)}</button>) : <p>No quiet intervals available.</p>}</div>
    {measurement?.conversation?.quiet_intervals?.length > 50 && <p className="muted">Showing the first 50 quiet intervals. Full interval measurements are retained with the analysis.</p>}
    {measurement?.source?.channels === 2 && <><h3>Separate channel measurements</h3><div className="audio-table-scroll"><table><thead><tr><th>Channel / supplied role</th><th>Detected speech</th><th>Quiet</th><th>No detected speech</th></tr></thead><tbody>{measurement.channels.map(item => <tr key={item.channel}><td>Channel {item.channel + 1} · {item.role === 'unknown' ? 'speaker unknown' : item.role}</td><td>{seconds(item.totals.speech_seconds)}</td><td>{seconds(item.totals.quiet_seconds)}</td><td>{seconds(item.totals.no_speech_seconds)}</td></tr>)}</tbody></table></div>{measurement.roles_verified_by_import && <details><summary>Customer speaking while agent has no detected speech</summary><p className="muted">These periods can be ordinary listening. Check the supplied channel map and listen before interpreting them.</p><div className="audio-intervals">{measurement.conversation.customer_speech_agent_no_speech_intervals.slice(0, 50).map((interval, i) => <button className="button secondary" key={i} onClick={() => seek(interval.start_seconds)}>{seconds(interval.start_seconds)} – {seconds(interval.end_seconds)}</button>)}</div></details>}</>}
    <h3>Inspect the audio</h3><div className="audio-controls"><label>Start (seconds)<input type="number" min="0" step="1" value={start} onChange={e => setStart(e.target.value)} /></label><label>Channel<select value={channel} onChange={e => setChannel(Number(e.target.value))}><option value="0">Channel 1</option>{measurement?.source?.channels === 2 && <option value="1">Channel 2</option>}</select></label><label>K frequencies<select value={k} onChange={e => setK(Number(e.target.value))}>{[1, 3, 5, 10, 20].map(value => <option key={value} value={value}>{value}</option>)}</select></label><button className="button secondary" disabled={busy || previewJob || !measurement} onClick={() => action(() => requestPreview())}>{previewJob ? 'Preparing sound waves and spectrum…' : 'Show next 30 seconds'}</button></div>{previewJob && <p role="status">Preparing sound waves, Top K and Min K…</p>}<Spectrum data={preview} onSeek={seek} />
    <h3>Transcript</h3><div className="audio-controls"><label>Language<select value={language} onChange={e => setLanguage(e.target.value)}><option value="auto">Detect English / Spanish</option><option value="en">English</option><option value="es">Spanish</option></select></label><button className="button primary" disabled={busy} onClick={() => action(async () => { await post(`/recordings/${id}/transcribe`, { language }); setNotice('Transcription queued. Load latest evidence when it is ready.'); })}>Transcribe locally</button></div>
    <p className="muted">Machine transcription can miss or change words. Listen to confirm. Transcript gaps are never used to measure silence.</p>
    {transcript ? <div className="audio-transcript">{transcript.segments.length ? transcript.segments.map((segment, i) => <div key={i}><button className="text-button" onClick={() => seek(segment.start_seconds)}>{seconds(segment.start_seconds)} · {segment.role && segment.role !== 'unknown' ? segment.role : `Channel ${segment.channel + 1} · speaker unknown`}</button><p>{segment.text}</p></div>) : <p>No speech was transcribed.</p>}</div> : <p>No transcript in this evidence view yet.</p>}
    <h3>Processing</h3>{detail.jobs.filter(job => job.operation !== 'preview').map(job => <div className="audio-job" key={job.id}><span>{job.operation === 'measure' ? 'Silence measurement' : 'Transcription'} · {job.state} · {job.message}</span>{['queued', 'running'].includes(job.state) ? <button className="text-button" onClick={() => action(() => post(`/jobs/${job.id}/cancel`))}>Cancel</button> : ['failed', 'cancelled'].includes(job.state) && <button className="text-button" onClick={() => action(() => post(`/jobs/${job.id}/retry`))}>Retry</button>}</div>)}
    <h3>Human review</h3><form className="audio-review" onSubmit={e => { e.preventDefault(); action(async () => { await post('/reviews', { recording_id: id, bundle_id: detail.bundle_id, publication_id: recording.publication_id, state, reviewer, note }); setNote(''); setNotice('Review saved against this recording and evidence version.'); }); }}><label>Outcome<select value={state} onChange={e => setState(e.target.value)}>{states.map(value => <option key={value}>{value}</option>)}</select></label><label>Reviewer<input value={reviewer} maxLength="120" required onChange={e => setReviewer(e.target.value)} /></label><label>What did you hear?<textarea value={note} maxLength="4000" required onChange={e => setNote(e.target.value)} /></label><button className="button primary" disabled={busy || !detail.is_current || !detail.bundle_id}>Save review</button></form>{detail.reviews.map(review => <p key={review.id}><strong>{review.state} · {review.reviewer}</strong><br />{review.note}</p>)}
    <details><summary>Measurement settings and source identity</summary><pre>{JSON.stringify({ source_sha256: recording.sha256, scope: measurement?.scope, settings: measurement?.settings, provenance: measurement?.provenance, bundle_id: detail.bundle_id }, null, 2)}</pre></details>
  </>}</section>;
}

export function CallAudioLinks({ transactions, publicationId, onOpen }) {
  const [links, setLinks] = useState(null), [error, setError] = useState('');
  const ids = transactions.map(row => row.transaction_id).join(',');
  useEffect(() => {
    let stopped = false;
    setLinks(null); setError('');
    if (ids) api(`/links?publication_id=${encodeURIComponent(publicationId)}&transaction_ids=${encodeURIComponent(ids)}`).then(result => { if (!stopped) setLinks(result); }).catch(e => { if (!stopped) setError(e.message); });
    return () => { stopped = true; };
  }, [ids, publicationId]);
  const found = Object.entries(links || {}).filter(([, values]) => values.length);
  return <section><h3>Audio for these call records</h3>{error ? <p>{error}</p> : !links ? <p>Checking recording links…</p> : !found.length ? <p>No linked recordings for these rows. Import their audio folder from Recordings.</p> : <div className="audio-intervals">{found.flatMap(([call, values]) => values.map(value => <button key={call + value.id} className="button secondary" onClick={() => onOpen(value.id)}>Call {call} · Listen and inspect</button>))}</div>}</section>;
}

export default function Audio({ report, initialRecording = null, onBack }) {
  const callFolderInput = useRef(), audioFolderInput = useRef();
  const [status, setStatus] = useState(null), [list, setList] = useState({ items: [], total: 0 }), [page, setPage] = useState(1);
  const [search, setSearch] = useState(''), [selected, setSelected] = useState(initialRecording), [callFiles, setCallFiles] = useState([]), [files, setFiles] = useState([]);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false), [sample, setSample] = useState(50);
  const [pendingImport, setPendingImport] = useState(null);
  const publication = report?.publication?.id;
  useEffect(() => {
    let stopped = false, timer;
    const poll = async () => { try {
      const [current, inventory] = await Promise.all([api('/status'), api(`/recordings?page=${page}&search=${encodeURIComponent(search)}${publication ? '&publication_id=' + publication : ''}`)]);
      if (!stopped) { setStatus(current); setList(inventory); }
    } catch (e) { if (!stopped) setError(e.message); } if (!stopped) timer = setTimeout(poll, 2000); };
    poll(); return () => { stopped = true; clearTimeout(timer); };
  }, [page, search, publication]);
  const action = async fn => { setBusy(true); setError(''); try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  const upload = async () => {
    if (!files.some(file => /\.(wav|mp3)$/i.test(file.name))) throw new Error('Choose a recordings folder containing WAV or MP3 files.');
    let activePublication = publication;
    if (callFiles.length) {
      setNotice('Importing Excel exports from all selected day folders…');
      const source = new FormData();
      callFiles.forEach(file => source.append('files', file));
      const relativePaths = callFiles.map(file => { const path = file.webkitRelativePath || file.name; return path.includes('/') ? path.slice(path.indexOf('/') + 1) : path; });
      source.append('paths', JSON.stringify(relativePaths));
      const uploadResponse = await fetch('/api/import', { method: 'POST', headers: { 'X-Call-Review': '1' }, body: source });
      const uploadResult = await uploadResponse.json();
      if (!uploadResponse.ok) throw new Error(uploadResult.detail || 'The Excel folder could not be imported.');
      const deadline = Date.now() + 15 * 60 * 1000;
      while (true) {
        const response = await fetch('/api/status');
        const progress = await response.json();
        if (!response.ok) throw new Error(progress.detail || 'Unable to check the Excel import.');
        if (progress.job?.state === 'failed') throw new Error(progress.job.message);
        if (progress.job?.state !== 'running') {
          activePublication = progress.publication?.id;
          if (!activePublication) throw new Error('The Excel folder did not produce a call report. Check the workbook import issues.');
          break;
        }
        if (Date.now() > deadline) throw new Error('Excel validation is still running. Wait for it to finish, then import the recordings using the current report.');
        setNotice(progress.job.message || 'Validating the selected Excel folders…');
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
    }
    if (!activePublication) throw new Error('Choose the folder of Excel call exports first, or load a call report from Imports.');
    const maps = files.filter(file => file.name.toLowerCase() === 'recordings.csv');
    if (maps.length > 1) throw new Error('The recordings folder has more than one recordings.csv. Keep one mapping file at its root.');
    let batch;
    if (maps.length) {
      const form = new FormData(); form.append('csv', maps[0]); form.append('publication_id', activePublication);
      batch = await api('/imports', { method: 'POST', body: form });
    } else {
      const paths = files.filter(file => /\.(wav|mp3)$/i.test(file.name)).map(file => { const path = file.webkitRelativePath || file.name; return path.includes('/') ? path.slice(path.indexOf('/') + 1) : path; });
      batch = await post('/imports/folder', { paths, publication_id: activePublication });
    }
    const byPath = new Map();
    files.forEach(file => { const path = file.webkitRelativePath || file.name; byPath.set(path, file); if (path.includes('/')) byPath.set(path.slice(path.indexOf('/') + 1), file); });
    const missing = batch.files.filter(item => item.state !== 'uploaded' && !byPath.has(item.recording_file));
    for (let index = 0; index < batch.files.length; index++) {
      const item = batch.files[index]; if (item.state === 'uploaded' || !byPath.has(item.recording_file)) continue;
      setNotice(`Retaining audio ${index + 1} of ${batch.files.length}…`);
      const body = new FormData(); body.append('recording_file', item.recording_file); body.append('file', byPath.get(item.recording_file));
      await api(`/imports/${batch.id}/files`, { method: 'POST', body });
    }
    if (missing.length) { setPendingImport(batch.id); throw new Error(`Missing ${missing.length} file(s), including ${missing[0].recording_file}. Retry with the matching folder, or finish this batch without the missing files.`); }
    setPendingImport(null);
    setNotice(`Audio retained; silence analysis queued. ${batch.issues.length ? `${batch.issues.length} call link(s) need attention; open those recordings to review the issue.` : 'Call IDs linked successfully.'}`);
  };
  if (selected) return <Recording key={selected} id={selected} onClose={() => { setSelected(null); onBack?.(); }} />;
  return <div className="audio-page"><div className="audio-heading"><div><h1>Call recordings</h1><p>Measure quiet periods, listen to the call, and transcribe the calls you need to review.</p></div>{report?.synthetic && <button className="button secondary" disabled={busy} onClick={() => action(async () => { await post('/fixtures'); setNotice('10 generated spoken recordings imported. Measurements and selected transcripts are queued.'); })}>Add included audio calls</button>}</div>{error && <p role="alert" className="alert error">{error}</p>}{notice && <p role="status" className="alert success">{notice}</p>}
    <section className="card audio-card"><h2>Local processing</h2><p>{status?.message || 'Checking audio tools…'}</p><p className="muted">{status?.profile}. Speech and audio stay on this computer after installation.</p>{status?.worker_error && <p className="alert error">{status.worker_error}</p>}<div className="audio-metrics">{['measure', 'transcribe'].map(operation => <div key={operation}><span>{operation === 'measure' ? 'Silence measurement' : 'Transcription'}</span><strong>{status?.stages?.[operation]?.completed || 0} ready</strong><small>{status?.stages?.[operation]?.queued || 0} queued · {status?.stages?.[operation]?.running || 0} running · {status?.stages?.[operation]?.failed || 0} failed</small></div>)}</div><p className="muted">{status?.capacity_note}</p><details><summary>Transcription selection</summary><p>All recordings are measured. Spreadsheet review candidates plus a reproducible sample are transcribed. Silence alone does not establish avoidance.</p><label>Quality sample per business day<input type="number" min="0" max="5000" value={sample} onChange={e => setSample(e.target.value)} /></label><button className="button secondary" disabled={busy} onClick={() => action(async () => { await post('/policy', { random_sample_size: Number(sample) }); setNotice('Sampling policy saved. Already selected transcripts are retained.'); })}>Save sample size</button><p>Current setting: {status?.policy?.random_sample_size ?? '—'}. Additional quiet-duration candidate selection is disabled by default.</p></details></section>
    <section className="card audio-card"><h2>Import call and recording folders</h2><p>Choose the parent folder containing all days of Excel call exports, then the folder containing the recordings. Subfolders are included automatically.</p><div className="audio-controls"><div className="audio-folder-choice"><span>1. Excel call exports — all days</span><button type="button" className="button secondary" disabled={busy} onClick={() => callFolderInput.current?.click()}>Choose Excel folder</button><input aria-label="Excel call exports folder" className="folder-input" ref={callFolderInput} type="file" webkitdirectory="" multiple disabled={busy} onChange={e => { setCallFiles(Array.from(e.target.files).filter(file => /\.xlsx$/i.test(file.name) || ['manifest.json', 'incidents.json'].includes(file.name))); setError(''); }} /><small>{callFiles.length ? `${callFiles.length} workbook and supporting files selected` : publication ? 'Optional: use the current call report, or choose a new folder' : 'Select the parent folder containing your daily exports'}</small></div><div className="audio-folder-choice"><span>2. Recordings folder</span><button type="button" className="button secondary" disabled={busy} onClick={() => audioFolderInput.current?.click()}>Choose recordings folder</button><input aria-label="Recordings folder" className="folder-input" ref={audioFolderInput} type="file" webkitdirectory="" multiple disabled={busy} onChange={e => { setFiles(Array.from(e.target.files)); setError(''); }} /><small>{files.length ? `${files.filter(file => /\.(wav|mp3)$/i.test(file.name)).length} recordings selected` : 'WAV and MP3 files, including nested day folders'}</small></div><button className="button primary" disabled={busy || !files.some(file => /\.(wav|mp3)$/i.test(file.name)) || (!publication && !callFiles.length)} onClick={() => action(upload)}>{busy ? 'Importing folders…' : 'Import both folders'}</button>{pendingImport && <button className="button secondary" disabled={busy} onClick={() => action(async () => { await post(`/imports/${pendingImport}/finish`); setPendingImport(null); setNotice('Batch finished with available recordings. Missing files remain listed as issues.'); })}>Finish without missing files</button>}</div><p className="muted">Recording names such as 70003501.wav link to that exact Excel transaction ID. If your filenames use a different format or you need channel roles, put recordings.csv inside the recordings folder; it is picked up automatically. Include the roster and coverage files used by your existing Excel import.</p></section>
    <section className="card audio-card"><div className="audio-heading"><h2>Recordings in this report <small>({list.total})</small></h2><label>Find a file or call ID<input type="search" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} /></label></div><div className="audio-table-scroll"><table><thead><tr><th>Recording / call</th><th>Call link</th><th>Quiet</th><th>Longest quiet</th><th>Measurement</th><th>Transcript</th><th /></tr></thead><tbody>{list.items.map(item => <tr key={item.id}><td><strong>{item.filename.split('/').at(-1)}</strong><br /><small>{item.transaction_ids.join(', ') || 'No matching call'}{item.synthetic ? ' · Generated' : ''}</small></td><td>{item.link_state}{item.issue && <p>{item.issue}</p>}</td><td>{seconds(item.quiet_seconds)}</td><td>{seconds(item.longest_quiet_seconds)}</td><td>{item.measurement_state}</td><td>{item.transcription_state}<br /><small>{item.selection_reasons.map(reason => reason.replaceAll('_', ' ')).join(', ')}</small></td><td><button className="button secondary" onClick={() => setSelected(item.id)}>Inspect</button></td></tr>)}</tbody></table></div>{!list.items.length && <p>Import a recording folder or add the included audio calls to begin.</p>}<div className="audio-controls"><button className="button secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page}</span><button className="button secondary" disabled={page * 25 >= list.total} onClick={() => setPage(page + 1)}>Next</button></div></section>
  </div>;
}
