import base64
import math
import os
from collections import Counter
from datetime import date


# ── Annotation classification ─────────────────────────────────────────────────

def _is_insertion(a) -> bool:
    return a.body_purpose == 'insertion' or a.target_start == a.target_end

def _is_atr_noise(a) -> bool:
    return a.body_purpose == 'atr_noise'

def _is_non_resolv(a) -> bool:
    return a.body_purpose == 'non_resolv_abbr'

def _is_space_exact(a) -> bool:
    if _is_insertion(a) or _is_atr_noise(a) or _is_non_resolv(a):
        return False
    return not (a.target_exact or '').strip()

def _is_substitution(a) -> bool:
    return not _is_insertion(a) and not _is_atr_noise(a) and not _is_non_resolv(a) and not _is_space_exact(a)


# ── Levenshtein distance ──────────────────────────────────────────────────────

def levenshtein(s: str, t: str) -> int:
    if s == t:
        return 0
    if not s:
        return len(t)
    if not t:
        return len(s)
    row = list(range(len(t) + 1))
    for i, cs in enumerate(s):
        prev = i + 1
        for j, ct in enumerate(t):
            val = row[j] if cs == ct else 1 + min(row[j], row[j + 1], prev)
            row[j] = prev
            prev = val
        row[len(t)] = prev
    return row[len(t)]


def _quantile(vals: list, p: float) -> float:
    if not vals:
        return 0.0
    pos = p * (len(vals) - 1)
    lo, hi = int(pos), math.ceil(pos)
    return float(vals[lo]) if lo == hi else vals[lo] * (hi - pos) + vals[hi] * (pos - lo)


# ── Statistics computation ────────────────────────────────────────────────────

def compute_stats(pages) -> dict:
    """
    Compute aggregated statistics across one or more Page objects.
    Returns a dict consumed by build_chart_svg() and the stats_report.html template.
    """
    all_subs, all_val_subs = [], []
    all_inss, all_noises, all_nonres, all_spaces = [], [], [], []
    tok_count = 0
    page_stats = []

    for page in pages:
        p_subs, p_val, p_inss, p_noi, p_non, p_sp = [], [], [], [], [], []
        for a in page.annotation_rows:
            if _is_substitution(a):
                p_subs.append(a)
                if a.validated_by:
                    p_val.append(a)
            elif _is_insertion(a) and (a.body_value or '').strip():
                p_inss.append(a)
            elif _is_atr_noise(a):
                p_noi.append(a)
            elif _is_non_resolv(a):
                p_non.append(a)
            elif _is_space_exact(a):
                p_sp.append(a)

        p_tok = len(page.normalized_text.split()) if page.normalized_text.strip() else 0
        tok_count += p_tok
        page_stats.append({'label': page.label, 'subs': len(p_subs),
                           'validated': len(p_val), 'tokens': p_tok})

        all_subs.extend(p_subs);     all_val_subs.extend(p_val)
        all_inss.extend(p_inss);     all_noises.extend(p_noi)
        all_nonres.extend(p_non);    all_spaces.extend(p_sp)

    # Levenshtein distances (substitutions only)
    dists = sorted(levenshtein(a.target_exact or '', a.body_value or '') for a in all_subs)
    nd = len(dists)

    dmean   = sum(dists) / nd if nd else 0.0
    dmedian = _quantile(dists, 0.5)
    dq1     = _quantile(dists, 0.25)
    dq3     = _quantile(dists, 0.75)
    dmin    = dists[0]  if nd else 0
    dmax    = dists[-1] if nd else 0
    dstd    = math.sqrt(sum((v - dmean) ** 2 for v in dists) / nd) if nd else 0.0
    diqr    = dq3 - dq1

    # Frequency tables
    src_map, dst_map = {}, {}
    for a in all_subs:
        src = a.target_exact or ''
        dst = a.body_value   or ''
        if src not in src_map:
            src_map[src] = {'n': 0, 'dsts': set()}
        src_map[src]['n'] += 1
        src_map[src]['dsts'].add(dst)
        if dst not in dst_map:
            dst_map[dst] = {'n': 0, 'srcs': set()}
        dst_map[dst]['n'] += 1
        dst_map[dst]['srcs'].add(src)

    return {
        'subs':      len(all_subs),
        'val_subs':  len(all_val_subs),
        'inss':      len(all_inss),
        'noises':    len(all_noises),
        'nonres':    len(all_nonres),
        'spaces':    len(all_spaces),
        'tok_count': tok_count,
        'dists':     dists,
        'nd':        nd,
        'dmean':     dmean,
        'dmedian':   dmedian,
        'dq1':       dq1,
        'dq3':       dq3,
        'dmin':      dmin,
        'dmax':      dmax,
        'dstd':      dstd,
        'diqr':      diqr,
        'dist_freq': dict(Counter(dists)),
        'top_src':   sorted(src_map.items(), key=lambda x: -x[1]['n'])[:25],
        'top_dst':   sorted(dst_map.items(), key=lambda x: -x[1]['n'])[:25],
        'page_stats': page_stats,
    }


# ── SVG chart ─────────────────────────────────────────────────────────────────

def build_chart_svg(stats: dict) -> str:
    nd = stats['nd']
    if not nd:
        return '<p style="color:#ccc;font-style:italic;margin:.5em 0">No data.</p>'

    dists    = stats['dists']
    dist_freq = stats['dist_freq']
    dmin, dmax = stats['dmin'], stats['dmax']
    dq1, dmedian, dq3, diqr = stats['dq1'], stats['dmedian'], stats['dq3'], stats['diqr']

    W, pL, pR, pT, pB = 660, 44, 20, 20, 24
    hist_h, gap, bp_box_h = 140, 20, 22
    chart_w = W - pL - pR
    x_range = (dmax - dmin) or 1

    def xs(v):
        return pL + ((v - dmin) / x_range) * chart_w

    dist_keys = sorted(dist_freq)
    max_freq  = max(dist_freq.values())
    b_w       = max(8, min(44, chart_w / len(dist_keys) * 0.65))

    parts = []

    # Axes
    parts += [
        f'<line x1="{pL}" y1="{pT}" x2="{pL}" y2="{pT+hist_h}" stroke="#ddd" stroke-width="1"/>',
        f'<line x1="{pL}" y1="{pT+hist_h}" x2="{W-pR}" y2="{pT+hist_h}" stroke="#ddd" stroke-width="1"/>',
    ]

    # Y ticks
    for t in [0, round(max_freq / 2), max_freq]:
        y = pT + hist_h - (t / max_freq) * hist_h
        parts += [
            f'<line x1="{pL-4}" y1="{y:.1f}" x2="{pL}" y2="{y:.1f}" stroke="#ccc" stroke-width="1"/>',
            f'<text x="{pL-7:.1f}" y="{y+3.5:.1f}" text-anchor="end" font-size="9" fill="#999">{t}</text>',
        ]

    # Histogram bars + x-labels
    for v in dist_keys:
        freq = dist_freq[v]
        b_h  = (freq / max_freq) * hist_h
        cx   = xs(v)
        parts += [
            f'<rect x="{cx-b_w/2:.1f}" y="{pT+hist_h-b_h:.1f}" width="{b_w:.1f}" height="{b_h:.1f}" fill="rgba(99,155,255,.6)" stroke="rgba(59,130,246,.8)" stroke-width="1" rx="2"/>',
            f'<text x="{cx:.1f}" y="{pT+hist_h-b_h-4:.1f}" text-anchor="middle" font-size="9" fill="#444">{freq}</text>',
            f'<text x="{cx:.1f}" y="{pT+hist_h+14:.1f}" text-anchor="middle" font-size="10" fill="#666">{v}</text>',
        ]

    # X-axis label
    parts.append(f'<text x="{pL+chart_w/2:.1f}" y="{pT+hist_h+pB:.1f}" text-anchor="middle" font-size="10" fill="#aaa">Levenshtein distance</text>')

    # Boxplot
    bp_y  = pT + hist_h + gap + pB + 4
    half  = bp_box_h / 2
    w_lo  = max(dmin, dq1 - 1.5 * diqr)
    w_hi  = min(dmax, dq3 + 1.5 * diqr)
    xwl, xq1, xmed, xq3, xwh = xs(w_lo), xs(dq1), xs(dmedian), xs(dq3), xs(w_hi)

    parts += [
        f'<line x1="{xwl:.1f}" y1="{bp_y:.1f}" x2="{xq1:.1f}" y2="{bp_y:.1f}" stroke="#999" stroke-width="1.5"/>',
        f'<line x1="{xq3:.1f}" y1="{bp_y:.1f}" x2="{xwh:.1f}" y2="{bp_y:.1f}" stroke="#999" stroke-width="1.5"/>',
        f'<line x1="{xwl:.1f}" y1="{bp_y-8:.1f}" x2="{xwl:.1f}" y2="{bp_y+8:.1f}" stroke="#999" stroke-width="1.5"/>',
        f'<line x1="{xwh:.1f}" y1="{bp_y-8:.1f}" x2="{xwh:.1f}" y2="{bp_y+8:.1f}" stroke="#999" stroke-width="1.5"/>',
        f'<rect x="{min(xq1,xq3):.1f}" y="{bp_y-half:.1f}" width="{max(3,xq3-xq1):.1f}" height="{bp_box_h:.1f}" fill="rgba(99,155,255,.2)" stroke="rgba(59,130,246,.8)" stroke-width="1.5" rx="3"/>',
        f'<line x1="{xmed:.1f}" y1="{bp_y-half:.1f}" x2="{xmed:.1f}" y2="{bp_y+half:.1f}" stroke="#2563eb" stroke-width="2.5"/>',
    ]

    # Outliers
    for v in dists:
        if v < w_lo or v > w_hi:
            parts.append(f'<circle cx="{xs(v):.1f}" cy="{bp_y:.1f}" r="3.5" fill="none" stroke="rgba(239,68,68,.7)" stroke-width="1.5"/>')

    lbl_y = bp_y + half + 13
    parts += [
        f'<text x="{xq1:.1f}" y="{lbl_y:.1f}" text-anchor="middle" font-size="9" fill="#888">Q1 {dq1:.1f}</text>',
        f'<text x="{xmed:.1f}" y="{lbl_y:.1f}" text-anchor="middle" font-size="9" fill="#2563eb">Med {dmedian:.1f}</text>',
        f'<text x="{xq3:.1f}" y="{lbl_y:.1f}" text-anchor="middle" font-size="9" fill="#888">Q3 {dq3:.1f}</text>',
    ]

    svg_h = bp_y + half + 28
    return (f'<svg width="{W}" height="{svg_h:.0f}" viewBox="0 0 {W} {svg_h:.0f}" '
            f'style="max-width:100%;display:block;overflow:visible;">'
            + ''.join(parts) + '</svg>')


# ── Font loading ──────────────────────────────────────────────────────────────

def load_font_face() -> str:
    font_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'fonts', 'JunicodeVF-Roman.woff2')
    try:
        with open(font_path, 'rb') as fh:
            b64 = base64.b64encode(fh.read()).decode('ascii')
        return (f"@font-face{{font-family:'Junicode';"
                f"src:url('data:font/woff2;base64,{b64}')format('woff2');"
                f"font-weight:100 900;}}")
    except OSError:
        return ''


def today_str() -> str:
    return date.today().strftime('%d %B %Y')
