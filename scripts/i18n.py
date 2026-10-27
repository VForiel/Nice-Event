"""Catalogue de traduction anglais, sans dépendre des outils GNU gettext (absents sous Windows).

    python scripts/i18n.py           extrait les chaînes, met à jour locale/en/LC_MESSAGES/django.po, compile le .mo
    python scripts/i18n.py --check   échoue s'il reste des chaînes sans traduction

L'extraction s'appuie sur Django lui-même (`templatize`) pour les gabarits, et sur une expression régulière
pour les appels `_("…")` / `gettext("…")` / `gettext_lazy("…")` du code Python.
"""

import ast
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PO = ROOT / "locale" / "en" / "LC_MESSAGES" / "django.po"
SOURCES = ["core", "events", "venues", "community", "social", "aggregator", "siteconfig", "alerts", "templates", "config"]
SKIP = ("migrations", "gestion", "admin", "templates/gestion")

PY_CALL = re.compile(r"""\b(?:_|gettext|gettext_lazy|pgettext_lazy|pgettext)\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)""")


def literal(source):
    return ast.literal_eval(source)


def extract():
    import django
    from django.conf import settings

    sys.path.insert(0, str(ROOT))
    if not settings.configured:
        import os
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        django.setup()
    from django.utils.translation.template import templatize

    found = {}
    for folder in SOURCES:
        for path in sorted((ROOT / folder).rglob("*")):
            rel = path.relative_to(ROOT).as_posix()
            if any(part in rel for part in SKIP) or not path.is_file() or path.suffix not in (".html", ".py", ".txt"):
                continue
            text = path.read_text(encoding="utf-8")
            if path.suffix in (".html", ".txt"):
                text = templatize(text)
            for match in PY_CALL.finditer(text):
                msgid = "".join(literal(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', match.group(1)))
                found.setdefault(msgid, rel)
            if path.suffix == ".py":
                for match in re.finditer(r'\bngettext\(\s*("(?:[^"\\]|\\.)*"),\s*("(?:[^"\\]|\\.)*")', text):
                    found.setdefault((literal(match.group(1)), literal(match.group(2))), rel)
            if path.suffix in (".html", ".txt"):
                # templatize écrit gettext(u'…') ou gettext(u"…") selon les guillemets du texte
                string = r"""(u?(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"))"""
                for match in re.finditer(r"(?<!n)gettext\(" + string + r"\)", text):
                    found.setdefault(literal(match.group(1)), rel)
                for match in re.finditer(r"ngettext\(" + string + r",\s*" + string, text):
                    found.setdefault((literal(match.group(1)), literal(match.group(2))), rel)
    return found


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def read_po():
    entries, key, current, field = {}, None, {}, None
    if not PO.exists():
        return entries
    for line in PO.read_text(encoding="utf-8").splitlines() + [""]:
        if not line.strip():
            if "msgid" in current and current["msgid"]:
                key = (current["msgid"], current["msgid_plural"]) if "msgid_plural" in current else current["msgid"]
                entries[key] = current
            current, field = {}, None
            continue
        if line.startswith("#"):
            continue
        m = re.match(r'(msgid|msgid_plural|msgstr(?:\[\d\])?) "(.*)"$', line)
        if m:
            field = m.group(1)
            current[field] = literal('"' + m.group(2) + '"')
        elif line.startswith('"') and field:
            current[field] += literal(line)
    return entries


def write_po(found, existing):
    out = [
        "# Traduction anglaise du site Nice-Event. Générée et compilée par scripts/i18n.py.",
        'msgid ""',
        'msgstr ""',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Language: en\\n"',
        '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"',
        "",
    ]
    for key, where in sorted(found.items(), key=lambda kv: (kv[1], str(kv[0]))):
        old = existing.get(key, {})
        out.append(f"#: {where}")
        if isinstance(key, tuple):
            out += [f'msgid "{esc(key[0])}"', f'msgid_plural "{esc(key[1])}"',
                    f'msgstr[0] "{esc(old.get("msgstr[0]", ""))}"', f'msgstr[1] "{esc(old.get("msgstr[1]", ""))}"']
        else:
            out += [f'msgid "{esc(key)}"', f'msgstr "{esc(old.get("msgstr", ""))}"']
        out.append("")
    PO.parent.mkdir(parents=True, exist_ok=True)
    PO.write_text("\n".join(out), encoding="utf-8")


def compile_mo(entries):
    """Format .mo de GNU gettext (petit-boutiste, sans table de hachage)."""
    pairs = [(b"", b"Content-Type: text/plain; charset=UTF-8\nPlural-Forms: nplurals=2; plural=(n != 1);\n")]
    for key, e in entries.items():
        if isinstance(key, tuple):
            if e.get("msgstr[0]") and e.get("msgstr[1]"):
                pairs.append((f"{key[0]}\0{key[1]}".encode(), f"{e['msgstr[0]']}\0{e['msgstr[1]']}".encode()))
        elif e.get("msgstr"):
            pairs.append((key.encode(), e["msgstr"].encode()))
    pairs.sort()
    n = len(pairs)
    ids = strs = b""
    offsets = []
    for msgid, msgstr in pairs:
        offsets.append((len(msgid), len(ids), len(msgstr), len(strs)))
        ids += msgid + b"\0"
        strs += msgstr + b"\0"
    start_ids = 7 * 4 + n * 16
    start_strs = start_ids + len(ids)
    table = b"".join(struct.pack("<2I", l, start_ids + o) for l, o, _, _ in offsets)
    table += b"".join(struct.pack("<2I", l, start_strs + o) for _, _, l, o in offsets)
    header = struct.pack("<7I", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    PO.with_suffix(".mo").write_bytes(header + table + ids + strs)
    return n - 1


def main():
    found = extract()
    existing = read_po()
    write_po(found, existing)
    entries = read_po()
    missing = [k for k, e in entries.items() if not (e.get("msgstr") or e.get("msgstr[0]"))]
    count = compile_mo(entries)
    print(f"{len(found)} chaînes, {count} traduites, {len(missing)} sans traduction.")
    for k in missing[:50]:
        print("  à traduire :", k)
    if "--check" in sys.argv and missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
