#!/usr/bin/env python
"""Scrape faculty profile photos from the NED department sites.

Reads org/seed/people.csv, walks every department faculty page listed in
build_directory.DEPARTMENTS, pairs each portrait <img> with the nearest
person name on the page (same department), downloads it to
media/people/avatars/seed/<email-local>.jpg and writes the file name into the
``photo`` column of people.csv. The images are not committed (media/ is git-ignored);
copy that folder to the server's media root on deploy. ``import_directory`` links it as the
person's avatar.

    python -I tools/scrape_photos.py [--cache-dir DIR] [--offline] [--force] [--photo-dir DIR]

--force  re-download photos that already exist on disk
"""
import argparse
import csv
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_directory import DEFAULT_OUT, DEPARTMENTS, Fetcher, clean_line, key, tidy_name  # noqa: E402

SKIP_SRC = re.compile(r"icon|logo|banner|slider|\.svg|\.gif|base_path|facebook|twitter|linkedin|youtube|"
                      r"instagram|whatsapp|header|footer|bg[_-]|background|arrow|button|flag|map", re.I)


class Tokens(HTMLParser):
    """Flatten a page into ("img", src) / ("text", line) tokens in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag == "img":
            a = dict(attrs)
            src = a.get("data-src") or a.get("src") or ""
            if src and not SKIP_SRC.search(src):
                self.out.append(("img", src))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self.skip:
            return
        line = clean_line(data)
        if line and len(line) > 3:
            self.out.append(("text", line))


def name_index(rows):
    """dept code -> {name key: email} using full name + aliases."""
    idx = {}
    for r in rows:
        d = idx.setdefault(r["department_code"], {})
        for n in [r["full_name"], *filter(None, (r.get("aliases") or "").split(";"))]:
            k = key(tidy_name(n))
            if k:
                d.setdefault(k, r["email"])
    return idx


def match_line(line, names):
    k = key(tidy_name(line))
    if k in names:
        return names[k]
    # lines like "Dr. X, Associate Professor" / "X (Chairman)"
    head = re.split(r"[,(|–-]\s", line)[0]
    k = key(tidy_name(head))
    return names.get(k)


COMMON = {"muhammad", "mohammad", "syed", "syeda", "ahmed", "ahmad", "khan", "ali", "hussain", "abdul", "uddin",
          "ullah", "shah", "sheikh", "shaikh", "prof", "dr", "engr", "mr", "ms", "mrs", "new", "pic", "img", "image",
          "photo", "picture", "cropped", "final", "jpg", "jpeg", "png", "copy", "faculty", "sites", "default", "files"}
PLACEHOLDER = re.compile(r"user_0|female_dp|male_dp|hijab|avatar|default[_-]?(user|pic|img)|dummy|no[-_ ]?image|placeholder|"
                         r"/itm\.jpg|/web_\d|notavailable|clipart|/(fe)?male\.(jpe?g|png)|^null$", re.I)
NEAR = 3  # max text tokens between a photo and the name it belongs to (by proximity)


def words(s):
    return {w for w in re.split(r"[^a-z]+", s.lower()) if len(w) >= 3}


def by_filename(src, people):
    """Person whose (rarer) name words appear in the image file name; None if ambiguous."""
    fname = words(os.path.basename(src.split("?")[0]).replace("%20", " "))
    scored = []
    for email, ws in people.items():
        hit = (ws & fname) - COMMON
        if hit:
            scored.append((len(hit), email))
    scored.sort(reverse=True)
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def _scan(tokens, i, direction, names, limit):
    """Nearest name from token i in one direction, stopping at the neighbouring photo."""
    rng = range(i + 1, len(tokens)) if direction > 0 else range(i - 1, -1, -1)
    seen = 0
    for j in rng:
        kind, v = tokens[j]
        if kind == "img" or seen >= limit:
            break
        seen += 1
        email = match_line(v, names)
        if email:
            return email, seen
    return None, None


def pair_photos(tokens, names):
    """Return {email: (confidence, src)}; lower confidence value = stronger match.

    File names that spell the person's name are trusted outright. They also tell us the
    page layout (name after the photo, or photo after the details block), which is then
    used for the remaining photos on that page.
    """
    people = {}
    for k, email in names.items():
        people.setdefault(email, set()).update(words(k))
    srcs = [v for k, v in tokens if k == "img"]
    shared = {s for s in srcs if srcs.count(s) > 1}
    imgs = [(i, src) for i, (kind, src) in enumerate(tokens)
            if kind == "img" and src not in shared and not PLACEHOLDER.search(src)]

    best, votes = {}, {1: 0, -1: 0}
    for i, src in imgs:
        email = by_filename(src, people)
        if email:
            best[email] = (0, src)
            for direction in (1, -1):
                if _scan(tokens, i, direction, names, 12)[0] == email:
                    votes[direction] += 1
                    break
    layout = 1 if votes[1] >= votes[-1] else -1
    sure = abs(votes[1] - votes[-1]) >= 2
    for i, src in imgs:
        if any(v[1] == src for v in best.values()):
            continue
        email, dist = _scan(tokens, i, layout, names, 12 if sure else NEAR)
        conf = dist
        if not email and not sure:
            email, dist = _scan(tokens, i, -layout, names, NEAR)
            conf = dist and dist * 1.5
        if email and (email not in best or conf < best[email][0]):
            best[email] = (conf, src)
    # one photo per person and one person per photo
    owners = {}
    for email, (conf, src) in sorted(best.items(), key=lambda x: x[1][0]):
        owners.setdefault(src, email)
    return {e: v for e, v in best.items() if owners[v[1]] == e}


def looks_like_placeholder(im):
    """Silhouettes / 'image not available' tiles: very few distinct tones."""
    small = im.convert("RGB").resize((48, 48))
    data = small.tobytes()
    return len({data[i:i + 3] for i in range(0, len(data), 3)}) < 180


MAX_SIDE = 400


def normalise(photo_dir, fname):
    """Shrink to a 400px JPEG (Pillow, when installed) so the seed stays small. Returns the file name."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return fname
    path = os.path.join(photo_dir, fname)
    out = os.path.splitext(fname)[0] + ".jpg"
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        im = im.convert("RGB")
        if looks_like_placeholder(im):
            im.close()
            os.remove(path)
            return None
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        im.save(os.path.join(photo_dir, out), "JPEG", quality=84, optimize=True, progressive=True)
    if out != fname:
        os.remove(path)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--photo-dir", default=os.path.join(os.path.dirname(DEFAULT_OUT), "..", "media", "people",
                                                        "avatars", "seed"))
    args = ap.parse_args()

    people_csv = os.path.join(args.out, "people.csv")
    photo_dir = os.path.normpath(args.photo_dir)
    os.makedirs(photo_dir, exist_ok=True)
    with open(people_csv, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames)
        rows = list(reader)
    if "photo" not in header:
        header.append("photo")
    idx = name_index(rows)
    fetcher = Fetcher(args.cache_dir, args.offline)

    found = {}
    for code, _name, _fac, sub, path, _cfg in DEPARTMENTS:
        if not sub or not path or code not in idx:
            continue
        url = f"https://{sub}.neduet.edu.pk{path}"
        page = fetcher.get(url)
        if not page:
            print(f"[{code}] no page", file=sys.stderr)
            continue
        t = Tokens()
        t.feed(page)
        pairs = pair_photos(t.out, idx[code])
        for email, (_d, src) in pairs.items():
            found.setdefault(email, src if src.startswith("data:") else urljoin(url, src.strip()))
        print(f"[{code}] {len(pairs)} photos / {len(idx[code])} people", file=sys.stderr)

    session = fetcher.session
    got = 0
    for r in rows:
        src = found.get(r["email"])
        r["photo"] = ""
        if not src:
            continue
        inline = src.startswith("data:image/")
        ext = ("." + src[11:src.index(";")]) if inline and ";" in src else os.path.splitext(src.split("?")[0])[1].lower()
        ext = ".jpg" if ext == ".jpeg" else ext if ext in (".jpg", ".png", ".webp") else ".jpg"
        fname = re.sub(r"[^a-z0-9._-]+", "-", r["email"].split("@")[0].lower()) + ext
        dest = os.path.join(photo_dir, fname)
        done = os.path.splitext(fname)[0] + ".jpg"
        if not args.force and os.path.exists(os.path.join(photo_dir, done)):
            r["photo"] = done
            got += 1
            continue
        if args.force or not os.path.exists(dest):
            if inline:
                import base64
                with open(dest, "wb") as fh:
                    fh.write(base64.b64decode(src.split(",", 1)[1]))
                r["photo"] = normalise(photo_dir, fname) or ""
                got += bool(r["photo"])
                continue
            if args.offline or session is None:
                continue
            try:
                resp = session.get(src, timeout=40, verify=False)  # NED sites: incomplete TLS chain
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {src}: {exc.__class__.__name__}", file=sys.stderr)
                continue
            ctype = resp.headers.get("content-type", "")
            if resp.status_code != 200 or not ctype.startswith("image/") or len(resp.content) < 2500:
                print(f"  ! {src}: {resp.status_code} {ctype} {len(resp.content)}B", file=sys.stderr)
                continue
            with open(dest, "wb") as fh:
                fh.write(resp.content)
        r["photo"] = normalise(photo_dir, fname) or ""
        got += bool(r["photo"])

    # the same picture on several people is a stock placeholder, not a portrait
    import hashlib
    digests = {}
    for r in rows:
        if r.get("photo"):
            with open(os.path.join(photo_dir, r["photo"]), "rb") as fh:
                digests.setdefault(hashlib.md5(fh.read()).hexdigest(), []).append(r)
    for same in digests.values():
        if len(same) > 1:
            for r in same:
                os.remove(os.path.join(photo_dir, r["photo"]))
                r["photo"] = ""
                got -= 1

    for r in rows:
        r.setdefault("photo", "")
    with open(people_csv, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    print(f"photos: {got} of {len(rows)} people", file=sys.stderr)


if __name__ == "__main__":
    main()
