"""Hallucination test: closed book vs. with the MCP tools.

Two stages, so the expensive stage runs once and the grading can be tuned
without re-querying:

  python eval/halluc_test.py collect --out answers.jsonl
      Asks the same 33 golden questions twice per question (closed book, then
      with the four tools reachable over MCP function calling) and checkpoints
      every answer. Thinking is on, at the model's maximum reasoning effort:
      that is how the model is used in practice, so it is the only honest
      setting for an answer-quality measurement.

  python eval/halluc_test.py grade --answers answers.jsonl
      Grades the saved answers against NXOpen reflection. Never calls a model.

Requires the model endpoint below plus a built index; the API key is read from
the environment (NXOPEN_MCP_EMBED_API_KEY by default), never from a file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
DEFAULT_BASE = "https://api.siliconflow.cn/v1"
DEFAULT_EFFORT = "max"
DEFAULT_NX = r"D:\UG-NX12"
N_QUESTIONS = 33
MAX_ROUNDS = 24
# thinking puts its reasoning tokens in completion_tokens; a small max_tokens
# truncates the visible answer at finish_reason=length
MAX_TOKENS = 16384

SYSTEM = (
    "You are an NXOpen API assistant for Siemens NX 12. Answer the question by "
    "writing the concrete NXOpen C# or Python (journal) code that does it, and "
    "name the classes/methods you use. Do not use any tool you were not given. "
    "You have a limited tool budget; stop calling tools as soon as you can "
    "answer, and end with the code."
)
TOOL_BUDGET = 16

DOTTED = re.compile(r"\bNXOpen(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
CAMEL = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b")
# anything the answer declares itself: types, variables, methods
DECL = [
    re.compile(r"\b(?:class|struct|enum|interface)\s+([A-Za-z_]\w*)"),
    re.compile(r"\b(?:var|let|const|auto)\s+([A-Za-z_]\w*)"),
    re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*=\s*(?:new\b|[A-Za-z_])"),
    re.compile(r"\b[A-Za-z_][\w<>,\[\]\. ]*\s+([A-Z][A-Za-z0-9_]*)\s*\("),
]
# journal template entry point, not an API claim
BOILERPLATE = {"GetUnloadOption"}
DOTNET = {"Object", "MarshalByRefObject"}


# --------------------------------------------------------------------- collect
def golden_questions(path: Path) -> list[dict]:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    return rows[:N_QUESTIONS]


def chat(model: str, base: str, key: str, messages: list[dict],
         tools: list[dict] | None, effort: str) -> dict:
    body = {"model": model, "messages": messages, "temperature": 0,
            "max_tokens": MAX_TOKENS, "enable_thinking": True,
            "reasoning_effort": effort}
    if tools:
        body["tools"] = tools
    payload = json.dumps(body).encode()
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {key}"}
    last = None
    for attempt in range(5):        # gateways drop connections under load
        try:
            req = urllib.request.Request(f"{base}/chat/completions",
                                         data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read().decode())
        except Exception as exc:
            last = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"chat failed after retries: {last}")


def tokens(d: dict) -> int:
    return (d.get("usage") or {}).get("completion_tokens") or 0


async def collect(args) -> None:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    key = os.environ.get(args.key_env, "")
    if not key:
        sys.exit(f"error: {args.key_env} is not set")
    golden = golden_questions(args.golden)[:args.limit]

    # resume an interrupted run: keep completed rows, skip their questions
    out = []
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    done = {r["query"] for r in out}

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "nxopen_mcp_enhanced.cli", "serve", "--db", str(args.db)],
        env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            specs = [{"type": "function",
                      "function": {"name": t.name,
                                   "description": (t.description or "")[:900],
                                   "parameters": t.inputSchema
                                   or {"type": "object", "properties": {}}}}
                     for t in listed.tools]

            for i, item in enumerate(golden, 1):
                q, exp = item["query"], item["expected"]
                if q in done:
                    print(f"{i:02d}/{len(golden)} {q} | done, skipped", flush=True)
                    continue
                t0 = time.time()
                cb = chat(args.model, args.base, key,
                          [{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": q}], None, args.effort)
                closed = cb["choices"][0]["message"].get("content") or ""
                closed_finish = cb["choices"][0].get("finish_reason")
                closed_tokens = tokens(cb)

                msgs = [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": q}]
                t1 = time.time()
                tools_tokens = 0
                tools_finish = None
                used = 0
                for rnd in range(args.max_rounds):
                    d = chat(args.model, args.base, key, msgs, specs, args.effort)
                    tools_tokens += tokens(d)
                    tools_finish = d["choices"][0].get("finish_reason")
                    msg = d["choices"][0]["message"]
                    calls = msg.get("tool_calls") or []
                    if args.debug:
                        print(f"    round {rnd + 1}: {tools_finish} "
                              f"{tokens(d)}t {len(calls)} calls, reasoning "
                              f"{len(msg.get('reasoning_content') or '')} chars",
                              flush=True)
                    msgs.append({"role": "assistant", "content": msg.get("content") or "",
                                 **({"tool_calls": calls} if calls else {})})
                    if not calls:
                        break
                    for c in calls:
                        if used >= args.tool_budget:
                            msgs.append({"role": "tool", "tool_call_id": c["id"],
                                         "content": "tool budget exhausted"})
                            continue
                        used += 1
                        try:
                            a = json.loads(c["function"].get("arguments") or "{}")
                        except json.JSONDecodeError:
                            a = {}
                        if args.debug:
                            print(f"      call {c['function']['name']} "
                                  f"{(c['function'].get('arguments') or '')[:160]}",
                                  flush=True)
                        try:
                            res = await session.call_tool(c["function"]["name"], a)
                            text = "\n".join(getattr(x, "text", "") or ""
                                             for x in res.content)[:6000]
                        except Exception as exc:
                            text = f"tool error: {exc}"
                        if args.debug:
                            print("      -> " + text[:160].replace("\n", " "),
                                  flush=True)
                        msgs.append({"role": "tool", "tool_call_id": c["id"],
                                     "content": text})
                    if used >= args.tool_budget:
                        break
                # ending on tool results means the model never wrote the
                # answer; ask once more with tools withheld
                forced = False
                if msgs[-1]["role"] != "assistant" or not msgs[-1].get("content"):
                    forced = True
                    msgs.append({"role": "user", "content":
                                 "Stop calling tools. Write the final answer "
                                 "now with the API names you have verified."})
                    d = chat(args.model, args.base, key, msgs, None, args.effort)
                    tools_tokens += tokens(d)
                    tools_finish = d["choices"][0].get("finish_reason")
                    final = d["choices"][0]["message"].get("content") or ""
                    msgs.append({"role": "assistant", "content": final})
                with_tools = next((m["content"] for m in reversed(msgs)
                                   if m["role"] == "assistant" and m["content"]), "")

                out.append({"query": q, "expected": exp,
                            "closed": closed, "tools": with_tools,
                            "closed_finish": closed_finish,
                            "tools_finish": tools_finish,
                            "tool_calls_used": used, "forced_final": forced,
                            "closed_tokens": closed_tokens,
                            "tools_tokens": tools_tokens,
                            "closed_s": round(t1 - t0, 1),
                            "tools_s": round(time.time() - t1, 1)})
                args.out.write_text(
                    "\n".join(json.dumps(r, ensure_ascii=False) for r in out),
                    encoding="utf-8")
                print(f"{i:02d}/{len(golden)} {q} | closed {closed_finish} "
                      f"{closed_tokens}t {t1-t0:.0f}s | tools {tools_finish} "
                      f"{tools_tokens}t {used} calls forced={forced} "
                      f"{time.time()-t1:.0f}s", flush=True)


# ------------------------------------------------------------------------ grade
def build_oracle(nx_root: Path):
    """Reflection over the NXOpen assemblies; the DLL is the API surface.

    The XML-doc index is not a valid oracle: it omits real members such as
    NXOpen.Session.GetSession.
    """
    import clr

    base = nx_root / "NXBIN" / "managed"
    dlls = ["NXOpen.dll", "NXOpen.Utilities.dll", "NXOpen.UF.dll",
            "NXOpen.Guide.dll", "NXOpenUI.dll"]
    for d in dlls:
        if (base / d).exists():
            clr.AddReference(str(base / d))
    from System.Reflection import Assembly, BindingFlags

    flags_all = BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static

    def ret_name(t):
        try:
            return (t.FullName or str(t)).replace("+", ".")
        except Exception:
            return None

    types: dict[str, dict[str, str | None]] = {}

    def index_type(t, alias=None):
        name = alias or (t.FullName or "")
        if not name or name in types:
            return
        members: dict[str, str | None] = {}
        try:
            for m in t.GetMembers(flags_all | BindingFlags.FlattenHierarchy):
                n = m.Name
                members.setdefault(n[4:] if n[:4] in ("get_", "set_") else n, None)
        except Exception:
            pass
        try:        # GetMembers omits enum values; they are static fields
            for f in t.GetFields(flags_all | BindingFlags.FlattenHierarchy):
                members.setdefault(f.Name, None)
        except Exception:
            pass
        try:        # property return types enable chain resolution
            for p in t.GetProperties(flags_all | BindingFlags.FlattenHierarchy):
                members[p.Name] = ret_name(p.PropertyType)
        except Exception:
            pass
        types[name] = members
        try:
            for nt in t.GetNestedTypes(BindingFlags.Public):
                # .NET spells nested types with '+', source code uses '.'
                parent = alias if alias is not None else (t.FullName or "")
                index_type(nt, f"{parent}.{nt.Name}")
        except Exception:
            pass

    for d in dlls:
        p = base / d
        if not p.exists():
            continue
        asm = Assembly.LoadFrom(str(p))
        try:
            all_types = list(asm.GetTypes())
        except Exception:
            all_types = []
        for t in all_types:
            index_type(t, (t.FullName or "").replace("+", "."))

    def is_real_dotted(name: str) -> bool:
        """Accept type names, type.member, and chains through properties.

        Only intermediate segments must name a type; the last segment may be a
        method, field, property or enum value.
        """
        if name in types:
            return True
        parts = name.split(".")
        for cut in range(len(parts) - 1, 0, -1):
            cur = ".".join(parts[:cut])
            if cur not in types:
                continue
            segs = parts[cut:]
            for i, seg in enumerate(segs):
                members = types.get(cur, {})
                if seg not in members:
                    return False
                if i == len(segs) - 1:
                    return True
                nxt = members[seg]
                if nxt is None:     # method/field cannot be walked into
                    return False
                cur = nxt
            return True
        return False

    def is_namespace(name: str) -> bool:
        return name not in types and any(f.startswith(name + ".") for f in types)

    return types, is_real_dotted, is_namespace


def calibrate(types, is_real_dotted) -> None:
    member_names = {m for members in types.values() for m in members}
    type_short = {f.rsplit(".", 1)[-1] for f in types}

    def resolves(n: str) -> bool:
        return is_real_dotted(n) if n.startswith("NXOpen") else (
            n in member_names or n in type_short)

    real = ["NXOpen.Session.GetSession", "NXOpen.Builder.Commit",
            "NXOpen.PartCollection.Open", "NXOpen.Session.Parts",
            "NXOpen.CAM.CavityMillingBuilder.BlankGeometry",
            "NXOpen.CAM.OperationCollection.CreateCavityMillingBuilder",
            "NXOpen.CAM.CavityMillingBuilder", "NXOpen.NXObject.AttributeType",
            "NXOpen.Session.UndoMarkId", "NXOpen.CAM.CAMSetup.Postprocess",
            "NXOpen.Session.Parts.Work.CAMSetup",     # property chain
            "NXOpen.CAM.CutLevel.Types.Constant",     # enum value
            "NXOpen.TaggedObject", "NXOpen.Utilities.NXRemotableObject"]
    fake = ["NXOpen.CAM.MillGeometryBuilder", "NXOpen.Session.GetUnloadOption",
            "CreateCavityMilling", "NXOpen.CAM.CavityMillingBuilder.CommitAndDestroy",
            "NXOpen.CAM.CutMethod", "NXOpen.CAM.NonexistentBuilder",
            "NXOpen.CAM.CutLevel.Types.NonexistentValue"]
    bad = [n for n in real if not resolves(n)] + [n for n in fake if resolves(n)]
    if bad:
        sys.exit("oracle failed calibration: " + ", ".join(bad))


def grade(args) -> None:
    types, is_real_dotted, is_namespace = build_oracle(Path(args.nx_path))
    calibrate(types, is_real_dotted)
    member_names = {m for members in types.values() for m in members}
    type_short = {f.rsplit(".", 1)[-1] for f in types}
    print("types:", len(types), "member names:", len(member_names))

    def check(n: str) -> bool:
        if n in DOTNET or n in BOILERPLATE:
            return True
        if n.startswith("NXOpen"):
            return is_real_dotted(n)
        return n in member_names or n in type_short

    def declared(t: str) -> set[str]:
        out = set()
        for rx in DECL:
            out |= set(rx.findall(t))
        return out

    def claims(t: str) -> set[str]:
        d = declared(t)
        out = set(DOTTED.findall(t))
        for n in CAMEL.findall(t):
            if n in d or len(re.findall(r"[A-Z]", n)) < 3:
                continue
            out.add(n)
        return {n for n in out if not is_namespace(n)}

    rows = [json.loads(l) for l in
            Path(args.answers).read_text(encoding="utf-8").splitlines() if l.strip()]
    for cond in ("closed", "tools"):
        fin = {}
        for r in rows:
            f = r.get(f"{cond}_finish")
            if f:
                fin[f] = fin.get(f, 0) + 1
        if fin:
            print(f"{cond} finish_reason:", fin)
    res = {}
    for cond in ("closed", "tools"):
        proposed = invented = zero = named = clean = 0
        spent = 0.0
        spent_tokens = 0
        for r in rows:
            cs = claims(r[cond])
            fake = [n for n in cs if not check(n)]
            proposed += len(cs)
            invented += len(fake)
            zero += not fake
            short = r["expected"].rsplit(".", 1)[-1]
            if r["expected"] in r[cond] or short in r[cond]:
                named += 1
                clean += not fake
            spent += r[f"{cond}_s"]
            spent_tokens += r.get(f"{cond}_tokens", 0)
        n = len(rows)
        res[cond] = dict(proposed=proposed, invented=invented,
                         invented_rate=round(invented / max(proposed, 1), 4),
                         answers_no_invention=zero,
                         expected_api_named=named, named_without_invention=clean,
                         n=n, total_s=round(spent, 1),
                         total_tokens=spent_tokens)
        print(f"{cond}: proposed {proposed}, invented {invented} "
              f"({res[cond]['invented_rate']:.1%}), answers with no invented name "
              f"{zero}/{n}, expected API named {named}/{n}, "
              f"named without invention {clean}/{n}, {res[cond]['total_s']}s")
    if rows:
        print("\nmodel:", args.model, "| queries:", len(rows))
    Path(args.out_json).write_text(json.dumps(res, indent=1),
                                   encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="ask the questions, save answers")
    c.add_argument("--golden", type=Path,
                   default=Path(__file__).parent / "golden.jsonl")
    c.add_argument("--db", type=Path,
                   default=Path.home() / ".nxopen-mcp-enhanced" / "index.db")
    c.add_argument("--out", type=Path, default=Path("answers.jsonl"))
    c.add_argument("--model", default=DEFAULT_MODEL)
    c.add_argument("--base", default=DEFAULT_BASE)
    c.add_argument("--effort", default=DEFAULT_EFFORT,
                   help="reasoning_effort sent to the model (default: max)")
    c.add_argument("--limit", type=int, default=N_QUESTIONS,
                   help="number of golden questions to ask (smoke runs)")
    c.add_argument("--max-rounds", type=int, default=MAX_ROUNDS)
    c.add_argument("--tool-budget", type=int, default=TOOL_BUDGET,
                   help="max tool calls per question before a forced final answer")
    c.add_argument("--debug", action="store_true")
    c.add_argument("--key-env", default="NXOPEN_MCP_EMBED_API_KEY")

    g = sub.add_parser("grade", help="grade saved answers against NXOpen reflection")
    g.add_argument("--answers", type=Path, default=Path("answers.jsonl"))
    g.add_argument("--nx-path", default=os.environ.get("NX_HOME", DEFAULT_NX))
    g.add_argument("--out-json", default="halluc_metrics.json")
    g.add_argument("--model", default=DEFAULT_MODEL)

    args = ap.parse_args()
    if args.cmd == "collect":
        import asyncio
        asyncio.run(collect(args))
    else:
        grade(args)


if __name__ == "__main__":
    main()