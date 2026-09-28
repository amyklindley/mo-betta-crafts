#!/usr/bin/env python3
"""Pull crafting recipes from the Monsters & Memories community wiki into recipes.json.

Source: https://monstersandmemories.miraheze.org  (the "Skill <Name>" pages in Category:Tradeskills).
Wiki text is community-written (CC BY-SA); recipes.json keeps the source and fetch date for credit.

  python wiki_recipes.py            fetch and write recipes.json next to this script
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

API = "https://monstersandmemories.miraheze.org/w/api.php?"
WIKI = "https://monstersandmemories.miraheze.org/wiki/"
UA = "MoBettaCrafts/0.2 (+https://github.com/amyklindley/mo-betta-crafts; contact: amyklindley@gmail.com) community crafting tool"
HERE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
OUT = HERE / "recipes.json"

# Column names used across the skill pages, in priority order. The pages were written by different
# people, so each table names its columns a little differently.
RESULT_COLS = ["result", "product", "jewelry item", "scroll name", "enchanted material", "component",
               "disenchants into", "resulting materials yield", "item", "recipe name"]
INGREDIENT_COLS = ["ingredients", "materials required", "components", "unenchanted material", "item target",
                   "scrapped item*", "ingredients*"]
TRIVIAL_COLS = ["trivial", "trivial at"]
STATION_COLS = ["crafting bench", "station", "required station / notes", "mold required"]
NOTE_COLS = ["notes", "notes / effect", "source / notes", "stats", "scraps yield", "slot"]


def api(**params) -> dict:
    params["format"] = "json"
    req = urllib.request.Request(API + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    time.sleep(0.3)  # be polite to a volunteer-run wiki
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def skill_pages() -> list[str]:
    out, cont = [], {}
    while True:
        r = api(action="query", list="categorymembers", cmtitle="Category:Tradeskills", cmlimit=500, **cont)
        out += [m["title"] for m in r["query"]["categorymembers"] if m["title"].startswith("Skill ")]
        if "continue" not in r:
            return out
        cont = {"cmcontinue": r["continue"]["cmcontinue"]}


def wikitext(title: str) -> str:
    return api(action="parse", page=title, prop="wikitext")["parse"]["wikitext"]["*"]


# ---------------------------------------------------------------- wikitext -> rows

def clean(s: str) -> str:
    s = re.sub(r'^\s*(?:colspan|style|rowspan|class)="[^"]*"(?:\s+\w+="[^"]*")*\s*\|(?!\|)', "", s.strip())
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.sub(r"<br\s*/?>", "; ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\{\{[^}]*\}\}", "", s)
    return re.sub(r"\s+", " ", s).strip(" ;")


def cells(block: str) -> list[str]:
    out: list[str] = []
    for line in block.split("\n"):
        line = line.strip()
        if not line or line.startswith(("|}", "{|", "|+")):
            continue
        if line[0] in "|!":
            out += re.split(r"\|\||!!", line[1:])
        elif out:
            out[-1] += " " + line
    return [clean(c) for c in out]


def find_col(hdr: list[str], keys: list[str]) -> int | None:
    for k in keys:
        for i, h in enumerate(hdr):
            if h == k or (k.endswith("*") and h.startswith(k[:-1])):
                return i
    return None


def infobox(w: str, label: str) -> list[str]:
    m = re.search(r"\|\s*" + re.escape(label) + r"\s*\n\|[^\n]*\|\s*([^\n]+)", w)
    return [x for x in (clean(p) for p in re.split(r"<br\s*/?>", m.group(1))) if x] if m else []


def split_items(s: str) -> list[dict]:
    """'6x Copper Bar, 1x Smithing Pliers' -> [{qty: 6, name: 'Copper Bar'}, ...]"""
    out = []
    for part in re.split(r"[,;]\s*(?![^()]*\))", s):
        part = part.strip()
        if not part or part in ("-", "—"):
            continue
        m = re.match(r"^(\d+)\s*x\s+(.+)$", part, re.I) or re.match(r"^(.+?)\s+x(\d+)$", part, re.I)
        if m and m.group(1).isdigit():
            out.append({"qty": int(m.group(1)), "name": m.group(2).strip()})
        elif m:
            out.append({"qty": int(m.group(2)), "name": m.group(1).strip()})
        else:
            out.append({"qty": 1, "name": part})
    return out


def parse_skill(title: str, w: str) -> list[dict]:
    skill = title.removeprefix("Skill ")
    tools = {t.lower() for t in infobox(w, "Primary Tools") + infobox(w, "Primary Tool")
             + infobox(w, "Tool Required")}
    default_station = ", ".join(infobox(w, "Crafting Station") or infobox(w, "Required Station"))
    recipes, section = [], ""
    for m in re.finditer(r"(^=+\s*(.*?)\s*=+\s*$)|(\{\|.*?\n\|\})", w, re.M | re.S):
        if m.group(2):
            section = clean(m.group(2))
            continue
        rows = re.split(r"\n\|-[^\n]*", m.group(3))
        hdr = [h.lower() for h in cells(rows[0])]
        ri, ii = find_col(hdr, RESULT_COLS), find_col(hdr, INGREDIENT_COLS)
        combo = None
        if ri is not None and ii is None and all(x in hdr for x in ("metal", "gem", "mold type")):
            combo = [hdr.index("metal"), hdr.index("gem"), hdr.index("mold type")]  # jewelry catalog
            ii = combo[0]
        if ri is None or ii is None or ri == ii:
            continue
        ti, si, ni = find_col(hdr, TRIVIAL_COLS), find_col(hdr, STATION_COLS), find_col(hdr, NOTE_COLS)
        salvage = "scrap" in section.lower() or "disenchant" in skill.lower() or "yield" in hdr[ri]
        for r in rows[1:]:
            c = cells(r)
            if len(c) <= max(ri, ii):
                continue
            get = lambda i: c[i] if i is not None and i < len(c) else ""
            result = get(ri)
            if not result or result.lower() == "example":
                continue
            ing_text = ", ".join("1x " + c[j] for j in combo if j < len(c)) if combo else get(ii)
            ingredients = split_items(ing_text)
            for it in ingredients:
                it["tool"] = it["name"].lower() in tools
            station = get(si) or default_station
            if si is not None and hdr[si] == "mold required" and get(si):
                station = f"{default_station} + {get(si)}"
            notes = get(ni)
            if notes and notes.lower() in ing_text.lower():  # some tables repeat an ingredient in the notes column
                notes = ""
            res = split_items(result)
            name = res[0]["name"] if len(res) == 1 else result
            recipes.append({
                "id": f"{skill}|{section}|{name}|" + "+".join(i["name"] for i in ingredients),
                "skill": skill,
                "section": section,
                "trivial": int(get(ti)) if get(ti).isdigit() else None,
                "name": name,
                "makes": res[0]["qty"] if len(res) == 1 else None,
                "results": res,
                "ingredients": ingredients,
                "station": station,
                "notes": notes,
                "salvage": salvage,
                "url": WIKI + urllib.parse.quote(title.replace(" ", "_")),
            })
    return recipes


def main() -> None:
    pages = skill_pages()
    recipes: list[dict] = []
    for title in pages:
        try:
            got = parse_skill(title, wikitext(title))
        except Exception as e:  # one bad page shouldn't sink the rest
            print(f"  {title}: failed ({e})")
            continue
        print(f"  {title}: {len(got)}")
        recipes += got
    seen, unique = set(), []
    for r in recipes:
        if r["id"] not in seen:
            seen.add(r["id"])
            unique.append(r)
    OUT.write_text(json.dumps({
        "source": "https://monstersandmemories.miraheze.org (community wiki, CC BY-SA)",
        "fetched": date.today().isoformat(),
        "recipes": unique,
    }, indent=1, ensure_ascii=False), "utf-8")
    print(f"wrote {len(unique)} recipes to {OUT}")


if __name__ == "__main__":
    main()
