import io
import re
import random
import zipfile
import xml.etree.ElementTree as ET

QZ_MAX_Q = 1000
QZ_MAX_BYTES = 5 * 1024 * 1024
_QZ_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_QZ_ANS_RE = re.compile(r"^\s*(?:to['‘’ʻ`]?g['‘’ʻ`]?ri\s+)?(?:javob|answer|ans|kalit|key|ответ)\s*[:=\-–]\s*\(?([A-Ha-hА-Яа-я1-8])\)?\b", re.I)
_QZ_OPT_RE = re.compile(r"^\s*([*+#✅✔√]?)\s*\(?([A-Za-zА-Яа-я])\)?\s*[\.\)\]:]\s*(.*\S)\s*$")
_QZ_NUM_RE = re.compile(r"^\s*(?:savol|вопрос|question)?\s*№?\s*(\d{1,4})\s*[\.\)\-:]\s*", re.I)
_QZ_LOOK = {"А": 0, "В": 1, "С": 2, "Е": 4, "Н": 7}
_QZ_SEQ = {c: i for i, c in enumerate("АБВГДЕЖЗ")}
_QZ_NOSHUFFLE = re.compile(r"(hammasi|barcha|yuqoridagi|ikkalasi|hech biri|va\s+[a-h]\b|\b[a-h]\s+va\b|все|ни одно|оба)", re.I)


def _qz_idx(ch):
    ch = ch.upper()
    if "A" <= ch <= "H":
        return {ord(ch) - 65}
    c = set()
    if ch in _QZ_LOOK: c.add(_QZ_LOOK[ch])
    if ch in _QZ_SEQ: c.add(_QZ_SEQ[ch])
    return c


def qz_read_docx(data):
    """[(matn, qalin_mi)] : abzatslar (bo'sh abzatslar ham saqlanadi)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    root = ET.fromstring(z.read("word/document.xml"))
    out = []
    for p in root.iter(_QZ_W + "p"):
        text, runs_bold = "", []
        for r in p.iter(_QZ_W + "r"):
            t = ""
            for n in r:
                if n.tag == _QZ_W + "t": t += n.text or ""
                elif n.tag == _QZ_W + "tab": t += " "
                elif n.tag == _QZ_W + "br": t += "\n"
            if not t.strip(): 
                text += t
                continue
            rp = r.find(_QZ_W + "rPr")
            b = rp.find(_QZ_W + "b") if rp is not None else None
            bold = b is not None and b.get(_QZ_W + "val") not in ("0", "false")
            text += t
            runs_bold.append(bold)
        allbold = bool(runs_bold) and all(runs_bold)
        for line in text.split("\n"):
            out.append((line, allbold and bool(line.strip())))
    return out


def qz_read_xlsx(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(ns + "si"):
            shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    if not sheets:
        raise ValueError(("pe_no_sheet",))
    rows = []
    for row in ET.fromstring(z.read(sheets[0])).iter(ns + "row"):
        cells = {}
        for c in row.iter(ns + "c"):
            ref = c.get("r", "")
            col = 0
            for ch in re.match(r"[A-Z]+", ref).group(0):
                col = col * 26 + (ord(ch) - 64)
            t = c.get("t")
            if t == "s":
                v = c.find(ns + "v")
                val = shared[int(v.text)] if v is not None and v.text and int(v.text) < len(shared) else ""
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(ns + "t"))
            else:
                v = c.find(ns + "v")
                val = (v.text or "") if v is not None else ""
            cells[col - 1] = val.strip()
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def _qz_finish(qs, notes):
    """Tekshiruv va to'g'ri javobsiz savollarni hal qilish."""
    known = [q for q in qs if q["c"] is not None]
    if not qs:
        return [], notes
    if not known:   # hech bir savolda to'g'ri javob belgilanmagan: 1-variant to'g'ri deb olinadi
        for q in qs: q["c"] = 0
        notes.append(("pn_first", 0))
        return qs, notes
    miss = len(qs) - len(known)
    if miss:
        notes.append(("pn_miss", miss))
    return known, notes


def _qz_clean_opt(t):
    t = re.sub(r"\s*(?:\(\s*(?:\+|to['‘’ʻ`]?g['‘’ʻ`]?ri)\s*\)|✅|✔|\*)\s*$", "", t, flags=re.I)
    return t.strip()


def qz_parse_block(text):
    """Savol / ==== / #to'g'ri / ==== / xato ... ++++ ko'rinishi."""
    notes, qs = [], []
    blocks = re.split(r"\n\s*\+{3,}\s*\n", "\n" + text + "\n")
    if len(blocks) == 1:
        blocks = re.split(r"\n\s*\n(?=[^\n]+\n\s*={3,})", "\n" + text + "\n")
    bad = 0
    for b in blocks:
        parts = [p.strip() for p in re.split(r"\n\s*={3,}\s*\n", b.strip())]
        parts = [p for p in parts if p]
        if len(parts) < 3:
            if parts: bad += 1
            continue
        q = _QZ_NUM_RE.sub("", " ".join(parts[0].split("\n")), count=1).strip()
        opts, c, marks = [], None, 0
        for p in parts[1:]:
            p = " ".join(p.split("\n")).strip()
            if p[:1] in "#*+":
                marks += 1
                c = len(opts)
                p = p[1:].strip()
            opts.append(p)
        qs.append({"q": q, "o": opts, "c": c if marks == 1 else None})
    if bad: notes.append(("pn_badblock", bad))
    return _qz_finish(qs, notes)


def qz_parse_letter(lines):
    """lines: [(matn, qalin)]. Variantlar A) B) C) D) ko'rinishida."""
    notes, qs = [], []
    cur = None
    blank_after_opts = False

    def flush():
        nonlocal cur
        if cur and len(cur["o"]) >= 2:
            marks = [i for i, m in enumerate(cur["m"]) if m]
            c = None
            if len(marks) == 1: c = marks[0]
            elif not marks and cur.get("ans") is not None and cur["ans"] < len(cur["o"]): c = cur["ans"]
            else:
                bolds = [i for i, b in enumerate(cur["b"]) if b]
                if len(bolds) == 1 and len(cur["o"]) > 1: c = bolds[0]
            qs.append({"q": cur["q"].strip(), "o": cur["o"], "c": c})
        cur = None

    for raw, bold in lines:
        t = raw.strip()
        if not t:
            if cur and cur["o"]: blank_after_opts = True
            continue
        ma = _QZ_ANS_RE.match(t)
        if ma and cur and cur["o"]:
            ch = ma.group(1)
            if ch.isdigit(): idx = int(ch) - 1
            else:
                cand = _qz_idx(ch)
                idx = min(cand) if cand else None
            cur["ans"] = idx
            continue
        mo = _QZ_OPT_RE.match(t)
        if mo and cur is not None:
            mark, ch, body = mo.group(1), mo.group(2), mo.group(3)
            expect = len(cur["o"])
            if expect in _qz_idx(ch):
                trail = bool(re.search(r"(?:\(\s*(?:\+|to['‘’ʻ`]?g['‘’ʻ`]?ri)\s*\)|✅|✔|\*)\s*$", body, re.I))
                lead = body[:1] in "*+#✅✔√"
                if lead: body = body[1:].strip()
                cur["o"].append(_qz_clean_opt(body))
                cur["m"].append(bool(mark) or trail or lead)
                cur["b"].append(bold)
                blank_after_opts = False
                continue
        # variant bo'lmagan qator
        if cur is not None and cur["o"]:
            new_q = bool(_QZ_NUM_RE.match(t)) or blank_after_opts or len(cur["o"]) >= 2
            if not new_q:   # variantning davomi
                cur["o"][-1] += " " + t
                continue
            flush()
            blank_after_opts = False
        if cur is None:
            cur = {"q": "", "o": [], "m": [], "b": [], "ans": None}
        cur["q"] += (" " if cur["q"] else "") + _QZ_NUM_RE.sub("", t, count=1)
    flush()
    return _qz_finish(qs, notes)


def qz_parse_rows(rows):
    """Excel: Savol | A | B | C | D | To'g'ri javob."""
    notes, qs = [], []
    if not rows: return [], notes
    head = [c.lower() for c in rows[0]]
    has_head = any(len(c) <= 20 and "?" not in c and re.search(r"savol|question|вопрос", c) for c in head)
    ans_col = None
    if has_head:
        for i, c in enumerate(head):
            if re.search(r"to['‘’ʻ`]?g['‘’ʻ`]?ri|javob|answer|correct|key|ответ|kalit", c): ans_col = i
        q_col = next((i for i, c in enumerate(head) if re.search(r"savol|question|вопрос", c)), 0)
        body = rows[1:]
    else:
        q_col, body = 0, rows
        sample = [r[-1].strip().upper() for r in body[:20] if len(r) > 3 and r[-1].strip()]
        if sample and all(re.fullmatch(r"[A-H1-8]", x) for x in sample):
            ans_col = max(len(r) for r in body) - 1
    # Savoldan oldin raqam ustuni bo'lsa (1, 2, 3...), uni o'tkazib yuboramiz: savol keyingi ustunda
    def _numeric_col(c):
        vals = [r[c].strip() for r in body if len(r) > c and r[c].strip()]
        return bool(vals) and all(re.fullmatch(r"\d{1,5}[.)]?", v) for v in vals)
    while q_col < 3 and _numeric_col(q_col):
        q_col += 1
    for r in body:
        r = r + [""] * 12
        q = r[q_col].strip()
        if not q: continue
        opt_idx = [i for i in range(len(r)) if i > q_col and i != ans_col and r[i].strip()]
        opts = [r[i].strip() for i in opt_idx]
        if len(opts) < 2: continue
        c = None
        if ans_col is not None and r[ans_col].strip():
            a = r[ans_col].strip()
            if re.fullmatch(r"[A-Ha-h]", a): c = ord(a.upper()) - 65
            elif re.fullmatch(r"[1-8]", a): c = int(a) - 1
            else:
                low = [o.lower() for o in opts]
                c = low.index(a.lower()) if a.lower() in low else None
            if c is not None and c >= len(opts): c = None
        qs.append({"q": q, "o": opts, "c": c})
    return _qz_finish(qs, notes)


def qz_parse_file(name, data):
    """(savollar, izohlar) qaytaradi yoki ValueError(xabar)."""
    if len(data) > QZ_MAX_BYTES:
        raise ValueError(("pe_big",))
    low = name.lower()
    try:
        if low.endswith(".docx"):
            lines = qz_read_docx(data)
            text = "\n".join(t for t, _ in lines)
            qs, notes = qz_parse_block(text) if re.search(r"^\s*={3,}\s*$", text, re.M) else qz_parse_letter(lines)
        elif low.endswith(".xlsx"):
            qs, notes = qz_parse_rows(qz_read_xlsx(data))
        elif low.endswith(".txt"):
            text = None
            for enc in ("utf-8-sig", "cp1251", "latin-1"):
                try: text = data.decode(enc); break
                except Exception: pass
            qs, notes = qz_parse_block(text) if re.search(r"^\s*={3,}\s*$", text, re.M) else qz_parse_letter([(l, False) for l in text.split("\n")])
        else:
            raise ValueError(("pe_fmt",))
    except ValueError:
        raise
    except Exception:
        raise ValueError(("pe_unreadable",))
    if not qs:
        raise ValueError(("pe_empty",))
    clean = []
    for q in qs:
        o = [x for x in q["o"] if x]
        if len(o) < 2 or len(o) > 10 or not q["q"] or q["c"] is None or q["c"] >= len(o):
            continue
        clean.append({"q": q["q"], "o": o, "c": q["c"]})
    if len(clean) > QZ_MAX_Q:
        notes.append(("pn_cut", QZ_MAX_Q))
        clean = clean[:QZ_MAX_Q]
    if not clean:
        raise ValueError(("pe_noans",))
    return clean, notes


def qz_shuffle_options(q, rnd=random):
    """Variantlarni aralashtiradi (\"hammasi\", \"A va B\" kabi bog'liq variantlar bo'lsa, tegmaydi)."""
    if any(_QZ_NOSHUFFLE.search(o) for o in q["o"]):
        return q
    idx = list(range(len(q["o"])))
    rnd.shuffle(idx)
    return {"q": q["q"], "o": [q["o"][i] for i in idx], "c": idx.index(q["c"])}
