"""Local web UI for the review queue — Phase 2C.5b.

Spins up a tiny stdlib `http.server` on localhost that displays one
`ReviewGroup` per page : source coin image on the left, candidate canonical
coins with their BCE images on the right, live enrichment preview under each
candidate, and keyboard-friendly action buttons. Decisions hit the same
persistence functions as the CLI (now removed) via `review_core`, so the
referential, review queue and manual resolutions stay in sync.

Design notes :
- Zero external dependencies : stdlib http.server + html string templates.
- State is loaded at process start and mutated in-memory between requests.
  Every mutation is flushed to disk immediately (Ctrl-C safe).
- Images are served directly from the BCE CDN and lmdlp CDN — we don't
  proxy them. The browser fetches them with its own headers.
- Auto-opens the default browser on startup (opt-out with --no-browser).

Usage :
    python ml/review_queue_server.py                # serve all unresolved
    python ml/review_queue_server.py --port 8081
    python ml/review_queue_server.py --source lmdlp
    python ml/review_queue_server.py --no-browser
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
import threading
import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

_ML_DIR = Path(__file__).parent.parent
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from referential.eurio_referential import load_referential, save_referential
from referential.review_core import (
    SOURCE_ENRICHERS,
    ReviewGroup,
    append_matching_log,
    build_groups,
    candidate_preview,
    load_queue,
    load_resolutions,
    load_source_snapshot,
    mark_group_resolved,
    save_queue,
    save_resolutions,
)


# ---------- in-memory state ----------


class ServerState:
    """Holds all mutable state for the session. Not thread-safe but the
    stdlib HTTPServer is single-threaded by default so that's fine."""

    def __init__(self, source_filter: str | None):
        self.source_filter = source_filter
        self.queue = load_queue()
        self.resolutions = load_resolutions()
        self.referential = load_referential()
        self.groups: list[ReviewGroup] = []
        self.snapshots: dict[str, list[dict]] = {}
        self.log_buffer: list[dict] = []
        self.stats = {"picked": 0, "skipped": 0, "no_match": 0, "variants_enriched": 0}
        self._refresh_groups()

    def _refresh_groups(self) -> None:
        self.groups = build_groups(
            self.queue,
            source_filter=self.source_filter,
            only_unresolved=True,
        )

    def get_snapshot(self, source: str) -> list[dict]:
        if source not in self.snapshots:
            self.snapshots[source] = load_source_snapshot(source)
        return self.snapshots[source]

    def persist(self) -> None:
        save_queue(self.queue)
        save_resolutions(self.resolutions)
        save_referential(self.referential)
        if self.log_buffer:
            append_matching_log(self.log_buffer)
            self.log_buffer.clear()


# ---------- source item info lookup ----------


def find_source_item(state: ServerState, group: ReviewGroup) -> dict[str, Any]:
    """Locate the raw product in the source snapshot for the first variant of the group."""
    sample = group.sample_item
    sku = sample.get("source_native_id")
    snapshot = state.get_snapshot(group.source)
    product = None
    for p in snapshot:
        if p.get("sku") == sku:
            product = p
            break
    info: dict[str, Any] = {
        "name": (sample.get("raw_payload") or {}).get("name"),
        "url": (sample.get("raw_payload") or {}).get("permalink"),
        "image": None,
        "price_eur": None,
        "quality": None,
        "mintage": None,
    }
    if product:
        images = product.get("images") or []
        if images and isinstance(images[0], dict):
            info["image"] = images[0].get("src")
        info["name"] = html_mod.unescape(product.get("name") or info["name"] or "")
        info["url"] = product.get("permalink") or info["url"]
        # Source-specific extras
        if group.source == "lmdlp":
            from scrape_lmdlp import extract_mintage, extract_price_eur, extract_quality
            info["price_eur"] = extract_price_eur(product)
            info["quality"] = extract_quality(product)
            info["mintage"] = extract_mintage(product)
    return info


# ---------- HTML rendering ----------


PAGE_CSS = """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0e1116;
    color: #e6edf3;
    margin: 0;
    padding: 24px;
    max-width: 1280px;
    margin: 0 auto;
}
h1 { font-size: 20px; margin: 0 0 12px 0; }
h2 { font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #7d8590; margin: 24px 0 12px; }
a { color: #2f81f7; text-decoration: none; }
a:hover { text-decoration: underline; }
.topbar { display: flex; align-items: center; gap: 16px; padding-bottom: 12px; border-bottom: 1px solid #30363d; }
.progress { color: #7d8590; font-size: 14px; }
.stats { margin-left: auto; color: #7d8590; font-size: 13px; }
.source-box {
    display: grid;
    grid-template-columns: 260px 1fr;
    gap: 24px;
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 20px;
    margin-top: 16px;
}
.source-image, .candidate-image {
    width: 100%;
    max-width: 260px;
    aspect-ratio: 1;
    object-fit: contain;
    background: #0e1116;
    border: 1px solid #30363d;
    border-radius: 6px;
}
.placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    color: #7d8590;
    font-size: 12px;
    width: 100%;
    aspect-ratio: 1;
    background: #0e1116;
    border: 1px dashed #30363d;
    border-radius: 6px;
}
.source-meta { font-size: 14px; line-height: 1.6; }
.source-meta b { color: #e6edf3; font-weight: 600; }
.source-name { font-size: 17px; font-weight: 600; margin-bottom: 8px; }
.tags { color: #7d8590; font-size: 13px; }
.candidates { display: flex; flex-direction: column; gap: 12px; }
.candidate {
    display: grid;
    grid-template-columns: 180px 1fr;
    gap: 16px;
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 16px;
    cursor: pointer;
    transition: border-color 0.1s;
}
.candidate:hover { border-color: #2f81f7; }
.candidate.selected { border-color: #3fb950; background: #0e2818; }
.candidate-body { font-size: 14px; line-height: 1.5; }
.candidate-theme { font-size: 16px; font-weight: 600; margin-bottom: 4px; }
.candidate-slug { color: #7d8590; font-family: "SF Mono", monospace; font-size: 12px; margin-bottom: 8px; }
.candidate-description { color: #c9d1d9; font-size: 13px; margin-bottom: 10px; line-height: 1.4; }
.enrichment { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; color: #7d8590; }
.enrichment span { background: #0e1116; border: 1px solid #30363d; padding: 3px 8px; border-radius: 12px; }
.enrichment .ok { color: #3fb950; border-color: #3fb950; }
.enrichment .none { color: #7d8590; }
.pick-index {
    display: inline-block;
    width: 22px; height: 22px;
    border-radius: 50%;
    background: #2f81f7;
    color: white;
    font-weight: 700;
    text-align: center;
    line-height: 22px;
    margin-right: 8px;
    font-size: 12px;
}
.candidate.selected .pick-index { background: #3fb950; }
.actions {
    margin-top: 24px;
    display: flex;
    gap: 12px;
    padding-top: 16px;
    border-top: 1px solid #30363d;
}
.actions button, .actions a.button {
    font-size: 14px;
    padding: 10px 20px;
    border-radius: 6px;
    border: 1px solid #30363d;
    background: #21262d;
    color: #e6edf3;
    cursor: pointer;
    font-family: inherit;
}
.actions button.primary { background: #238636; border-color: #238636; }
.actions button.primary:hover { background: #2ea043; }
.actions button.secondary { background: #0e1116; }
.actions .spacer { flex: 1; }
.hint { color: #7d8590; font-size: 12px; margin-top: 8px; }
.done-panel {
    text-align: center;
    padding: 80px 20px;
    color: #7d8590;
}
.done-panel h1 { color: #3fb950; font-size: 32px; }
"""

DONE_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Eurio review — done</title>
<style>{css}</style></head><body>
<div class="done-panel">
<h1>✓ Queue cleared</h1>
<p>No unresolved groups remain for this filter.</p>
<p>Session stats — picked: {picked} · skipped: {skipped} · no_match: {no_match} · variants enriched: {variants}</p>
<p style="margin-top:32px;font-size:12px">You can close this tab.</p>
</div></body></html>
"""


def render_candidate(
    idx_ui: int,
    eurio_id: str,
    entry: dict | None,
    selected: bool,
) -> str:
    preview = candidate_preview(entry)
    if preview["missing"]:
        body = f'<div class="candidate-theme">{html_mod.escape(eurio_id)}</div>' \
               '<div class="candidate-slug">(entry not found in referential)</div>'
        img_tag = '<div class="placeholder">missing</div>'
    else:
        theme = html_mod.escape(preview.get("theme") or "?")
        slug = "-".join(eurio_id.split("-")[3:])
        desc = html_mod.escape((preview.get("design_description") or "")[:320])
        img_url = preview.get("image_url")
        img_tag = (
            f'<img class="candidate-image" src="{html_mod.escape(img_url)}" alt="">'
            if img_url
            else '<div class="placeholder">no image</div>'
        )
        enrichment_parts: list[str] = []
        for k, label, fmt in [
            ("lmdlp_variants_count", "lmdlp", "{} variants"),
            ("mdp_issue_count", "mdp", "{} issues"),
            ("ebay_samples", "ebay", "{} samples"),
            ("wikipedia_volume", "mintage", "{:,}"),
        ]:
            v = preview.get(k)
            if v:
                enrichment_parts.append(
                    f'<span class="ok">{label}: {fmt.format(v)}</span>'
                )
            else:
                enrichment_parts.append(f'<span class="none">{label}: —</span>')
        if preview.get("ebay_p50"):
            enrichment_parts.append(
                f'<span class="ok">P50 {preview["ebay_p50"]}€</span>'
            )
        if preview.get("is_joint_issue"):
            enrichment_parts.append(
                f'<span class="ok">joint {len(preview.get("national_variants") or [])} pays</span>'
            )
        enrichment = "".join(enrichment_parts)
        body = (
            f'<div class="candidate-theme"><span class="pick-index">{idx_ui}</span>{theme}</div>'
            f'<div class="candidate-slug">{html_mod.escape(slug)}</div>'
            f'<div class="candidate-description">{desc}</div>'
            f'<div class="enrichment">{enrichment}</div>'
        )

    return f"""
<form method="post" action="/review/{{group_idx}}/action" class="candidate-form">
  <input type="hidden" name="action" value="pick">
  <input type="hidden" name="candidate_idx" value="{idx_ui - 1}">
  <button type="submit" class="candidate{' selected' if selected else ''}" style="all:unset;display:block">
    <div style="display:grid;grid-template-columns:180px 1fr;gap:16px;background:#161b22;border:1px solid {'#3fb950' if selected else '#30363d'};border-radius:8px;padding:16px;cursor:pointer">
      <div>{img_tag}</div>
      <div class="candidate-body">{body}</div>
    </div>
  </button>
</form>
"""


def render_review_page(
    state: ServerState,
    group_idx: int,
    group: ReviewGroup,
    source_info: dict[str, Any],
) -> str:
    # Source image + meta
    src_img = source_info.get("image")
    src_img_html = (
        f'<img class="source-image" src="{html_mod.escape(src_img)}" alt="source">'
        if src_img
        else '<div class="placeholder">no source image</div>'
    )
    name = html_mod.escape(source_info.get("name") or "")
    url = source_info.get("url") or ""
    url_html = f'<a href="{html_mod.escape(url)}" target="_blank" rel="noopener">view on {group.source} ↗</a>' if url else ""
    price = source_info.get("price_eur")
    price_html = f'<b>{price}€</b>' if price is not None else "—"
    qual = html_mod.escape(source_info.get("quality") or "—")
    mintage = source_info.get("mintage")
    mintage_html = f'{mintage:,}' if mintage else "—"

    # Candidates
    candidate_blocks = []
    for i, eurio_id in enumerate(group.candidates, 1):
        entry = state.referential.get(eurio_id)
        block = render_candidate(i, eurio_id, entry, selected=False)
        candidate_blocks.append(block.replace("{group_idx}", str(group_idx)))
    candidates_html = "".join(candidate_blocks)

    total_unresolved = len(state.groups)
    remaining_queue = sum(1 for x in state.queue if not x.get("resolved"))
    stats = state.stats

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Eurio review — {html_mod.escape(group.source)} {group.country}/{group.year}</title>
  <style>{PAGE_CSS}</style>
</head>
<body>
<div class="topbar">
  <h1>Eurio review</h1>
  <div class="progress">Group {group_idx + 1}/{total_unresolved} · {remaining_queue} items in queue</div>
  <div class="stats">picked {stats['picked']} · skipped {stats['skipped']} · no_match {stats['no_match']} · +{stats['variants_enriched']} variants</div>
</div>

<h2>Source product · {html_mod.escape(group.source)} · {html_mod.escape(group.country)}/{group.year} · {len(group.items)} variant(s)</h2>
<div class="source-box">
  <div>{src_img_html}</div>
  <div class="source-meta">
    <div class="source-name">{name}</div>
    <div class="tags">theme_slug: <code>{html_mod.escape(group.theme_slug)}</code></div>
    <div style="margin-top:8px">price: {price_html} · quality: {qual} · mintage: {mintage_html}</div>
    <div style="margin-top:8px">{url_html}</div>
  </div>
</div>

<h2>Canonical candidates ({len(group.candidates)})</h2>
<div class="candidates">
{candidates_html}
</div>

<div class="actions">
  <form method="post" action="/review/{group_idx}/action" style="display:inline">
    <input type="hidden" name="action" value="skip">
    <button class="secondary" type="submit">Skip (s)</button>
  </form>
  <form method="post" action="/review/{group_idx}/action" style="display:inline">
    <input type="hidden" name="action" value="no_match">
    <button class="secondary" type="submit">No match (n)</button>
  </form>
  <div class="spacer"></div>
  <form method="post" action="/quit" style="display:inline">
    <button class="secondary" type="submit">Quit (q)</button>
  </form>
</div>
<div class="hint">Keyboard: 1..{len(group.candidates)} to pick a candidate, s skip, n no_match, q quit.</div>

<script>
document.addEventListener('keydown', function(e) {{
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  const key = e.key.toLowerCase();
  const forms = document.querySelectorAll('form.candidate-form');
  if (/^[0-9]$/.test(key)) {{
    const i = parseInt(key, 10);
    if (i >= 1 && i <= forms.length) {{
      forms[i - 1].submit();
    }}
    return;
  }}
  if (key === 's') {{
    document.querySelector('form[action$="/action"] input[value="skip"]').form.submit();
  }} else if (key === 'n') {{
    document.querySelector('form[action$="/action"] input[value="no_match"]').form.submit();
  }} else if (key === 'q') {{
    document.querySelector('form[action="/quit"]').submit();
  }}
}});
</script>
</body></html>
"""


def render_done(state: ServerState) -> str:
    return DONE_TEMPLATE.format(
        css=PAGE_CSS,
        picked=state.stats["picked"],
        skipped=state.stats["skipped"],
        no_match=state.stats["no_match"],
        variants=state.stats["variants_enriched"],
    )


# ---------- HTTP handler ----------


def make_handler(state: ServerState, quit_event: threading.Event) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            # Quieter log — only print warnings
            return

        def _html(self, body: str, status: int = 200) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("", "/"):
                self._redirect("/review/0")
                return
            if path.startswith("/review/"):
                try:
                    group_idx = int(path.split("/")[2])
                except (ValueError, IndexError):
                    self._redirect("/review/0")
                    return
                state._refresh_groups()
                if group_idx >= len(state.groups):
                    self._html(render_done(state))
                    return
                group = state.groups[group_idx]
                src_info = find_source_item(state, group)
                self._html(render_review_page(state, group_idx, group, src_info))
                return
            self._html("<h1>Not found</h1>", status=404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            form = {k: v[0] for k, v in parse_qs(raw).items()}

            if path == "/quit":
                state.persist()
                print("\n[server] quit requested from browser")
                quit_event.set()
                self._html(render_done(state))
                return

            if path.startswith("/review/") and path.endswith("/action"):
                try:
                    group_idx = int(path.split("/")[2])
                except (ValueError, IndexError):
                    self._redirect("/review/0")
                    return
                state._refresh_groups()
                if group_idx >= len(state.groups):
                    self._redirect("/review/0")
                    return
                group = state.groups[group_idx]
                action = form.get("action", "")
                self._apply_action(group, action, form)
                state.persist()
                state._refresh_groups()
                # After mutation the current group is resolved, so stay at same index
                self._redirect(f"/review/{group_idx}")
                return

            self._html("<h1>Not found</h1>", status=404)

        def _apply_action(self, group: ReviewGroup, action: str, form: dict[str, str]) -> None:
            eurio_id: str | None = None
            if action == "pick":
                try:
                    ci = int(form.get("candidate_idx", "-1"))
                except ValueError:
                    ci = -1
                if 0 <= ci < len(group.candidates):
                    eurio_id = group.candidates[ci]
                else:
                    print(f"[server] bad candidate_idx {ci} for group {group.key}")
                    return

                enricher = SOURCE_ENRICHERS.get(group.source)
                added = 0
                if enricher is not None:
                    snapshot = state.get_snapshot(group.source)
                    added = enricher(state.referential, eurio_id, group.items, snapshot)
                state.stats["variants_enriched"] += added
                state.stats["picked"] += 1
                state.resolutions[group.key] = eurio_id
                print(f"[server] picked {eurio_id} (+{added} variants) for {group.key}")
            elif action == "skip":
                state.resolutions[group.key] = "skip"
                state.stats["skipped"] += 1
                print(f"[server] skipped {group.key}")
            elif action == "no_match":
                state.resolutions[group.key] = "no_match"
                state.stats["no_match"] += 1
                print(f"[server] no_match {group.key}")
            else:
                print(f"[server] unknown action {action!r}")
                return

            mark_group_resolved(group, action, eurio_id)
            state.log_buffer.append(
                {
                    "source": group.source,
                    "stage": "human_review",
                    "country": group.country,
                    "year": group.year,
                    "theme_slug": group.theme_slug,
                    "action": action,
                    "eurio_id": eurio_id,
                    "variants": len(group.items),
                }
            )

    return Handler


# ---------- main ----------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Local web UI for the Eurio review queue")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--source", help="Filter by source (e.g. lmdlp)")
    ap.add_argument("--no-browser", action="store_true", help="Don't auto-open the browser")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    state = ServerState(source_filter=args.source)

    if not state.groups:
        print("No unresolved groups match the filter. Nothing to review.")
        return

    quit_event = threading.Event()
    handler = make_handler(state, quit_event)
    httpd = HTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/review/0"
    print(f"[server] listening on {url}")
    print(f"[server] {len(state.groups)} unresolved groups to review")
    print("[server] use Ctrl-C or the Quit button to stop.\n")

    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    try:
        while not quit_event.is_set():
            httpd.handle_request()
    except KeyboardInterrupt:
        print("\n[server] Ctrl-C, saving state...")
    finally:
        state.persist()
        httpd.server_close()
        print(f"[server] stopped. picked={state.stats['picked']} skipped={state.stats['skipped']} no_match={state.stats['no_match']} variants={state.stats['variants_enriched']}")


if __name__ == "__main__":
    main()
