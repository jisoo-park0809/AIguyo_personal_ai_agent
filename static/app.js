// 커리큘럼 에이전트 프로토타입 - 화면 흐름
const SUBJECTS = ['웹 프론트엔드', '백엔드', '풀스택', '데이터 분석', 'AI/머신러닝', '클라우드/DevOps', '모바일 앱', '정보보안', '게임 개발', '기타'];

const MODE = {
  generate: { label: '커리큘럼 생성하기', step: '커리큘럼 생성안 미리보기', category: '커리큘럼 생성안', secondary: '다시 생성하기' },
  revise:   { label: '커리큘럼 수정하기', step: '수정안 미리보기', category: '수정안', secondary: '다시 생성하기' },
  validate: { label: '학생 입장에서 검증하기', step: '검증 반영안 미리보기', category: '검증 반영안', secondary: '다시 검증하기' },
};

const S = {
  mode: null,
  survey: null,
  original: null,            // 불러온(또는 생성된) 기준 커리큘럼
  curriculum: null,          // 지금 미리보기 중인 커리큘럼
  lastRevision: null,        // 수정 모드: 직전 수정안
  validation: null,
  validatedCurriculum: null, // 검증 대상이 된 커리큘럼
  regulations: [],
  documents: [],             // 신청 서류 묶음을 문서별로 나눈 결과
  docsFor: '',               // documents를 분석한 원문 (원문이 바뀌면 다시 분석)
  filled: { for: null, forms: {} }, // 미리보기에서 작성한 신청 서류 (for: 작성 기준이 된 커리큘럼)
  previewTab: 'curriculum',
  docsUsed: false,           // 넣은 서류로 생성·수정·검증을 한 번 했는지 (했으면 첫 화면으로 돌아갈 때 비운다)
};

const KIND_LABEL = { announcement: '공고·선정 방식', criteria: '심사 기준', form: '작성할 서류', other: '참고 자료' };

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ---------- 공통 ----------
async function api(path, body) {
  const opts = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `요청 실패 (${res.status})`);
  return data;
}

async function extractFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/extract', { method: 'POST', body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || '파일을 읽지 못했습니다.');
  return data.text;
}

async function withLoading(msg, fn) {
  $('#loading-msg').textContent = msg;
  $('#loading').hidden = false;
  try { return await fn(); }
  catch (e) { toast(e.message, { error: true }); throw e; }
  finally { $('#loading').hidden = true; }
}

let toastTimer;
function toast(msg, { error = false, action = null } = {}) {
  const el = $('#toast');
  el.className = error ? 'error' : '';
  el.innerHTML = `<span>${esc(msg)}</span>`;
  if (action) {
    const b = document.createElement('button');
    b.textContent = action.label;
    b.onclick = () => { el.hidden = true; action.fn(); };
    el.appendChild(b);
  }
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), action ? 8000 : 4000);
}

function show(name) {
  if (name === 'home' && S.docsUsed) clearDocs();
  if (name === 'survey') {
    const n = docsText().trim().length;
    $('#sv-docs-status').textContent = n ? `(넣은 공고·서류: ${n.toLocaleString()}자 ✓)` : '(넣은 공고·서류 없음)';
    updateCapacity();
  }
  $$('.screen').forEach((s) => (s.hidden = s.id !== `screen-${name}`));
  window.scrollTo(0, 0);
}

// 넣은 파일들: [{ name, text }]. 서버에는 파일 경계 표시와 함께 이어 붙인 원문을 보낸다
const joinFiles = (files) => files.map((f) => `===== 파일: ${f.name} =====\n${f.text}`).join('\n\n');
function splitFiles(text) {
  if (!text.trim()) return [];
  const parts = text.split(/^===== 파일: (.+?) =====\n?/m);
  const files = parts[0].trim() ? [{ name: '불러온 서류', text: parts[0].trim() }] : [];
  for (let i = 1; i < parts.length; i += 2) files.push({ name: parts[i], text: (parts[i + 1] || '').trim() });
  return files;
}
const docsText = () => joinFiles(S.files);
// 심사 기준도 같은 칸에 넣는다 (문서 구성 분석에서 심사 기준으로 분류된 부분을 쓴다)
const context = () => ({ application_docs: docsText(), criteria: '', documents: S.documents });

function store(key, val) { try { localStorage.setItem(key, val); } catch (e) { /* 저장 불가 환경 무시 */ } }
function restore(key) { try { return localStorage.getItem(key) || ''; } catch (e) { return ''; } }

// ---------- 시작 화면 ----------
S.files = splitFiles(restore('application_docs') || restore('business_plan'));
const setFiles = (files) => {
  S.files = files;
  store('application_docs', docsText());
  renderDocFiles();
};
// 예전에 따로 넣었던 심사 기준·불러온 원문은 파일 목록 끝에 붙인다
const appendDocs = (text) => setFiles([...S.files, ...splitFiles(text)]);
const oldCriteria = restore('criteria').trim();
if (oldCriteria && !docsText().includes(oldCriteria)) appendDocs(`===== 파일: 심사 기준 =====\n${oldCriteria}`);
store('criteria', '');
try {
  const saved = JSON.parse(restore('documents') || 'null');
  if (saved && saved.for === docsText()) Object.assign(S, { documents: saved.documents, docsFor: saved.for });
} catch (e) { /* 저장본이 깨졌으면 다시 분석 */ }

async function addDocFiles(files) {
  if (!files.length) return;
  const texts = await withLoading(`${files.map((f) => f.name).join(', ')} 읽는 중…`, () =>
    Promise.all(files.map(extractFile))).catch(() => null);
  if (!texts) return;
  // 같은 이름 파일은 새 것으로 바꾸고, 넣자마자 문서 구성을 나눈다
  const names = new Set(files.map((f) => f.name));
  setFiles([...S.files.filter((f) => !names.has(f.name)), ...files.map((f, i) => ({ name: f.name, text: texts[i].trim() }))]);
  analyzeDocs();
}

function renderDocFiles() {
  $('#doc-files').innerHTML = S.files.map((f, i) => `
    <li><span class="name">${esc(f.name)}</span><span class="muted small">${f.text.length.toLocaleString()}자</span></li>`).join('');
}

$('#docs-file').addEventListener('change', (ev) => {
  const files = [...ev.target.files];
  ev.target.value = '';
  addDocFiles(files);
});
const dz = $('#dropzone');
['dragenter', 'dragover'].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add('over'); }));
['dragleave', 'drop'].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove('over'); }));
dz.addEventListener('drop', (e) => addDocFiles([...e.dataTransfer.files]));
renderDocFiles();

async function analyzeDocs() {
  const text = docsText();
  if (!text.trim()) { S.documents = []; S.docsFor = ''; renderDocParts(); return true; }
  const data = await withLoading('서류 묶음을 문서별로 나누는 중…', () => api('/api/analyze', { text })).catch(() => null);
  if (!data) return false;
  S.documents = data.documents;
  S.docsFor = text;
  saveDocs();
  renderDocParts();
  return true;
}

// 한 번 작업에 쓴 서류는 다음 작업에 누적되지 않게 첫 화면에서 비운다
function clearDocs() {
  S.docsUsed = false;
  S.files = [];
  renderDocFiles();
  Object.assign(S, { documents: [], docsFor: '' });
  ['application_docs', 'documents'].forEach((k) => store(k, ''));
  renderDocParts();
}

// 작업이 끝나면 새로고침해도 예전 서류가 돌아오지 않게 저장본만 먼저 지운다 (진행 중인 화면은 그대로 쓴다)
function markDocsUsed() {
  S.docsUsed = true;
  ['application_docs', 'documents'].forEach((k) => store(k, ''));
}

const saveDocs = () => store('documents', JSON.stringify({ for: S.docsFor, documents: S.documents }));
const ensureAnalyzed = () => (S.docsFor === docsText() ? Promise.resolve(true) : analyzeDocs());


// 작성본은 원본 서식의 형식을 따른다 (한글 → .hwpx, 그 밖 → .docx)
const FORMAT_LABEL = { hwpx: '한글(.hwpx)', docx: 'Word(.docx)' };

function docPartsHtml(onlyForms) {
  const docs = onlyForms ? S.documents.filter((d) => d.kind === 'form') : S.documents;
  return docs.map((d) => `
    <label class="doc-part ${d.kind}">
      ${d.kind === 'form' ? `<input type="checkbox" data-doc="${esc(d.id)}" ${d.selected ? 'checked' : ''}>` : '<span class="dot"></span>'}
      <span class="kind">${KIND_LABEL[d.kind] || d.kind}</span>
      <span class="name">${esc(d.name)}</span>
      <span class="muted small">${d.text.length.toLocaleString()}자</span>
      ${d.kind === 'form' ? `<span class="fmt">${FORMAT_LABEL[d.output_format] || FORMAT_LABEL.docx}로 저장</span>` : ''}
    </label>`).join('');
}

function renderDocParts() {
  const stale = S.docsFor !== docsText();
  const home = $('#doc-parts');
  if (!docsText().trim()) {
    home.innerHTML = '<p class="muted small">파일을 넣으면 공고·심사 기준·작성할 서류로 나눠 보여드려요.</p>';
  } else if (stale) {
    home.innerHTML = '<p class="muted small">문서 구성을 나누는 중이에요. 작업을 고르면 자동으로 나눕니다.</p>';
  } else {
    home.innerHTML = (docPartsHtml(false) || '<p class="muted small">문서를 나누지 못했어요.</p>') +
      '<p class="muted small">체크한 작성할 서류는 저장할 때 원본과 같은 형식으로 작성됩니다. (한글 → .hwpx, Word → .docx, PDF·텍스트는 편집할 수 있게 .docx)</p>';
  }
  const forms = docPartsHtml(true);
  $('#form-list').innerHTML = forms ||
    '<p class="muted small">넣은 서류에서 작성할 서식을 찾지 못해 기본 사업계획서 양식으로 만듭니다.</p>';
  $$('input[data-doc]').forEach((c) => c.addEventListener('change', () => {
    const d = S.documents.find((x) => x.id === c.dataset.doc);
    if (d) d.selected = c.checked;
    saveDocs();
    renderDocParts();
    // 미리보기 중에 새로 체크한 서류는 바로 작성해서 탭에 넣는다
    if (!$('#screen-preview').hidden) fillMissingForms().then(renderPreviewTabs);
  }));
}

$$('.mode').forEach((btn) => btn.addEventListener('click', async () => {
  const mode = btn.dataset.mode;
  // 생성은 공고가 없어도 시작할 수 있다.
  if (!(await ensureAnalyzed())) return;
  resetFlow(mode);
  // 과정 정보 설문은 생성할 때만 받는다. 수정·검증은 불러온 커리큘럼에서 조건을 가져온다.
  if (mode === 'generate') show('survey');
  else if (mode === 'revise') showRevise();
  else showValidateInput();
}));

function showValidateInput() {
  refreshPickers();
  loadLearners();
  show('validate');
}

// 과정 조건 한 줄 요약 (새 입력이 없는 예전 저장본은 대상·수준·과목으로)
function surveyLabel(s) {
  if (!s) return '';
  if (s.total_hours || s.months) {
    return [s.subject, s.months ? `${s.months}개월` : '', s.total_hours ? `${s.total_hours}시간` : '',
      s.non_major_ratio != null ? `비전공 ${s.non_major_ratio}%` : ''].filter(Boolean).join(' · ');
  }
  return [s.target, s.level, s.subject].filter(Boolean).join(' · ');
}

// 붙여넣기·업로드한 커리큘럼은 저장된 과정 정보가 없으니 내용에서 추정한다
function inferSurvey(c) {
  const text = [c.title, c.summary, c.target_summary, ...(c.compliance_notes || [])].join(' ');
  const subject = SUBJECTS.find((s) => s !== '기타' && s.split('/').some((w) => text.includes(w.replace('웹 ', '')))) || c.title || '';
  return {
    target: /비전공/.test(text) || !/전공자/.test(text) ? '전공+비전공' : '전공',
    level: /심화/.test(text) ? '심화' : '일반',
    funding: 'KDT',
    subject,
    duration: c.total_weeks ? `${c.total_weeks}주` : '',
    intent: '',
    inferred: true,
  };
}

function resetFlow(mode) {
  Object.assign(S, { mode, survey: null, original: null, curriculum: null, lastRevision: null, validation: null, validatedCurriculum: null, regulations: [] });
  $('#survey-mode-label').textContent = MODE[mode].label;
  $('#revise-instruction').value = '';
  $$('.source-picker').forEach((p) => resetPicker(p));
}

// ---------- 설문 ----------
$('#subject-chips').innerHTML = SUBJECTS.map((s, i) =>
  `<label class="chip"><input type="radio" name="subject" value="${esc(s)}" ${i === 0 ? 'checked' : ''}> ${esc(s)}</label>`).join('');
$$('input[name=subject]').forEach((r) => r.addEventListener('change', () => {
  $('#subject-other').hidden = $('input[name=subject]:checked').value !== '기타';
}));

const radio = (name) => $(`input[name=${name}]:checked`).value;

const num = (id) => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };
const lines = (id) => $(id).value.split('\n').map((l) => l.trim()).filter(Boolean);
const weeksOf = (months) => Math.round(months * 52 / 12 * 10) / 10;

function readSurvey() {
  let field = radio('subject');
  if (field === '기타') field = $('#subject-other').value.trim();
  const track = $('#sv-track').value.trim();
  const subject = [field, track].filter(Boolean).join(' / ');
  const total = num('#sv-total'), months = num('#sv-months');
  const nonMajor = num('#sv-nonmajor');
  const tasks = lines('#sv-tasks').map((l) => {
    const [company, ...rest] = l.split(/\s+-\s+|\s*[|/]\s*/);
    return rest.length ? { company: company.trim(), title: rest.join(' - ').trim() } : { company: '', title: l };
  });
  return {
    // 기존 항목 (규정 검색·학생 페르소나·예전 저장본과 호환)
    target: nonMajor === 0 ? '전공' : '전공+비전공',
    level: '일반',
    funding: radio('profile'),
    subject,
    duration: [months ? `약 ${Math.round(weeksOf(months))}주` : '', total ? `${total}시간` : ''].filter(Boolean).join(' · '),
    intent: $('#intent').value.trim(),
    // 통합 입력 구성안
    owner: $('#sv-owner').value.trim(),
    total_hours: total, daily_hours: num('#sv-daily'), days_per_week: num('#sv-days'), months,
    training_mode: radio('mode'),
    target_desc: $('#sv-target').value.trim(), non_major_ratio: nonMajor,
    prior_experience: $('#sv-prior').value.trim(), learner_goal: $('#sv-goal').value.trim(),
    project_ratio: num('#sv-project'),
    required_subjects: $('#sv-required').value.split(',').map((x) => x.trim()).filter(Boolean),
    company_tasks: tasks,
    pass_score: num('#sv-pass'), budget_krw: num('#sv-budget'),
  };
}

// 기간이 총 훈련시간을 담을 수 있는지 바로 보여 준다
function updateCapacity() {
  const total = num('#sv-total'), daily = num('#sv-daily'), days = num('#sv-days'), months = num('#sv-months');
  const el = $('#sv-capacity');
  if (!months || !daily || !days) { el.textContent = ''; el.classList.remove('bad'); return; }
  const weeks = weeksOf(months), cap = Math.floor(weeks * days * daily);
  const short = total && total > cap;
  el.textContent = `${months}개월 ≈ ${weeks}주 · 주 ${days * daily}시간 → 최대 ${cap}시간까지 편성 가능` +
    (total ? (short ? ` (총 훈련시간 ${total}시간이 들어가지 않아요)` : ` (총 ${total}시간 ✓)`) : '');
  el.classList.toggle('bad', !!short);
}
['#sv-total', '#sv-daily', '#sv-days', '#sv-months'].forEach((id) => $(id).addEventListener('input', updateCapacity));

function surveyErrors(sv) {
  const errs = [];
  if (!sv.subject) errs.push('분야·직군');
  if (!sv.total_hours) errs.push('총 훈련시간');
  if (!sv.daily_hours) errs.push('1일 훈련시간');
  if (!sv.days_per_week) errs.push('주 훈련일');
  if (!sv.months) errs.push('기간(개월)');
  if (!sv.target_desc) errs.push('훈련 대상');
  if (!sv.intent) errs.push('교육 목적·설계 의도');
  const msgs = errs.length ? [`꼭 입력해야 하는 항목: ${errs.join(', ')}`] : [];
  if (sv.months && sv.total_hours && sv.daily_hours && sv.days_per_week &&
      sv.total_hours > Math.floor(weeksOf(sv.months) * sv.days_per_week * sv.daily_hours)) {
    msgs.push('기간이 총 훈련시간을 담지 못해요 (기간이나 1일·주 훈련시간을 늘려 주세요)');
  }
  return msgs;
}

$$('[data-intent]').forEach((b) => b.addEventListener('click', () => {
  const ta = $('#intent');
  ta.value = ta.value.trim() ? `${ta.value.trim()}\n${b.dataset.intent}` : b.dataset.intent;
  ta.focus();
}));

$('#survey-next').addEventListener('click', async () => {
  const survey = readSurvey();
  const errs = surveyErrors(survey);
  if (errs.length) { toast(errs.join('\n'), { error: true }); return; }
  $('#toast').hidden = true;  // 앞서 띄운 입력 오류 안내를 지운다
  S.survey = survey;
  const agent = /pipeline/.test($('#provider-badge').textContent);
  const data = await withLoading(agent ? '생성 agent가 규정을 확인하고 편성표를 만들어 점검하는 중… (1~2분 걸려요)' : '운영 규정을 찾고 커리큘럼을 생성하는 중…', () =>
    api('/api/generate', { context: context(), survey })).catch(() => null);
  if (!data) return;
  S.original = S.curriculum = data.curriculum;
  S.regulations = data.regulations;
  markDocsUsed();
  showPreview();
});

// ---------- 커리큘럼 불러오기 (붙여넣기 / 파일 / 자료실) ----------
function mountPicker(root) {
  root.appendChild($('#tpl-picker').content.cloneNode(true));
  $$('.tab', root).forEach((tab) => tab.addEventListener('click', () => {
    $$('.tab', root).forEach((t) => t.classList.toggle('active', t === tab));
    $$('.tab-body', root).forEach((b) => (b.hidden = b.dataset.body !== tab.dataset.tab));
    if (tab.dataset.tab === 'library') renderLibraryPick(root);
  }));
  $('.paste-load', root).addEventListener('click', async () => {
    const text = $('.paste-text', root).value;
    if (!text.trim()) { toast('커리큘럼 내용을 붙여넣으세요.', { error: true }); return; }
    const data = await withLoading('커리큘럼을 읽는 중…', () => api('/api/parse', { text })).catch(() => null);
    if (data) setLoaded(data.curriculum, '붙여넣은 문서');
  });
  $('.file-input', root).addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const data = await withLoading(`${file.name} 읽는 중…`, async () =>
      api('/api/parse', { text: await extractFile(file) })).catch(() => null);
    e.target.value = '';
    if (data) setLoaded(data.curriculum, file.name);
  });
}

async function renderLibraryPick(root) {
  const box = $('.lib-pick', root);
  box.innerHTML = '<p class="muted">불러오는 중…</p>';
  const lib = await api('/api/library').catch((e) => { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return null; });
  if (!lib) return;
  const entries = Object.values(lib).flat();
  if (!entries.length) { box.innerHTML = '<p class="muted">자료실이 비어 있습니다.</p>'; return; }
  box.innerHTML = entries.map((e, i) => `
    <button class="lib-item" data-i="${i}">
      <span class="tag">${esc(e.category)}</span><strong>${esc(e.title)}</strong>
      <span class="muted small">${esc(e.created_at.replace('T', ' '))}</span>
    </button>`).join('');
  $$('.lib-item', box).forEach((b) => b.addEventListener('click', async () => {
    const e = entries[+b.dataset.i];
    const full = await withLoading('자료실에서 불러오는 중…', () =>
      api(`/api/library/${encodeURIComponent(e.category)}/${encodeURIComponent(e.folder)}`)).catch(() => null);
    if (full) setLoaded(full.curriculum, `나의 자료실 > ${e.category} > ${e.title}`, full.survey);
  }));
}

function setLoaded(curriculum, label, survey = null) {
  S.original = S.curriculum = curriculum;
  S.lastRevision = null;
  S.originalLabel = label;
  S.survey = survey && survey.subject !== undefined ? survey : inferSurvey(curriculum);
  refreshPickers();
  $('#revise-base').hidden = true;
  toast('커리큘럼을 불러왔어요.');
}

function refreshPickers() {
  $$('.source-picker').forEach((root) => {
    const box = $('.loaded', root);
    if (!S.original) { box.hidden = true; return; }
    const c = S.original;
    const s = S.survey || {};
    box.hidden = false;
    box.innerHTML = `<span class="ok">불러옴</span> <strong>${esc(c.title)}</strong>
      <span class="muted small">${esc(S.originalLabel || '')} · 모듈 ${c.modules.length}개${c.total_weeks ? ` · ${c.total_weeks}주` : ''}</span>
      <span class="muted small full-row">과정 조건: ${esc(surveyLabel(s))}
        ${s.inferred ? '(커리큘럼 내용에서 추정)' : '(저장된 과정 정보)'} — 운영 규정 검색과 검증할 학생 유형에 쓰여요</span>`;
  });
}

function resetPicker(root) {
  $('.paste-text', root).value = '';
  $('.loaded', root).hidden = true;
}

// ---------- 수정 ----------
function showRevise() {
  refreshPickers();
  $('#revise-base').hidden = !S.lastRevision;
  show('revise');
  $('#revise-instruction').focus();
}

$('#revise-run').addEventListener('click', async () => {
  if (!S.original) { toast('먼저 수정할 커리큘럼을 불러오세요.', { error: true }); return; }
  const instruction = $('#revise-instruction').value.trim();
  if (!instruction) { toast('어떤 수정을 원하는지 입력하세요.', { error: true }); return; }
  const base = S.lastRevision && radio('revise-base') === 'latest' ? S.lastRevision : S.original;
  const data = await withLoading(/pipeline/.test($('#provider-badge').textContent) ? '생성 agent가 요청한 부분만 고치고 점검하는 중… (1분 정도 걸려요)' : '수정 요청을 반영하는 중…', () =>
    api('/api/revise', { context: context(), survey: S.survey, curriculum: base, instruction })).catch(() => null);
  if (!data) return;
  if (data.base) Object.assign(base, data.base);  // 버전 없던 원본은 v1로 기록됐다
  S.curriculum = S.lastRevision = data.curriculum;
  S.regulations = data.regulations;
  markDocsUsed();
  showPreview();
});

// ---------- 검증 ----------
$('#validate-run').addEventListener('click', () => {
  if (!S.original) { toast('먼저 검증할 커리큘럼을 불러오세요.', { error: true }); return; }
  runValidation(S.original, 'validate');
});

// from: 검증을 시작한 화면 ('validate' 입력 화면 | 'preview' 미리보기) - '아니오'를 누르면 이 화면으로 돌아간다
async function runValidation(curriculum, from) {
  const agent = /pipeline/.test($('#provider-badge').textContent);
  if (agent && !(S.learnerIds || []).length) { toast('검증할 학생을 한 명 이상 체크하세요.', { error: true }); return; }
  const n = agent ? S.learnerIds.length : 0;
  const data = await withLoading(agent ? `학생 ${n}명이 각자 커리큘럼을 수강해 보고 퀴즈 난이도까지 평가하는 중… (1~4분 걸려요. 합격 기준 근처면 다시 평가해요)` : '학생 역할별로 커리큘럼을 검토하는 중…', () =>
    api('/api/validate', { context: context(), survey: S.survey, curriculum, learner_ids: agent ? S.learnerIds : null })).catch(() => null);
  if (!data) return;
  S.validation = data.validation;
  S.validatedCurriculum = curriculum;
  S.validationFrom = from;
  S.regulations = data.regulations;
  markDocsUsed();
  renderValidation();
  show('validation');
}

const SEV = { '높음': 'high', '중간': 'mid', '낮음': 'low' };

function renderValidation() {
  const v = S.validation;
  const ver = S.validatedCurriculum.version ? ` v${S.validatedCurriculum.version}` : '';
  $('#validation-title').textContent = `「${S.validatedCurriculum.title}${ver}」 학생 역할별로 부족한 점이에요`;
  $('#validation-overall').textContent = v.overall;
  $('#quiz-fit').innerHTML = quizFitHtml(v.quiz_fit || []);
  $('#persona-list').innerHTML = v.personas.map((p) => `
    <div class="card persona">
      <div class="persona-head">
        <h2>${esc(p.persona)}</h2>
        ${p.score ? `<span class="score" title="만족도">${'★'.repeat(p.score)}${'☆'.repeat(Math.max(0, 5 - p.score))}</span>` : ''}
      </div>
      <p class="muted small">${esc(p.profile)}</p>
      ${p.strengths.length ? `<h3>좋은 점</h3><ul>${p.strengths.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>` : ''}
      <h3>부족한 점</h3>
      ${p.gaps.length ? p.gaps.map((g) => `
        <label class="gap">
          <input type="checkbox" value="${esc(g.id)}" ${g.severity === '낮음' ? '' : 'checked'}>
          <span>
            <span class="sev ${SEV[g.severity] || 'mid'}">${esc(g.severity)}</span>
            ${g.location ? `<span class="loc">${esc(g.location)}</span>` : ''}
            <span class="issue">${esc(g.issue)}</span>
            <span class="suggest">→ ${esc(g.suggestion)}</span>
          </span>
        </label>`).join('') : '<p class="muted">특별히 부족한 점이 없어요.</p>'}
    </div>`).join('');
  $$('#persona-list input[type=checkbox]').forEach((c) => c.addEventListener('change', updateGapCount));
  updateGapCount();
}

const selectedGaps = () => {
  const ids = new Set($$('#persona-list input:checked').map((c) => c.value));
  return S.validation.personas.flatMap((p) => p.gaps).filter((g) => ids.has(g.id));
};
const updateGapCount = () => ($('#gap-count').textContent = `(${selectedGaps().length}개 선택)`);

$('#apply-yes').addEventListener('click', async () => {
  const gaps = selectedGaps();
  if (!gaps.length) { toast('반영할 보완점을 하나 이상 체크하세요.', { error: true }); return; }
  const data = await withLoading(/pipeline/.test($('#provider-badge').textContent) ? '생성 agent가 고른 보완점을 반영하고 점검하는 중… (1분 정도 걸려요)' : '보완점을 반영하는 중…', () =>
    api('/api/apply-feedback', { context: context(), survey: S.survey, curriculum: S.validatedCurriculum, gaps })).catch(() => null);
  if (!data) return;
  if (data.base) Object.assign(S.validatedCurriculum, data.base);
  S.curriculum = data.curriculum;
  S.regulations = data.regulations;
  showPreview();
});

// '아니오' = 이번 검증 결과는 반영하지 않음. 미리보기 없이 검증을 시작한 화면으로 돌아간다.
$('#apply-no').addEventListener('click', () => {
  if (S.validationFrom === 'preview') show('preview');
  else showValidateInput();
  toast('검증 결과를 반영하지 않았어요.');
});

// ---------- 미리보기 ----------
// 체크한 신청 서류를 모두 작성한 뒤에 미리보기를 연다
async function showPreview() {
  const m = MODE[S.mode];
  await fillMissingForms();
  $('#preview-step').textContent = m.step;
  $('#save-hint').textContent = `나의 자료실 > ${m.category} 폴더에 커리큘럼 PPT · PDF와 신청 서류(원본 형식)를 묶어서 저장합니다.`;
  renderDocParts();
  $('#secondary-btn').textContent = m.secondary;
  renderPreview();
  renderRegs();
  renderMaterialsStatus();
  renderVersions('#version-list', '#version-card', S.curriculum, pickPreviewVersion);
  show('preview');
}

// ---------- 버전 (v1, v2, v3 …) ----------
async function renderVersions(boxSel, cardSel, cur, onPick) {
  const card = $(cardSel);
  if (!cur || !cur.lineage_id) { card.hidden = true; return; }
  const data = await api(`/api/versions/${cur.lineage_id}`).catch(() => null);
  if (!data || !data.versions.length) { card.hidden = true; return; }
  card.hidden = false;
  $(boxSel).innerHTML = data.versions.slice().reverse().map((v) => `
    <button class="version ${v.version === cur.version ? 'active' : ''}" data-v="${v.version}">
      <span><strong>v${v.version}</strong> ${esc(v.note)}</span>
      <span class="muted small">${esc(v.created_at.replace('T', ' ').slice(5, 16))}${v.parent ? ` · v${v.parent}에서` : ''}${v.materials ? ' · 학습 자료' : ''}</span>
      ${v.validation ? `<span class="small ${v.validation.verdict === '합격' ? 'ok' : 'bad-text'}">검증 ${esc(v.validation.verdict || '완료')}${v.validation.score != null ? ` ${v.validation.score}` : ''}</span>` : ''}
    </button>`).join('');
  $$(`${boxSel} [data-v]`).forEach((b) => b.addEventListener('click', async () => {
    if (+b.dataset.v === cur.version) return;
    const d = await withLoading(`v${b.dataset.v}을 불러오는 중…`, () => api(`/api/versions/${cur.lineage_id}/${b.dataset.v}`)).catch(() => null);
    if (d) onPick(d.curriculum);
  }));
}

function pickPreviewVersion(c) {
  S.curriculum = c;
  if (S.mode === 'revise') S.lastRevision = c;
  renderPreview();
  renderMaterialsStatus();
  renderVersions('#version-list', '#version-card', c, pickPreviewVersion);
}

// ---------- 학습 자료 (설명 → 실습, 퀴즈는 생성 단계에서 이미 있음) ----------
function renderMaterialsStatus() {
  const ms = S.curriculum.learning_materials || [];
  const meta = S.curriculum.materials_meta || {};
  $('#materials-status').textContent = ms.length
    ? `교과목 ${ms.length}개 자료 · 점검 통과 ${meta.checks_ok ?? '-'}/${ms.length}${meta.cost_krw ? ` · 약 ${meta.cost_krw}원` : ''}`
    : '교과목마다 설명 → 실습 자료를 만들어요. 퀴즈는 이미 들어 있어요.';
  $('#materials-btn').textContent = ms.length ? '학습 자료 다시 만들기' : '학습 자료 만들기';
}

$('#materials-btn').addEventListener('click', async () => {
  const old = S.curriculum;
  const data = await withLoading('교과목별 학습 자료(설명 → 실습)를 쓰는 중… (1분 정도 걸려요)', () =>
    api('/api/materials', { context: context(), survey: S.survey, curriculum: old })).catch(() => null);
  if (!data || old !== S.curriculum) return;
  S.curriculum = data.curriculum;
  // 같은 버전에 자료만 붙였으니 작성해 둔 신청 서류·수정 기준은 그대로 이어 쓴다
  if (S.filled.for === old) S.filled.for = S.curriculum;
  if (S.lastRevision === old) S.lastRevision = S.curriculum;
  if (S.original === old) S.original = S.curriculum;
  S.previewTab = 'materials';
  renderPreviewTabs();
  renderMaterialsStatus();
  renderVersions('#version-list', '#version-card', S.curriculum, pickPreviewVersion);
  toast('학습 자료를 만들었어요. 지금 버전에 함께 저장돼요.');
});

function materialsHtml(c) {
  const ms = c.learning_materials || [];
  if (!ms.length) return '<p class="muted">아직 학습 자료가 없어요.</p>';
  const quiz = (sid) => (c.quizzes || []).filter((q) => q.subject_id === sid);
  return `<header class="doc-head"><h1>${esc(c.title)} 학습 자료</h1>
    <p class="muted small">교과목마다 개념 설명 → 실습 → 퀴즈 순서예요. <mark>[작성 필요]</mark>는 확인해서 채워야 해요.</p></header>
    ${ms.map((m) => {
      const ck = m.checks || {};
      const warn = [ck.missing_topics?.length ? `자료에 없는 주요 내용: ${ck.missing_topics.join(', ')}` : '',
        ck.quiz_answers_not_explained?.length ? `설명에 없는 퀴즈 정답: ${ck.quiz_answers_not_explained.join(', ')}` : ''].filter(Boolean);
      return `<details class="module">
        <summary>${esc(m.title)} <span class="muted small">개념 ${m.sections.length} · 실습 ${m.practices.length}</span>
          ${warn.length ? '<span class="verdict verdict-check">확인 필요</span>' : '<span class="verdict verdict-ok">점검 통과</span>'}</summary>
        <div class="material">
          ${warn.length ? `<p class="small bad-text">${warn.map(esc).join('<br>')}</p>` : ''}
          <p>${markPlaceholders(m.overview)}</p>
          ${m.sections.map((s) => `<h3>${esc(s.title)}</h3><p>${markPlaceholders(s.explanation)}</p>
            ${s.example ? `<pre class="example">${markPlaceholders(s.example)}</pre>` : ''}`).join('')}
          ${m.practices.map((p) => `<h3>실습: ${esc(p.title)}</h3><p class="muted small">목표: ${esc(p.goal)}</p>
            <ol>${p.steps.map((x) => `<li>${markPlaceholders(x)}</li>`).join('')}</ol>
            <p><strong>확인할 결과</strong> ${esc(p.expected_result)}</p>
            ${p.hints.length ? `<p class="muted small">힌트: ${p.hints.map(esc).join(' / ')}</p>` : ''}`).join('')}
          ${m.summary_points.length ? `<h3>핵심 정리</h3>${list(m.summary_points)}` : ''}
          ${quiz(m.subject_id).length ? `<h3>퀴즈</h3>${quiz(m.subject_id).map((q) => q.questions.map((x, n) => `
            <div class="quiz-q"><p><strong>${n + 1}.</strong> ${esc(x.question)}</p>
              <ol class="choices">${x.choices.map((ch, i) => `<li class="${i === x.answer - 1 ? 'answer' : ''}">${MARKS[i]} ${esc(ch)}</li>`).join('')}</ol></div>`).join('')).join('')}` : ''}
        </div></details>`;
    }).join('')}`;
}

// ---------- 퀴즈 난이도 (학생 검증) ----------
const FIT = { '쉬움': 'check', '적절': 'ok', '어려움': 'bad' };
function quizFitHtml(rows) {
  if (!rows.length) return '';
  const names = [...new Set(rows.flatMap((r) => Object.keys(r.personas)))];
  return `<div class="card"><h2>퀴즈 난이도 (학생 수준에서)</h2>
    <p class="muted small">학생마다 교과목을 들은 뒤 퀴즈를 보고 판단했어요. 칸에 마우스를 올리면 이유가 보여요.</p>
    <div class="table-wrap"><table class="quiz-fit"><thead><tr><th>교과목</th>${names.map((n) => `<th>${esc(n.split(' · ')[0])}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((r) => `<tr><td>${esc(r.title)}</td>${names.map((n) => {
      const x = r.personas[n];
      return `<td>${x ? `<span class="verdict verdict-${FIT[x.fit] || 'check'}" title="${esc(x.note || '')}">${esc(x.fit)}</span>` : '-'}</td>`;
    }).join('')}</tr>`).join('')}</tbody></table></div></div>`;
}

// ---------- 검증할 학습자 유형 (c6f) ----------
S.learnerIds = (() => { try { return JSON.parse(restore('learner_ids') || 'null'); } catch (e) { return null; } })();
S.learnerTypes = [];

async function loadLearners() {
  // 학습자 유형 카드는 학생 검증 agent(pipeline)에서만 쓴다
  $('#learner-card').hidden = !/pipeline/.test($('#provider-badge').textContent);
  const d = await api('/api/learner-types').catch(() => null);
  S.learnerTypes = d ? d.types : [];
  const ids = new Set(S.learnerTypes.map((t) => t.id));
  S.learnerIds = (S.learnerIds || S.learnerTypes.filter((t) => !t.custom).map((t) => t.id)).filter((id) => ids.has(id));
  renderLearners();
}

function renderLearners() {
  $('#learner-list').innerHTML = S.learnerTypes.map((t) => `
    <label class="learner">
      <input type="checkbox" value="${esc(t.id)}" ${S.learnerIds.includes(t.id) ? 'checked' : ''}>
      <span class="learner-body"><strong>${esc(t.name)}</strong>
        <span class="muted small">${esc(t.summary)} · ${t.group === 'major' ? '전공자' : '비전공자'} · 하루 복습 ${t.review_hours_per_day}시간</span></span>
      ${t.custom ? `<button class="btn ghost small-btn danger-text" data-del-learner="${esc(t.id)}">삭제</button>` : ''}
    </label>`).join('');
  $('#learner-count').textContent = `${S.learnerIds.length}명 선택`;
  $$('#learner-list input').forEach((c) => c.addEventListener('change', () => {
    S.learnerIds = $$('#learner-list input:checked').map((x) => x.value);
    store('learner_ids', JSON.stringify(S.learnerIds));
    $('#learner-count').textContent = `${S.learnerIds.length}명 선택`;
  }));
  $$('[data-del-learner]').forEach((b) => b.addEventListener('click', async (e) => {
    e.preventDefault();
    const t = S.learnerTypes.find((x) => x.id === b.dataset.delLearner);
    if (!confirm(`학습자 유형 「${t.name}」을(를) 삭제할까요?`)) return;
    await fetch(`/api/learner-types/${encodeURIComponent(t.id)}`, { method: 'DELETE' });
    S.learnerIds = S.learnerIds.filter((id) => id !== t.id);
    store('learner_ids', JSON.stringify(S.learnerIds));
    loadLearners();
  }));
}

$('#lt-add').addEventListener('click', async () => {
  const form = {
    name: $('#lt-name').value, group: $('#lt-group').value, summary: $('#lt-summary').value,
    known_terms: $('#lt-known').value, knows_basics: $('#lt-basics').checked, unknown: $('#lt-unknown').value,
    project_experience: $('#lt-project').value, review_hours_per_day: $('#lt-review').value,
    cares_about: $('#lt-cares').value, dropout_signal: $('#lt-dropout').value,
  };
  if (!form.name.trim()) { toast('학습자 유형 이름을 입력하세요.', { error: true }); return; }
  const d = await api('/api/learner-types', form).catch(() => null);
  if (!d) return;
  ['#lt-name', '#lt-summary', '#lt-known', '#lt-unknown', '#lt-project', '#lt-cares', '#lt-dropout'].forEach((s) => ($(s).value = ''));
  $('#lt-basics').checked = false;
  $('.learner-add').open = false;
  S.learnerIds = [...(S.learnerIds || []), d.type.id];
  store('learner_ids', JSON.stringify(S.learnerIds));
  await loadLearners();
  toast(`「${d.type.name}」을(를) 추가했어요. 이번 검증에 포함돼요.`);
});

const list = (items) => (items && items.length ? `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '<p class="muted">-</p>');
const hours = (h) => (h ? `${h}시간` : '-');

// 미리보기: 커리큘럼과 체크한 신청 서류(미리 작성해 둔 것)를 탭으로 보여준다.
const selectedForms = () => S.documents.filter((d) => d.kind === 'form' && d.selected);

function filledForms() {
  if (S.filled.for !== S.curriculum) S.filled = { for: S.curriculum, forms: {} };
  return S.filled.forms;
}

function renderPreview() {
  S.previewTab = 'curriculum';
  renderPreviewTabs();
}

function renderPreviewTabs() {
  const forms = selectedForms();
  if (S.previewTab !== 'materials' && !forms.some((d) => d.id === S.previewTab)) S.previewTab = 'curriculum';
  const tabs = [{ key: 'curriculum', label: '커리큘럼' },
    ...((S.curriculum.learning_materials || []).length ? [{ key: 'materials', label: '학습 자료' }] : []),
    ...forms.map((d) => ({ key: d.id, label: d.name }))];
  if (S.previewTab === 'materials' && !tabs.some((t) => t.key === 'materials')) S.previewTab = 'curriculum';
  $('#preview-tabs').hidden = tabs.length < 2;
  $('#preview-tabs').innerHTML = tabs.map((t) =>
    `<button class="tab ${t.key === S.previewTab ? 'active' : ''}" data-view="${esc(t.key)}">${esc(t.label)}</button>`).join('');
  $$('#preview-tabs .tab').forEach((tab) => tab.addEventListener('click', () => showPreviewTab(tab.dataset.view)));
  renderPreviewBody();
}

function renderPreviewBody() {
  const body = $('#preview');
  if (S.previewTab === 'curriculum') { body.innerHTML = curriculumHtml(S.curriculum); return; }
  if (S.previewTab === 'materials') { body.innerHTML = materialsHtml(S.curriculum); return; }
  body.innerHTML = formHtml(filledForms()[S.previewTab]);
}

async function showPreviewTab(key) {
  // 작성에 실패했던 서류는 탭을 누를 때 다시 시도한다
  if (key !== 'curriculum' && key !== 'materials' && !filledForms()[key] && !(await fillMissingForms())) return;
  S.previewTab = key;
  renderPreviewTabs();
}

// 아직 작성하지 않은 체크된 서류를 한 번에 작성한다 (서버에서 병렬로 작성)
async function fillMissingForms() {
  const todo = selectedForms().filter((d) => !filledForms()[d.id]);
  if (!todo.length) return true;
  const curriculum = S.curriculum;
  const data = await withLoading(`신청 서류 ${todo.length}건(${todo.map((d) => d.name).join(', ')})을 작성하는 중…`, () =>
    api('/api/forms/fill', { context: context(), survey: S.survey, curriculum, ids: todo.map((d) => d.id) })).catch(() => null);
  if (!data || curriculum !== S.curriculum) return false;
  data.forms.forEach((f) => (filledForms()[f.id] = f.form));
  return true;
}

function curriculumHtml(c) {
  return `
    <header class="doc-head">
      <h1>${esc(c.title)}</h1>
      <div class="chips">
        ${c.version ? `<span class="pill version-pill" title="${esc(c.version_note || '')}">v${c.version}${c.version_note ? ` · ${esc(c.version_note)}` : ''}</span>` : ''}
        ${c.target_summary ? `<span class="pill">${esc(c.target_summary)}</span>` : ''}
        ${c.total_weeks ? `<span class="pill">${c.total_weeks}주</span>` : ''}
        ${c.total_hours ? `<span class="pill">${c.total_hours}시간</span>` : ''}
        <span class="pill">모듈 ${c.modules.length}개</span>
      </div>
    </header>
    ${c.change_log.length ? `<div class="changes"><strong>이번에 바뀐 내용</strong>${list(c.change_log)}</div>` : ''}
    <p class="summary">${esc(c.summary)}</p>
    ${(c.design_rationale || []).length ? `<div class="why"><strong>왜 이렇게 짰나요?</strong>${list(c.design_rationale)}</div>` : ''}
    <h2>최종 학습 목표</h2>${list(c.learning_goals)}
    <h2>커리큘럼 한눈에 보기</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>기간</th><th>모듈</th><th>시간</th><th>주요 내용</th></tr></thead>
      <tbody>${c.modules.map((m) => `<tr><td>${esc(m.period)}</td><td>${esc(m.title)}</td><td>${hours(m.hours)}</td><td>${esc(m.topics.join(', '))}</td></tr>`).join('')}</tbody>
    </table></div>
    <h2>모듈 상세</h2>
    ${c.modules.map((m) => `
      <details class="module">
        <summary><span class="period">${esc(m.period)}</span> ${esc(m.title)} <span class="muted small">${hours(m.hours)}</span></summary>
        <div class="module-body">
          <div><h3>학습 목표</h3>${list(m.objectives)}</div>
          <div><h3>주요 내용</h3>${list(m.topics)}</div>
          <div><h3>실습 / 과제</h3><p>${esc(m.practice || '-')}</p></div>
          <div><h3>선수 지식</h3>${list(m.prerequisites)}</div>
          ${m.rationale ? `<div class="full-row"><h3>이렇게 짠 이유</h3><p>${esc(m.rationale)}</p></div>` : ''}
        </div>
      </details>`).join('')}
    ${c.projects.length ? `<h2>프로젝트</h2><ul>${c.projects.map((p) => `<li><strong>${esc(p.name)}</strong> <span class="muted">${esc(p.period)}</span> — ${esc(p.description)}</li>`).join('')}</ul>` : ''}
    ${skillTargetsHtml(c.skill_targets || [])}
    <h2>평가</h2><p>${esc(c.assessment || '-')}</p>
    ${quizzesHtml(c.quizzes || [])}
    ${proficiencyHtml(c.proficiency_methods || [])}
    ${complianceHtml(c.compliance_table || [])}
    ${c.compliance_notes.length ? `<h2>운영 규정·심사 기준 반영</h2>${list(c.compliance_notes)}` : ''}`;
}

const MARKS = ['①', '②', '③', '④'];

function skillTargetsHtml(ts) {
  if (!ts.length) return '';
  return `<h2>숙련목표</h2><ul>${ts.map((t) => `<li><strong>${esc(t.id)}</strong> ${esc(t.text)}
    <span class="muted small">${esc(t.level || '')}${t.subject_ids?.length ? ` · ${esc(t.subject_ids.join(', '))}` : ''}</span></li>`).join('')}</ul>`;
}

function quizzesHtml(qs) {
  if (!qs.length) return '';
  return `<h3>이해도 평가 퀴즈 (객관식)</h3>${qs.map((q) => `
    <details class="module">
      <summary><span class="period">${q.week ? `${q.week}주차` : ''}</span> ${esc(q.subject_title || q.subject_id)} <span class="muted small">${q.questions.length}문항</span></summary>
      <div class="module-body quiz">${q.questions.map((x, n) => `
        <div class="quiz-q"><p><strong>${n + 1}.</strong> ${esc(x.question)} <span class="muted small">${esc((x.skill_target_ids || []).join(', '))}</span></p>
          <ol class="choices">${x.choices.map((ch, i) => `<li class="${i === x.answer - 1 ? 'answer' : ''}">${MARKS[i]} ${esc(ch)}</li>`).join('')}</ol>
          ${x.explanation ? `<p class="muted small">정답 ${MARKS[x.answer - 1]} · ${esc(x.explanation)}</p>` : ''}</div>`).join('')}
      </div>
    </details>`).join('')}`;
}

function proficiencyHtml(ms) {
  if (!ms.length) return '';
  return `<h2>숙련도 향상 방법</h2><ul>${ms.map((m) => `<li><strong>${esc(m.method)}</strong>${m.timing ? ` <span class="muted small">(${esc(m.timing)})</span>` : ''} — ${esc(m.description)}</li>`).join('')}</ul>`;
}

const VERDICT = { '지킴': 'ok', '위반': 'bad', '확인 필요': 'check' };

function complianceHtml(rows) {
  if (!rows.length) return '';
  return `<h2>운영 규정 대조표</h2>
    <p class="muted small">계산·구조 조항은 코드가, 판단 조항은 별도 심사 AI가 판정했어요(근거 인용은 코드가 확인). '팀 확인 전' 조항은 규정집 원문과 맞는지 팀이 확인해야 해요.</p>
    <div class="table-wrap"><table class="compliance">
      <colgroup><col style="width:18%"><col style="width:32%"><col style="width:10%"><col style="width:30%"><col style="width:10%"></colgroup>
      <thead><tr><th>조항</th><th>내용</th><th>결과</th><th>근거</th><th>판정</th></tr></thead>
      <tbody>${rows.map((r) => `<tr>
        <td>${esc(r.article)}<div class="muted small">${esc(r.type)}</div></td>
        <td>${esc(r.text)}</td>
        <td><span class="verdict verdict-${VERDICT[r.verdict] || 'check'}">${esc(r.verdict)}</span></td>
        <td class="small">${esc(r.evidence)}</td>
        <td class="small">${esc(r.by)}${r.confirmed ? '' : '<div class="muted">팀 확인 전</div>'}</td></tr>`).join('')}</tbody>
    </table></div>`;
}

function renderRegs() {
  $('#reg-count').textContent = `(${S.regulations.length})`;
  $('#reg-list').innerHTML = S.regulations.length
    ? S.regulations.map((r) => `<div class="reg"><strong>${esc(r.article)}</strong><span class="muted"> ${esc(r.source)} p.${r.page}</span><p>${esc(r.text.slice(0, 280))}${r.text.length > 280 ? '…' : ''}</p></div>`).join('')
    : '<p class="muted small">찾은 규정이 없습니다. data/regulations 폴더에 운영 규정집 PDF를 넣어주세요.</p>';
}

$('#save-btn').addEventListener('click', async () => {
  const category = MODE[S.mode].category;
  const body = {
    category, context: context(), survey: S.survey, curriculum: S.curriculum,
    validation: S.mode === 'validate' ? S.validation : null, regulations: S.regulations,
    filled_forms: Object.entries(filledForms()).map(([id, form]) => ({ id, form })),
  };
  const nForms = selectedForms().filter((d) => !filledForms()[d.id]).length;
  const msg = nForms ? `신청 서류 ${nForms}건을 작성하고 PPT · PDF와 함께 저장하는 중…` : 'PPT · PDF · 문서를 만들어 저장하는 중…';
  const saved = await withLoading(msg, () => api('/api/library/save', body)).catch(() => null);
  if (saved) toast(`나의 자료실 > ${category} 에 저장했어요.`, { action: { label: '자료실 보기', fn: openLibrary } });
});

$('#secondary-btn').addEventListener('click', () => {
  // 생성: 입력했던 과정 정보가 그대로 남은 설문 화면으로 돌아간다
  if (S.mode === 'generate') show('survey');
  else if (S.mode === 'revise') { $('#revise-instruction').value = ''; showRevise(); }
  else runValidation(S.curriculum, 'preview');
});

// ---------- 나의 자료실 ----------
const entryUrl = (cat, folder) => `/api/library/${encodeURIComponent(cat)}/${encodeURIComponent(folder)}`;
const fileLinks = (cat, folder, files) =>
  files.map((f) => `<a href="${entryUrl(cat, folder)}/files/${encodeURIComponent(f)}" download>${esc(f)}</a>`).join('');

async function openLibrary() {
  show('library');
  const box = $('#library-list');
  box.innerHTML = '<p class="muted">불러오는 중…</p>';
  const lib = await api('/api/library').catch((e) => { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return null; });
  if (!lib) return;
  box.innerHTML = Object.entries(lib).map(([cat, entries]) => `
    <section class="lib-cat">
      <h2>📁 ${esc(cat)} <span class="muted small">${entries.length}개</span></h2>
      ${entries.length ? entries.map((e) => `
        <div class="card lib-entry">
          <button class="lib-main" data-act="view" data-cat="${esc(cat)}" data-folder="${esc(e.folder)}" title="내용 보기">
            <strong>${esc(e.title)}${e.version ? ` <span class="pill version-pill">v${e.version}</span>` : ''}</strong>
            <span class="muted small">${esc(e.created_at.replace('T', ' '))} · ${esc(surveyLabel(e.survey))}${e.version_note ? ` · ${esc(e.version_note)}` : ''}</span>
            <span class="muted small">파일 ${e.files.length}개 · 클릭해서 내용 보기</span>
          </button>
          <div class="lib-actions">
            <button class="btn ghost small-btn" data-act="validate" data-cat="${esc(cat)}" data-folder="${esc(e.folder)}">검증하기</button>
            <button class="btn ghost small-btn" data-act="revise" data-cat="${esc(cat)}" data-folder="${esc(e.folder)}">수정하기</button>
            <button class="btn ghost small-btn danger-text" data-act="delete" data-cat="${esc(cat)}" data-folder="${esc(e.folder)}" data-title="${esc(e.title)}">삭제</button>
          </div>
        </div>`).join('') : '<p class="muted small">아직 저장된 자료가 없습니다.</p>'}
    </section>`).join('');
  $$('[data-act]', box).forEach((b) => b.addEventListener('click', () => {
    const { act, cat, folder } = b.dataset;
    if (act === 'view') openEntry(cat, folder);
    else if (act === 'delete') deleteEntry(cat, folder, b.dataset.title);
    else startFromLibrary(cat, folder, act);
  }));
}

async function deleteEntry(cat, folder, title) {
  if (!confirm(`「${title}」을(를) 나의 자료실 > ${cat}에서 삭제할까요?\n저장된 PPT·PDF·신청 서류 파일이 모두 지워지고 되돌릴 수 없어요.`)) return;
  const ok = await withLoading('삭제하는 중…', async () => {
    const res = await fetch(entryUrl(cat, folder), { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || '삭제하지 못했습니다.');
    return true;
  }).catch(() => false);
  if (!ok) return;
  toast('삭제했어요.');
  openLibrary();
}

// 자료실 자료 보기: 커리큘럼 / 작성한 신청 서류 / 검증 결과를 탭으로 보여준다
let viewing = null;

async function openEntry(cat, folder) {
  const e = await withLoading('자료를 불러오는 중…', () => api(entryUrl(cat, folder))).catch(() => null);
  if (!e) return;
  viewing = { ...e, category: cat, folder };
  $('#libview-step').textContent = `나의 자료실 > ${cat} · ${e.created_at.replace('T', ' ')}`;
  $('#libview-files').innerHTML = fileLinks(cat, folder, e.files);
  renderEntryTabs();
  renderVersions('#libview-versions', '#libview-version-card', e.curriculum, pickLibraryVersion);
  show('libview');
}

// 자료실에서 지난 버전을 골라 본다 (검증하기·수정하기도 고른 버전으로 시작한다)
function pickLibraryVersion(c) {
  viewing.curriculum = c;
  renderEntryTabs();
  renderVersions('#libview-versions', '#libview-version-card', c, pickLibraryVersion);
}

function renderEntryTabs() {
  const e = viewing;
  const tabs = [{ key: 'curriculum', label: '커리큘럼' },
    ...((e.curriculum.learning_materials || []).length ? [{ key: 'materials', label: '학습 자료' }] : []),
    ...e.forms.map((f, i) => ({ key: `form${i}`, label: f.name })),
    ...(e.validation ? [{ key: 'validation', label: '검증 결과' }] : [])];
  $('#libview-tabs').innerHTML = tabs.map((t, i) =>
    `<button class="tab ${i === 0 ? 'active' : ''}" data-view="${t.key}">${esc(t.label)}</button>`).join('');
  $$('#libview-tabs .tab').forEach((tab) => tab.addEventListener('click', () => {
    $$('#libview-tabs .tab').forEach((t) => t.classList.toggle('active', t === tab));
    renderEntryView(tab.dataset.view);
  }));
  renderEntryView('curriculum');
}

function renderEntryView(key) {
  const body = $('#libview-body');
  if (key === 'curriculum') body.innerHTML = curriculumHtml(viewing.curriculum);
  else if (key === 'materials') body.innerHTML = materialsHtml(viewing.curriculum);
  else if (key === 'validation') body.innerHTML = validationHtml(viewing.validation);
  else body.innerHTML = formHtml(viewing.forms[+key.slice(4)].form);
}

const markPlaceholders = (s) => esc(s).replace(/(\[작성 필요[^\]]*\])/g, '<mark>$1</mark>');

function formHtml(f) {
  const blocks = f.blocks.map((b) => {
    if (b.type === 'heading') return `<h${Math.min(Math.max(b.level, 1), 3) + 1}>${markPlaceholders(b.text)}</h${Math.min(Math.max(b.level, 1), 3) + 1}>`;
    if (b.type === 'bullet') return `<ul><li>${markPlaceholders(b.text)}</li></ul>`;
    if (b.type === 'table') return `<div class="table-wrap"><table class="grid">${b.rows.map((r) =>
      `<tr>${r.map((c) => `<td>${markPlaceholders(c)}</td>`).join('')}</tr>`).join('')}</table></div>`;
    return `<p>${markPlaceholders(b.text)}</p>`;
  }).join('');
  const todo = (JSON.stringify(f).match(/\[작성 필요/g) || []).length;
  return `<header class="doc-head"><h1>${esc(f.title)}</h1>
    ${todo ? `<p class="muted small"><mark>[작성 필요]</mark> 표시 ${todo}곳은 직접 채워야 해요.</p>` : ''}</header>${blocks}`;
}

function validationHtml(v) {
  return `<header class="doc-head"><h1>학생 관점 검증 결과</h1></header>
    <p class="summary">${esc(v.overall)}</p>
    ${quizFitHtml(v.quiz_fit || [])}
    ${v.personas.map((p) => `
      <h2>${esc(p.persona)} ${p.score ? `<span class="score">${'★'.repeat(p.score)}${'☆'.repeat(Math.max(0, 5 - p.score))}</span>` : ''}</h2>
      <p class="muted small">${esc(p.profile)}</p>
      ${p.strengths.length ? `<h3>좋은 점</h3>${list(p.strengths)}` : ''}
      <h3>부족한 점</h3>
      ${p.gaps.length ? `<ul>${p.gaps.map((g) => `<li><span class="sev ${SEV[g.severity] || 'mid'}">${esc(g.severity)}</span>
        ${g.location ? `<span class="loc">${esc(g.location)}</span>` : ''} ${esc(g.issue)}
        <span class="suggest">→ ${esc(g.suggestion)}</span></li>`).join('')}</ul>` : '<p class="muted">없음</p>'}`).join('')}`;
}

$('#libview-back').addEventListener('click', openLibrary);
$('#libview-validate').addEventListener('click', () => startFromLibrary(viewing.category, viewing.folder, 'validate', viewing.curriculum));
$('#libview-revise').addEventListener('click', () => startFromLibrary(viewing.category, viewing.folder, 'revise', viewing.curriculum));
$('#libview-delete').addEventListener('click', () => deleteEntry(viewing.category, viewing.folder, viewing.title));

async function startFromLibrary(cat, folder, mode, picked = null) {
  const e = await withLoading('자료실에서 불러오는 중…', () => api(entryUrl(cat, folder))).catch(() => null);
  if (!e) return;
  resetFlow(mode);
  const saved = e.context || {};
  const savedDocs = saved.application_docs || saved.business_plan || '';
  if (!docsText().trim() && savedDocs) {
    setFiles(splitFiles(savedDocs));
    if (saved.documents && saved.documents.length) Object.assign(S, { documents: saved.documents, docsFor: docsText() });
    // 예전 저장본에 따로 있던 심사 기준은 같은 칸에 붙인다 (그러면 다시 분석된다)
    if (saved.criteria && saved.criteria.trim()) appendDocs(`===== 파일: 심사 기준 =====\n${saved.criteria.trim()}`);
    saveDocs();
    renderDocParts();
  }
  if (!(await ensureAnalyzed())) return;
  S.original = S.curriculum = picked || e.curriculum;
  S.originalLabel = `나의 자료실 > ${cat} > ${e.title}${S.original.version ? ` v${S.original.version}` : ''}`;
  S.survey = e.survey && e.survey.subject !== undefined ? e.survey : inferSurvey(e.curriculum);
  if (mode === 'revise') showRevise();
  else showValidateInput();
}

// ---------- 초기화 ----------
$$('.source-picker').forEach(mountPicker);
renderDocParts();
$$('[data-nav]').forEach((b) => b.addEventListener('click', () => (b.dataset.nav === 'library' ? openLibrary() : show('home'))));

api('/api/status').then((s) => {
  $('#provider-badge').textContent = `AI: ${s.provider}`;
  const n = s.regulations.files.length;
  $('#reg-status').textContent = n ? `등록된 운영 규정집: ${s.regulations.files.join(', ')}` : '(운영 규정집 PDF가 아직 등록되지 않았습니다)';
}).catch(() => ($('#provider-badge').textContent = 'AI: 연결 실패'));
