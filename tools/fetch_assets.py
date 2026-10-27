"""تحميل الموارد التي كانت تُجلب من الإنترنت وتضمينها في البرنامج (تعمل أثناء البناء على GitHub فقط).

  1) مكتبة Excel (xlsx.full.min.js)  -> renderer/vendor/      (إلزامية)
  2) خطوط Google العربية والاتينية     -> fonts/ + fonts/fonts.css  (اختيارية: عند الفشل يُكمل البناء بخطوط النظام)

بعد التثبيت يعمل البرنامج بالكامل دون إنترنت.
"""
import re, sys, time, hashlib, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
XLSX_URL = "https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"
FAMILIES = ["Cairo", "Tajawal", "Almarai", "Amiri", "Noto Naskh Arabic", "Noto Kufi Arabic", "Changa",
            "Reem Kufi", "El Messiri", "Harmattan", "Lateef", "Markazi Text", "Scheherazade New",
            "IBM Plex Sans Arabic", "Mada", "Aref Ruqaa"]
REQUIRED = {"Amiri", "Noto Naskh Arabic", "Cairo", "Tajawal", "Almarai"}   # يفشل البناء إن تعذّر أيٌّ منها: ثبات الطباعة بين الأجهزة
KEEP_SUBSETS = {"arabic", "latin"}          # العربية + الأرقام/اللاتينية فقط لتقليل الحجم


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:                                     # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def parse_google_css(css):
    """يعيد قائمة (subset, block) لكل @font-face؛ الاسم الفرعي مأخوذ من تعليق /* arabic */ السابق."""
    out = []
    for m in re.finditer(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{[^}]*\})", css):
        out.append((m.group(1), m.group(2)))
    return out


def localize(block, fonts_dir, downloader):
    """ينزّل ملف الخط ويستبدل الرابط برابط نسبي محلي."""
    def sub(m):
        url = m.group(1)
        ext = ".woff2" if ".woff2" in url or "woff2" in block else ".ttf"
        name = hashlib.sha1(url.encode()).hexdigest()[:16] + ext
        dest = fonts_dir / name
        if not dest.exists():
            dest.write_bytes(downloader(url))
        return f"url({name})"
    return re.sub(r"url\((https://[^)]+)\)", sub, block)


def fetch_xlsx():
    dest = ROOT / "renderer" / "vendor" / "xlsx.full.min.js"
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = get(XLSX_URL)
    if len(data) < 400_000 or b"XLSX" not in data:
        raise SystemExit("xlsx download looks invalid")
    dest.write_bytes(data)
    print(f"xlsx OK ({len(data)//1024} KB)")


def fetch_fonts():
    fonts_dir = ROOT / "fonts"
    fonts_dir.mkdir(exist_ok=True)
    css_parts, ok, bad = [], 0, []
    for fam in FAMILIES:
        blocks, err = [], None
        for axis in (":wght@400;700", ":wght@400", ""):            # بعض الخطوط لا تدعم الوزن 700
            url = "https://fonts.googleapis.com/css2?family=" + fam.replace(" ", "+") + axis + "&display=swap"
            try:
                css = get(url, tries=2).decode("utf-8")
                blocks = [b for sub, b in parse_google_css(css) if sub in KEEP_SUBSETS]
                if blocks:
                    break
            except Exception as e:                                  # noqa: BLE001
                err = e
        try:
            if not blocks:
                raise RuntimeError(err or "no arabic/latin blocks")
            css_parts += [localize(b, fonts_dir, get) for b in blocks]
            ok += 1
        except Exception as e:                                      # noqa: BLE001
            bad.append(f"{fam}: {e}")
    (fonts_dir / "fonts.css").write_text("\n".join(css_parts) + "\n", encoding="utf-8")
    size = sum(f.stat().st_size for f in fonts_dir.iterdir()) // 1024
    print(f"fonts: {ok}/{len(FAMILIES)} families, {size} KB")
    for b in bad:
        print("::warning::font skipped - " + b)
    missing = [f for f in REQUIRED if any(x.startswith(f + ":") for x in bad)]
    css_all = (fonts_dir / "fonts.css").read_text(encoding="utf-8")
    if missing or "Amiri" not in css_all:
        raise SystemExit("required fonts missing: " + ", ".join(missing or ["Amiri"]) + " - build aborted so printing stays identical on all devices")


if __name__ == "__main__":
    fetch_xlsx()                       # إلزامي: يفشل البناء إن تعذّر
    fetch_fonts()                      # إلزامي: بدون الخطوط المضمّنة تختلف الطباعة من جهاز إلى آخر
