#!/usr/bin/env python3
"""
build.py — Bundles src/ into a single self-contained dist/index.html
"""

import re
import sys
import base64
import hashlib
import textwrap
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Config

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent

SRC_DIR  = PROJECT_ROOT / "src"
DIST_DIR = PROJECT_ROOT / "dist"
OUT_FILE = DIST_DIR / "index.html"
CACHE_DIR = PROJECT_ROOT / ".build_cache"

# If your files exist with these names they'll be used in this order.
# Anything in src/css/ or src/js/ NOT in these lists gets appended automatically,
# so you never silently lose a file just because it's not listed here.
CSS_PREFERRED_ORDER = ["css/main.css", "css/addons.css", "css/mobile.css"]
JS_PREFERRED_ORDER  = [
    "js/utils.js", "js/state.js", "js/terminal.js", "js/ui.js",
    "js/ui-controls.js", "js/markdown-renderer.js", "js/geometry.js",
    "js/pdf-parser.js",
    "js/ocr.js", "js/file-tree.js", "js/dropzone.js", "js/reset-utils.js",
    "js/downloads.js", "js/mobile-ux.js", "js/addons.js", "js/demo.js",
    "js/main.js",  # must stay last
]

# Logging

OK   = "\033[92m✔\033[0m"
WARN = "\033[93m⚠\033[0m"
ERR  = "\033[91m✖\033[0m"
INFO = "\033[94m•\033[0m"

def log(sym, msg): print(f"  {sym}  {msg}")

# File helpers

def read(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    log(OK, f"{path}  ({len(text):,} chars)")
    return text

def fetch_url(url: str) -> str:
    CACHE_DIR.mkdir(exist_ok=True)
    key = CACHE_DIR / f"{hashlib.md5(url.encode()).hexdigest()}.txt"
    if key.exists():
        log(INFO, f"cache hit: {url}")
        return key.read_text(encoding="utf-8", errors="ignore")
    log(INFO, f"downloading: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as r:
            data = r.read().decode("utf-8", errors="ignore")
        key.write_text(data, encoding="utf-8")
        return data
    except Exception as e:
        log(ERR, f"download failed {url}: {e}")
        return ""

# File discovery

def resolve_file_order(src: Path, preferred: list[str], glob: str, exclude: list[str] = None) -> list[str]:
    """
    Returns the final ordered list of files to bundle.
    - Preferred list entries that exist come first, in order.
    - Any files found on disk that aren't in the preferred list are appended,
      sorted alphabetically — so nothing gets silently dropped.
    - 'main.js' is always kept last if present.
    """
    if exclude is None: exclude = []
    
    existing_preferred = [p for p in preferred if (src / p).exists() and p not in exclude]
    preferred_set = set(existing_preferred)

    # Find everything on disk
    all_on_disk = sorted(
        str(f.relative_to(src)).replace("\\", "/")
        for f in (src / glob.split("/")[0]).glob(f"*.{glob.split('.')[-1]}")
    )

    # Filter out excluded files
    all_on_disk = [f for f in all_on_disk if f not in exclude]

    # Force main.js last
    main = "js/main.js"
    extras = [f for f in all_on_disk if f not in preferred_set and f != main]
    result = existing_preferred + extras
    if main in all_on_disk and main not in result:
        result.append(main)

    missing = [p for p in preferred if p not in existing_preferred]
    if missing:
        log(WARN, f"not found (skipped): {', '.join(missing)}")
    extras_found = [f for f in all_on_disk if f not in preferred_set and f != main]
    if extras_found:
        log(INFO, f"auto-discovered (not in list): {', '.join(extras_found)}")

    return result

# Bundlers

def safe_js(content: str) -> str:
    # </script> anywhere inside a <script> block ends it — browser doesn't care about context
    return content.replace("</script>", "<\\/script>")

def bundle_css(src: Path, files: list[str]) -> str:
    parts = []
    for rel in files:
        content = read(src / rel)
        if content:
            parts.append(f"/* {rel} */\n{content}")
    return "\n\n".join(parts)

def bundle_js(src: Path, files: list[str]) -> str:
    parts = []
    for rel in files:
        content = read(src / rel)
        if content:
            # Must escape </script> in ALL JS — local or remote — otherwise the
            # browser's HTML parser ends the <script> block mid-source when it
            # hits that exact byte sequence, dropping everything that follows.
            content = content.replace("</script>", "<\\/script>")
            banner = (
                f"/* {'═'*60}\n"
                f"   {rel}\n"
                f"   {'═'*60} */\n"
            )
            wrapped = f"{banner}// ----- {rel} -----\n;\n{content}\n;\n"
            parts.append(wrapped)
    return "\n".join(parts)

# HTML inlining

def inline_into_html(html: str, css_blob: str, js_blob: str) -> str:
    # Strip local <link> tags
    local_link = re.compile(
        r'<link\b[^>]*rel=["\']stylesheet["\'][^>]*href=["\'](?!https?://)([^"\']+)["\'][^>]*/?>',
        re.IGNORECASE)
    n_links = [0]
    def drop_link(m): n_links[0] += 1; return ""
    html = local_link.sub(drop_link, html)

    # Fetch + inline remote <link> tags
    remote_link = re.compile(
        r'<link\b[^>]*rel=["\']stylesheet["\'][^>]*href=["\'](https?://[^"\']+)["\'][^>]*/?>',
        re.IGNORECASE)
    remote_css = []
    def fetch_link(m):
        c = fetch_url(m.group(1))
        if c: remote_css.append(f"/* {m.group(1)} */\n{c}")
        return ""
    html = remote_link.sub(fetch_link, html)

    full_css = "\n\n".join(remote_css) + ("\n\n" if remote_css else "") + css_blob
    style_tag = f"\n<style>\n{full_css}\n</style>\n"
    html = html.replace("</head>", style_tag + "</head>", 1) if "</head>" in html else style_tag + html
    log(INFO, f"inlined {n_links[0]} local link(s) + {len(remote_css)} remote stylesheet(s)")

    # Strip local <script src> tags
    local_script = re.compile(
        r'<script\b[^>]*src=["\'](?!https?://)([^"\']+)["\'][^>]*>\s*</script>',
        re.IGNORECASE)
    n_scripts = [0]
    def drop_script(m): n_scripts[0] += 1; return ""
    html = local_script.sub(drop_script, html)

    # Fetch + inline remote <script src> tags
    remote_script = re.compile(
        r'<script\b[^>]*src=["\'](https?://[^"\']+)["\'][^>]*>\s*</script>',
        re.IGNORECASE)
    remote_js = []
    def fetch_remote_script(m):
        url = m.group(1)
        content = fetch_url(url)
        content = content.replace("</script>", "<\\/script>")
        remote_js.append(f"// {url}\n;\n{content}\n;\n")
        return ""
    html = remote_script.sub(fetch_remote_script, html)

    full_js = "\n\n".join(remote_js) + ("\n\n" if remote_js else "") + js_blob
    script_tag = f"\n<script>\n{full_js}\n</script>\n"
    html = html.replace("</body>", script_tag + "</body>", 1) if "</body>" in html else html + "\n" + script_tag
    log(INFO, f"inlined {n_scripts[0]} local script(s) + {len(remote_js)} remote script(s)")

    return html

# Main

def build():
    print("\n╔══════════════════════════════════════╗")
    print(  "║        build.py  —  bundler          ║")
    print(  "╚══════════════════════════════════════╝\n")

    if not SRC_DIR.exists():
        log(ERR, "src/ not found — run from project root"); sys.exit(1)

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # Discover files
    print("── Discovering files ────────────────────")
    css_files = resolve_file_order(SRC_DIR, CSS_PREFERRED_ORDER, "css/*.css")
    js_files  = resolve_file_order(SRC_DIR, JS_PREFERRED_ORDER,  "js/*.js", exclude=["js/benchmark.js"])
    print(f"  CSS files ({len(css_files)}): {', '.join(css_files) or 'none'}")
    print(f"  JS files  ({len(js_files)}):  {', '.join(js_files) or 'none'}")
    print()

    if not css_files and not js_files:
        log(ERR, "No CSS or JS files found in src/css/ or src/js/ — nothing to bundle")
        sys.exit(1)

    # Bundle CSS
    print("── CSS ──────────────────────────────────")
    css_blob = bundle_css(SRC_DIR, css_files)
    print()

    # Bundle JS
    print("── JavaScript ───────────────────────────")
    js_blob = bundle_js(SRC_DIR, js_files)
    print()

    # Heavy CDN assets
    print("── CDN assets ───────────────────────────")

    # PDF.js worker — patch any pdf.worker URL found in the JS source
    pdf_worker_url = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js"
    pdf_worker_code = fetch_url(pdf_worker_url)
    if pdf_worker_code:
        b64 = base64.b64encode(pdf_worker_code.encode()).decode()
        data_uri = f"data:application/javascript;base64,{b64}"
        js_blob, n = re.subn(r'https?://[^\s\'"]+pdf\.worker[^\s\'"]*\.js', data_uri, js_blob)
        log(OK if n else WARN, f"pdf.worker: {'patched ' + str(n) + ' URL(s)' if n else 'URL not found in JS (worker fetches at runtime)'}")

    # Tesseract — just prepend the library, let it fetch worker/core from CDN
    # to avoid "NetworkError: Failed to execute 'importScripts' on 'WorkerGlobalScope'"
    # which happens when a data URI worker tries to load relative WASM scripts.
    tess_lib = safe_js(fetch_url("https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"))
    if tess_lib:
        js_blob = tess_lib + "\n\n" + js_blob
        log(OK, "Tesseract library inlined (worker/core will fetch from CDN)")
    else:
        log(WARN, "Tesseract download failed — OCR will need network access for the library too")

    print()

    # HTML
    print("── HTML ─────────────────────────────────")
    html = read(SRC_DIR / "index.html")
    if not html:
        log(ERR, "src/index.html missing"); sys.exit(1)
    print()

    # Inlining
    print("── Inlining ─────────────────────────────")
    output = inline_into_html(html, css_blob, js_blob)
    print()

    # Write
    OUT_FILE.write_text(output, encoding="utf-8")
    kb = OUT_FILE.stat().st_size / 1024
    print("── Done ─────────────────────────────────")
    log(OK, f"output: {OUT_FILE.name}")
    log(OK, f"size:   {kb:,.1f} KB")
    
    # PWA Support
    manifest_src = SRC_DIR / "manifest.json"
    sw_src = SRC_DIR / "sw.js"
    if manifest_src.exists():
        (DIST_DIR / "manifest.json").write_text(manifest_src.read_text(encoding="utf-8"), encoding="utf-8")
        log(OK, "copied: manifest.json")
    if sw_src.exists():
        (DIST_DIR / "sw.js").write_text(sw_src.read_text(encoding="utf-8"), encoding="utf-8")
        log(OK, "copied: sw.js")

    # Bundle benchmark.html
    BENCH_SRC = SRC_DIR / "benchmark.html"
    if BENCH_SRC.exists():
        print(f"\n── Bundling {BENCH_SRC.name} ──")
        bench_html = BENCH_SRC.read_text(encoding="utf-8")
        
        # Custom minimal JS bundle for benchmark
        bench_js_files = ["js/state.js", "js/utils.js", "js/pdf-parser.js", "js/benchmark.js"]
        bench_js_files = [f for f in bench_js_files if (SRC_DIR / f).exists()]
        bench_js_blob = bundle_js(SRC_DIR, bench_js_files)
        
        # Patch worker in benchmark JS blob
        if pdf_worker_code:
            b64 = base64.b64encode(pdf_worker_code.encode()).decode()
            data_uri = f"data:application/javascript;base64,{b64}"
            bench_js_blob, _ = re.subn(r'https?://[^\s\'"]+pdf\.worker[^\s\'"]*\.js', data_uri, bench_js_blob)

        bench_output = inline_into_html(bench_html, css_blob, bench_js_blob)
        BENCH_OUT = DIST_DIR / "benchmark.html"
        BENCH_OUT.write_text(bench_output, encoding="utf-8")
        bench_kb = BENCH_OUT.stat().st_size / 1024
        log(OK, f"output: {BENCH_OUT.name}")
        log(OK, f"size:   {bench_kb:,.1f} KB")
    
    print("\n  Open dist/index.html in your browser — no server needed.\n")


if __name__ == "__main__":
    build()