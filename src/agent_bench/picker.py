"""Start-up tick list: choose which harnesses to run. Pure logic plus an injectable input function, so it is testable."""
from __future__ import annotations

from typing import Callable


def tick_list(items: list[dict], preselected: set[str], ask: Callable[[str], str] = input,
              show: Callable[[str], None] = print) -> list[str]:
    """items: [{"name", "label", "status"}] where status is None when runnable, else the reason it is not.
    Returns the chosen names in list order. Empty list means the user quit."""
    runnable = [i["name"] for i in items if i["status"] is None]
    selected = {n for n in preselected if n in runnable}
    while True:
        show("")
        show("Harnesses to run  (x = selected)")
        for idx, it in enumerate(items, 1):
            if it["status"] is None:
                mark = "[x]" if it["name"] in selected else "[ ]"
                show(f"  {idx:>2}. {mark} {it['label']:<14} ({it['name']})")
            else:
                show(f"   -  [unavailable] {it['label']:<14} ({it['name']}): {it['status']}")
        ans = ask("toggle numbers (e.g. 1 3), a=all, n=none, Enter=start, q=quit > ").strip().lower()
        if ans == "":
            if selected:
                return [it["name"] for it in items if it["name"] in selected]
            show("nothing selected; toggle at least one harness, or q to quit")
            continue
        if ans == "q":
            return []
        if ans in ("a", "all"):
            selected = set(runnable)
            continue
        if ans in ("n", "none"):
            selected = set()
            continue
        for tok in ans.replace(",", " ").split():
            if not tok.isdigit() or not (1 <= int(tok) <= len(items)):
                show(f"not a valid entry: {tok}")
                continue
            name = items[int(tok) - 1]["name"]
            if name not in runnable:
                show(f"{name} is unavailable: {items[int(tok) - 1]['status']}")
                continue
            selected ^= {name}
