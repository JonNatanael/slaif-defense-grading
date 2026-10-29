from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

FINAL_REPORT_HTML = "final_report.html"

# ==== BEGIN Student 0001 | submission | main.py ====
_SECTION_RE = re.compile(r"^==== BEGIN [^|]*\s*\|[^|]*\|\s*(?P<file>.+?)\s*====\s*$")
_SECTION_END_RE = re.compile(r"^==== END .*====\s*$")


def load_code_files(output_txt: Path) -> List[Dict[str, object]]:
    """Extract individual submission files from a named concatenated student output.

    The concatenated text uses '==== BEGIN <pseudonym> | submission | <file> ===='
    markers; line 1 of a file is the first line after its BEGIN marker.
    """
    files: List[Dict[str, object]] = []
    try:
        lines = output_txt.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return files
    current: Optional[Dict[str, object]] = None
    for line in lines:
        begin = _SECTION_RE.match(line)
        if begin is not None:
            if current is not None:
                files.append(current)
            current = {"file": begin.group("file"), "lines": []}
            continue
        if current is not None:
            if _SECTION_END_RE.match(line):
                files.append(current)
                current = None
            else:
                current["lines"].append(line)
    if current is not None:
        files.append(current)
    return files


def _read_index_rows(output: Path) -> List[Dict[str, str]]:
    with (output / "final_index.csv").open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _read_overview_rows(output: Path) -> List[Dict[str, str]]:
    try:
        with (output / "final_report.csv").open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _read_missing_reasons(output: Path) -> Dict[str, str]:
    try:
        with (output / "missing_reports.csv").open("r", encoding="utf-8-sig", newline="") as f:
            return {row["pseudonym"]: row.get("reason", "") for row in csv.DictReader(f)}
    except OSError:
        return {}


def _load_named_report(output: Path, rel_path: str) -> Tuple[Optional[Dict[str, object]], str]:
    if not rel_path:
        return None, "No report"
    path = output / rel_path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "No report"
    if not isinstance(data, dict):
        return None, "No report"
    return data, ""


def build_html_data(output: Path) -> List[Dict[str, object]]:
    """Assemble viewer data solely from the final (private, named) outputs."""
    index_rows = _read_index_rows(output)
    overview_rows = _read_overview_rows(output)
    missing_reasons = _read_missing_reasons(output)
    students: List[Dict[str, object]] = []
    for i, row in enumerate(index_rows):
        pseudonym = row.get("pseudonym", "")
        overview = overview_rows[i] if i < len(overview_rows) else {}
        report, _ = _load_named_report(output, row.get("report_json_file", ""))
        code_files: List[Dict[str, object]] = []
        student_output_file = row.get("student_output_file", "")
        if student_output_file:
            code_files = load_code_files(output / student_output_file)
        students.append(
            {
                "id": row.get("full_name", "").strip() or pseudonym or f"student_{i}",
                "name": row.get("full_name", ""),
                "pseudonym": pseudonym,
                "status": row.get("report_status", "missing"),
                "missingReason": missing_reasons.get(pseudonym, ""),
                "reportPdf": row.get("report_pdf_file", ""),
                "reportJson": row.get("report_json_file", ""),
                "studentOutputFile": student_output_file,
                "overview": {
                    "all_tasks_implemented": overview.get("all_tasks_implemented", "Unknown"),
                    "copying_indications": overview.get("copying_indications", "Unknown"),
                    "llm_indications": overview.get("llm_indications", "Unknown"),
                    "notes": overview.get("notes", ""),
                },
                "report": report,
                "code": code_files,
            }
        )
    return students


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Final overview - local HTML viewer</title>
<style>
:root {
  --bg: #f6f7f9; --card: #ffffff; --ink: #1c2330; --muted: #5b6472;
  --line: #d9dee5; --accent: #2456d6; --accent-soft: #e8effd;
  --ok: #1e7e34; --warn: #9a6700; --bad: #b3261e; --bad-soft: #fdecea;
  --hl-own: #fff3bf; --hl-other: #fbd5d5; --hl-note: #d0e2ff;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
header.top { background: var(--card); border-bottom: 1px solid var(--line);
  padding: 14px 22px; position: sticky; top: 0; z-index: 5; }
header.top h1 { margin: 0; font-size: 18px; }
header.top .sub { color: var(--muted); font-size: 13px; margin-top: 2px; }
main { padding: 18px 22px 60px; max-width: 1200px; margin: 0 auto; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.search { margin: 0 0 12px; }
.search input { width: 340px; max-width: 100%; padding: 8px 12px; font-size: 14px;
  border: 1px solid var(--line); border-radius: 8px; }
table.overview { border-collapse: collapse; width: 100%; table-layout: fixed;
  background: var(--card); border: 1px solid var(--line); }
table.overview th, table.overview td { border: 1px solid var(--line); padding: 8px 10px;
  text-align: left; vertical-align: top; font-size: 13.5px;
  word-wrap: break-word; overflow-wrap: break-word; }
table.overview th { background: #eef1f5; position: sticky; top: 62px; }
table.overview tr:hover td { background: #f2f6ff; }
.pname { font-weight: 600; }
.pseudo { color: var(--muted); font-size: 12px; }
.files { margin-top: 4px; font-size: 12px; }
.badge { display: inline-block; border-radius: 10px; padding: 1px 9px; font-size: 12px;
  font-weight: 600; }
.b-yes { background: #e2f4e6; color: var(--ok); }
.b-no { background: #f1e2f2; color: #8e24aa; }
.b-unknown, .b-uncertain { background: #eceff3; color: var(--muted); }
.b-likely, .b-copy { background: var(--bad-soft); color: var(--bad); }
.b-unlikely { background: #e8f1e9; color: var(--ok); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 16px 18px; margin-bottom: 14px; }
.card h2 { margin: 0 0 4px; font-size: 19px; }
.card h3 { margin: 16px 0 6px; font-size: 14.5px; text-transform: uppercase;
  letter-spacing: .4px; color: var(--muted); }
.crumbs { margin-bottom: 12px; font-size: 13.5px; }
.kv { margin: 4px 0; }
.task { margin: 6px 0 6px 14px; }
.task .t { font-weight: 600; }
.evidence { color: var(--muted); font-size: 13px; margin: 2px 0 2px 14px; }
.copycard { border: 1px solid var(--line); border-left: 4px solid var(--bad);
  border-radius: 8px; padding: 10px 14px; margin: 10px 0; background: #fffafa; }
.copycard .who { font-weight: 600; }
.codelinks { margin: 8px 0; display: flex; gap: 8px; flex-wrap: wrap; }
.codelink { display: inline-block; border: 1px solid var(--line); border-radius: 7px;
  background: var(--card); padding: 5px 10px; font-size: 12.5px; font-family: ui-monospace,
  "Cascadia Code", Consolas, monospace; }
.codelink.own { border-color: #e0c341; background: #fffbe8; }
.codelink.other { border-color: #d98c8c; background: #fff0f0; }
.codelink.dead { opacity: .5; cursor: not-allowed; border-style: dashed; }
.legend { font-size: 12px; color: var(--muted); margin: 6px 0 0; }
.legend span { display: inline-block; width: 11px; height: 11px; border-radius: 3px;
  margin: 0 4px 0 10px; vertical-align: -1px; border: 1px solid rgba(0,0,0,.15); }
pre.code { background: #0f1520; color: #dce3ee; border-radius: 8px; overflow: auto;
  padding: 10px 0; font: 12.5px/1.45 ui-monospace, "Cascadia Code", Consolas, monospace; }
pre.code .row { display: flex; white-space: pre; }
pre.code .ln { flex: 0 0 52px; text-align: right; padding: 0 10px 0 0; color: #5d6a80;
  user-select: none; border-right: 1px solid #232c3d; margin-right: 10px; }
pre.code .row.hl-own .lc { background: var(--hl-own); color: #20242e; }
pre.code .row.hl-own .ln { background: #f7e9b0; color: #4d3f00; }
pre.code .row.hl-other .lc { background: var(--hl-other); color: #3d1212; }
pre.code .row.hl-other .ln { background: #f5bcbc; color: #5c1212; }
pre.code .row.hl-note .lc { background: var(--hl-note); color: #10233f; }
pre.code .row.hl-note .ln { background: #b9d2f7; color: #10233f; }
.codetitle { display: flex; align-items: baseline; gap: 10px; margin: 6px 0; flex-wrap: wrap; }
.codetitle .file { font-family: ui-monospace, Consolas, monospace; font-weight: 700; }
.tag { font-size: 11.5px; font-weight: 700; border-radius: 9px; padding: 1px 9px; }
.tag.own { background: var(--hl-own); color: #5c4b00; }
.tag.other { background: var(--hl-other); color: #6e1414; }
.tag.note { background: var(--hl-note); color: #17345e; }
.tag.plain { background: #eceff3; color: var(--muted); }
.ref { border-bottom: 1px dotted var(--accent); }
.muted { color: var(--muted); }
.footer { margin-top: 26px; font-size: 12.5px; color: var(--muted); }
ul.plain { margin: 4px 0; padding-left: 20px; }
</style>
</head>
<body>
<header class="top">
  <h1>Final overview &mdash; local HTML viewer</h1>
  <div class="sub">Private, instructor-facing overview for human review during in-person oral verification.
  Open <a href="final_report.pdf">final_report.pdf</a> or <a href="final_report.csv">final_report.csv</a> for the print versions.</div>
</header>
<main id="app"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("data").textContent);
const STUDENTS = {};
const BY_PSEUDONYM = {};
DATA.students.forEach(s => { STUDENTS[s.id] = s; BY_PSEUDONYM[s.pseudonym] = s; });

const app = document.getElementById("app");

function esc(t) {
  return String(t == null ? "" : t)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function hashParams() {
  const h = location.hash.replace(/^#/, "");
  const p = new URLSearchParams(h);
  return { s: p.get("s"), c: p.get("c"), l: p.get("l"), t: p.get("t") };
}
function studentHref(id) { return "#s=" + encodeURIComponent(id); }
function codeHref(id, file, range, type) {
  return studentHref(id) + "&c=" + encodeURIComponent(file) +
    (range ? "&l=" + range : "") + (type ? "&t=" + type : "");
}
function parseRange(s) {
  if (!s) return null;
  const m = String(s).match(/(\d+)\s*[-\u2013\u2014]\s*(\d+)/);
  if (m) return [Math.min(+m[1], +m[2]), Math.max(+m[1], +m[2])];
  const m2 = String(s).match(/(\d+)/);
  if (m2) return [+m2[1], +m2[1]];
  return null;
}
function fileIndex(student, fileToken) {
  if (!student || !fileToken) return -1;
  const t = fileToken.replace(/[\\\/]+$/, "");
  const base = t.split(/[\\\/]/).pop();
  const files = student.code || [];
  let i = files.findIndex(f => f.file === t);
  if (i >= 0) return i;
  i = files.findIndex(f => f.file.split(/[\\\/]/).pop() === base);
  if (i >= 0) return i;
  i = files.findIndex(f => f.file.endsWith(t) || t.endsWith(f.file));
  if (i >= 0) return i;
  return -1;
}
// Annotate free text: turn "file lines X-Y" / "line X" references into links.
const REF_RE = /((?:[A-Za-z0-9_\-]+[\\\/])?[A-Za-z0-9_\-]+\.[A-Za-z0-9]{1,6})?\s*(?:lines?\s+|L\s*)(\d+)(?:\s*[-\u2013\u2014]\s*L?(\d+))?/gi;
function annotate(text, self, other, type) {
  text = String(text == null ? "" : text);
  let out = "", last = 0;
  REF_RE.lastIndex = 0;
  let m;
  while ((m = REF_RE.exec(text)) !== null) {
    const prev = m.index > 0 ? text[m.index - 1] : " ";
    const boundaryOk = !/[A-Za-z0-9]/.test(prev);
    const fileToken = m[1] || "";
    const a = +m[2];
    const b = m[3] ? +m[3] : a;
    const range = Math.min(a, b) + "-" + Math.max(a, b);
    let idx = -1, owner = null;
    if (boundaryOk) {
      idx = fileIndex(self, fileToken);
      owner = self;
      if (idx < 0 && other) { idx = fileIndex(other, fileToken); if (idx >= 0) owner = other; }
      if (idx < 0 && !fileToken && (self && self.code.length === 1)) { idx = 0; owner = self; }
    }
    out += esc(text.slice(last, m.index));
    last = m.index + m[0].length;
    if (idx >= 0) {
      const file = owner.code[idx].file;
      const kind = owner === self ? type : "other";
      out += '<a class="ref" href="' + codeHref(owner.id, file, range, kind) + '">' + esc(m[0]) + "</a>";
    } else {
      out += esc(m[0]);
    }
    if (m.index === REF_RE.lastIndex) REF_RE.lastIndex++;
  }
  return out + esc(text.slice(last));
}
function badge(v) {
  const k = String(v || "").trim().toLowerCase();
  let cls = "b-unknown";
  if (k === "yes") cls = "b-yes";
  else if (k === "no") cls = "b-no";
  else if (k === "likely" || k.startsWith("yes")) cls = "b-likely";
  else if (k === "unlikely") cls = "b-unlikely";
  else if (k === "uncertain") cls = "b-uncertain";
  return '<span class="badge ' + cls + '">' + esc(v || "Unknown") + "</span>";
}
function fileLink(student, fileToken, label) {
  const idx = fileIndex(student, fileToken);
  if (idx < 0) return '<span class="codelink dead" title="File not found in the available submission text">' + esc(label) + "</span>";
  return '<a class="codelink" href="' + codeHref(student.id, student.code[idx].file, "", "") + '" title="Open file">' + esc(label) + "</a>";
}
function overviewTable() {
  let html = '<div class="search"><input id="q" type="search" placeholder="Filter by name or pseudonym\u2026"></div>';
  html += '<table class="overview"><colgroup><col style="width:15%"><col style="width:11%">' +
    '<col style="width:17%"><col style="width:12%"><col style="width:45%"></colgroup>' +
    '<thead><tr><th>Student</th><th>All tasks implemented</th>' +
    "<th>Copying indications</th><th>LLM-use indications</th><th>Notes</th></tr></thead><tbody>";
  DATA.students.forEach(s => {
    const o = s.overview || {};
    const pdf = s.reportPdf ? ' <a class="files" href="' + esc(s.reportPdf) + '" target="_blank">report.pdf</a>' : "";
    const js = s.reportJson ? ' <a class="files" href="' + esc(s.reportJson) + '" target="_blank">report.json</a>' : "";
    const txt = s.studentOutputFile ? ' <a class="files" href="' + esc(s.studentOutputFile) + '" target="_blank">submission text</a>' : "";
    html += "<tr data-name=\"" + esc((s.name + " " + s.pseudonym).toLowerCase()) + "\">" +
      "<td><a class=\"pname\" href=\"" + studentHref(s.id) + "\">" + esc(s.name) + "</a>" +
      '<div class="pseudo">' + esc(s.pseudonym) + (s.status !== "found" ? " \u00b7 no report" : "") + "</div>" +
      '<div class="files">' + pdf + js + txt + "</div></td>" +
      "<td>" + badge(o.all_tasks_implemented) + "</td>" +
      "<td>" + badge(o.copying_indications) + "</td>" +
      "<td>" + badge(o.llm_indications) + "</td>" +
      "<td>" + annotate(o.notes, s, null, "note") + "</td></tr>";
  });
  html += "</tbody></table>";
  return html;
}
function copyCard(student, copy) {
  const other = BY_PSEUDONYM[String(copy.other_student_pseudonym || "").trim()] || null;
  let who = esc(copy.other_student_pseudonym || "unknown pseudonym");
  if (other) who = '<a href="' + studentHref(other.id) + '">' + esc(other.name) + "</a>";
  let links = "";
  const thisRef = [copy.this_file, copy.this_lines].filter(Boolean).join(", ");
  const otherRef = [copy.other_file, copy.other_lines].filter(Boolean).join(", ");
  const thisIdx = fileIndex(student, copy.this_file);
  const otherIdx = other ? fileIndex(other, copy.other_file) : -1;
  if (thisIdx >= 0) {
    const r = parseRange(copy.this_lines);
    links += '<a class="codelink own" href="' + codeHref(student.id, student.code[thisIdx].file, r ? r.join("-") : "", "own") + '" title="Open own submission at these lines">\u25b8 own: ' + esc(thisRef) + "</a> ";
  } else if (thisRef) links += '<span class="codelink dead" title="File not found in the available submission text">\u25b8 own: ' + esc(thisRef) + "</span> ";
  if (other && otherIdx >= 0) {
    const r = parseRange(copy.other_lines);
    links += '<a class="codelink other" href="' + codeHref(other.id, other.code[otherIdx].file, r ? r.join("-") : "", "other") + '" title="Open the other student\'s submission at these lines">\u25b8 their: ' + esc(otherRef) + "</a>";
  } else if (otherRef) links += '<span class="codelink dead" title="File not available (missing output or unknown file)">\u25b8 their: ' + esc(otherRef) + "</span>";
  return '<div class="copycard"><div class="who">From ' + who +
    (other ? ' <span class="pseudo">(' + esc(other.pseudonym) + ")</span>" : "") + "</div>" +
    '<div class="codelinks">' + links + "</div>" +
    '<div class="evidence">' + annotate(copy.evidence || "", student, other, "own") + "</div></div>";
}
function detail(student, code) {
  const r = student.report || {};
  let html = '<div class="crumbs"><a href="#">\u25c2 All students</a></div>';
  html += '<div class="card"><h2>' + esc(student.name) +
    ' <span class="pseudo">' + esc(student.pseudonym) + "</span></h2>";
  if (student.reportPdf) html += ' <a href="' + esc(student.reportPdf) + '" target="_blank">Full PDF report</a>';
  if (student.reportJson) html += ' &middot; <a href="' + esc(student.reportJson) + '" target="_blank">report.json</a>';
  if (student.studentOutputFile) html += ' &middot; <a href="' + esc(student.studentOutputFile) + '" target="_blank">raw submission text</a>';
  if (student.status !== "found") {
    html += '<div class="kv muted">No valid report.json for this student' +
      (student.missingReason ? ": " + esc(student.missingReason) : "") + "</div></div>";
    return html + codePanel(student, code, null);
  }
  html += '<h3>1. Was the assignment submitted?</h3><div class="kv">' +
    (r.assignment_submitted ? "Yes" : "No") + "</div>";
  html += '<h3>2. Are all the tasks implemented?</h3><div class="kv">' +
    (r.all_tasks_implemented === true ? "Yes" : r.all_tasks_implemented === false ? "No" : "Unknown") + "</div>";
  (r.task_details || []).forEach(t => {
    const state = t.implemented === true ? "implemented" : t.implemented === false ? "not implemented" : "unknown";
    html += '<div class="task"><span class="t">' + esc(t.task || "") + "</span>: " + esc(state) + "</div>" +
      (t.evidence ? '<div class="evidence">evidence: ' + annotate(t.evidence, student, null, "note") + "</div>" : "");
  });
  html += '<h3>3. Does the code look LLM-generated?</h3><div class="kv">' +
    badge(String(r.looks_llm_generated || "uncertain")) + "</div>";
  (r.llm_generation_indicators || []).forEach(ind => {
    html += '<div class="task">' + annotate(ind, student, null, "note") + "</div>";
  });
  html += '<h3>4. Indications of copying code from another student?</h3>';
  const copies = r.code_copy_indications || [];
  if (copies.length) copies.forEach(c => { html += copyCard(student, c); });
  else html += '<div class="kv muted">None.</div>';
  if (r.notes) html += '<h3>Notes</h3><div class="kv">' + annotate(r.notes, student, null, "note") + "</div>";
  html += '</div>';
  return html + codePanel(student, code, null);
}
function codePanel(owner, code, fallbackType) {
  if (!code) return "";
  const idx = fileIndex(owner, code.file);
  if (idx < 0) return "";
  const f = owner.code[idx];
  const range = parseRange(code.l);
  const type = ["own", "other", "note"].includes(code.t) ? code.t : "note";
  const context = range
    ? (type === "own" ? "own submission" : type === "other" ? "other student's submission" : "referenced in notes")
    : "full file (no specific lines)";
  const tagClass = range ? type : "plain";
  let rows = "";
  (f.lines || []).forEach((line, i) => {
    const n = i + 1;
    const hl = range && n >= range[0] && n <= range[1] ? " hl-" + type : "";
    rows += '<div class="row' + hl + '" id="ln-' + n + '"><span class="ln">' + n +
      '</span><span class="lc">' + esc(line) + "\u00a0</span></div>";
  });
  let html = '<div class="card" id="codepanel"><div class="codetitle"><span class="file">' + esc(f.file) +
    "</span><span class=\"tag " + tagClass + '\">' + context + "</span>" +
    "<span class=\"muted\">" + esc(owner.name) + " (" + esc(owner.pseudonym) + ")</span>" +
    '<a href="' + studentHref(owner.id) + '">close code view</a></div>' +
    '<pre class="code">' + rows + "</pre>" +
    '<div class="legend">Legend: <span style="background:var(--hl-own)"></span> lines opened via an own-submission copy link' +
    ' <span style="background:var(--hl-other)"></span> lines opened via another student\'s copy link' +
    ' <span style="background:var(--hl-note)"></span> lines referenced in notes, task evidence or indicators</div></div>';
  return html;
}
function render() {
  const p = hashParams();
  const code = p.c !== undefined && p.c ? { file: p.c, l: p.l, t: p.t } : null;
  if (p.s && STUDENTS[p.s]) {
    app.innerHTML = detail(STUDENTS[p.s], code);
    if (code) {
      const panel = document.getElementById("codepanel");
      if (panel) {
        const range = parseRange(p.l);
        const target = range ? panel.querySelector("#ln-" + range[0]) : panel;
        if (target) setTimeout(() => {
          // Scroll so the first target line sits *below* the sticky header;
          // scrollIntoView({block:"start"}) would hide it underneath.
          const header = document.querySelector("header.top");
          const offset = header ? header.getBoundingClientRect().height + 12 : 70;
          const y = target.getBoundingClientRect().top +
            (window.pageYOffset || document.documentElement.scrollTop) - offset;
          window.scrollTo(0, Math.max(0, y));
        }, 30);
      }
    }
  } else {
    app.innerHTML =
      overviewTable() +
      '<div class="footer">Evidence-based indicators for human review (oral verification). ' +
      "They do not prove plagiarism, unauthorized collaboration, or improper AI-tool use. " +
      "Line numbers refer to lines inside each submission file, as seen in the pseudonymized workspace.</div>";
    const q = document.getElementById("q");
    if (q) q.addEventListener("input", () => {
      const v = q.value.toLowerCase();
      document.querySelectorAll("table.overview tbody tr").forEach(tr => {
        tr.style.display = tr.dataset.name.includes(v) ? "" : "none";
      });
    });
  }
}
window.addEventListener("hashchange", render);
render();
</script>
</body>
</html>
"""


def render_final_report_html(output: Path) -> Path:
    """Render the self-contained local HTML viewer from the final outputs.

    Built post festum: it reads only files already written under `output`
    (final_index.csv, final_report.csv, missing_reports.csv, the named
    instructor reports and the named student outputs).
    """
    students = build_html_data(output)
    payload = json.dumps({"students": students}, ensure_ascii=False).replace("</", "<\\/")
    html = _TEMPLATE.replace("__DATA__", payload)
    output_path = output / FINAL_REPORT_HTML
    output_path.write_text(html, encoding="utf-8", newline="\n")
    return output_path
