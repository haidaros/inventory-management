#!/usr/bin/env python3
"""
Heuristic scanner for Vue 3 single-file components.

Produces an inventory of components plus leads for the vue-component-optimizer
skill: template hotspots, v-for key problems, watchers, unregistered components,
and cross-file duplication (function names, component families, CSS rules).

Everything here is regex-based and intentionally approximate: results are
*leads to verify by reading the code*, not findings. Standard library only.

Usage:
    python3 scan_vue.py <dir-or-file> [--format text|json] [--exclude DIR ...]
"""
import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_EXCLUDES = {"node_modules", "dist", "build", ".nuxt", ".output", "coverage", ".git"}

# Names that are fine to call in templates (i18n, globals, casts) and would
# otherwise drown out the interesting method calls.
TEMPLATE_CALL_IGNORE = {
    "t", "$t", "$tc", "$te", "$d", "$n", "String", "Number", "Boolean", "Math", "JSON",
    "Object", "Array", "Date", "parseInt", "parseFloat", "isNaN", "encodeURIComponent",
    "$emit", "emit", "if", "for", "while", "switch", "return", "typeof", "new",
}
BUILTIN_COMPONENTS = {
    "RouterView", "RouterLink", "Teleport", "Transition", "TransitionGroup", "KeepAlive",
    "Suspense", "Component", "Slot", "Template",
}
JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "else", "do", "try", "with"}

# Top-level SFC blocks start at column 0; nested <template> tags are indented.
BLOCK_RE = re.compile(r"^<(template|script|style)\b([^>]*)>(.*?)^</\1>", re.S | re.M)
# An opening tag with attributes, allowing '>' inside quoted attribute values.
TAG_RE = re.compile(r"<([A-Za-z][\w.-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)/?>", re.S)
ATTR_RE = re.compile(r"([:@#]?[\w.:-]+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'))?")
INTERP_RE = re.compile(r"\{\{(.*?)\}\}", re.S)
CALL_RE = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(")
ARRAY_OP_RE = re.compile(r"\.(filter|map|sort|reduce|slice|find|reverse|concat)\s*\(")
VFOR_RE = re.compile(r"^\s*\(?\s*([\w$]+)\s*(?:,\s*([\w$]+))?\s*(?:,\s*[\w$]+)?\s*\)?\s+(?:in|of)\s+(.+)$")
FUNC_DEF_RES = [
    re.compile(r"^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>", re.M),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", re.M),
    # Options API / object-literal methods: `name(args) {` on its own line
    re.compile(r"^\s{2,}(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", re.M),
]
IMPORT_VUE_RE = re.compile(r"import\s+([A-Za-z_$][\w$]*)\s+from\s+['\"][^'\"]+\.vue['\"]")
CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def line_of(text, offset, base_line):
    return base_line + text.count("\n", 0, offset)


def pascal(name):
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[-_]", name))


def find_blocks(src):
    blocks = defaultdict(list)
    for m in BLOCK_RE.finditer(src):
        start_line = src.count("\n", 0, m.start(3)) + 1
        blocks[m.group(1)].append({"attrs": m.group(2), "body": m.group(3), "line": start_line})
    return blocks


def analyze_template(tpl, base_line):
    res = {"vfor_issues": [], "calls": defaultdict(list), "array_ops": [], "components_used": defaultdict(list)}
    for m in TAG_RE.finditer(tpl):
        tag, attr_text = m.group(1), m.group(2)
        line = line_of(tpl, m.start(), base_line)
        if tag[:1].isupper() or "-" in tag:
            name = pascal(tag)
            if name not in BUILTIN_COMPONENTS:
                res["components_used"][name].append(line)
        attrs = {}
        for a in ATTR_RE.finditer(attr_text):
            attrs[a.group(1)] = (a.group(2) or "")[1:-1]
        vfor = attrs.get("v-for")
        if vfor is not None:
            key = attrs.get(":key", attrs.get("v-bind:key"))
            vm = VFOR_RE.match(vfor)
            index_var = vm.group(2) if vm else None
            if key is None and "key" not in attrs:
                res["vfor_issues"].append({"line": line, "issue": "v-for without :key", "expr": vfor})
            elif key is not None and (key.strip() in {index_var, "index", "i", "idx"} or "Math.random" in key):
                res["vfor_issues"].append({"line": line, "issue": f"unstable key :key=\"{key}\"", "expr": vfor})
            if "v-if" in attrs:
                res["vfor_issues"].append({"line": line, "issue": "v-if on same element as v-for", "expr": vfor})
        # Calls inside bindings and directives (not @event handlers, which run on demand)
        for name, value in attrs.items():
            if name.startswith((":", "v-bind", "v-if", "v-else-if", "v-show", "v-for", "v-html", "v-text")) and value:
                _collect_calls(value, line, res)
    for m in INTERP_RE.finditer(tpl):
        _collect_calls(m.group(1), line_of(tpl, m.start(), base_line), res)
    return res


def _collect_calls(expr, line, res):
    for c in CALL_RE.finditer(expr):
        if c.group(1) not in TEMPLATE_CALL_IGNORE:
            res["calls"][c.group(1)].append(line)
    for a in ARRAY_OP_RE.finditer(expr):
        res["array_ops"].append({"line": line, "op": a.group(1), "expr": " ".join(expr.split())[:100]})


def analyze_script(script, base_line):
    res = {"deep_watchers": [], "watch_count": 0, "computed_count": 0, "ref_count": 0,
           "functions": defaultdict(list), "imported_components": {}}
    for m in re.finditer(r"deep\s*:\s*true", script):
        res["deep_watchers"].append(line_of(script, m.start(), base_line))
    res["watch_count"] = len(re.findall(r"\bwatch(?:Effect)?\s*\(", script)) + len(re.findall(r"^\s*watch\s*:\s*\{", script, re.M))
    res["computed_count"] = len(re.findall(r"\bcomputed\s*\(", script))
    if re.search(r"^\s*computed\s*:\s*\{", script, re.M):
        res["computed_count"] += 1  # Options API block; count is approximate
    res["ref_count"] = len(re.findall(r"\b(?:ref|reactive|shallowRef)\s*\(", script))
    for rx in FUNC_DEF_RES:
        for m in rx.finditer(script):
            name = m.group(1)
            if name not in JS_KEYWORDS and name not in {"setup", "data", "mounted", "created", "onMounted"}:
                res["functions"][name].append(line_of(script, m.start(), base_line))
    for m in IMPORT_VUE_RE.finditer(script):
        res["imported_components"][m.group(1)] = line_of(script, m.start(), base_line)
    return res


def analyze_styles(style_blocks):
    rules = {}  # single-class selector -> normalized declaration hash
    classes = set()
    for blk in style_blocks:
        for m in CSS_RULE_RE.finditer(blk["body"]):
            selector = " ".join(m.group(1).split())
            if selector.startswith("@"):
                continue
            classes.update(re.findall(r"\.([A-Za-z][\w-]*)", selector))
            if re.fullmatch(r"\.[A-Za-z][\w-]*", selector):
                decls = sorted(d.strip() for d in m.group(2).split(";") if d.strip())
                if decls:
                    rules[selector] = hashlib.md5(";".join(decls).encode()).hexdigest()[:10]
    return classes, rules


def api_style(script_blocks):
    if any("setup" in b["attrs"] for b in script_blocks):
        return "script-setup"
    body = "\n".join(b["body"] for b in script_blocks)
    if re.search(r"\bsetup\s*\(", body):
        return "setup()"
    if re.search(r"^\s*(data|methods|computed)\s*[:(]", body, re.M):
        return "options"
    return "none" if not script_blocks else "other"


def scan_file(path, root):
    src = path.read_text(encoding="utf-8", errors="replace")
    blocks = find_blocks(src)
    rel = str(path.relative_to(root)) if path != root else path.name
    info = {"file": rel, "lines": src.count("\n") + 1, "api_style": api_style(blocks["script"]),
            "template_lines": sum(b["body"].count("\n") for b in blocks["template"]),
            "script_lines": sum(b["body"].count("\n") for b in blocks["script"]),
            "style_lines": sum(b["body"].count("\n") for b in blocks["style"])}
    tpl = analyze_template(blocks["template"][0]["body"], blocks["template"][0]["line"]) if blocks["template"] else analyze_template("", 1)
    scr = {"deep_watchers": [], "watch_count": 0, "computed_count": 0, "ref_count": 0,
           "functions": defaultdict(list), "imported_components": {}}
    for b in blocks["script"]:
        part = analyze_script(b["body"], b["line"])
        for k in ("watch_count", "computed_count", "ref_count"):
            scr[k] += part[k]
        scr["deep_watchers"] += part["deep_watchers"]
        scr["imported_components"].update(part["imported_components"])
        for n, ls in part["functions"].items():
            scr["functions"][n] += ls
    classes, rules = analyze_styles(blocks["style"])

    used = tpl["components_used"]
    imported = scr["imported_components"]
    # Globally registered components (main.js app.component) will show up here as
    # false positives; the skill verifies before reporting.
    unregistered = {n: ls for n, ls in used.items() if n not in imported}
    unused_imports = {n: l for n, l in imported.items() if n not in used}

    # Template calls of functions defined in this component are the interesting ones:
    # they re-run on every render (computed would cache).
    local_fns = set(scr["functions"])
    template_calls = {n: ls for n, ls in tpl["calls"].items() if n in local_fns}

    info.update({
        "computed": scr["computed_count"], "refs": scr["ref_count"], "watchers": scr["watch_count"],
        "deep_watchers": scr["deep_watchers"], "vfor_issues": tpl["vfor_issues"],
        "template_method_calls": {n: sorted(set(ls)) for n, ls in sorted(template_calls.items(), key=lambda kv: -len(kv[1]))},
        "template_array_ops": tpl["array_ops"],
        "unregistered_components": unregistered, "unused_component_imports": unused_imports,
        "functions": {n: ls for n, ls in scr["functions"].items()},
        "emits": sorted(set(re.findall(r"""\$?emit\(\s*['"]([\w:-]+)['"]""", src))),
        "css_classes": sorted(classes), "_css_rules": rules,
    })
    return info


def cross_file(files):
    out = {}
    fn_index = defaultdict(list)
    for f in files:
        for name, lines in f["functions"].items():
            fn_index[name].append(f"{f['file']}:{lines[0]}")
    out["duplicate_function_names"] = {n: locs for n, locs in sorted(fn_index.items(), key=lambda kv: -len(kv[1])) if len(locs) >= 2}

    # Families: components sharing a trailing PascalCase word (FooModal, BarModal...)
    fam = defaultdict(list)
    for f in files:
        stem = Path(f["file"]).stem
        words = re.findall(r"[A-Z][a-z0-9]*", stem)
        if len(words) >= 2:
            fam[words[-1]].append(f)
    families = {}
    for suffix, members in fam.items():
        if len(members) < 3:
            continue
        shared_classes = set.intersection(*(set(m["css_classes"]) for m in members))
        shared_emits = set.intersection(*(set(m["emits"]) for m in members))
        families[suffix] = {"members": [m["file"] for m in members],
                            "total_lines": sum(m["lines"] for m in members),
                            "shared_emits": sorted(shared_emits),
                            "css_classes_in_all": sorted(shared_classes)}
    out["component_families"] = families

    # CSS: same single-class selector defined in 3+ files; note how many copies are identical
    sel_index = defaultdict(list)
    for f in files:
        for sel, h in f["_css_rules"].items():
            sel_index[sel].append((f["file"], h))
    css = {}
    for sel, entries in sel_index.items():
        if len(entries) >= 3:
            by_hash = defaultdict(list)
            for file, h in entries:
                by_hash[h].append(file)
            largest = max(by_hash.values(), key=len)
            css[sel] = {"files": len(entries), "identical_copies": len(largest), "variants": len(by_hash)}
    out["repeated_css_rules"] = dict(sorted(css.items(), key=lambda kv: (-kv[1]["identical_copies"], -kv[1]["files"])))
    return out


def render_text(files, xf, root):
    p = print
    p(f"# Vue scan: {root}  ({len(files)} .vue files, {sum(f['lines'] for f in files)} lines)\n")
    p("## Inventory (largest first)")
    p(f"{'file':<48} {'lines':>5} {'tpl':>5} {'js':>5} {'css':>5}  {'api':<12} cmp ref wch")
    for f in sorted(files, key=lambda f: -f["lines"]):
        p(f"{f['file']:<48} {f['lines']:>5} {f['template_lines']:>5} {f['script_lines']:>5} {f['style_lines']:>5}  "
          f"{f['api_style']:<12} {f['computed']:>3} {f['refs']:>3} {f['watchers']:>3}")
    styles = defaultdict(int)
    for f in files:
        styles[f["api_style"]] += 1
    p("API styles: " + ", ".join(f"{k}={v}" for k, v in styles.items()) + "\n")

    p("## Per-file leads")
    for f in sorted(files, key=lambda f: -f["lines"]):
        leads = []
        for v in f["vfor_issues"]:
            leads.append(f"  L{v['line']}: {v['issue']}  (v-for=\"{v['expr']}\")")
        for n, ls in f["template_method_calls"].items():
            leads.append(f"  template calls local function {n}() at L{', L'.join(map(str, ls[:8]))}" + (" ..." if len(ls) > 8 else ""))
        for a in f["template_array_ops"]:
            leads.append(f"  L{a['line']}: .{a['op']}() in template: {a['expr']}")
        for l in f["deep_watchers"]:
            leads.append(f"  L{l}: deep watcher")
        for n, ls in f["unregistered_components"].items():
            leads.append(f"  L{ls[0]}: <{n}> used but not imported in this file (check global registration)")
        for n, l in f["unused_component_imports"].items():
            leads.append(f"  L{l}: component {n} imported but not used in template")
        if leads:
            p(f"### {f['file']}")
            p("\n".join(leads))
    p("")

    p("## Cross-file duplication candidates")
    dups = xf["duplicate_function_names"]
    if dups:
        p("Function names defined in 2+ files (diff bodies before calling it duplication):")
        for n, locs in list(dups.items())[:40]:
            p(f"  {n}  x{len(locs)}: {', '.join(locs)}")
    for suffix, fam in xf["component_families"].items():
        p(f"Component family '*{suffix}' ({len(fam['members'])} files, {fam['total_lines']} lines): {', '.join(Path(m).name for m in fam['members'])}")
        p(f"  emits shared by all: {fam['shared_emits'] or '-'}")
        p(f"  CSS classes in all: {', '.join(fam['css_classes_in_all'][:25]) or '-'}")
    if xf["repeated_css_rules"]:
        p("CSS selectors defined in 3+ files (identical copies / files):")
        for sel, d in list(xf["repeated_css_rules"].items())[:30]:
            p(f"  {sel:<28} {d['identical_copies']}/{d['files']} identical ({d['variants']} variants)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--exclude", nargs="*", default=[])
    args = ap.parse_args()
    root = Path(args.target).resolve()
    excludes = DEFAULT_EXCLUDES | set(args.exclude)
    if root.is_file():
        paths, base = [root], root.parent
    else:
        paths = [p for p in sorted(root.rglob("*.vue")) if not excludes & set(p.relative_to(root).parts)]
        base = root
    if not paths:
        sys.exit(f"No .vue files found under {root}")
    files = [scan_file(p, base) for p in paths]
    xf = cross_file(files)
    if args.format == "json":
        for f in files:
            f.pop("_css_rules", None)
        print(json.dumps({"root": str(root), "files": files, "cross_file": xf}, indent=2))
    else:
        render_text(files, xf, root)


if __name__ == "__main__":
    main()
