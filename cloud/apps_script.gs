/**
 * Zillow Cloud Harvester — Google Sheet backend
 * ---------------------------------------------
 * Paste this whole file into Extensions → Apps Script of the harvester sheet,
 * run setup() once, then Deploy → New deployment → Web app
 * (Execute as: Me, Who has access: Anyone). Copy the Web app URL.
 *
 * The GitHub workers talk to this script to:
 *   claim a city · check which agents are new · save leads · mark a city finished
 */

const LEAD_HEADERS = [
  'Agent Name', 'Company / Agency', 'Email', 'Primary Phone', 'Cell Phone',
  'Business Phone', 'Full Address', 'City', 'State', 'Zip Code', 'Rating', 'Review Count',
  'Website', 'Zillow Profile URL', 'Specialties', 'Years in Industry', 'Searched City',
  'Searched State', 'Scraped At (UTC)'
];
const COL_EMAIL = 3, COL_PROFILE = 14;   // 1-based
const READY_HEADERS = ['Agent Name', 'Email', 'Company / Agency', 'Phone', 'City', 'State', 'Zillow Profile URL'];
const QUEUE_HEADERS = ['#', 'State', 'City', 'Status', 'Attempts', 'Worker', 'Claimed At', 'Finished At',
  'Agents Found', 'New Agents', 'Leads Saved', 'With Email', 'Failed Pages', 'Failed Profiles', 'Minutes', 'Note'];
const MAX_ATTEMPTS = 3;           // real failures before a city is marked "failed"
const STALE_HOURS = 7;            // an in_progress claim older than this is re-claimable

// Your earlier sheet ("Zillow Links From software"). setup() copies its leads in once.
const OLD_SHEET_ID = '1Mxz2rJrrxhx6OR3t4wgj_K0M8NsU5ocbc0KwlKgFZtQ';

// City list (top 15 by population x 50 states). Edit the Queue tab freely after setup.
const CITIES_URL = 'https://raw.githubusercontent.com/zuryabhasnain/zillow-agent-scraper/main/cloud/cities.json';

// ---------------------------------------------------------------------------
// One-time setup (run from the editor)
// ---------------------------------------------------------------------------
function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss.getSheetByName('Leads')) {
    // Use the blank "Sheet1" of a new spreadsheet (or an imported CSV tab) as the Leads tab.
    const first = ss.getSheets()[0];
    const a1 = first ? String(first.getRange(1, 1).getValue()).trim() : 'x';
    if (a1 === '' || a1 === 'Agent Name') first.setName('Leads');
  }
  const leads = getOrCreate_(ss, 'Leads', LEAD_HEADERS);
  const ready = getOrCreate_(ss, 'Unique Emails', READY_HEADERS);
  const queue = getOrCreate_(ss, 'Queue', QUEUE_HEADERS);

  if (queue.getLastRow() < 2) {
    const CITIES = JSON.parse(UrlFetchApp.fetch(CITIES_URL).getContentText());
    const rows = CITIES.map((c, i) => [i + 1, c[0], c[1], 'pending', 0, '', '', '', '', '', '', '', '', '', '', '']);
    queue.getRange(2, 1, rows.length, QUEUE_HEADERS.length).setValues(rows);
  }
  buildSummary_(ss);
  [leads, ready, queue].forEach(sh => { sh.setFrozenRows(1); sh.getRange(1, 1, 1, sh.getLastColumn()).setFontWeight('bold'); });

  const props = PropertiesService.getScriptProperties();
  let token = props.getProperty('TOKEN');
  if (!token) {
    token = Utilities.getUuid().replace(/-/g, '');
    props.setProperty('TOKEN', token);
  }
  if (leads.getLastRow() < 2) importOld_(leads);
  rebuildReady_();
  Logger.log('SETUP DONE. Your SHEET_TOKEN is:  ' + token);
  try { SpreadsheetApp.getUi().alert('Setup done!\n\nYour SHEET_TOKEN (copy it into GitHub secrets):\n\n' + token); } catch (e) {}
}

/** Copies leads from the old sheet (deduplicated by Zillow profile URL). */
function importOld_(leads) {
  let src;
  try { src = SpreadsheetApp.openById(OLD_SHEET_ID).getSheets()[0]; } catch (e) { Logger.log('Old sheet not imported: ' + e); return; }
  const vals = src.getDataRange().getValues();
  if (vals.length < 2) return;
  const h = vals[0].map(x => String(x).trim());
  const ix = name => h.indexOf(name);
  const get = (r, name) => (ix(name) >= 0 ? r[ix(name)] : '');
  const seen = new Set();
  const rows = [];
  vals.slice(1).forEach(r => {
    const url = String(get(r, 'Zillow Profile URL')).trim();
    const k = normUrl_(url);
    if (!k || seen.has(k)) return;
    seen.add(k);
    const city = String(get(r, 'City')) === 'None' ? '' : get(r, 'City');
    rows.push([get(r, 'Agent Name'), get(r, 'Company / Agency'), String(get(r, 'Email')).trim(),
      get(r, 'Primary Phone'), get(r, 'Cell Phone'), get(r, 'Business Phone'), get(r, 'Full Address'), city,
      get(r, 'State'), get(r, 'Zip Code'), get(r, 'Rating'), get(r, 'Review Count'), get(r, 'Website'), url,
      get(r, 'Specialties'), '', '', '', 'imported']);
  });
  if (rows.length) leads.getRange(2, 1, rows.length, LEAD_HEADERS.length).setValues(rows);
  Logger.log('Imported ' + rows.length + ' leads from the old sheet');
}

function getOrCreate_(ss, name, headers) {
  let sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  if (sh.getLastRow() === 0) sh.getRange(1, 1, 1, headers.length).setValues([headers]);
  return sh;
}

function buildSummary_(ss) {
  let sh = ss.getSheetByName('Summary');
  if (!sh) { sh = ss.insertSheet('Summary', 0); }
  sh.clear();
  const rows = [
    ['Zillow Cloud Harvester', ''],
    ['Total leads (agents)', '=MAX(0,COUNTA(Leads!A:A)-1)'],
    ['Leads with an email', '=COUNTIF(Leads!C2:C,"?*")'],
    ['Unique emails', "=MAX(0,COUNTA('Unique Emails'!B:B)-1)"],
    ['Cities total', '=COUNTA(Queue!C2:C)'],
    ['Cities done', '=COUNTIF(Queue!D2:D,"done")+COUNTIF(Queue!D2:D,"no_results")'],
    ['Cities in progress', '=COUNTIF(Queue!D2:D,"in_progress")'],
    ['Cities waiting / retry', '=COUNTIF(Queue!D2:D,"pending")+COUNTIF(Queue!D2:D,"retry")'],
    ['Cities failed', '=COUNTIF(Queue!D2:D,"failed")'],
    ['Progress', '=IFERROR(TEXT(B6/B5,"0%"),"0%")'],
    ['Avg minutes per city', '=IFERROR(ROUND(AVERAGE(Queue!O2:O),1),"")'],
    ['Last activity (UTC)', '=IFERROR(INDEX(SORT(FILTER(Queue!H2:H,Queue!H2:H<>""),1,FALSE),1),"")'],
  ];
  sh.getRange(1, 1, rows.length, 2).setValues(rows);
  sh.getRange('A1').setFontWeight('bold').setFontSize(14);
  sh.getRange('A2:A12').setFontWeight('bold');
  sh.setColumnWidth(1, 300); sh.setColumnWidth(2, 520);
}

// ---------------------------------------------------------------------------
// Web app
// ---------------------------------------------------------------------------
function doGet() {
  return json_({ ok: true, service: 'zillow-harvester', hint: 'POST only' });
}

function doPost(e) {
  let req;
  try { req = JSON.parse(e.postData.contents); } catch (err) { return json_({ ok: false, error: 'bad json' }); }
  const token = PropertiesService.getScriptProperties().getProperty('TOKEN');
  if (!token || req.token !== token) return json_({ ok: false, error: 'bad token' });

  const lock = LockService.getScriptLock();
  if (!lock.tryLock(90000)) return json_({ ok: false, error: 'busy, retry' });
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    switch (req.action) {
      case 'claim': return json_(claim_(ss, req));
      case 'finish': return json_(finish_(ss, req));
      case 'filter_new': return json_(filterNew_(ss, req));
      case 'append_leads': return json_(appendLeads_(ss, req));
      case 'ping': return json_({ ok: true });
      default: return json_({ ok: false, error: 'unknown action ' + req.action });
    }
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  } finally {
    SpreadsheetApp.flush();
    lock.releaseLock();
  }
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

function nowStr_() {
  return Utilities.formatDate(new Date(), 'UTC', 'yyyy-MM-dd HH:mm');
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------
function claim_(ss, req) {
  const q = ss.getSheetByName('Queue');
  const n = q.getLastRow() - 1;
  if (n < 1) return { ok: true, job: null };
  const data = q.getRange(2, 1, n, 8).getValues();   // # .. Finished At
  const staleMs = STALE_HOURS * 3600 * 1000;
  const now = new Date();
  for (let i = 0; i < data.length; i++) {
    const status = String(data[i][3]).trim();
    const attempts = Number(data[i][4]) || 0;
    let ok = status === 'pending' || status === '' || (status === 'retry' && attempts < MAX_ATTEMPTS);
    if (status === 'in_progress') {
      const claimed = parseUtc_(data[i][6]);
      ok = !claimed || (now - claimed) > staleMs;
    }
    if (ok && String(data[i][2]).trim()) {
      const row = i + 2;
      q.getRange(row, 4, 1, 4).setValues([['in_progress', attempts, req.worker || '', nowStr_()]]);
      return { ok: true, job: { row: row, state: String(data[i][1]).trim(), city: String(data[i][2]).trim() } };
    }
  }
  return { ok: true, job: null };
}

function parseUtc_(v) {
  if (!v) return null;
  if (v instanceof Date) return v;
  const m = String(v).match(/(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/);
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])) : null;
}

function finish_(ss, req) {
  const q = ss.getSheetByName('Queue');
  const row = Number(req.row);
  if (!row || row < 2) return { ok: false, error: 'bad row' };
  const cur = q.getRange(row, 1, 1, QUEUE_HEADERS.length).getValues()[0];
  let attempts = Number(cur[4]) || 0;
  let status = req.status;
  if (status === 'retry') {
    attempts += 1;
    if (attempts >= MAX_ATTEMPTS) status = 'failed';
  } else if (status === 'blocked') {
    status = 'pending';                 // not the city's fault: no attempt counted
  }
  const s = req.stats || {};
  const add = (k, idx) => (s[k] === undefined || s[k] === null) ? cur[idx] : (Number(cur[idx]) || 0) + Number(s[k]);
  const newRow = [
    cur[0], cur[1], cur[2], status, attempts, req.worker || cur[5], cur[6], nowStr_(),
    s.found === undefined ? cur[8] : s.found,
    s.new === undefined ? cur[9] : s.new, add('saved', 10), add('with_email', 11),
    s.failed_pages === undefined ? cur[12] : s.failed_pages,
    s.failed_profiles === undefined ? cur[13] : s.failed_profiles,
    s.minutes === undefined ? cur[14] : s.minutes,
    req.note || ''
  ];
  q.getRange(row, 1, 1, QUEUE_HEADERS.length).setValues([newRow]);
  return { ok: true, status: status };
}

// ---------------------------------------------------------------------------
// Leads
// ---------------------------------------------------------------------------
function normUrl_(u) {
  let s = String(u || '').trim();
  try { s = decodeURIComponent(s); } catch (e) {}
  return s.split('?')[0].split('#')[0].replace(/\/+$/, '').toLowerCase();
}

function knownProfiles_(leads) {
  const n = leads.getLastRow() - 1;
  const set = new Set();
  if (n < 1) return set;
  leads.getRange(2, COL_PROFILE, n, 1).getValues().forEach(r => { if (r[0]) set.add(normUrl_(r[0])); });
  return set;
}

function filterNew_(ss, req) {
  const known = knownProfiles_(ss.getSheetByName('Leads'));
  const out = [];
  const seen = new Set();
  (req.urls || []).forEach(u => {
    const k = normUrl_(u);
    if (k && !known.has(k) && !seen.has(k)) { seen.add(k); out.push(u); }
  });
  return { ok: true, new: out };
}

function appendLeads_(ss, req) {
  const leads = ss.getSheetByName('Leads');
  const known = knownProfiles_(leads);
  const rows = [];
  (req.rows || []).forEach(r => {
    if (!r || r.length !== LEAD_HEADERS.length) return;
    const k = normUrl_(r[COL_PROFILE - 1]);
    if (!k || known.has(k)) return;          // duplicate agent -> skip
    known.add(k);
    rows.push(r.map(v => (v === null || v === undefined) ? '' : v));
  });
  if (rows.length) {
    leads.getRange(leads.getLastRow() + 1, 1, rows.length, LEAD_HEADERS.length).setValues(rows);
    addToReady_(ss, rows);
  }
  return { ok: true, added: rows.length, skipped: (req.rows || []).length - rows.length };
}

function addToReady_(ss, leadRows) {
  const ready = ss.getSheetByName('Unique Emails');
  const n = ready.getLastRow() - 1;
  const have = new Set();
  if (n > 0) ready.getRange(2, 2, n, 1).getValues().forEach(r => have.add(String(r[0]).trim().toLowerCase()));
  const out = [];
  leadRows.forEach(r => {
    const email = String(r[COL_EMAIL - 1] || '').trim();
    const key = email.toLowerCase();
    if (!email || email.indexOf('@') < 1 || have.has(key)) return;   // one row per email
    have.add(key);
    out.push([r[0], email, r[1], r[3], r[7] || r[16], r[8] || r[17], r[COL_PROFILE - 1]]);
  });
  if (out.length) ready.getRange(ready.getLastRow() + 1, 1, out.length, READY_HEADERS.length).setValues(out);
}

/** Rebuilds "Unique Emails" from the whole Leads tab (setup() calls it; safe to run any time). */
function rebuildReady_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ready = ss.getSheetByName('Unique Emails');
  if (ready.getLastRow() > 1) ready.getRange(2, 1, ready.getLastRow() - 1, READY_HEADERS.length).clearContent();
  const leads = ss.getSheetByName('Leads');
  const n = leads.getLastRow() - 1;
  if (n > 0) addToReady_(ss, leads.getRange(2, 1, n, LEAD_HEADERS.length).getValues());
}
