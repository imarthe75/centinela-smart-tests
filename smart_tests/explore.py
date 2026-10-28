"""Screen mapping helper: log in as one profile and run SAFE steps (navigate, click, dump DOM, screenshot, Escape).
It never submits a form: a step that clicks a button whose text is in WRITE_WORDS is refused.

steps: [{"goto": url} | {"click": selector} | {"click_text": text} | {"expand": [names...]} | {"dump": selector, "max": n}
        | {"shot": name} | {"escape": true} | {"wait": ms} | {"texts": selector}]
"""
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from playwright.sync_api import sync_playwright

from smart_tests.recipes import primeng
from smart_tests.session import Session, screenshot_dir

logger = logging.getLogger(__name__)
WRITE_WORDS = re.compile(r"\b(guardar|aceptar|confirmar|eliminar|restaurar|enviar|registrar|firmar|turnar)\b", re.I)


def run_explore(profile: Dict[str, Any], steps: List[Dict[str, Any]], out_dir: Path) -> Dict[str, Any]:
    log: List[Dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        s = Session(browser, profile, screenshot_dir(out_dir), "explore")
        try:
            s.login()
            log.append({"step": "login", "url": s.page.url})
            page = s.page
            for st in steps:
                entry: Dict[str, Any] = {"step": st}
                try:
                    if "goto" in st:
                        page.goto(st["goto"], wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_timeout(1500)
                    elif "click" in st:
                        loc = page.locator(st["click"]).nth(st.get("nth", 0))
                        if WRITE_WORDS.search(loc.inner_text() or ""):
                            raise RuntimeError("explore no pulsa botones que escriben datos")
                        loc.click()
                        page.wait_for_timeout(st.get("after_ms", 1000))
                    elif "click_text" in st:
                        if WRITE_WORDS.search(st["click_text"]):
                            raise RuntimeError("explore no pulsa botones que escriben datos")
                        page.get_by_text(st["click_text"], exact=st.get("exact", True)).first.click()
                        page.wait_for_timeout(st.get("after_ms", 1000))
                    elif "expand" in st:
                        primeng.expand_path(page, st["expand"])
                    elif "dump" in st:
                        loc = page.locator(st["dump"])
                        entry["count"] = loc.count()
                        entry["html"] = [loc.nth(i).evaluate("e => e.outerHTML")[: st.get("chars", 600)]
                                         for i in range(min(loc.count(), st.get("max", 5)))]
                    elif "texts" in st:
                        entry["texts"] = [t.strip()[:200] for t in page.locator(st["texts"]).all_inner_texts()][: st.get("max", 40)]
                    elif "shot" in st:
                        entry["evidence"] = s.shot(st["shot"]).value
                    elif "escape" in st:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)
                    elif "wait" in st:
                        page.wait_for_timeout(int(st["wait"]))
                    entry["url"] = page.url
                except Exception as e:
                    logger.error("paso de exploración fallido: %s", st, exc_info=True)
                    entry["error"] = str(e)[:400]
                log.append(entry)
        finally:
            s.close()
            browser.close()
    return {"log": log}


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
