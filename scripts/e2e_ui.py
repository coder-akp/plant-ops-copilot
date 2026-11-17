"""Browser end-to-end check of the web UI (English and German, light and dark, desktop and mobile).

    pip install playwright && playwright install chromium
    python -m scripts.e2e_ui http://localhost:8000 [--live-url http://localhost:8001]

BASE is a server whose live agents may be off. The optional LIVE URL is a server started with
LLM_PROVIDER=mock (and, for German replays, REPLAY_DIR pointing at mock recordings) so that live runs,
the guard messages and German recordings can be exercised without a model.
The tool exits with status 1 if any check fails.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from playwright.sync_api import Page, sync_playwright

RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail and not ok else ""))


def wait(page: Page, js: str, timeout: int = 20000) -> bool:
    try:
        page.wait_for_function(js, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def text(page: Page, sel: str) -> str:
    return page.locator(sel).first.inner_text().strip()


def open_page(ctx, url: str, errors: list[str]) -> Page:
    page = ctx.new_page()
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.goto(url)
    wait(page, "document.querySelectorAll('#scenarioCards .scn').length === 4")
    wait(page, "document.querySelector('#k-sev .v') && document.querySelector('#k-sev .v').dataset.v !== '0'")
    if "gl=force" in url:
        wait(page, "document.body.classList.contains('has3d')", 20000)
    return page


def replay_done(page: Page, timeout: int = 25000) -> bool:
    return wait(page, "document.querySelector('#pipe li[data-step=\"3\"]').dataset.state === 'done'", timeout)


def static_language_checks(page: Page, lang: str) -> None:
    de = lang == "de"
    check(page.evaluate("document.documentElement.lang") == lang, f"[{lang}] html lang attribute")
    check(("Multi-Agenten" in text(page, "h1")) == de, f"[{lang}] headline language", text(page, "h1"))
    check(("Abläufe" not in text(page, "nav")) and (("Funktionsweise" in text(page, "nav")) == de), f"[{lang}] navigation labels")
    check(("Erkennen" in text(page, "#pipe")) == de and ("Detect" in text(page, "#pipe")) != de, f"[{lang}] pipeline labels")
    check(("anlagenverfügbarkeit" in text(page, "#kpiRibbon").lower()) == de, f"[{lang}] KPI ribbon labels")
    check(("Verfügbarkeit %" in text(page, "#kpiTable")) == de, f"[{lang}] KPI table headers")
    check(("Abfüller" in page.locator("#machineSel").inner_text()) == de, f"[{lang}] machine selector roles")
    check(("Vibration (mm/s)" in page.locator("#signalSel").inner_text()), f"[{lang}] signal selector filled")
    check(("Abschaltgrenze" in text(page, "#legend")) == de, f"[{lang}] chart legend")
    check(("Ablauf" in text(page, "#agents h2") or "Untersuchungsablauf" in text(page, "#agents h2")) == de, f"[{lang}] trace heading")
    check(("Wartungshandbücher" in text(page, "#how")) == de, f"[{lang}] architecture diagram text")
    check(("synthetischen Daten" in text(page, "footer")) == de, f"[{lang}] footer")
    check(("Alarm" in text(page, "#flat") or "Alarm" in text(page, ".m3d-label.alert")) == de, f"[{lang}] machine status labels")
    check(page.locator("#btnLang").inner_text() == ("EN" if de else "DE"), f"[{lang}] language button shows the other language")


def run_replay_checks(page: Page, lang: str, scenario_title_part: str, expect_order: bool) -> None:
    page.locator("#btnReplay").click()
    ok = replay_done(page)
    check(ok, f"[{lang}] replay completes ({scenario_title_part})")
    if not ok:
        return
    check(page.locator("#timeline .ev").count() > 5, f"[{lang}] trace has events")
    check(not page.locator("#report").is_hidden(), f"[{lang}] report shown")
    check(page.locator("#orders .order").count() == (1 if expect_order else 0), f"[{lang}] work order count ({'1' if expect_order else '0'})")
    check(page.locator("#pipe li[data-step='4']").get_attribute("data-state") == ("wait" if expect_order else "skip"), f"[{lang}] approval step state")
    check(float(text(page, "#mTools") or 0) >= 1, f"[{lang}] tool counter updated")
    check(text(page, "#mTokens") not in ("–", ""), f"[{lang}] token meter updated")
    if expect_order:
        page.locator("#orders .order button").click()
        check(wait(page, "document.querySelector('#pipe li[data-step=\"4\"]').dataset.state === 'done'", 5000), f"[{lang}] approve flow")
        check(("Freigegeben" in text(page, "#orders")) == (lang == "de"), f"[{lang}] approval message language")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--live-url", default="")
    ap.add_argument("--chrome", default=os.environ.get("CHROME_PATH", ""))
    ap.add_argument("--gl-force", action="store_true", help="force WebGL even if only software rendering is available")
    args = ap.parse_args()
    q = "&gl=force" if args.gl_force else ""
    launch = {"args": ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]}
    if args.chrome:
        launch["executable_path"] = args.chrome

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        errors: list[str] = []

        # ---------- Desktop, English ----------
        ctx = browser.new_context(viewport={"width": 1360, "height": 900}, bypass_csp=True)
        page = open_page(ctx, f"{args.base}/?lang=en{q}", errors)
        check(page.evaluate("document.body.classList.contains('has3d')") if args.gl_force else True, "3D scene loads")
        if args.gl_force:
            check(page.locator(".m3d-label").count() == 4, "four machine labels in 3D")
            page.locator('.m3d-label[data-id="CAPPER-01"]').hover()
            check(wait(page, "!document.querySelector('#mtip').hidden", 3000) and "Click to inspect" in text(page, "#mtip"), "hover card on a machine (EN)")
            page.locator('.m3d-label[data-id="CAPPER-01"]').click()
            check(page.locator("#machineSel").input_value() == "CAPPER-01", "clicking a machine selects it")
            check("CAPPER-01" in text(page, "#mpanel"), "machine panel follows the selection")
            page.locator("#btnReset").click()
        static_language_checks(page, "en")
        check(page.locator("#chart svg").count() == 1, "chart renders")
        page.locator("#chart svg").scroll_into_view_if_needed()
        box = page.locator("#chart svg").bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + box["height"] * 0.5)
        check(wait(page, "!document.querySelector('#chart .tip').hidden", 2000), "chart hover tooltip")

        # scenario sweep in English
        for idx, (part, order) in enumerate([("Normal", False), ("bearing", True), ("thermal", True), ("temperature", True)]):
            page.locator("#scenarioCards .scn").nth(idx).click()
            wait(page, f"document.querySelectorAll('#scenarioCards .scn')[{idx}].getAttribute('aria-pressed')==='true'", 3000)
            wait(page, "document.querySelector('#findings').textContent.length>0", 3000)
            run_replay_checks(page, "en", part, order)

        # skip button
        page.locator("#scenarioCards .scn").nth(1).click()
        page.locator("#btnReplay").click()
        page.wait_for_timeout(700)
        t0 = time.time()
        page.locator("#btnSkip").click()
        check(replay_done(page, 5000) and time.time() - t0 < 3, "skip to result is immediate")

        # theme toggle
        bg_dark = page.evaluate("getComputedStyle(document.body).backgroundColor")
        page.locator("#btnTheme").click()
        bg_light = page.evaluate("getComputedStyle(document.body).backgroundColor")
        check(bg_dark != bg_light and page.evaluate("document.documentElement.dataset.theme") == "light", "theme toggle changes colours")
        page.goto(f"{args.base}/?lang=en{q}"); wait(page, "document.querySelectorAll('#scenarioCards .scn').length === 4")
        check(page.evaluate("document.documentElement.dataset.theme") == "light", "theme persists after reload")
        page.locator("#btnTheme").click()
        check(page.evaluate("document.documentElement.dataset.theme") == "dark", "theme toggles back to dark")

        # ---------- Language toggle, persistence, German ----------
        page.locator("#btnLang").click()
        wait(page, "document.documentElement.lang === 'de'", 3000)
        static_language_checks(page, "de")
        check(page.locator("#timeline .ev").count() == 0, "language change ends the previous run")
        page.goto(f"{args.base}/?{q.lstrip('&')}"); wait(page, "document.querySelectorAll('#scenarioCards .scn').length === 4")
        check(page.evaluate("document.documentElement.lang") == "de", "language persists after reload (no URL parameter)")
        check("Schleichender Lagerverschleiß" in text(page, "#scenarioCards"), "scenario titles in German")
        page.locator("#scenarioCards .scn").nth(1).click()
        page.locator("details.truth summary").click()
        check("verschleiß" in text(page, "#truthText"), "spoiler text in German")
        for theme in ("dark", "light"):
            if page.evaluate("document.documentElement.dataset.theme") != theme:
                page.locator("#btnTheme").click()
            for idx, (part, order) in enumerate([("Normale", False), ("Lager", True)]):
                page.locator("#scenarioCards .scn").nth(idx).click()
                wait(page, "document.querySelector('#findings').textContent.length>0", 3000)
                page.locator("#btnReplay").click()
                ok = replay_done(page)
                check(ok, f"[de/{theme}] replay completes ({part})")
                if ok:
                    notice = page.locator("#notice").inner_text()
                    check("Aufzeichnung" in notice, f"[de/{theme}] replay notice in German (or fallback)", notice)
                    check("Erkennungs-Agent" in text(page, "#timeline"), f"[de/{theme}] trace step names in German")

        # language switch in the middle of a run
        page.locator("#scenarioCards .scn").nth(1).click()
        page.locator("#btnReplay").click()
        page.wait_for_timeout(800)
        page.locator("#btnLang").click()
        wait(page, "document.documentElement.lang === 'en'", 3000)
        page.wait_for_timeout(1500)
        check(page.locator("#timeline .ev").count() == 0 and not page.locator("#btnReplay").is_disabled(), "language switch during a run stops it cleanly")
        page.locator("#btnReplay").click()
        check(replay_done(page), "replay works again after switching during a run")

        # tour start / stop and presentation mode
        page.locator("#btnTour").click()
        check(wait(page, "!document.querySelector('#caption').hidden", 6000), "tour shows captions")
        check(wait(page, "document.querySelectorAll('#scenarioCards .scn')[2].getAttribute('aria-pressed')==='true'", 30000), "tour advances to the next shift")
        page.locator("#btnTour").click()
        check(wait(page, "document.querySelector('#caption').hidden", 3000) and not page.locator("#scenarioCards .scn").first.is_disabled(), "tour stops cleanly")
        page.locator("#btnPresent").click()
        check(wait(page, "document.documentElement.classList.contains('present')", 2000) and page.locator("#btnExit").is_visible(), "presentation mode on")
        page.locator("#btnExit").click()
        check(wait(page, "!document.documentElement.classList.contains('present')", 2000), "presentation mode off")

        # 2D fallback
        p2 = open_page(ctx, f"{args.base}/?lang=de&scene=2d", errors)
        check(not p2.evaluate("document.body.classList.contains('has3d')") and p2.locator("#flat .tile").count() == 4, "2D fallback shows four machine tiles")
        p2.locator('#flat .tile[data-id="LABELER-01"]').click()
        check(p2.locator("#machineSel").input_value() == "LABELER-01", "2D tile selects a machine")
        p2.locator('#flat .tile[data-id="FILLER-01"]').hover()
        check(wait(p2, "!document.querySelector('#mtip').hidden", 2000) and "Zum Untersuchen klicken" in text(p2, "#mtip"), "2D hover card in German")
        p2.close()

        # ---------- Mobile ----------
        mctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, has_touch=True, is_mobile=True, bypass_csp=True,
                                   user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1")
        for lang in ("en", "de"):
            m = open_page(mctx, f"{args.base}/?lang={lang}{q}", errors)
            check(m.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"[mobile/{lang}] no horizontal overflow",
                  str(m.evaluate("[document.documentElement.scrollWidth, innerWidth]")))
            m.locator("#btnReplay").tap()
            check(replay_done(m), f"[mobile/{lang}] replay by tap")
            check(m.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"[mobile/{lang}] no overflow after a run")
            m.locator("#btnLang").tap()
            wait(m, f"document.documentElement.lang === '{'en' if lang == 'de' else 'de'}'", 3000)
            check(m.locator("#timeline .ev").count() == 0, f"[mobile/{lang}] language switch resets the run")
            m.close()

        # ---------- Live runs with the scripted model ----------
        if args.live_url:
            for lang in ("en", "de"):
                time.sleep(9)  # the guard enforces a cooldown between live runs
                lp = open_page(ctx, f"{args.live_url}/?lang={lang}", errors)
                check(not lp.locator("#btnLive").is_disabled(), f"[live/{lang}] live button available")
                lp.locator("#btnLive").click()
                ok = replay_done(lp, 40000)
                check(ok, f"[live/{lang}] live run completes")
                report = text(lp, "#report")
                check(("Zusammenfassung" in report) == (lang == "de") and ("Summary" in report) == (lang == "en"), f"[live/{lang}] agents write in the selected language", report[:60])
                check(lp.locator("#orders .order").count() == 1, f"[live/{lang}] live work order proposed")
                lp.locator("#btnLive").click()
                wait(lp, "document.querySelector('#notice').textContent.length > 0", 5000)
                msg = text(lp, "#notice")
                check(("Bitte" in msg) == (lang == "de") and ("Please wait" in msg) == (lang == "en"), f"[live/{lang}] guard message language", msg)
                lp.close()
            # German recordings, no fallback
            dp = open_page(ctx, f"{args.live_url}/?lang=de", errors)
            dp.locator("#btnReplay").click()
            replay_done(dp)
            check("Zusammenfassung" in text(dp, "#report") and "Englisch" not in text(dp, "#notice") and "englische" not in text(dp, "#notice"), "German recording plays without fallback")
            dp.close()

        browser.close()

    real_errors = [e for e in errors if "favicon" not in e and "429" not in e]  # 429 is the expected guard answer
    check(not real_errors, "no console or page errors", "; ".join(real_errors[:4]))
    failed = [n for ok, n in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    for n in failed:
        print("  failed:", n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
