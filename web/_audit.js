// Layout audit (test only, git-ignored via _ prefix? removed after use): overflow, overlapping buttons, cut-off text.
window.auditScreen = (label) => {
  const W = innerWidth, out = { label, docOverflow: document.documentElement.scrollWidth - W, wide: [], overlaps: [], clipped: [] };
  const visible = el => { const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false; for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden' || e.hidden) return false; } return true; };
  const inHScroll = el => { for (let e = el.parentElement; e; e = e.parentElement) { const ox = getComputedStyle(e).overflowX; if ((ox === 'auto' || ox === 'scroll') && e.scrollWidth > e.clientWidth) return true; } return false; };
  const top = [...document.querySelectorAll('.sheet:not([hidden]), .viewer:not([hidden])')].pop();
  const root = top || document.querySelector('.app');
  const els = [...root.querySelectorAll('*')].filter(visible);
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if ((r.right > W + 1 || r.left < -1) && !inHScroll(el)) out.wide.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}.${[...el.classList].join('.')} [${Math.round(r.left)}..${Math.round(r.right)}] "${(el.innerText || '').trim().slice(0, 30)}"`);
  }
  const btns = els.filter(e => e.matches('button, .btn, input:not([type=hidden]), select'));
  for (const b of btns) if (b.scrollWidth > b.clientWidth + 2 && b.tagName === 'BUTTON' && !b.closest('.col')) out.clipped.push(`"${b.innerText.trim().slice(0, 30)}" ${b.clientWidth}<${b.scrollWidth}`);
  for (let i = 0; i < btns.length; i++) for (let j = i + 1; j < btns.length; j++) {
    const a = btns[i], b = btns[j]; if (a.contains(b) || b.contains(a)) continue;
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    const ox = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left), oy = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
    if (ox > 2 && oy > 2) out.overlaps.push(`"${a.innerText.trim().slice(0, 20)}" × "${b.innerText.trim().slice(0, 20)}"`);
  }
  out.wide = [...new Set(out.wide)].slice(0, 8);
  return out;
};
// Visible words on buttons and headings, for a capitalisation pass.
window.auditWords = () => [...new Set([...document.querySelectorAll('button, h1, h2, .btn')].filter(e => e.getClientRects().length).map(e => e.innerText.trim().replace(/\s+/g, ' ')).filter(t => t && t.length < 40))];
