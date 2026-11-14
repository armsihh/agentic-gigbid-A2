// Render docs/REPORT.md to docs/REPORT.pdf with headless Chromium (Playwright from apps/web).
//   cd apps/web && node scripts/render_report.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const md = readFileSync(resolve(root, "docs/REPORT.md"), "utf-8");

// Minimal markdown -> HTML (headings, tables, lists, bold/italic/code, paragraphs): enough for this report.
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const inline = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
  .replace(/\*([^*]+)\*/g, "<i>$1</i>");
const lines = md.split(/\r?\n/);
let html = "", i = 0;
while (i < lines.length) {
  const l = lines[i];
  if (/^#{1,3} /.test(l)) { const n = l.match(/^#+/)[0].length; html += `<h${n}>${inline(l.slice(n + 1))}</h${n}>`; i++; continue; }
  if (l.startsWith("|")) {
    const rows = [];
    while (i < lines.length && lines[i].startsWith("|")) { rows.push(lines[i]); i++; }
    const cells = (r) => r.split("|").slice(1, -1).map((c) => c.trim());
    html += "<table><thead><tr>" + cells(rows[0]).map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>";
    for (const r of rows.slice(2)) html += "<tr>" + cells(r).map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
    html += "</tbody></table>"; continue;
  }
  if (/^- /.test(l)) {
    html += "<ul>";
    while (i < lines.length && /^(- |  )/.test(lines[i])) {
      let item = lines[i].slice(2); i++;
      while (i < lines.length && /^  \S/.test(lines[i])) { item += " " + lines[i].trim(); i++; }
      html += `<li>${inline(item)}</li>`;
    }
    html += "</ul>"; continue;
  }
  if (!l.trim()) { i++; continue; }
  let p = l; i++;
  while (i < lines.length && lines[i].trim() && !/^(#|\||- )/.test(lines[i])) { p += " " + lines[i]; i++; }
  html += `<p>${inline(p)}</p>`;
}

const page = `<!doctype html><html><head><meta charset="utf-8"><style>
  @page { size: A4; margin: 16mm 15mm; }
  body { font-family: "Segoe UI", Arial, sans-serif; font-size: 9.6pt; line-height: 1.38; color: #111; }
  h1 { font-size: 17pt; margin: 0 0 4px; } h2 { font-size: 12.5pt; margin: 14px 0 4px; border-bottom: 1px solid #ccc; }
  h3 { font-size: 10.5pt; } p { margin: 4px 0 6px; } ul { margin: 4px 0 6px 18px; padding: 0; }
  table { border-collapse: collapse; width: 100%; margin: 6px 0 8px; font-size: 8.4pt; page-break-inside: avoid; }
  th, td { border: 1px solid #bbb; padding: 3px 5px; text-align: left; vertical-align: top; } th { background: #eef1f7; }
  code { font-family: Consolas, monospace; font-size: 8.6pt; background: #f2f2f2; padding: 0 2px; }
</style></head><body>${html}</body></html>`;

const browser = await chromium.launch();
const tab = await browser.newPage();
await tab.setContent(page, { waitUntil: "load" });
const pdf = await tab.pdf({ format: "A4", printBackground: true,
  displayHeaderFooter: true, headerTemplate: "<span></span>",
  footerTemplate: '<div style="font-size:8px;width:100%;text-align:center;color:#666">GigBid R&D report · page <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
  margin: { top: "14mm", bottom: "16mm", left: "14mm", right: "14mm" } });
writeFileSync(resolve(root, "docs/REPORT.pdf"), pdf);
await browser.close();
console.log("wrote docs/REPORT.pdf");
