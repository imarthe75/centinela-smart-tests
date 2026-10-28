"""Recipes for PrimeNG (Angular) screens, learned against a real application:

* Radio buttons: the native <input type=radio> lives inside `.p-hidden-accessible` (size 0); the clickable control is its <label for=...>.
* Tree tables (`p-treetable`): child rows do not exist in the DOM until the parent row is expanded (`[data-pc-section=rowtoggler]`).
* Dialogs: `.p-dialog`; the visible one is the last one in the DOM.
* Messages: `.p-toast-message` (transient) — prefer the HTTP response of the action as evidence; the toast text is a secondary signal.
"""
import re
from typing import Optional

TOAST = ".p-toast-message, .p-message, [role=alert]"


def dialog(page):
    return page.locator(".p-dialog:visible").last


def close_dialog(page) -> None:
    """Cierra el diálogo visible de forma robusta. En algunas aplicaciones la máscara del `p-dialog` intercepta el click sobre
    «Cancelar» (el botón «resuelve» pero el click expira), así que se intenta en orden: el botón de cerrar del header,
    Cancelar/Cerrar (con fallback `force=True` que atraviesa la máscara) y finalmente Escape. Cada intento acotado."""
    for _ in range(3):
        dlg = page.locator(".p-dialog:visible").last
        if not (dlg.count() and dlg.is_visible()):
            return
        closed = False
        for sel in ("[data-pc-section=closebutton]", ".p-dialog-header-close",
                    "button:has-text('Cancelar')", "button:has-text('Cerrar')"):
            b = dlg.locator(sel)
            if not b.count():
                continue
            for kw in ({"timeout": 2500}, {"timeout": 1500, "force": True}):
                try:
                    b.first.click(**kw)
                    closed = True
                    break
                except Exception:
                    continue
            if closed:
                break
        if not closed:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
        page.wait_for_timeout(500)


def click_radio(page, input_id: str) -> None:
    page.locator(f"label[for='{input_id}']").first.click()


def toast_text(page, wait_ms: int = 2500) -> str:
    try:
        page.locator(TOAST).first.wait_for(state="visible", timeout=wait_ms)
        return " ".join(t.strip() for t in page.locator(TOAST).all_inner_texts() if t.strip())[:400]
    except Exception:
        return ""


def tree_row(page, name: str):
    return page.locator("tr", has=page.get_by_text(name, exact=True)).first


def expand_path(page, path) -> None:
    """Make the row of path[-1] visible: for each (parent, child) pair, click the parent's toggler only when the child row is not
    visible yet. (Guessing the state from the chevron icon is unreliable; clicking an expanded node collapses it.)"""
    tree_row(page, path[0]).wait_for(state="visible", timeout=15000)
    for parent, child in zip(path, path[1:]):
        if tree_row(page, child).is_visible():
            continue
        # El nombre del data-pc-section del toggler cambia entre versiones de PrimeNG: en algunas versiones es `rowtogglebutton`
        # (botón `.p-treetable-toggler`), en versiones previas era `rowtoggler`. Se aceptan ambos + el botón por clase.
        tog = tree_row(page, parent).locator("button.p-treetable-toggler, [data-pc-section=rowtogglebutton], [data-pc-section=rowtoggler]")
        if not tog.count():
            raise RuntimeError(f"«{parent}» no tiene unidades dependientes visibles (se buscaba «{child}»)")
        tog.first.click()
        tree_row(page, child).wait_for(state="visible", timeout=10000)


def row_action(row, kind: str):
    """kind: add | edit | delete | restore. PrimeNG/PrimeIcons classes, with SVG-icon and tooltip fallbacks."""
    sel = {
        "add": ".pi-plus, [ptooltip*='gregar' i], [ptooltip*='nueva' i], button:has(svg[data-pc-name=plusicon])",
        "edit": ".pi-pencil, [ptooltip*='ditar' i], button:has(svg[data-pc-name=pencilicon])",
        "delete": ".pi-trash, [ptooltip*='liminar' i], button:has(svg[data-pc-name=trashicon])",
        "restore": ".pi-replay, .pi-undo, .pi-refresh, [ptooltip*='estaurar' i]",
    }[kind]
    return row.locator(sel).first


def fill_control(page, formcontrolname: str, value: str, scope=None) -> None:
    s = scope or page
    s.locator(f"[formcontrolname='{formcontrolname}']").first.fill(value)


def select_dropdown(page, trigger, option_text: str) -> None:
    trigger.click()
    page.locator(".p-dropdown-item, .p-select-item, [role=option]").filter(has_text=re.compile(rf"^\s*{re.escape(option_text)}\s*$")).first.click()


def button(scope, text: str):
    return scope.locator(f"button:has-text('{text}')").first


def nav(page, menu_text: str, wait_ms: int = 2500) -> None:
    """Navigate via the left sidebar. Angular's router guards reject a direct goto to a deep route (it redirects to the landing page),
    so screens are reached by clicking their menu link (the `<a>`, not the inner `<span>`)."""
    page.locator(f"a:has-text(\"{menu_text}\")").first.click()
    page.wait_for_timeout(wait_ms)


def set_calendar(page, field_id: str, iso_date: str) -> None:
    """Pick a date in a PrimeNG p-calendar whose input is readonly. Opens the panel and clicks the day cell by its `data-date`
    attribute, navigating months with the prev/next chevrons. `iso_date` is standard `YYYY-MM-DD`.
    Two real gotchas handled: (1) the DOM's `data-date` is NOT zero-padded (`2026-9-16`, not `2026-09-16`), so months are compared
    numerically, not by string; (2) everything is scoped to THIS field's open overlay (via the trigger's aria-controls), because the
    page can have other calendars whose prev/next buttons would otherwise be clicked, leaving the panel stuck."""
    y, m, d = (int(x) for x in iso_date.split("-"))
    dom_date = f"{y}-{m}-{d}"                       # non-padded, as the attribute is written
    want = y * 12 + m
    # PrimeNG nuevo: el disparador es `.p-datepicker-dropdown`; el viejo era `.p-datepicker-trigger`.
    trigger = page.locator(f"#{field_id} .p-datepicker-dropdown, #{field_id} .p-datepicker-trigger").first
    if not trigger.count():
        trigger = page.locator(f"#{field_id} input").first
    trigger.click()
    page.wait_for_timeout(500)
    # Scope by visibility, not by the trigger's aria-controls: PrimeNG re-creates the overlay (new id) on each month change, so a
    # fixed panel id goes stale. Only one datepicker overlay is open at a time, so `:visible` isolates it.
    # PrimeNG nuevo usa `td[data-date]` (antes `span[data-date]`) -> se acepta cualquier elemento con data-date.
    for _ in range(36):
        cell = page.locator(f"[data-date='{dom_date}']:visible:not(.p-disabled)")
        if cell.count():
            cell.first.click()
            page.wait_for_timeout(300)
            return
        months = sorted({int(v.split("-")[0]) * 12 + int(v.split("-")[1])
                         for v in (s.get_attribute("data-date") for s in page.locator("[data-date]:visible").all()) if v})
        if not months:
            raise RuntimeError(f"no se abrió el calendario de #{field_id}")
        shown = months[len(months) // 2]           # the month actually displayed (ignores adjacent-month edge cells)
        nxt = "next" if want > shown else "prev"
        # PrimeNG nuevo: botones de navegación por aria-label («Mes siguiente»/«Mes anterior»); el viejo usaba `.p-datepicker-next/prev`.
        label = "Mes siguiente" if nxt == "next" else "Mes anterior"
        btn = page.locator(f"button[aria-label='{label}']:visible, .p-datepicker-{nxt}:visible")
        if not btn.count():
            raise RuntimeError(f"no se encontró el control de mes ({nxt}) del calendario")
        btn.first.click()
        page.wait_for_timeout(350)
    raise RuntimeError(f"no se pudo navegar a {iso_date} en #{field_id}")


def checkbox(page, input_id: str, checked: bool, scope=None) -> None:
    """Set a PrimeNG checkbox/inputswitch to `checked`. The real toggle is the box, not the hidden input.
    `scope` matters: the same `id` can appear twice (a page filter AND a dialog field) — pass the dialog to hit the right one."""
    s = scope or page
    box = s.locator(f"[id='{input_id}']").first
    if (box.get_attribute("aria-checked") == "true") == checked:
        return
    box.locator("xpath=ancestor::*[contains(@class,'p-checkbox') or contains(@class,'p-inputswitch')][1]").first.click()
    page.wait_for_timeout(300)


def visible_text(page) -> str:
    return page.locator("body").inner_text()


def first_number(text: str) -> Optional[int]:
    m = re.search(r"\d+", text or "")
    return int(m.group(0)) if m else None
