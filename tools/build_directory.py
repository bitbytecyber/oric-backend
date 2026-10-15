#!/usr/bin/env python
"""Build the NED University faculty / department / people directory seed CSVs.

Scrapes every department's faculty page, cleans names / designations / emails,
merges in PI / inventor / award-winner names from the ORIC self-assessment
scorecard workbook, and writes:

    org/seed/faculties.csv
    org/seed/departments.csv
    org/seed/people.csv
    org/seed/oric_staff.csv

Re-runnable. Run from the backend root:

    python -I tools/build_directory.py [--cache-dir DIR] [--offline] [--excel PATH]  (default: .local/hec_fy2024-25.xlsx)
                                       [--raw-json PATH] [--out DIR]

--cache-dir  save fetched HTML there and reuse it on later runs (no re-fetch)
--offline    never hit the network; use cache, then the raw JSON fallback
Dependencies: stdlib only; uses `requests` and `openpyxl` when installed
(openpyxl is required for the Excel merge, which is skipped without it).
"""
import argparse
import csv
import difflib
import html as htmlmod
import json
import os
import re
import sys
import time
import unicodedata
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(ROOT, "org", "seed")
DEFAULT_EXCEL = os.path.join(ROOT, ".local", "hec_fy2024-25.xlsx")
DEFAULT_RAW = os.path.join(
    os.environ.get("TEMP", ""), "claude", "D--Remote-oric",
    "2cdeb2f1-0a06-4fc2-b8f9-d5bf1d5626b5", "scratchpad", "ned_faculty_raw.json")
PLACEHOLDER_DOMAIN = "placeholder.neduet.edu.pk"
UA = "Mozilla/5.0 (ORIC directory builder; NED University ORIC)"
DELAY = 1.0

# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
FACULTIES = [
    # code, name, short_name, dean full name, dean home dept
    ("CPL", "Faculty of Civil & Petroleum Engineering", "Civil & Petroleum", "Prof. Dr. Asad-ur-Rehman Khan", "CED"),
    ("ECE", "Faculty of Electrical & Computer Engineering", "Electrical & Computer", "Prof. Dr. Saad Ahmed Qazi", "EED"),
    ("MME", "Faculty of Mechanical & Manufacturing Engineering", "Mechanical & Manufacturing", "Prof. Dr. Syed Amir Iqbal", "MED"),
    ("CPE", "Faculty of Chemical & Process Engineering", "Chemical & Process", "Prof. Dr. Zahoor ul Hussain Awan", "CHE"),
    ("ASC", "Faculty of Architecture & Sciences", "Architecture & Sciences", "Prof. Dr. Mirza Mahmood Baig", "EMS"),
    ("TIEST", "Thar Institute of Engineering, Sciences & Technology", "TIEST", None, None),
]

# code, name, faculty, subdomain, path, parse-config
DEPARTMENTS = [
    ("CED", "Civil Engineering", "CPL", "ced", "/teaching-staff-new", {"mode": "header"}),
    ("UED", "Urban & Infrastructure Engineering", "CPL", "ued", "/teaching-staff", {"mode": "after"}),
    ("PED", "Petroleum Engineering", "CPL", "ped", "/faculties", {"mode": "after", "all": True}),
    ("EQD", "Earthquake Engineering", "CPL", "eqd", "/Faculty", {"mode": "header"}),
    ("END", "Environmental Engineering", "CPL", "end", "/teaching-staff", {"mode": "after"}),
    ("EED", "Electrical Engineering", "ECE", "eed", "/teaching-staff", {"mode": "after"}),
    ("ELD", "Electronic Engineering", "ECE", "eld", "/teaching-staff", {"mode": "after"}),
    ("TCD", "Telecommunications Engineering", "ECE", "tcd", "/faculty", {"mode": "before"}),
    ("CIS", "Computer & Information Systems Engineering", "ECE", "cis", "/portfolio", {"mode": "after", "profiles": True}),
    ("BMD", "Biomedical Engineering", "ECE", "bmd", "/faculty", {"mode": "after", "email": "before"}),
    ("CSIT", "Computer Science & Information Technology", "ECE", "cct", "/faculty", {"mode": "header"}),
    ("SWE", "Software Engineering", "ECE", "se", "/faculty", {"mode": "header"}),
    ("MED", "Mechanical Engineering", "MME", "med", "/node/22", {"mode": "header"}),
    ("IMD", "Industrial & Manufacturing Engineering", "MME", "imd", "/faculty", {"mode": "after"}),
    ("TXD", "Textile Engineering", "MME", "txd", "/faculty", {"mode": "header"}),
    ("AMD", "Automotive & Marine Engineering", "MME", "atd", "/Faculty", {"mode": "after"}),
    ("CHE", "Chemical Engineering", "CPE", "dec", "/teaching-staff", {"mode": "after"}),
    ("PPD", "Polymer & Petrochemical Engineering", "CPE", "ppd", "/teaching-staff", {"mode": "after", "all": True}),
    ("MMD", "Materials Engineering", "CPE", "mmd", "/teaching-staff", {"mode": "after"}),
    ("MYD", "Metallurgical Engineering", "CPE", "myd", "/teaching-staff-0", {"mode": "after", "all": True}),
    ("FED", "Food Engineering", "CPE", "fed", "/teaching-staff", {"mode": "fed"}),
    ("ARD", "Architecture & Planning", "ASC", "ard", "/faculty", {"mode": "before"}),
    ("EMS", "Economics & Management Sciences", "ASC", "emd", "/PermanentFaculty", {"mode": "header"}),
    ("PHY", "Physics", "ASC", "dph", "/teaching-staff", {"mode": "header"}),
    ("CHY", "Chemistry", "ASC", "dcy", "/teaching_staff", {"mode": "after"}),
    ("MTH", "Mathematics", "ASC", "dmt", "/node/20", {"mode": "after"}),
    ("ELS", "English Linguistics & Allied Studies", "ASC", "del", "/teaching-staff", {"mode": "header"}),
    ("ESD", "Essential Studies", "ASC", "des", "/teaching-staff", {"mode": "after"}),
    ("TCE", "Civil Engineering (TIEST)", "TIEST", "ced.tiest", None, None),
    ("TCS", "Computer Science & Technology (TIEST)", "TIEST", "cct.tiest", "/faculty", {"mode": "inline"}),
    ("TSH", "Sciences & Humanities (TIEST)", "TIEST", None, None, None),
]

# chair, co-chairs (full names as given by ORIC)
CHAIRS = {
    "CED": ("Prof. Dr. Abdul Jabbar Sangi", []),
    "UED": ("Prof. Adnan Qadir", ["Dr. Afzal Ahmed", "Dr. Muhammad Ahmed"]),
    "PED": ("Dr. Shaine Mohammadali Lalji", []),
    "EQD": ("Prof. Muhammad Masood Rafi", []),
    "END": ("Prof. Dr. Atif Mustafa", []),
    "EED": ("Prof. Dr. Attaullah Khawaja", []),
    "ELD": ("Prof. Dr. Sadia Muniza Faraz", []),
    "TCD": ("Prof. Dr. Muhammad Imran Aslam", []),
    "CIS": ("Dr. Muhammad Ali Ismail", []),
    "BMD": ("Prof. Dr. Eraj Humayun Mirza", []),
    "CSIT": ("Prof. Dr. Muhammad Mubashir Khan", ["Prof. Dr. Shariq Mahmood Khan"]),
    "SWE": ("Prof. Dr. Shehnila Zardari", []),
    "MED": ("Dr. Mubashir Ali Siddiqui", ["Dr. Muhammad Shakaib"]),
    "IMD": ("Prof. Dr. Muhammad Wasif", []),
    "TXD": ("Prof. Dr. Bilal Zahid", []),
    "AMD": ("Prof. Dr. Ali Raza Jafri", []),
    "CHE": ("Prof. Dr. Saud Hashmi", []),
    "PPD": ("Prof. Dr. Saud Hashmi", []),  # PPD site lists him as "Ag. Chairperson"
    "MMD": ("Prof. Dr. Fayaz Hussain", []),
    "MYD": ("Prof. Dr. Ali Dad Chandio", []),
    "FED": ("Dr. Syed Ali Ammar Taqvi", []),
    "ARD": ("Prof. Dr. Anila Naeem", ["Dr. Saeed Ud Din Ahmed"]),
    "EMS": ("Prof. Dr. Mirza Mahmood Baig", []),
    "PHY": ("Dr. Junaid Kareem Khan", []),
    "CHY": ("Dr. Amtul Qayoom", []),
    "MTH": ("Dr. Fahim Raees", []),
    "ELS": ("Prof. Dr. Sajida Zaki", []),
    "ESD": ("Prof. Dr. Abdul Hai Madni", ["Prof. Dr. Farooq Hasan"]),
    "TCE": ("Prof. Dr. Muhammad Aslam Bhutto", []),
    "TCS": ("Prof. Dr. Syed Abbas Ali", []),
    "TSH": (None, []),
}

# Home department for people listed on several department pages.
HOME = {
    "asad ur rehman khan": "CED",
    "saad ahmed qazi": "EED",
    "syed amir iqbal": "IMD",     # listed on IMD page (Dean MME); moved to MED below if required
    "zahoor ul hussain awan": "CHE",
    "mirza mahmood baig": "EMS",
    "syed abbas ali": "TCS",
    "saud hashmi": "CHE",
}
# Force a person into a department (deans in their home dept per ORIC brief).
FORCE_DEPT = {"syed amir iqbal": "MED"}

# Names on faculty pages that are not NED teaching faculty (IT managers, adjuncts...)
EXCLUDE = {
    "CHY": ["syed adnan ali shah", "haider abbas khwaja"],
    "CSIT": ["zahid nazir ahmed", "nazish irfan", "muhammad noman khan"],
    "SWE": ["nazish irfan", "muhammad noman khan"],
    "TXD": ["arsalan waheed"],
    "MYD": ["nuzhat afreen", "naveed ahmed", "shahid hussain"],
    "PED": ["mei chun li", "numair ahmed siddiqui"],
    "TCD": ["muhammad zeeshan shakir"],
    "END": ["heekwan lee"],
}
DESIG_OVERRIDE = {("PED", "javed haneef"): "Professor"}
# Final designation for people whose rows were merged from several department pages.
FINAL_DESIG = {
    "zahoor ul hussain awan": "Professor & Dean CPE",
    "asad ur rehman khan": "Meritorious Professor & Dean CPL",
    "saad ahmed qazi": "Meritorious Professor & Dean ECE",
    "syed amir iqbal": "Professor & Dean MME",
    "mirza mahmood baig": "Professor & Dean ASC",
    "saud hashmi": "Professor & Chairman (Ag. Chairperson PPD)",
    "syed abbas ali": "Professor & Chairperson (TIEST Computer Science & Technology; Professor, CIS)",
}

ORIC_STAFF = [
    # email, full_name, title, role, order, match-name
    ("oric@neduet.edu.pk", "Dr. Riaz Uddin", "Director ORIC", "oric_director", "riaz uddin"),
    ("uzair@neduet.edu.pk", "Dr. Muhammad Uzair", "Manager Research Operations", "research_ops_manager", "muhammad uzair"),
    ("aahmed@neduet.edu.pk", "Dr. Ashar Ahmed", "Manager Intellectual Property", "ip_manager", "ashar ahmed"),
    ("saeeda@neduet.edu.pk", "Dr. Saeeda Nadir Ali", "Manager Technology Transfer", "tech_transfer_manager", "saeeda nadir ali"),
    ("mirzafaizan@cloud.neduet.edu.pk", "Dr. Mirza Faizan Ahmed", "Manager Incubation", "incubation_manager", "mirza faizan ahmed"),
    ("tahreem@neduet.edu.pk", "Ms. Tehreem Beg", "Assistant Manager ORIC", "oric_manager", "tehreem beg"),
    ("engrimran@neduet.edu.pk", "Dr. Syed Imran Ali", "Assistant Manager ORIC", "oric_manager", "syed imran ali"),
    ("farwa.hasan@" + PLACEHOLDER_DOMAIN, "Ms. Farwa Hasan", "Communication Manager", "oric_staff", "farwa hasan"),
]

# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------
EM = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
GENERIC_LOCAL = re.compile(r"^(c[a-z]{1,3}|c[a-z]{2,3}d|dean[a-z]*|chair[a-z]*|pa\..*|ccs\..*|info|office|oric|turkishfaculty\d*)$", re.I)
TITLE_WORDS = r"(?:Prof\.?|Professor|Dr\.?|Dr\.-Ing\.?|-Ing\.?|Ing\.?|Engr\.?|Mr\.?|Ms\.?|Mrs\.?|Miss|Ar\.?)"
TITLE_RE = re.compile(r"^(?:%s(?:\s+|(?<=\.)))+" % TITLE_WORDS, re.I)
NAMESTART = re.compile(r"^(?:Dr\.?\s?-\s?Ing\.?|Prof\.?|Dr\.?|Engr\.?|Mr\.?|Ms\.?|Mrs\.?|Miss|Syed|Syeda|Sayyda|Hafiz|Hafiza|Muhammad|Mirza)\s", re.I)
DES_CORE = (r"(?:Professor|Associate\s*Professor|Assistant\s*Professor|Lecturer|Chairman|Chairperson|Chairwoman|"
            r"Co-?\s?Chairman|Co-?\s?Chairperson|Dean|Senior Lecturer|Professor Emeritus|Pro[- ]Vice[- ]Chancellor|Vice[- ]Chancellor|"
            r"Lab(?:oratory)?\s+Engineers?|Senior Lab|IT Manager|Senior IT Manager|PA to|Instructor|Director|Lecturers|Professors)")
DES = re.compile(r"^\(?(?:Meritori?o?us\s+|Distinguished\s+|Tenured\s+|Visiting\s+|Adjunct\s+|Honorary\s+|Acting\s+|Ag\.\s*|Contract\s+|Guest\s+|Senior\s+)?%ss?\b" % DES_CORE, re.I)
FACULTY_DES = re.compile(r"professor|lecturer|chair|dean|vice[- ]chancellor", re.I)
NONFAC_DES = re.compile(r"message|adjunct|visiting|guest|lab(oratory)? eng|it manager|pa to|instructor\b(?!.*lecturer)", re.I)
NOT_NAME = re.compile(
    r"\d|:|http|\[|@|Email|E-mail|Phone|Tel\b|Ext|Ph\.?\s?D|B\.?\s?E\b|M\.?\s?E\b|M\.?\s?Sc|M\.?S\b|MS\b|BS\b|Engg|Supervisor|Scholar|"
    r"Professor|Lecturer|Chair|Dean|Department|Faculty|Home|Staff|University|Engineering|Institute|Qualification|Profile|"
    r"Contact|Follow|Message|Research|Laborator|Program|Student|Office|Manager|Notice|Event|Copyright|Google|Scopus|Message|"
    r"Coordinator|Advisor|Director|Area|Name|Designation|Teaching|Adjunct|Visiting|Quick|Links|News|Bio\b|Specialization|Centre|Center|Committee|Society|Network|"
    r"Engineers?\b|Universit|Zealand|Malaysia|Pakistan|Kingdom|\bUSA\b|\bUK\b|Germany|China|Japan|Korea|Australia|Canada|"
    r"Norway|Italy|France|Sweden|Turkey|Teknologi|Ijazah|Course|Islamic|Jurisprudence|Studies|About\b|\bUs$|"
    r"\bBS[A-Z]*\b|\bBSc|NUCES|\bFAST\b|\bMCIT\b|\bMBA\b|Doctorate",
    re.I)
PAREN_OK = re.compile(r"leave|supervisor|approved|retired|co-?chair|abroad|contract", re.I)
CONNECT = {"ul", "ud", "ur", "un", "al", "e", "bin", "din", "uddin", "ullah", "-", "ud-din", "ur-rehman", "de", "van", "u", "us", "un-nabi"}


def fold(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def clean_line(s):
    s = s.replace("\u200b", "").replace("\xa0", " ").replace("\u2013", "-").replace("\u2014", "-")
    s = re.sub(r"\b(Dr|Prof|Engr|Mr|Ms|Mrs)\.(?=[A-Za-z])", r"\1. ", s)
    s = re.sub(r"\b(Dr|Prof|Engr|Mr|Ms|Mrs)\s(?=[A-Z])", r"\1. ", s)
    s = re.sub(r"\.\.+", ".", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip("| ").strip()


def strip_parens(s):
    """Remove '(On Study Leave)' / '(PhD Approved Supervisor)' etc. Return (clean, ok)."""
    ok = True
    for m in re.findall(r"\(([^)]*)\)?", s):
        if not PAREN_OK.search(m):
            ok = False
    s2 = re.sub(r"\([^)]*\)?", " ", s)
    return re.sub(r"\s+", " ", s2).strip(" .,-"), ok


def namey(line):
    s, ok = strip_parens(line)
    if re.match(r"^(MS|BS|BE|ME|MBA|MCS|PhD|M\.?Engg|M\. ?Phil|Member)\b", s or "") or "," in (s or ""):
        return False
    if not ok or not s or len(s) > 60 or NOT_NAME.search(TITLE_RE.sub("", s)):
        return False
    words = [w for w in re.split(r"[\s.]+", TITLE_RE.sub("", s)) if w]
    if not (1 <= len(words) <= 7):
        return False
    if len(words) == 1 and not TITLE_RE.match(s):
        return False
    for w in words:
        if not w[0].isalpha():
            return False
        if not w[0].isupper() and w.lower() not in CONNECT and not w.lower().startswith(("ul-", "ud-", "ur-", "un-")):
            return False
    return True


def tidy_name(raw):
    s, _ = strip_parens(clean_line(raw))
    s = s.rstrip(".,").strip()
    # Title-case ALL-CAPS words (e.g. "BILAL ZAHID")
    s = " ".join(w.title() if (w.isupper() and len(w) > 2) else w for w in s.split())
    s = re.sub(r"\s+", " ", s)
    return s


def bare_name(name):
    """Strip honorifics -> 'Asad-ur-Rehman Khan'."""
    s = clean_line(name)
    s = re.sub(r"\([^)]*\)", " ", s)
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"^(?:Proof\.?|Prof(?:essor)?\.?|Dr\.?(?:\s*-\s*Ing\.?)?|-?Ing\.?|Engr\.?|Mr\.?|Ms\.?|Mrs\.?|Miss|Ar\.?)(?:\s+|(?<=\.))", "", s, flags=re.I).strip()
    return re.sub(r"\s+", " ", s).strip(" .,")


VARIANTS = [
    (r"\bud[\s-]?din\b", "uddin"), (r"\bur[\s-]?rehman\b", "urrehman"), (r"\bur[\s-]?rahman\b", "urrehman"),
    (r"\bhussian\b", "hussain"), (r"\bhusain\b", "hussain"), (r"\bmujib\b", "mujeeb"), (r"\bhassan\b", "hasan"),
    (r"\blodhi\b", "lodi"), (r"\bmohammad\b|\bmohammed\b|\bmuhammed\b|\bmohd\b|\bm\b", "muhammad"),
    (r"\bmurtaza\b", "murtuza"), (r"\bfaraz jawed\b", "faraz javed"), (r"\bul[\s-]haq\b", "ulhaq"), (r"\bul[\s-]hussain\b", "ulhussain"),
    (r"\bullah\b", "ullah"), (r"\bsheikh\b", "shaikh"), (r"\btehreem\b", "tahreem"), (r"\bbeg\b", "baig"),
    (r"\bsiddique\b", "siddiqui"), (r"\bsherazi\b", "shirazi"), (r"\bfaheem\b", "fahim"), (r"\bakhter\b", "akhtar"),
    (r"\basfaq\b", "ashfaq"), (r"\baaisha\b", "ayesha"), (r"\bjaved\b", "javed"), (r"\bjawed\b", "javed"), (r"\bperween\b|\bperveen\b", "parveen"),
]


def norm(name):
    s = fold(bare_name(name)).lower()
    s = s.replace("-", " ").replace(".", " ").replace("'", "")
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for a, b in VARIANTS:
        s = re.sub(a, b, s)
    toks = [t for t in s.split() if t not in ("syed", "syeda", "sayyda", "engr", "dr", "prof")]
    return " ".join(toks)


def key(name):
    """Readable normalized key used for config dicts ('asad ur rehman khan')."""
    s = fold(bare_name(name)).lower().replace("-", " ").replace(".", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()


def is_phd(name, extra=""):
    return 1 if re.search(r"\bDr\b\.?", name) or re.search(r"\bDr\.", extra or "") else 0


def generic_email(e):
    return bool(GENERIC_LOCAL.match(e.split("@")[0]))


def ned(e):
    return e.lower().endswith("neduet.edu.pk")


# --------------------------------------------------------------------------
# HTML -> lines
# --------------------------------------------------------------------------
BLOCK = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "ul", "ol", "dd", "dt"}


class TextLines(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0
        self.a_href = None
        self.a_text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in BLOCK:
            self.out.append("\n")
        if tag == "a":
            self.a_href = dict(attrs).get("href") or ""
            self.a_text = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag == "a" and self.a_href is not None:
            txt = "".join(self.a_text)
            if self.a_href.lower().startswith("mailto") and "@" not in txt:
                self.out.append(" " + htmlmod.unescape(self.a_href[7:]).replace("%20", "").lstrip("%") + " ")
            self.links.append((self.a_href, txt.strip()))
            self.a_href = None
        if tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        self.out.append(data)
        if self.a_href is not None:
            self.a_text.append(data)


def html_lines(text):
    p = TextLines()
    p.feed(text)
    raw = "".join(p.out)
    lines = [clean_line(l) for l in raw.split("\n")]
    return [l for l in lines if l], p.links


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------
class Fetcher:
    def __init__(self, cache_dir=None, offline=False):
        self.cache_dir = cache_dir
        self.offline = offline
        self.session = None
        if not offline:
            try:
                import requests
                import urllib3
                urllib3.disable_warnings()
                self.session = requests.Session()
                self.session.headers["User-Agent"] = UA
            except ImportError:
                self.session = None

    def _cache_path(self, url):
        return os.path.join(self.cache_dir, re.sub(r"[^A-Za-z0-9]+", "_", url)[:150] + ".html")

    def get(self, url):
        if self.cache_dir:
            cp = self._cache_path(url)
            if os.path.exists(cp):
                with open(cp, encoding="utf-8") as fh:
                    return fh.read()
        if self.offline:
            return None
        text = None
        for attempt in range(4):
            try:
                time.sleep(DELAY * (1 + 2 * attempt))
                if self.session is not None:
                    # NED department sites serve an incomplete TLS chain; these are public pages.
                    r = self.session.get(url, timeout=40, verify=False)
                    if r.status_code == 200:
                        r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
                        text = r.text
                        break
                else:
                    import ssl
                    import urllib.request
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    req = urllib.request.Request(url, headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=40, context=ctx) as resp:
                        text = resp.read().decode("utf-8", "replace")
                        break
            except Exception as exc:  # noqa: BLE001
                print(f"  ! fetch {url} attempt {attempt + 1}: {exc.__class__.__name__}", file=sys.stderr)
        if text and self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._cache_path(url), "w", encoding="utf-8") as fh:
                fh.write(text)
        return text


# --------------------------------------------------------------------------
# Department page parsers
# --------------------------------------------------------------------------
def tidy_des(d):
    if not d:
        return None
    d = clean_line(d).strip(" ,/&")
    d = re.sub(r",?\s*Department of [A-Za-z &]+$", "", d, flags=re.I)
    d = re.sub(r"\s*&\s*$|\s*/\s*$", "", d)
    d = re.sub(r"(?i)\bAssociateProfessor\b", "Associate Professor", d)
    d = re.sub(r",\s*[A-Z]{2,5}$", "", d)
    d = re.sub(r"(?i)^(Associate |Assistant )?Professors$", lambda m: (m.group(1) or "").title() + "Professor", d)
    d = re.sub(r"(?i)^Lecturers$", "Lecturer", d)
    if d.isupper():
        d = d.title()
    d = re.sub(r"\s+", " ", d).strip(" ,/&")
    return d or None


def pick_email(lines):
    """First line that carries a non-generic email; prefer NED address on that line."""
    for l in lines:
        ems = [e.strip(".") for e in EM.findall(l)]
        ems = [e for e in ems if not generic_email(e)]
        if ems:
            nd = [e for e in ems if ned(e)]
            return (nd or ems)[0].lower()
    return None


def pick_ext(lines):
    for l in lines:
        m = re.search(r"Ext(?:ension|n)?\.?\s*(?:no\.?)?\s*[:.]?\s*(\d{3,4})", l, re.I)
        if m:
            return "Ext. " + m.group(1)
    return ""


def parse_generic(lines, cfg):
    mode = cfg.get("mode", "after")
    n = len(lines)
    idx = []
    for i, l in enumerate(lines):
        if not namey(l):
            continue
        s, _ = strip_parens(l)
        ahead = lines[i + 1:i + 5]
        behind = lines[max(0, i - 4):i]
        if NAMESTART.match(s) or any(DES.match(x) for x in lines[i + 1:i + 3]) \
                or (mode == "header" and any(EM.search(x) for x in ahead)) \
                or (cfg.get("email") == "before" and any(EM.search(x) for x in behind)):
            idx.append(i)
    people = []
    header = None
    hpos = 0
    for k, i in enumerate(idx):
        prev_i = idx[k - 1] if k else -1
        nxt = idx[k + 1] if k + 1 < len(idx) else min(n, i + 15)
        after = lines[i + 1:nxt]
        before = lines[prev_i + 1:i]
        # sticky header (header mode): last DES line before this name
        for j in range(hpos, i):
            if DES.match(lines[j]) and len(lines[j]) < 70 and not re.match(r"(?i)director", lines[j]):
                header = lines[j]
        hpos = i
        des = None
        if mode == "after":
            ds = [x for x in after if DES.match(x) and len(x) < 120 and not re.match(r"(?i)^(Associate |Assistant )?Professors$|^Lecturers$", x)]
            if cfg.get("all"):
                seen = []
                for x in ds:
                    t = tidy_des(x)
                    if t and t not in seen:
                        seen.append(t)
                des = " / ".join(seen) if seen else None
            else:
                des = ds[0] if ds else None
            if not des:
                des = header if header and mode == "after" and cfg.get("fallback_header") else None
        elif mode == "before":
            ds = [x for x in before if DES.match(x) and len(x) < 120]
            des = ds[-1] if ds else None
            if not des:
                ds = [x for x in after[:3] if DES.match(x)]
                des = ds[0] if ds else None
        elif mode == "header":
            # a personal designation right after the name wins, else the section header
            nxt_line = after[0] if after else ""
            personal = DES.match(nxt_line) and len(nxt_line) < 120 and not re.match(
                r"(?i)^(director|(associate |assistant )?professors$|lecturers$)", nxt_line)
            des = nxt_line if personal else header
        email_zone = before if cfg.get("email") == "before" else after
        if mode in ("before",) and not pick_email(after):
            email_zone = after
        people.append({
            "raw_name": lines[i],
            "designation": tidy_des(des),
            "email": pick_email(email_zone),
            "phone": pick_ext(email_zone),
            "header": header,
        })
    return people


def parse_fed(lines, cfg):
    out = []
    for l in lines:
        if l.startswith("\u25b6") or l.startswith("▶"):
            body = l.lstrip("\u25b6▶ ").strip()
            parts = re.split(r"\s+[-]\s+", body, maxsplit=1)
            name = parts[0]
            des = parts[1] if len(parts) > 1 else None
            if des:
                des = re.sub(r",?\s*PhD Approved Supervisor", "", des, flags=re.I)
                des = re.sub(r"\(.*?\)", "", des)
                des = re.sub(r",?\s*Dean Faculty of Chemical and Process Engineering.*", " / Dean CPE", des)
                des = re.sub(r"\s*,\s*", " / ", des.strip(" ,"))
            out.append({"raw_name": name, "designation": tidy_des(des), "email": None, "phone": ""})
    return out


def parse_inline(lines, cfg):
    out = []
    for i, l in enumerate(lines):
        m = re.match(r"^(.*?)\s+(Dean|Chairperson|Chairman|Professor|Associate Professor|Assistant Professor|Lecturer)$", l)
        if m and namey(m.group(1)):
            zone = []
            for x in lines[i + 1:i + 8]:
                if re.match(r"^(.*?)\s+(Dean|Chairperson|Chairman|Professor|Associate Professor|Assistant Professor|Lecturer)$", x):
                    break
                zone.append(x)
            des = m.group(2)
            if des == "Chairperson":
                des = "Professor / Chairperson"
            out.append({"raw_name": m.group(1), "designation": des, "email": pick_email(zone), "phone": pick_ext(zone)})
    return out


def cis_profile_emails(fetcher, links, people):
    base = "https://cis.neduet.edu.pk"
    slugs = {}
    for href, txt in links:
        if txt and href.startswith("/") and namey(txt):
            slugs[norm(tidy_name(txt))] = href
    for p in people:
        slug = slugs.get(norm(tidy_name(p["raw_name"])))
        if not slug or p.get("email"):
            continue
        page = fetcher.get(base + slug)
        if not page:
            continue
        ems = [e.lower() for e in EM.findall(page) if not generic_email(e)]
        nd = [e for e in ems if ned(e)]
        if nd or ems:
            p["email"] = (nd or ems)[0]


# --------------------------------------------------------------------------
# Main build
# --------------------------------------------------------------------------
class Person:
    def __init__(self, full_name, designation, dept, email=None, phone="", source="website"):
        self.full_name = full_name
        self.designation = designation or ""
        self.dept = dept
        self.email = email
        self.phone = phone or ""
        self.aliases = []
        self.source = source
        self.email_source = "scraped" if email else "placeholder"
        self.excel = False

    @property
    def nkey(self):
        return norm(self.full_name)

    def add_alias(self, a):
        a = re.sub(r"\s+", " ", (a or "").replace("\n", " ")).strip(" ,;")
        if a and a != self.full_name and a not in self.aliases and ";" not in a:
            self.aliases.append(a)


def des_rank(d):
    d = (d or "").lower()
    r = 0
    if "chair" in d:
        r += 4
    if "dean" in d:
        r += 4
    if "vice" in d:
        r += 3
    r += min(len(d), 60) / 100.0
    return r


def merge_into(a, b):
    """Merge person b into a (same human)."""
    if des_rank(b.designation) > des_rank(a.designation):
        a.designation = b.designation
    if not a.email and b.email:
        a.email, a.email_source = b.email, "scraped"
    if not a.phone and b.phone:
        a.phone = b.phone
    if len(bare_name(b.full_name)) > len(bare_name(a.full_name)) and norm(b.full_name) == norm(a.full_name):
        pass
    if b.full_name != a.full_name:
        a.add_alias(b.full_name)
    for x in b.aliases:
        a.add_alias(x)
    # richer title (Prof. Dr.) wins
    ta = len(a.full_name) - len(bare_name(a.full_name))
    tb = len(b.full_name) - len(bare_name(b.full_name))
    if tb > ta and norm(b.full_name) == norm(a.full_name):
        a.add_alias(a.full_name)
        a.full_name = b.full_name
        if a.full_name in a.aliases:
            a.aliases.remove(a.full_name)


def scrape(args):
    fetcher = Fetcher(args.cache_dir, args.offline)
    raw = {}
    if args.raw_json and os.path.exists(args.raw_json):
        with open(args.raw_json, encoding="utf-8") as fh:
            raw = json.load(fh)
    people = []
    report = {}
    for code, dname, fac, sub, path, cfg in DEPARTMENTS:
        if not sub or not path:
            report[code] = "no faculty page"
            continue
        url = f"https://{sub}.neduet.edu.pk{path}"
        print(f"[{code}] {url}", file=sys.stderr)
        page = fetcher.get(url)
        recs = []
        if page:
            lines, links = html_lines(page)
            mode = cfg.get("mode")
            if mode == "fed":
                recs = parse_fed(lines, cfg)
            elif mode == "inline":
                recs = parse_inline(lines, cfg)
            else:
                recs = parse_generic(lines, cfg)
            if cfg.get("profiles"):
                cis_profile_emails(fetcher, links, recs)
            report[code] = "website"
        if not recs and sub in raw:
            print(f"  -> falling back to raw json for {code}", file=sys.stderr)
            for m in raw[sub].get("members", []):
                recs.append({"raw_name": m.get("name") or "", "designation": tidy_des(m.get("designation")),
                             "email": (m.get("email") or "").lower() or None, "phone": ""})
            report[code] = "raw-json fallback"
        excl = set(EXCLUDE.get(code, []))
        dept_people = []
        for r in recs:
            name = tidy_name(r["raw_name"])
            k = key(name)
            if not name or k in excl:
                continue
            des = DESIG_OVERRIDE.get((code, k), r.get("designation"))
            if not des or not FACULTY_DES.search(des) or NONFAC_DES.search(des):
                continue
            email = r.get("email")
            if email and generic_email(email):
                email = None
            p = Person(name, des, code, email, r.get("phone", ""))
            if r["raw_name"].strip() != name:
                pass
            # within-dept dedupe
            dup = next((q for q in dept_people if q.nkey == p.nkey), None)
            if dup:
                merge_into(dup, p)
            else:
                dept_people.append(p)
        people.extend(dept_people)
    return people, report


def resolve_cross_dept(people):
    """Same human listed on several department pages -> keep one row."""
    out = []
    by_key = {}
    for p in people:
        by_key.setdefault(p.nkey, []).append(p)
    removed = set()
    for k, group in by_key.items():
        if len(group) < 2:
            continue
        # split into humans: different real emails => different people
        clusters = []
        for p in group:
            for c in clusters:
                emails = {q.email for q in c if q.email}
                if not p.email or not emails or p.email in emails:
                    c.append(p)
                    break
            else:
                clusters.append([p])
        for c in clusters:
            if len(c) < 2:
                continue
            home = HOME.get(key(c[0].full_name))
            keep = next((q for q in c if q.dept == home), None) or c[0]
            for q in c:
                if q is not keep:
                    merge_into(keep, q)
                    removed.add(id(q))
            if home and keep.dept != home:
                keep.dept = home
    for p in people:
        if id(p) not in removed:
            out.append(p)
    for p in out:
        f = FORCE_DEPT.get(key(p.full_name))
        if f:
            p.dept = f
    return out


def find_person(people, name, dept=None):
    nk = norm(name)
    cands = [p for p in people if p.nkey == nk]
    if dept:
        d = [p for p in cands if p.dept == dept]
        if d:
            return d[0]
    if len(cands) == 1:
        return cands[0]
    # subset match (e.g. "Saeed Ud Din Ahmed" vs "Saeed Uddin Ahmed")
    toks = set(nk.split())
    sub = [p for p in people if (dept is None or p.dept == dept) and len(toks) >= 2 and toks <= set(p.nkey.split())]
    if len(sub) == 1:
        return sub[0]
    return cands[0] if cands else None


def ensure_leaders(people):
    """Every dean / chair / co-chair exists, in the right department."""
    created = []

    def ensure(name, dept, role):
        p = find_person(people, name, dept)
        if p is None:
            des = {"dean": "Professor / Dean", "chair": "Chairperson", "co": "Co-Chairperson"}[role]
            if role != "dean" and name.startswith("Prof"):
                des = "Professor / " + des
            p = Person(name, des, dept, None, "", "website")
            people.append(p)
            created.append((dept, name))
        else:
            if p.dept != dept:
                p.dept = dept
            # prefer the fuller official title spelling
            if len(name) > len(p.full_name) and norm(name) == p.nkey:
                p.add_alias(p.full_name)
                p.full_name = name
        return p

    leaders = {"dean": {}, "chair": {}, "co": {}}
    for code, _, _, dean, home in FACULTIES:
        if dean:
            leaders["dean"][code] = ensure(dean, home, "dean")
    for dept, (chair, cos) in CHAIRS.items():
        if chair:
            leaders["chair"][dept] = ensure(chair, dept if not (dept == "PPD") else "CHE", "chair")
        leaders["co"][dept] = [ensure(c, dept, "co") for c in cos]
    return leaders, created


# ---------------------------- Excel merge ---------------------------------
DEPT_HINTS = [
    (r"urban|\bued\b", "UED"), (r"petroleum|\bped\b", "PED"), (r"earthquake|\beqd\b", "EQD"),
    (r"environment", "END"), (r"polymer|petrochem|\bppd\b", "PPD"), (r"metallurg|\bmyd\b", "MYD"),
    (r"chemistry|\bdcy\b", "CHY"), (r"chemical|\bdec\b|\bche\b", "CHE"), (r"tele\s*com|\btcd?\b", "TCD"),
    (r"electronic|\beld\b", "ELD"), (r"computer\s*(and|&)\s*info|\bcis\b|computer systems", "CIS"),
    (r"bio-?\s*medical|\bbmd\b", "BMD"), (r"computer science|cs\s*&\s*it|\bcsit\b|\bcct\b", "CSIT"),
    (r"software|\bswe?\b", "SWE"), (r"electrical|elec\.?\s*eng|\beed\b|\bee\b", "EED"),
    (r"\bcivil\b|\bced\b", "CED"), (r"mech[a-z]*\b|\bmed\b|\bme\b", "MED"),
    (r"industrial|manufactur|\bimd\b", "IMD"), (r"textile|\btxd\b", "TXD"), (r"automotive|marine|\bamd\b|\batd\b", "AMD"),
    (r"material|\bmmd\b", "MMD"), (r"\bfood\b|\bfed\b", "FED"), (r"architect|\bard\b", "ARD"),
    (r"economics|management sci|\bemd\b|\bems\b", "EMS"), (r"physics|\bdph\b", "PHY"),
    (r"math|\bdmt\b", "MTH"), (r"english|linguist|humanit|\bdel\b", "ELS"), (r"essential|islamic|pakistan studies|\bdes\b", "ESD"),
]
EXTERNAL = re.compile(r"universit(y|i)|institute|\bltd\b|\bpvt\b|company|hospital|\bnust\b|\buet\b|\bfast\b|szabist|\bitu\b|"
                      r"college|agency|corporation|\bjv\b|board|council", re.I)
NAME_TOKEN_STOP = re.compile(r"^(professor|prof|associate|assistant|asst|assoc|lecturer|dean|chair\w*|co|department|dept|director|vice|pro|"
                             r"senior|sr|lab|pi|principal|registrar|meritorious|head|faculty|engineering|eng|and|of|the|ned|"
                             r"manager|member|incharge|in|for|ag|acting|approved|phd|supervisor|centre|center|national|investigator|"
                             r"assiatent|assistance|rofessor)$", re.I)
TITLE_TOK = re.compile(r"^(proof\.?|prof\.?|dr\.?|engr\.?|mr\.?|ms\.?|mrs\.?|ar\.?|miss|dr\.-ing\.?)$", re.I)
EX_DES = [("Pro-Vice Chancellor", r"pro[- ]?vice"), ("Vice Chancellor", r"vice\s*chancellor"),
          ("Associate Professor", r"assoc\w*\.?\s*prof"), ("Assistant Professor", r"ass\w*\.?\s*prof"),
          ("Professor", r"\bprof(essor)?\b(?!\.\s*dr)"), ("Lecturer", r"lecturer")]


def dept_hint(text):
    t = text.lower()
    for rx, code in DEPT_HINTS:
        if re.search(rx, t):
            return code
    return None


def split_excel_people(cell):
    """Yield (raw_name, context_text) for every person mentioned in a cell."""
    text = str(cell).replace("\r", "\n")
    text = re.sub(r"\b(Dr|Prof|Engr|Mr|Ms|Mrs|Ar)\.(?=[A-Za-z])", r"\1. ", text)
    text = re.sub(r"\(\s*(co-?)?pi\s*\)|\bco-?pi\b|\bPI\b\s*[-:]?", " , ", text, flags=re.I)
    # tokenize keeping separators
    pieces = re.split(r"(\n|;|,|/|\||\(|\)| and |&)", text)
    results = []
    cur_name = None
    cur_ctx = []
    for piece in pieces:
        if piece is None:
            continue
        seg = piece.strip()
        if not seg or seg in (",", ";", "/", "|", "(", ")", "\n", "and", "&"):
            cur_ctx.append(" ")
            continue
        toks = seg.split()
        # Does this segment start with a person name?
        i = 0
        titled = False
        while i < len(toks) and TITLE_TOK.match(toks[i]):
            i += 1
            titled = True
        name_toks = []
        while i < len(toks):
            t = toks[i].strip(".,:")
            if not t or NAME_TOKEN_STOP.match(t) or not (t[0].isupper() or t.lower() in CONNECT):
                break
            name_toks.append(toks[i].strip(","))
            i += 1
        looks_name = len(name_toks) >= 2 and (titled or not EXTERNAL.search(seg)) and not dept_hint(" ".join(name_toks)) \
            and not re.search(r"\d", seg)
        if looks_name and (titled or cur_name is None or not cur_ctx or all(c == " " for c in cur_ctx[-1:])):
            if cur_name:
                results.append((cur_name, " ".join(cur_ctx)))
            cur_name = " ".join(toks[:i])
            cur_ctx = [" ".join(toks[i:])]
        else:
            cur_ctx.append(seg)
    if cur_name:
        results.append((cur_name, " ".join(cur_ctx)))
    return results


def read_excel(path):
    try:
        import openpyxl
    except ImportError:
        print("openpyxl not installed -> Excel merge skipped", file=sys.stderr)
        return []
    import warnings
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    pc = re.compile(r"(Name|Details)\b.*\b(PI|Inventor|Winner|Lead|Personnel)\b|\bPI\b.*Name|Name of (the )?Faculty", re.I)
    out = []
    for sn in ("Index-B", "Index-C", "Index-D"):
        if sn not in wb.sheetnames:
            continue
        cols = []
        for row in wb[sn].iter_rows(values_only=True):
            row = list(row)
            if any(str(c).strip().upper() == "SN" for c in row if c is not None):
                cols = [i for i, c in enumerate(row) if c and pc.search(str(c))]
                continue
            for i in cols:
                if i >= len(row) or not row[i] or str(row[i]).strip() in ("-", "N/A", "None"):
                    continue
                cell = str(row[i])
                neighbours = " ".join(str(x) for x in row[i + 1:i + 3] if x)
                for raw_name, ctx in split_excel_people(cell):
                    hint = dept_hint(ctx)
                    if not hint and not dept_hint(cell) and not EXTERNAL.search(cell):
                        # shifted rows: designation / department sit in the next columns
                        if re.search(r"professor|lecturer|department|engineering|dept", neighbours, re.I):
                            ctx = ctx + " " + neighbours
                            hint = dept_hint(neighbours)
                    out.append({"sheet": sn, "raw": raw_name.strip(), "ctx": ctx, "hint": hint})
    return out


def excel_designation(ctx):
    for label, rx in EX_DES:
        if re.search(rx, ctx, re.I):
            return label
    return ""


def merge_excel(people, entries):
    stats = {"entries": len(entries), "matched": 0, "added": 0, "skipped": 0}
    added = {}
    skipped = []
    for e in entries:
        raw = re.sub(r"\s+", " ", e["raw"]).strip(" ,.")
        nk = norm(raw)
        toks = nk.split()
        if len(toks) < 2:
            stats["skipped"] += 1
            continue
        ctx = e["ctx"]
        if EXTERNAL.search(ctx) and not re.search(r"\bned\b", ctx, re.I):
            stats["skipped"] += 1
            skipped.append(raw)
            continue
        hint = e["hint"]
        match = None
        pool = [p for p in people if p.dept == hint] if hint else []
        # 1. exact normalized within dept, then globally (unique)
        match = next((p for p in pool if p.nkey == nk), None)
        if not match:
            g = [p for p in people if p.nkey == nk]
            if len(g) == 1:
                match = g[0]
        # 2. subset within dept / globally unique
        if not match:
            s = [p for p in (pool or []) if set(toks) <= set(p.nkey.split())]
            if len(s) == 1:
                match = s[0]
        if not match and pool:
            # website name is a subset of the Excel name ("Danyal Rashid" ~ "Danyal Rashid Khan")
            s = [p for p in pool if (len(p.nkey.split()) >= 2 and set(p.nkey.split()) <= set(toks))
                 or (len(p.nkey.split()) == 1 and p.nkey == toks[0])]
            if len(s) == 1:
                match = s[0]
        if not match and len(toks) >= 3:
            s = [p for p in people if set(toks) <= set(p.nkey.split())]
            if len(s) == 1:
                match = s[0]
        # 3. fuzzy token-set within dept
        if not match and pool:
            best, br = None, 0
            st = " ".join(sorted(toks))
            for p in pool:
                r = max(difflib.SequenceMatcher(None, st, " ".join(sorted(p.nkey.split()))).ratio(),
                        difflib.SequenceMatcher(None, nk.replace(" ", ""), p.nkey.replace(" ", "")).ratio())
                if r > br:
                    best, br = p, r
            if br >= 0.88:
                match = best
        if not match and pool:
            joined = nk.replace(" ", "")
            em = [p for p in pool if p.email and p.email.split("@")[0].replace(".", "").replace("_", "") == joined]
            if len(em) == 1:
                match = em[0]
        if match:
            if not match.excel:
                stats["matched"] += 1
            match.excel = True
            if match.source == "website":
                match.source = "website+excel"
            if raw != match.full_name:
                match.add_alias(raw)
            continue
        if not hint:
            stats["skipped"] += 1
            skipped.append(raw)
            continue
        des = excel_designation(ctx)
        if re.search(r"lab\s*eng|registrar|manager|officer|student|scholar|research assistant|\bra\b", ctx, re.I):
            stats["skipped"] += 1
            continue
        if not des and not re.match(r"(?i)^(prof|dr)", raw):
            stats["skipped"] += 1
            skipped.append(raw)
            continue
        k = (nk, hint)
        if k in added:
            added[k].add_alias(raw)
            if not added[k].designation and des:
                added[k].designation = des
            continue
        # fuzzy against already-added excel people in same dept
        sim = next((q for (qk, qd), q in added.items() if qd == hint and (
                    set(qk.split()) <= set(toks) or set(toks) <= set(qk.split()) or
                    difflib.SequenceMatcher(None, " ".join(sorted(qk.split())), " ".join(sorted(toks))).ratio() >= 0.88)), None)
        if sim:
            sim.add_alias(raw)
            continue
        full = tidy_excel_name(raw)
        p = Person(full, des, hint, None, "", "excel")
        p.excel = True
        if raw != full:
            p.add_alias(raw)
        added[k] = p
        people.append(p)
        stats["added"] += 1
    return stats


def tidy_excel_name(raw):
    s = re.sub(r"\b(Dr|Prof|Engr|Mr|Ms|Mrs|Ar)\.?\s*(?=[A-Z])", lambda m: m.group(1) + ". ", raw)
    s = re.sub(r"\s+", " ", s).strip(" ,.")
    return " ".join(w.title() if (w.isupper() and len(w) > 3) else w for w in s.split())


# ---------------------------- Emails & output ------------------------------
def slug_ascii(s):
    s = fold(s).lower()
    return re.sub(r"[^a-z]", "", s)


def assign_emails(people):
    used = {}
    for p in people:
        if p.email:
            e = p.email.lower()
            if e in used and used[e] is not p:
                print(f"  ! duplicate email {e}: {used[e].full_name} / {p.full_name} -> placeholder for latter", file=sys.stderr)
                p.email = None
                p.email_source = "placeholder"
            else:
                used[e] = p
                p.email = e
                p.email_source = "scraped"
    for p in people:
        if p.email:
            continue
        toks = [t for t in re.split(r"[\s\-]+", bare_name(p.full_name)) if slug_ascii(t)]
        toks = [slug_ascii(t) for t in toks]
        drop = {"syed", "syeda", "muhammad", "m"} if len(toks) > 2 else set()
        core = [t for t in toks if t not in drop] or toks
        first, last = core[0], core[-1]
        base = f"{first}.{last}" if first != last else first
        e = f"{base}@{PLACEHOLDER_DOMAIN}"
        i = 2
        while e in used:
            e = f"{base}{i}@{PLACEHOLDER_DOMAIN}"
            i += 1
        p.email = e
        p.email_source = "placeholder"
        used[e] = p


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--excel", default=DEFAULT_EXCEL)
    ap.add_argument("--raw-json", default=DEFAULT_RAW)
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    people, report = scrape(args)
    people = resolve_cross_dept(people)
    leaders, created = ensure_leaders(people)
    for p in people:
        fd = FINAL_DESIG.get(key(p.full_name))
        if fd:
            p.designation = fd

    xl_stats = {"entries": 0, "matched": 0, "added": 0, "skipped": 0}
    if args.excel and os.path.exists(args.excel):
        xl_stats = merge_excel(people, read_excel(args.excel))
    else:
        print(f"Excel not found: {args.excel} -> merge skipped", file=sys.stderr)

    # ORIC staff aliases (e.g. "Tehreem Beg" == TXD "Tahreem Baig")
    staff_rows = []
    for email, full, title, role, nm in ORIC_STAFF:
        p = next((q for q in people if q.email == email), None) or find_person(people, full)
        if p is not None and full != p.full_name:
            p.add_alias(full)
        staff_rows.append((email, full, title, role, p))

    assign_emails(people)

    # sort: department order, then seniority, then name
    order = {d[0]: i for i, d in enumerate(DEPARTMENTS)}

    def senior(p):
        d = p.designation.lower()
        if "vice" in d:
            return 0
        if "dean" in d:
            return 1
        if "chair" in d and "co" not in d.split("chair")[0][-4:]:
            return 2
        if "chair" in d:
            return 3
        if "emerit" in d:
            return 4
        if "associate prof" in d:
            return 6
        if "assistant prof" in d:
            return 7
        if "prof" in d:
            return 5
        if "lecturer" in d:
            return 8
        return 9
    people.sort(key=lambda p: (order.get(p.dept, 99), senior(p), bare_name(p.full_name).lower()))

    os.makedirs(args.out, exist_ok=True)
    emails = {p.email for p in people}

    fac_rows = []
    for code, name, short, dean, home in FACULTIES:
        de = leaders["dean"][code].email if dean else ""
        fac_rows.append((code, name, short, de))
    write_csv(os.path.join(args.out, "faculties.csv"), ["code", "name", "short_name", "dean_email"], fac_rows)

    dep_rows = []
    for code, dname, fac, sub, path, cfg in DEPARTMENTS:
        ch = leaders["chair"].get(code)
        cos = leaders["co"].get(code, [])
        site = f"https://{sub}.neduet.edu.pk" if sub else ""
        dep_rows.append((code, f"Department of {dname}", fac, ch.email if ch else "", ";".join(c.email for c in cos), site))
    write_csv(os.path.join(args.out, "departments.csv"),
              ["code", "name", "faculty_code", "chair_email", "co_chair_emails", "website"], dep_rows)

    ppl_rows = []
    for p in people:
        ppl_rows.append((p.email, p.full_name, p.designation, p.dept, is_phd(p.full_name), "", p.phone,
                         ";".join(p.aliases), p.email_source, p.source))
    write_csv(os.path.join(args.out, "people.csv"),
              ["email", "full_name", "designation", "department_code", "is_phd", "employee_id", "phone", "aliases",
               "email_source", "source"], ppl_rows)

    st_rows = []
    for i, (email, full, title, role, p) in enumerate(staff_rows, 1):
        if role == "oric_director" and p is not None and p.email_source == "scraped":
            email = p.email  # keep the person single: use his EED faculty address
        elif p is not None:
            email = p.email
        st_rows.append((email, full, title, role, p.dept if p else "", p.phone if p else "", i))
    write_csv(os.path.join(args.out, "oric_staff.csv"),
              ["email", "full_name", "title", "role", "department_code", "phone_ext", "order"], st_rows)

    # ---------------- verification ----------------
    errors = []
    dept_codes = {d[0] for d in DEPARTMENTS}
    fac_codes = {f[0] for f in FACULTIES}
    if len(emails) != len(people):
        errors.append("duplicate emails in people.csv")
    for r in fac_rows:
        if r[3] and r[3] not in emails:
            errors.append(f"faculty {r[0]} dean_email {r[3]} missing")
    for r in dep_rows:
        if r[2] not in fac_codes:
            errors.append(f"dept {r[0]} bad faculty")
        for e in [r[3]] + [x for x in r[4].split(";") if x]:
            if e and e not in emails:
                errors.append(f"dept {r[0]} leader email {e} missing")
    for p in people:
        if p.dept not in dept_codes:
            errors.append(f"person {p.full_name} bad dept {p.dept}")
    for r in st_rows:
        if r[4] and r[4] not in dept_codes:
            errors.append(f"staff {r[1]} bad dept")
        if r[4] and r[0] not in emails:
            errors.append(f"staff {r[1]} email {r[0]} not in people")
    seen = {}
    for p in people:
        k = (p.nkey, p.dept)
        if k in seen:
            errors.append(f"duplicate person {p.full_name} in {p.dept}")
        seen[k] = p

    # ---------------- summary ----------------
    print("\n=== Directory summary ===")
    print(f"faculties: {len(fac_rows)}  departments: {len(dep_rows)}  people: {len(people)}  oric_staff: {len(st_rows)}")
    print(f"{'dept':6} {'total':>5} {'scraped':>7} {'placeh':>6} {'excel+':>6}  source")
    for code, *_ in DEPARTMENTS:
        ps = [p for p in people if p.dept == code]
        print(f"{code:6} {len(ps):5} {sum(p.email_source == 'scraped' for p in ps):7} "
              f"{sum(p.email_source == 'placeholder' for p in ps):6} {sum(p.source == 'excel' for p in ps):6}  {report.get(code, '')}")
    print(f"placeholder emails: {sum(p.email_source == 'placeholder' for p in people)}")
    print(f"excel: {xl_stats['entries']} name mentions, {xl_stats['matched']} people matched, "
          f"{xl_stats['added']} added, {xl_stats['skipped']} skipped (external / no NED dept hint)")
    if created:
        print("leaders not found on websites (created): " + "; ".join(f"{d}:{n}" for d, n in created))
    if errors:
        print("FK / integrity ERRORS:")
        for e in errors:
            print("  - " + e)
        sys.exit(1)
    print("FK check: all references resolve.")


if __name__ == "__main__":
    main()
