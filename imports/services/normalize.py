"""Cleaning helpers for messy spreadsheet cells (amounts, dates, names, departments)."""
from __future__ import annotations

import datetime
import re
from difflib import SequenceMatcher

NULLS = {"", "na", "n/a", "n.a", "n.a.", "nil", "nill", "none", "-", "--", "not applicable", "nan", "#ref!",
         "null", "0"}

TITLES = re.compile(r"\b(prof(essor)?|dr|engr|eng|mr|mrs|ms|miss|syed(?=a\b)|sir|madam)\.?\s+", re.I)
DESIGNATIONS = [
    "pro-vice chancellor", "pro vice chancellor", "vice chancellor", "registrar", "dean", "director",
    "co-chairman", "co-chairperson", "co chairman", "chairman", "chairperson", "chairman/professor",
    "professor emeritus", "meritorious professor", "associate professor", "assistant professor", "professor",
    "senior lecturer", "lecturer", "lab engineer", "research associate", "research assistant", "manager",
]

# department hints (lower-case substrings / codes) -> department code
DEPT_HINTS = [
    (r"\b(urban|ued|ue)\b|urban and infra|urban & infra", "UED"),
    (r"earthquake|\beqd\b", "EQD"),
    (r"environment|enviroment|\bend\b", "END"),
    (r"petroleum|\bped\b", "PED"),
    (r"civil|\bced\b|\bce\b", "CED"),
    (r"electronic|\beld\b", "ELD"),
    (r"telecom|\btcd\b|\btc\b|\btel\b", "TCD"),
    (r"computer (and|&) information|\bcis\b|\bcise\b", "CIS"),
    (r"bio-?\s?medical|iomedical|\bbmd\b|\bbme\b", "BMD"),
    (r"computer science|cs\s?&\s?it|\bcsit\b|cs & it|\bcct\b|\bcs\b", "CSIT"),
    (r"software|\bse\b|\bswe\b", "SWE"),
    (r"electrical|elec\.?\s?eng|\beed\b|\bee\b", "EED"),
    (r"automotive|marine|\batd\b|\bamd\b", "AMD"),
    (r"industrial|manufactur|manf|\bimd\b", "IMD"),
    (r"textile|\btxd\b|\btx\b", "TXD"),
    (r"mechanical|mechnical|\bmed\b|\bme\b", "MED"),
    (r"polymer|petrochem|\bppd\b", "PPD"),
    (r"metallurg|\bmyd\b", "MYD"),
    (r"material|\bmmd\b", "MMD"),
    (r"food|\bfed\b", "FED"),
    (r"chemical eng|\bdec\b|\bche\b|chemical", "CHE"),
    (r"architect|planning|\bard\b", "ARD"),
    (r"economics|management sc|\bemd\b|\bems\b|\bdems\b", "EMS"),
    (r"physic|phsics|physcis|\bdph\b", "PHY"),
    (r"chemistry|\bdcy\b", "CHY"),
    (r"mathemat|\bdmt\b|\bmaths?\b", "MTH"),
    (r"english|linguistic|humanities|\bdel\b", "ELS"),
    (r"essential stud|\bdes\b", "ESD"),
]


def is_null(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip().lower() in NULLS
    return False


def text(v) -> str | None:
    if is_null(v):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (datetime.datetime, datetime.date)):
        return to_date(v)
    return " ".join(str(v).split())


DATE_FORMATS = ["%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%B %d, %Y",
                "%b %d, %Y", "%d-%b-%y", "%d/%m/%y", "%B %Y", "%b %Y", "%b-%Y", "%m/%d/%Y"]


def to_date(v) -> str | None:
    """ISO date or None. Handles Excel datetimes, serials and common text forms ('5th sept, 2024')."""
    if is_null(v):
        return None
    if isinstance(v, datetime.datetime):
        return v.date().isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, (int, float)) and 20000 < float(v) < 60000:  # Excel serial
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s, flags=re.I)
    s = re.sub(r"\bsept\b", "sep", s, flags=re.I)
    s = s.replace(",", ", ").replace("  ", " ")
    first = re.split(r"\s+(?:to|till|until|-|–)\s+", s)[0].strip(" ,")
    for cand in (s, first):
        for fmt in DATE_FORMATS:
            try:
                return datetime.datetime.strptime(cand.strip(" ,"), fmt).date().isoformat()
            except ValueError:
                continue
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return datetime.date(y, mth, d).isoformat()
        except ValueError:
            pass
    if not re.search(r"\d{4}", first):
        return None
    years = [m for m in re.finditer(r"(?<!\d)(\d{4})(?!\d)", first) if 1990 <= int(m.group(1)) <= 2100]
    # the year written after a month ('Room 2010, 5 May 2021' -> 2021), else the first plausible one (a range's start)
    dated = [m for m in years if re.search(r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec",
                                           first[max(0, m.start() - 16):m.start()], re.I)]
    year = int((dated or years)[0].group(1)) if years else None
    try:
        from dateutil import parser

        d = parser.parse(first, dayfirst=True, fuzzy=True, default=datetime.datetime(2000, 1, 1)).date()
    except Exception:  # noqa: BLE001
        return None
    # fuzzy parsing can take the year from a stray number ('9th and 10th July 2019' -> 2009) or drop one glued to
    # text ('July 2020(delayed due to COVID)' -> 2000): the 4-digit year written in the cell wins
    if year is None:
        return d.isoformat()
    try:
        return d.replace(year=year).isoformat()
    except ValueError:  # 29 Feb in a non-leap year
        return d.replace(year=year, day=28).isoformat()


def date_range(v) -> tuple[str | None, str | None]:
    """'01-07-2024 to 30-06-2025' / '2024-2026' / Excel date -> (start, end)."""
    if is_null(v):
        return None, None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return to_date(v), None
    s = str(v)
    parts = re.split(r"\s+(?:to|till|until|–|-)\s+|\s*\n\s*|\s*–\s*", s)
    if len(parts) >= 2:
        return to_date(parts[0]), to_date(parts[-1])
    return to_date(s), None


def to_number(v) -> float | None:
    if is_null(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "")
    m = re.search(r"pkr\s*([\d.]+)\s*(m(illion)?|mn)?", s, re.I) or re.search(r"([\d.]+)\s*(m(illion)?|mn)\b", s, re.I) \
        or re.search(r"([\d]+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    if len(m.groups()) > 1 and m.group(2):
        n *= 1_000_000
        return n
    return n


def million(v) -> float | None:
    """A 'PKR Million' cell -> millions (rupees typed into million columns are scaled down)."""
    n = to_number(v)
    if n is None:
        return None
    if isinstance(v, str) and re.search(r"million|\bm\b|mn", v, re.I) and n >= 1_000_000:
        return round(n / 1_000_000, 4)
    if n >= 10_000:  # clearly rupees
        return round(n / 1_000_000, 4)
    return n


def rupees(v) -> float | None:
    n = to_number(v)
    if n is None:
        return None
    if isinstance(v, str) and re.search(r"million", v, re.I) and n < 1_000_000:
        n *= 1_000_000
    return n


def nat_int(v) -> str | None:
    s = (text(v) or "").lower()
    if "inter" in s:
        return "International"
    if "nation" in s or "local" in s:
        return "National"
    return None


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
def norm_name(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = TITLES.sub(" ", s + " ")
    s = TITLES.sub(" ", s)
    s = s.replace("-", " ").replace(".", " ")
    s = re.sub(r"\bud\s+din\b", "uddin", s)
    s = re.sub(r"\bud\s+deen\b", "uddin", s)
    s = re.sub(r"\bur\s+rehman\b", "urrehman", s)
    s = re.sub(r"\bul\s+", "ul", s)
    s = s.replace("hussian", "hussain").replace("mujeeb", "mujib").replace("hassan", "hasan") \
        .replace("lodhi", "lodi").replace("muhammed", "muhammad").replace("mohammad", "muhammad") \
        .replace("mohammed", "muhammad")
    s = re.sub(r"[^a-z ]", " ", s)
    return " ".join(s.split())


def dept_code(hint: str | None) -> str | None:
    s = (hint or "").lower()
    if not s:
        return None
    for pattern, code in DEPT_HINTS:
        if re.search(pattern, s):
            return code
    return None


def split_people(cell) -> list[dict]:
    """'Dr. A, Associate Professor, Dept of X; Dr. B (EED)' -> [{name, designation, dept_hint, raw}]."""
    s = text(cell)
    if not s:
        return []
    s = s.replace("\n", "|")
    chunks = re.split(r"\s*(?:;|\|\||\s&\s(?=(?:dr|prof|engr|mr|ms)\.?\s)|\s+and\s+(?=(?:dr|prof|engr)\.?\s)|"
                      r"\n|,\s*(?=(?:dr|prof|engr)\.?\s))\s*", s, flags=re.I)
    out = []
    for ch in chunks:
        ch = ch.strip(" ,|")
        if not ch:
            continue
        parts = [p.strip() for p in re.split(r"\s*[|,]\s*", ch) if p.strip()]
        if not parts:
            continue
        name = parts[0]
        designation = ""
        hint_parts = []
        paren = re.findall(r"\(([^)]*)\)", ch)
        for p in parts[1:]:
            pl = p.lower()
            if not designation and any(d in pl for d in DESIGNATIONS):
                designation = p
            else:
                hint_parts.append(p)
        # "Dr X Associate Professor EED" without separators
        if not designation:
            for d in DESIGNATIONS:
                idx = name.lower().find(d)
                if idx > 3:
                    designation = name[idx:]
                    hint_parts.append(designation[len(d):])
                    designation = name[idx:idx + len(d)]
                    name = name[:idx]
                    break
        hint = " ".join(hint_parts + paren)
        out.append({"name": re.sub(r"\(.*?\)", "", name).strip(" ,-"), "designation": designation.strip(),
                    "dept_hint": hint, "raw": ch})
    return out


class PersonMatcher:
    """Match free-text names to Person rows (exact normalised name / alias, then fuzzy within department)."""

    def __init__(self):
        from people.models import Person

        self.people = list(Person.objects.select_related("department").all())
        self.by_norm: dict[str, list] = {}
        self.norms: list[tuple] = []  # (person, [normalised names])
        for p in self.people:
            keys = [k for k in {norm_name(n) for n in {p.full_name, *(p.aliases or [])}} if k]
            self.norms.append((p, keys))
            for key in keys:
                self.by_norm.setdefault(key, []).append(p)
        self.cache: dict[tuple, tuple] = {}

    def match(self, name: str, dept_hint: str = "", *, threshold=0.88):
        ck = (name, dept_hint)
        if ck not in self.cache:
            self.cache[ck] = self._match(name, dept_hint, threshold)
        return self.cache[ck]

    def _match(self, name: str, dept_hint: str, threshold: float):
        key = norm_name(name)
        if not key or len(key) < 4:
            return None, []
        code = dept_code(dept_hint)
        exact = self.by_norm.get(key, [])
        if len(exact) == 1:
            return exact[0], []
        if len(exact) > 1:
            same = [p for p in exact if p.department_id and p.department.code == code]
            if len(same) == 1:
                return same[0], []
        scored = []
        for p, keys in self.norms:
            best = 0.0
            for n in keys:
                sm = SequenceMatcher(None, key, n)
                if sm.real_quick_ratio() >= 0.7 and sm.quick_ratio() >= 0.7:
                    best = max(best, sm.ratio())
            if code and p.department_id and p.department.code == code:
                best += 0.04
            if best >= 0.7:
                scored.append((best, p))
        scored.sort(key=lambda x: -x[0])
        if scored and scored[0][0] >= threshold and (len(scored) == 1 or scored[0][0] - scored[1][0] > 0.03):
            return scored[0][1], []
        sugg = [{"person_id": p.pk, "name": p.full_name, "department": p.department.code if p.department_id else "",
                 "score": round(min(s, 1), 2)} for s, p in scored[:5]]
        return None, sugg
