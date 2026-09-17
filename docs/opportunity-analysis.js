/* Shared validation for public AI analysis. Contains no personal notes or keys. */
(function (root) {
  'use strict';
  const text = (x, max = 12000) => typeof x === 'string' && x.trim().length > 0 && x.length <= max;
  const record = x => x !== null && typeof x === 'object' && !Array.isArray(x);
  const date = x => typeof x === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(x) &&
    Number.isFinite(Date.parse(x)) && new Date(x).toISOString().slice(0, 10) === x;
  const timestamp = x => typeof x === 'string' && /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(x) && date(x.slice(0,10)) && Number.isFinite(Date.parse(x));
  function safeUrl(x) {
    try { const u = new URL(x); return u.protocol === 'https:' && !u.username && !u.password; }
    catch { return false; }
  }
  const list = (x, check, min = 1, max = 20) => Array.isArray(x) && x.length >= min && x.length <= max && x.every(check);
  const unique = xs => new Set(xs).size === xs.length;
  function validateReport(r) {
    if (!record(r) || typeof r.ticker !== 'string' || !/^[A-Z0-9.^-]{1,12}$/.test(r.ticker) ||
        !text(r.id, 120) || !text(r.model, 120) || !timestamp(r.generatedAt) || !date(r.asOf) ||
        r.asOf > r.generatedAt.slice(0, 10) || !text(r.headline, 300)) return false;
    if (!list(r.sources, s => record(s) && text(s.id, 80) && text(s.title, 500) &&
        safeUrl(s.url) && date(s.publishedAt) && s.publishedAt <= r.asOf) ||
        !unique(r.sources.map(s => s.id))) return false;
    const ids = new Set(r.sources.map(s => s.id));
    const refs = xs => list(xs, x => typeof x === 'string' && ids.has(x));
    if (!list(r.facts, f => record(f) && text(f.text) && refs(f.sourceIds))) return false;
    if (!record(r.story) || !['thesis', 'mechanism', 'earningsImpact'].every(k => text(r.story[k]))) return false;
    if (!record(r.expectations) || !['不明', '比較材料あり'].includes(r.expectations.status) ||
        !text(r.expectations.text) || !Array.isArray(r.expectations.sourceIds) ||
        !r.expectations.sourceIds.every(id => ids.has(id)) ||
        (r.expectations.status === '比較材料あり' && !refs(r.expectations.sourceIds))) return false;
    if (!list(r.counterarguments, x => text(x)) || !list(r.breakConditions, x => text(x)) ||
        !list(r.nextChecks, c => record(c) && text(c.event, 500) && text(c.condition) &&
          (c.date === null || date(c.date)))) return false;
    if (!record(r.change) || !['初回', '強まった', '弱まった', '変わらず', '判断保留'].includes(r.change.direction) ||
        !text(r.change.summary) || !(r.change.previousReportId === null || text(r.change.previousReportId, 120)) ||
        r.change.previousReportId === r.id || (r.change.direction !== '初回' && !r.change.previousReportId) ||
        (r.change.direction === '初回' && r.change.previousReportId !== null)) return false;
    return true;
  }
  function validateFeed(feed) {
    return !!(record(feed) && feed.version === 1 && typeof feed.demo === 'boolean' &&
      list(feed.reports, validateReport, 0, 100) && unique(feed.reports.map(r => r.ticker)) &&
      unique(feed.reports.map(r => r.id)));
  }
  function stale(report, today = new Date().toISOString().slice(0, 10)) {
    return Date.parse(today) - Date.parse(report.asOf) > 7 * 86400000;
  }
  function changedSinceReview(card, report) {
    return !!(report && card.judgment && card.judgment !== '未判断' && card.reviewedReportId !== report.id);
  }
  const api = {validateFeed, validateReport, safeUrl, stale, changedSinceReview};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.OpportunityAnalysis = api;
})(typeof window !== 'undefined' ? window : this);
