#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cérebro: segundo cérebro em Obsidian integrado ao Claude Code e ao Codex.

Comandos:
  recall "texto" [--cwd DIR] [--n 5]     busca notas relacionadas
  registrar --arquivo F.json | --stdin   grava aprendizados da execução
  processar-inbox                        ingere JSONs pendentes em _Sistema/inbox
  semear DIR...                          cria notas de projeto (detecta stack)
  reindex                                regenera o Painel
  hook-session | hook-prompt | hook-stop [--agente claude|codex]
"""
import sys, os, re, json, math, time, argparse, unicodedata
from datetime import datetime
from pathlib import Path
from collections import Counter

for s in (sys.stdout, sys.stderr, sys.stdin):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPT = Path(__file__).resolve()
SYS = SCRIPT.parent
VAULT = SYS.parent
INBOX = SYS / "inbox"
STATE = SYS / ".estado"
DIRS = {
    "projeto": "01-Projetos", "decisao": "02-Decisoes", "padrao": "03-Padroes",
    "preferencia": "04-Preferencias", "stack": "05-Stack",
    "aprendizado": "06-Aprendizados", "sessao": "07-Sessoes",
}
PESO_TIPO = {"projeto": 1.0, "decisao": 1.2, "padrao": 1.2, "preferencia": 1.3,
             "stack": 0.8, "aprendizado": 1.2, "sessao": 0.7}
PERFIL = VAULT / DIRS["preferencia"] / "Perfil do Usuario.md"
AUTO_I, AUTO_F = "<!-- CEREBRO:AUTO -->", "<!-- /CEREBRO:AUTO -->"

STOPWORDS = set("""a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sob sobre e ou mas que se
como mais menos muito pouco isso este esta esse essa isto aquilo ele ela eles elas eu voce vc nos meu minha seu sua nosso
ja nao sim tem ter ser estar foi sao era fazer faz fazendo quero preciso pode podemos vamos favor criar adicionar arquivo
codigo agora quando onde qual quais tambem ainda entao the an of to in on for with and or but is are be was were this that
these those it its i you we my your our do does make need want please can could should would from at by as if then so not
no yes add create file code ao aos pela pelo pelas pelos ate depois antes vez todo toda todos todas mesmo outro outra""".split())


# ---------- utilidades ----------
def norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def stem(t):
    t = norm(t)
    if len(t) > 4 and t.endswith("s"):
        t = t[:-1]
    return t[:6]


def tokens(texto):
    out = []
    for t in re.findall(r"[a-zA-ZÀ-ÿ0-9\.\+#]+", str(texto)):
        t = norm(t).strip(".+#")
        if len(t) >= 3 and t not in STOPWORDS:
            out.append(stem(t))
    return out


def clean(s, n=80):
    s = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", str(s))
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:n].strip(" .") or "Sem titulo"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-") or "geral"


def uma_linha(s, n=300):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:n]


def listify(x):
    if x is None or x == "":
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def fwd(p):
    return str(p).replace("\\", "/")


def log(msg):
    try:
        with open(SYS / "log.txt", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


# ---------- frontmatter ----------
def parse_val(v):
    v = v.strip()
    if v.startswith("[") or v.startswith('"'):
        try:
            return json.loads(v)
        except Exception:
            if v.startswith("["):
                return [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
    return v.strip("\"'")


def ler_nota(path):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}, ""
    fm, body = {}, text
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?(.*)", text, re.S)
    if m:
        chave = None
        for line in m.group(1).splitlines():
            item = line.strip()
            # lista YAML em várias linhas ("tags:" e depois "  - x"), como o Obsidian grava
            if item.startswith("- ") and chave is not None and isinstance(fm.get(chave), list):
                fm[chave].append(parse_val(item[2:]))
                continue
            if line[:1] in (" ", "\t", "-", "#"):
                continue
            k, sep, v = line.partition(":")
            if sep and k.strip():
                chave = k.strip()
                fm[chave] = [] if not v.strip() else parse_val(v)
        body = m.group(2)
    return fm, body


def fm_dump(fm):
    out = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            out.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        elif isinstance(v, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", v):
            out.append(f"{k}: {v}")
        else:
            out.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    out.append("---")
    return "\n".join(out) + "\n"


def escrever_nota(path, fm, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fm_dump(fm) + "\n" + body.lstrip("\n"), encoding="utf-8", newline="\n")


def atualizar_fm(path, **mudancas):
    fm, body = ler_nota(path)
    for k, v in mudancas.items():
        if isinstance(v, list):
            atual = listify(fm.get(k))
            for x in v:
                if x not in atual:
                    atual.append(x)
            fm[k] = atual
        else:
            fm[k] = v
    escrever_nota(path, fm, body)


def append_under(path, heading, line, dedupe=True):
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if dedupe and line in text:
        return
    lines = text.split("\n")
    head = f"## {heading}"
    for i, l in enumerate(lines):
        if l.strip() == head:
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            k = j
            while k > i + 1 and lines[k - 1].strip() == "":
                k -= 1
            lines.insert(k, line)
            if k == j or j >= len(lines) or True:
                pass
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [head, "", line]
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8", newline="\n")


def tags_de(tipo, proj, extras=()):
    t = [tipo, f"projeto/{slug(proj)}"] if proj else [tipo]
    for x in listify(extras):
        x = slug(x)
        if x and x not in t:
            t.append(x)
    return t


# ---------- projeto / stack ----------
PKG_MAP = {
    "next": "Next.js", "react": "React", "vue": "Vue", "svelte": "Svelte", "@angular/core": "Angular",
    "express": "Express", "fastify": "Fastify", "@nestjs/core": "NestJS", "tailwindcss": "Tailwind CSS",
    "typescript": "TypeScript", "vite": "Vite", "prisma": "Prisma", "@prisma/client": "Prisma",
    "drizzle-orm": "Drizzle", "mongoose": "MongoDB", "pg": "PostgreSQL", "electron": "Electron",
    "react-native": "React Native", "expo": "Expo", "three": "Three.js", "@supabase/supabase-js": "Supabase",
    "firebase": "Firebase", "zod": "Zod", "astro": "Astro", "nuxt": "Nuxt", "playwright": "Playwright",
    "puppeteer": "Puppeteer", "jest": "Jest", "vitest": "Vitest", "framer-motion": "Framer Motion",
    "motion": "Motion", "gsap": "GSAP", "@trpc/server": "tRPC", "socket.io": "Socket.IO", "discord.js": "Discord.js",
}
PY_MAP = ["django", "flask", "fastapi", "pandas", "numpy", "torch", "tensorflow", "selenium", "playwright",
          "streamlit", "pytest", "requests", "beautifulsoup4", "scrapy", "discord", "telegram", "openai", "anthropic"]
FILE_MAP = {"go.mod": "Go", "Cargo.toml": "Rust", "composer.json": "PHP", "pubspec.yaml": "Flutter",
            "pom.xml": "Java", "build.gradle": "Java", "Gemfile": "Ruby", "Dockerfile": "Docker",
            "docker-compose.yml": "Docker Compose", "Package.swift": "Swift", "tsconfig.json": "TypeScript"}


def detectar_stack(root):
    root = Path(root)
    stack, desc = [], ""

    def add(x):
        if x not in stack:
            stack.append(x)
    try:
        pj = root / "package.json"
        if pj.exists():
            add("Node.js")
            d = json.loads(pj.read_text(encoding="utf-8", errors="replace"))
            desc = d.get("description", "") or ""
            deps = {**d.get("dependencies", {}), **d.get("devDependencies", {})}
            for k, v in PKG_MAP.items():
                if k in deps:
                    add(v)
        for f in ("requirements.txt", "pyproject.toml", "Pipfile", "setup.py"):
            p = root / f
            if p.exists():
                add("Python")
                t = norm(p.read_text(encoding="utf-8", errors="replace"))
                for k in PY_MAP:
                    if re.search(r"(^|[^a-z])" + k + r"([^a-z]|$)", t):
                        add(k.capitalize() if k not in ("fastapi",) else "FastAPI")
        for f, v in FILE_MAP.items():
            if (root / f).exists():
                add(v)
        if any(root.glob("*.py")):
            add("Python")
        if any(root.glob("*.csproj")) or any(root.glob("*.sln")):
            add(".NET")
        if not stack and (root / "index.html").exists():
            add("HTML/CSS/JS")
        if not desc:
            for rd in ("README.md", "readme.md", "README"):
                p = root / rd
                if p.exists():
                    for l in p.read_text(encoding="utf-8", errors="replace").splitlines():
                        l = l.strip()
                        if l and not l.startswith(("#", "!", "[", "<", "-", "`", ">")):
                            desc = l
                            break
                    break
    except Exception:
        pass
    return stack, uma_linha(desc, 240)


def raiz_do_projeto(cwd):
    p = Path(cwd or ".").resolve()
    home = Path.home().resolve()
    for q in [p, *p.parents]:
        if q == home or q == q.parent:
            break
        if (q / ".git").exists():
            return q
    return p


def nome_do_projeto(cwd):
    root = raiz_do_projeto(cwd)
    home = Path.home().resolve()
    if root in (home, home / "Desktop", home / "Documents") or root == root.parent:
        return "Geral", root
    if VAULT in (root, *root.parents):
        return "Celebro", VAULT
    return clean(root.name), root


def ensure_stack(nome, proj, nota=""):
    nome = clean(nome, 60)
    path = VAULT / DIRS["stack"] / f"{nome}.md"
    data = f"{datetime.now():%Y-%m-%d}"
    if not path.exists():
        escrever_nota(path, {"tipo": "stack", "data": data, "tags": ["stack", slug(nome)],
                             "resumo": f"Onde e como {nome} foi usado nos meus projetos"},
                      f"# {nome}\n\n## Usado em\n")
    linha = f"- [[{proj}]]" + (f" ({data}) — {uma_linha(nota, 200)}" if nota else "")
    texto = path.read_text(encoding="utf-8")
    if nota or f"[[{proj}]]" not in texto:
        append_under(path, "Usado em", linha)
    return nome


def ensure_projeto(nome, root=None, scan=False):
    nome = clean(nome, 60)
    path = VAULT / DIRS["projeto"] / f"{nome}.md"
    data = f"{datetime.now():%Y-%m-%d}"
    stack, desc = (detectar_stack(root) if (root and scan) else ([], ""))
    if not path.exists():
        escrever_nota(path, {
            "tipo": "projeto", "caminho": [fwd(root)] if root else [], "stack": stack,
            "criado": data, "atualizado": data, "tags": tags_de("projeto", nome),
            "resumo": desc or f"Projeto {nome}"},
            f"# {nome}\n\n## Resumo\n\n{desc or '(descrição será enriquecida automaticamente)'}\n\n## Stack\n\n## Histórico\n")
    else:
        mud = {"atualizado": data}
        if root:
            mud["caminho"] = [fwd(root)]
        if stack:
            mud["stack"] = stack
        atualizar_fm(path, **mud)
    for s in stack:
        ensure_stack(s, nome)
        append_under(path, "Stack", f"- [[{s}]]")
    return path


# ---------- registro ----------
def normaliza_item(item):
    if isinstance(item, dict):
        d = dict(item)
        t = d.pop("titulo", None) or d.pop("title", None) or d.pop("nome", None) or ""
        desc = d.pop("descricao", None) or d.pop("description", None) or d.pop("texto", None) or ""
        if not t and desc:
            t = re.split(r"[.:—]", desc)[0]
        return {"titulo": clean(t, 80), "descricao": str(desc).strip(), "extra": d}
    s = str(item).strip()
    m = re.match(r"^(.{3,70}?):\s+(.+)$", s, re.S)
    if m:
        return {"titulo": clean(m.group(1), 80), "descricao": m.group(2).strip(), "extra": {}}
    return {"titulo": clean(re.split(r"[.—]", s)[0], 80), "descricao": s, "extra": {}}


def nota_atomica(tipo, item, proj, sess, extras_tags):
    it = normaliza_item(item)
    nome = clean(f"{proj} - {it['titulo']}") if tipo == "decisao" else clean(it["titulo"])
    path = VAULT / DIRS[tipo] / f"{nome}.md"
    data = f"{datetime.now():%Y-%m-%d}"
    curto = uma_linha(it["descricao"] or it["titulo"], 160)
    ocorr = f"- {data} · [[{proj}]] · [[{sess}]]" + (f" — {curto}" if path.exists() else "")
    if path.exists():
        atualizar_fm(path, projetos=[f"[[{proj}]]"], atualizado=data, tags=tags_de(tipo, proj, extras_tags))
        append_under(path, "Ocorrências", ocorr)
        if it["descricao"] and it["descricao"] not in path.read_text(encoding="utf-8"):
            append_under(path, "Atualizações", f"- {data} ({proj}): {uma_linha(it['descricao'], 400)}")
    else:
        corpo = f"# {it['titulo']}\n\n{it['descricao']}\n"
        for k, v in it["extra"].items():
            if v:
                corpo += f"\n**{str(k).capitalize()}:** {v}\n"
        corpo += f"\n## Ocorrências\n\n{ocorr}\n"
        escrever_nota(path, {
            "tipo": tipo, "projetos": [f"[[{proj}]]"], "data": data, "atualizado": data,
            "tags": tags_de(tipo, proj, extras_tags), "resumo": uma_linha(it["descricao"] or it["titulo"])}, corpo)
    return nome


def registrar(d):
    agora = datetime.now()
    data, hora = f"{agora:%Y-%m-%d}", f"{agora:%H:%M}"
    cwd = d.get("cwd") or os.getcwd()
    if d.get("projeto"):
        proj, root = clean(d["projeto"], 60), (raiz_do_projeto(cwd) if d.get("cwd") else None)
    else:
        proj, root = nome_do_projeto(cwd)
    ensure_projeto(proj, root)
    titulo = clean(d.get("titulo") or "Sessão", 70)
    sess = f"{data} {agora:%H%M} - {titulo}"
    extras = listify(d.get("tags"))
    links = {k: [] for k in ("decisao", "padrao", "preferencia", "aprendizado")}
    for chave, tipo in (("decisoes", "decisao"), ("padroes", "padrao"),
                        ("preferencias", "preferencia"), ("aprendizados", "aprendizado")):
        for item in listify(d.get(chave)):
            if item:
                links[tipo].append(nota_atomica(tipo, item, proj, sess, extras))
    techs = []
    for item in listify(d.get("stack")):
        if not item:
            continue
        it = normaliza_item(item)
        techs.append(ensure_stack(it["titulo"], proj, it["descricao"]))
        append_under(VAULT / DIRS["projeto"] / f"{proj}.md", "Stack", f"- [[{techs[-1]}]]")
    corpo = f"# {titulo}\n\n**Projeto:** [[{proj}]] · **Agente:** {d.get('agente', 'desconhecido')} · {data} {hora}\n\n"
    corpo += f"## Resumo\n\n{str(d.get('resumo', '')).strip()}\n"
    arqs = [str(a) for a in listify(d.get("arquivos"))]
    if arqs:
        corpo += "\n## Arquivos\n\n" + "\n".join(f"- `{a}`" for a in arqs[:40]) + "\n"
    for tit, tipo in (("Decisões", "decisao"), ("Padrões", "padrao"), ("Preferências", "preferencia"),
                      ("Aprendizados", "aprendizado")):
        if links[tipo]:
            corpo += f"\n## {tit}\n\n" + "\n".join(f"- [[{n}]]" for n in links[tipo]) + "\n"
    if techs:
        corpo += "\n## Stack\n\n" + "\n".join(f"- [[{n}]]" for n in techs) + "\n"
    escrever_nota(VAULT / DIRS["sessao"] / f"{sess}.md", {
        "tipo": "sessao", "projeto": f"[[{proj}]]", "agente": d.get("agente", "desconhecido"),
        "data": data, "hora": hora, "tags": tags_de("sessao", proj, extras),
        "resumo": uma_linha(d.get("resumo") or titulo)}, corpo)
    append_under(VAULT / DIRS["projeto"] / f"{proj}.md", "Histórico",
                 f"- {data} [[{sess}]] — {uma_linha(d.get('resumo') or titulo, 140)}")
    reindex()
    log(f"registrado: {sess} ({proj})")
    return sess


def processar_inbox():
    n = 0
    INBOX.mkdir(exist_ok=True)
    for f in sorted(INBOX.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
            for item in (d if isinstance(d, list) else [d]):
                registrar(item)
                n += 1
            f.unlink()
        except Exception as e:
            log(f"erro inbox {f.name}: {e}")
            (INBOX / "erro").mkdir(exist_ok=True)
            try:
                f.replace(INBOX / "erro" / f.name)
            except Exception:
                pass
    return n


# ---------- painel ----------
def todas_as_notas():
    notas = []
    for tipo, d in DIRS.items():
        for p in (VAULT / d).glob("*.md"):
            fm, body = ler_nota(p)
            notas.append({"tipo": tipo, "path": p, "titulo": p.stem, "fm": fm, "body": body})
    return notas


def reindex():
    notas = todas_as_notas()
    cont = Counter(n["tipo"] for n in notas)
    nomes = {"projeto": "Projetos", "decisao": "Decisões", "padrao": "Padrões", "preferencia": "Preferências",
             "stack": "Stack", "aprendizado": "Aprendizados", "sessao": "Sessões"}
    L = [AUTO_I, "", f"_Atualizado automaticamente em {datetime.now():%Y-%m-%d %H:%M}_", "",
         "| Tipo | Notas |", "|---|---|"]
    L += [f"| {nomes[t]} | {cont.get(t, 0)} |" for t in DIRS]

    def bloco(titulo, tipo, lim=None, chave=lambda n: n["titulo"].lower(), rev=False):
        sel = sorted([n for n in notas if n["tipo"] == tipo], key=chave, reverse=rev)[:lim]
        L.extend(["", f"## {titulo}", ""])
        L.extend([f"- [[{n['titulo']}]]" for n in sel] or ["- _(vazio)_"])
    bloco("🔵 Projetos", "projeto")
    bloco("🕘 Últimas sessões", "sessao", 15, rev=True)
    bloco("🩷 Preferências", "preferencia")
    bloco("🟢 Padrões", "padrao", 30, key_atual(), True)
    bloco("🟠 Decisões recentes", "decisao", 20, key_atual(), True)
    bloco("🩵 Aprendizados recentes", "aprendizado", 20, key_atual(), True)
    bloco("🟣 Stack", "stack")
    L += ["", AUTO_F]
    auto = "\n".join(L)
    painel = VAULT / "Painel.md"
    if painel.exists():
        t = painel.read_text(encoding="utf-8")
        if AUTO_I in t and AUTO_F in t:
            novo = t[:t.index(AUTO_I)] + auto + t[t.index(AUTO_F) + len(AUTO_F):]
        else:
            novo = t.rstrip() + "\n\n" + auto + "\n"
    else:
        novo = PAINEL_CABECALHO + "\n" + auto + "\n"
    painel.write_text(novo, encoding="utf-8", newline="\n")


def key_atual():
    return lambda n: str(n["fm"].get("atualizado") or n["fm"].get("data") or "")


PAINEL_CABECALHO = """---
tipo: painel
tags: ["painel"]
---
# 🧠 Cérebro

Segundo cérebro **100% automático**: o agente (Claude Code / Codex) consulta este cofre antes de cada tarefa e registra o aprendizado depois de cada entrega, em qualquer projeto.

> [!info] Cores
> 🔵 Projetos · 🟠 Decisões · 🟢 Padrões · 🩷 Preferências · 🟣 Stack · 🩵 Aprendizados · ⚪ Sessões

Veja [[LEIA-ME]] para entender o funcionamento. O bloco abaixo é gerado automaticamente — não edite entre os marcadores.
"""


# ---------- recall ----------
def indexar(n):
    fm = n["fm"]
    T = set(tokens(n["titulo"]))
    G = set()
    for t in listify(fm.get("tags")) + listify(fm.get("stack")):
        G |= set(tokens(re.sub(r"[/_\-]", " ", str(t))))
    for t in listify(fm.get("projetos")) + listify(fm.get("projeto")):
        G |= set(tokens(re.sub(r"[\[\]]", "", str(t))))
    R = set(tokens(fm.get("resumo", "")))
    B = Counter(tokens(n["body"][:5000]))
    n["_i"] = (T, G, R, B)


def recall(texto, cwd=None, n=5, excluir=()):
    proj = nome_do_projeto(cwd)[0] if cwd else ""
    Q = list(dict.fromkeys(tokens(texto)))
    if not Q:
        return []
    notas = todas_as_notas()
    for x in notas:
        indexar(x)
    N = len(notas) or 1
    df = Counter()
    for x in notas:
        T, G, R, B = x["_i"]
        for q in set(T | G | R | set(B)):
            df[q] += 1
    res = []
    for x in notas:
        if x["tipo"] == "projeto" and norm(x["titulo"]) == norm(proj):
            continue
        T, G, R, B = x["_i"]
        score, hit, forte = 0.0, 0, 0
        for q in Q:
            w = 5 * (q in T) + 4 * (q in G) + 3 * (q in R) + min(B.get(q, 0), 3) * 0.7
            if w:
                hit += 1
                forte = max(forte, 5 * (q in T) + 4 * (q in G))
                score += math.log(1 + N / (1 + df[q])) * w
        score *= PESO_TIPO[x["tipo"]]
        pj = " ".join(listify(x["fm"].get("projetos")) + listify(x["fm"].get("projeto")))
        if proj and f"[[{proj}]]" in pj:
            score *= 1.15
        if (hit >= min(2, len(Q)) and score >= 4 or forte and score >= 5) and str(x["path"]) not in excluir:
            res.append((score, x))
    res.sort(key=lambda t: -t[0])
    if not res:
        return []
    top = res[0][0]
    return [x for s, x in res if s >= 0.3 * top][:n]


def trecho(n, lim=600):
    if n.get("tipo") == "stack":
        return "Usado em: " + (", ".join(dict.fromkeys(re.findall(r"\[\[([^\]]+)\]\]", n["body"]))) or "—")
    if n.get("tipo") in ("sessao", "projeto") and n["fm"].get("resumo"):
        return uma_linha(n["fm"]["resumo"], lim)
    b = re.split(r"\n## ", n["body"], 1)[0]
    b = re.sub(r"^# .*\n", "", b.strip())
    return uma_linha(b, lim) or str(n["fm"].get("resumo", ""))


def formatar_recall(res, completo=3):
    L = ["🧠 CÉREBRO — notas relacionadas à tarefa (registradas em qualquer projeto). "
         "Considere-as antes de agir; use Read no caminho para ver a nota inteira. Não mencione esta busca ao usuário a menos que seja relevante."]
    for i, n in enumerate(res, 1):
        proj = ", ".join(re.sub(r"[\[\]]", "", str(p)) for p in
                         (listify(n["fm"].get("projetos")) + listify(n["fm"].get("projeto")))) or "—"
        L.append(f"{i}. [{n['tipo']}] {n['titulo']} · projeto(s): {proj} · {fwd(n['path'])}")
        L.append(f"   {trecho(n, 500 if i <= completo else 160)}")
    return "\n".join(L)[:6000]


# ---------- estado por sessão ----------
def estado(sid):
    STATE.mkdir(exist_ok=True)
    return STATE / (re.sub(r"[^A-Za-z0-9_-]", "_", sid or "semsessao")[:60] + ".json")


def ler_estado(sid):
    try:
        return json.loads(estado(sid).read_text(encoding="utf-8"))
    except Exception:
        return {}


def gravar_estado(sid, d):
    try:
        estado(sid).write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def limpar_estado():
    try:
        for f in STATE.glob("*.json"):
            if time.time() - f.stat().st_mtime > 7 * 86400:
                f.unlink()
    except Exception:
        pass


def ler_stdin_json():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


# ---------- hooks ----------
def hook_session(agente):
    d = ler_stdin_json()
    cwd = d.get("cwd") or os.getcwd()
    processar_inbox()
    limpar_estado()
    proj, root = nome_do_projeto(cwd)
    pnota = ensure_projeto(proj, root, scan=True)
    reindex()
    L = [f"🧠 CÉREBRO ATIVO (segundo cérebro Obsidian: {fwd(VAULT)}). Projeto atual: {proj}.",
         "Funcionamento 100% automático: a cada prompt, notas relacionadas de TODOS os projetos são injetadas no contexto; "
         "ao concluir uma entrega, o hook Stop pedirá o registro dos aprendizados — execute-o sem perguntar ao usuário e sem alongar a resposta. "
         "Use o cofre como memória: consulte com `python \"" + fwd(SCRIPT) + "\" recall \"tema\"` quando precisar de mais contexto."]
    if PERFIL.exists():
        _, b = ler_nota(PERFIL)
        L.append("PERFIL/PREFERÊNCIAS DO USUÁRIO:\n" + b.strip()[:1800])
    fm, b = ler_nota(pnota)
    L.append(f"NOTA DO PROJETO ({fwd(pnota)}): stack={', '.join(listify(fm.get('stack'))) or '—'}; " + trecho({'body': b, 'fm': fm}, 400))
    sess = sorted([n for n in todas_as_notas() if n["tipo"] == "sessao" and f"[[{proj}]]" in str(n["fm"].get("projeto"))],
                  key=lambda n: n["titulo"], reverse=True)[:3]
    if sess:
        L.append("ÚLTIMAS SESSÕES NESTE PROJETO:\n" + "\n".join(f"- {n['titulo']}: {n['fm'].get('resumo', '')}" for n in sess))
    print("\n\n".join(L)[:7000])


def hook_prompt(agente):
    d = ler_stdin_json()
    prompt = d.get("prompt") or ""
    sid = d.get("session_id") or ""
    processar_inbox()
    if len(set(tokens(prompt))) < 2:
        return
    st = ler_estado(sid)
    ja = set(st.get("injetadas", []))
    res = recall(prompt, d.get("cwd"), n=5, excluir=ja)
    if not res:
        return
    st["injetadas"] = list(ja | {str(n["path"]) for n in res})
    gravar_estado(sid, st)
    print(formatar_recall(res))


def analisar_transcricao(path):
    msgs = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for l in f:
                try:
                    msgs.append(json.loads(l))
                except Exception:
                    pass
    except Exception:
        return None
    idx, uuid, prompt = -1, "", ""
    for i, m in enumerate(msgs):
        if m.get("type") != "user" or m.get("isSidechain") or m.get("isMeta"):
            continue
        c = (m.get("message") or {}).get("content")
        txt = c if isinstance(c, str) else " ".join(
            x.get("text", "") for x in (c or []) if isinstance(x, dict) and x.get("type") == "text")
        if txt.strip():
            idx, uuid, prompt = i, m.get("uuid", str(i)), txt
    if idx < 0:
        return None
    tools = []
    for m in msgs[idx + 1:]:
        if m.get("type") == "assistant":
            for x in (m.get("message") or {}).get("content") or []:
                if isinstance(x, dict) and x.get("type") == "tool_use":
                    tools.append((x.get("name", ""), x.get("input") or {}))
    return uuid, prompt, tools


def houve_entrega(tools):
    edits, bash = 0, 0
    if any("_Sistema/inbox" in fwd(json.dumps(inp)) or "processar-inbox" in json.dumps(inp)
           or " registrar" in json.dumps(inp) for _, inp in tools):
        return False  # o agente já registrou neste turno
    for nome, inp in tools:
        alvo = fwd(inp.get("file_path", "") or inp.get("notebook_path", ""))
        if nome in ("Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"):
            if fwd(VAULT) + "/" not in alvo:
                edits += 1
        elif nome in ("Bash", "PowerShell", "shell", "local_shell"):
            if "cerebro.py" not in json.dumps(inp):
                bash += 1
    return edits >= 1 or bash >= 3


def hook_stop(agente):
    d = ler_stdin_json()
    if processar_inbox() or d.get("stop_hook_active"):
        return
    sid = d.get("session_id") or ""
    cwd = d.get("cwd") or os.getcwd()
    info = analisar_transcricao(d["transcript_path"]) if d.get("transcript_path") else None
    if info:
        uuid, _, tools = info
        if not houve_entrega(tools):
            return
    else:  # formato de transcrição desconhecido (ex.: Codex): usa a última resposta como sinal
        uuid = str(d.get("turn_id") or time.time())
        if len(d.get("last_assistant_message") or "") < 300:
            return
    st = ler_estado(sid)
    if st.get("bloqueado_para") == uuid:
        return
    st["bloqueado_para"] = uuid
    gravar_estado(sid, st)
    proj, _ = nome_do_projeto(cwd)
    arq = f"{fwd(INBOX)}/{datetime.now():%Y%m%d-%H%M%S}.json"
    modelo = {"cwd": fwd(cwd), "projeto": proj, "agente": agente, "titulo": "<título curto da entrega>",
              "resumo": "<o que foi pedido e entregue, 2-4 linhas>",
              "decisoes": [{"titulo": "...", "decisao": "...", "motivo": "..."}],
              "padroes": [{"titulo": "...", "descricao": "..."}],
              "preferencias": [{"titulo": "...", "descricao": "..."}],
              "stack": ["Tecnologia: como foi usada"],
              "aprendizados": [{"titulo": "...", "descricao": "armadilha, causa raiz, solução"}],
              "arquivos": ["caminhos principais alterados"], "tags": ["tema1", "tema2"]}
    reason = (
        "🧠 CÉREBRO (automático — não pergunte nada ao usuário): a entrega foi concluída; registre agora o aprendizado no segundo cérebro. "
        f"Use a ferramenta Write para criar o arquivo {arq} com JSON neste formato (ajuste os valores; omita listas sem conteúdo útil; "
        "inclua apenas o que for REUTILIZÁVEL em outros projetos: decisões com motivo, padrões de código/arquitetura, preferências do usuário, "
        "stack usada, armadilhas e soluções; escreva em português):\n"
        + json.dumps(modelo, ensure_ascii=False)
        + "\nNão rode mais nada: o hook ingere o arquivo sozinho. Depois responda apenas com uma linha curta, ex.: '🧠 Registrado no cérebro.'")
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd")
    r = sp.add_parser("recall")
    r.add_argument("texto")
    r.add_argument("--cwd")
    r.add_argument("--n", type=int, default=5)
    g = sp.add_parser("registrar")
    g.add_argument("--arquivo")
    g.add_argument("--stdin", action="store_true")
    sp.add_parser("processar-inbox")
    se = sp.add_parser("semear")
    se.add_argument("dirs", nargs="+")
    sp.add_parser("reindex")
    for h in ("hook-session", "hook-prompt", "hook-stop"):
        x = sp.add_parser(h)
        x.add_argument("--agente", default="claude")
    a = ap.parse_args()
    try:
        if a.cmd == "recall":
            res = recall(a.texto, a.cwd or os.getcwd(), a.n)
            print(formatar_recall(res) if res else "Nenhuma nota relacionada no cérebro.")
        elif a.cmd == "registrar":
            raw = sys.stdin.read() if a.stdin else Path(a.arquivo).read_text(encoding="utf-8-sig")
            d = json.loads(raw)
            for item in (d if isinstance(d, list) else [d]):
                print("registrado:", registrar(item))
        elif a.cmd == "processar-inbox":
            print(processar_inbox(), "arquivo(s) processado(s)")
        elif a.cmd == "semear":
            for p in a.dirs:
                nome, root = nome_do_projeto(p)
                print("projeto:", ensure_projeto(nome, root, scan=True))
            reindex()
        elif a.cmd == "reindex":
            reindex()
        elif a.cmd == "hook-session":
            hook_session(a.agente)
        elif a.cmd == "hook-prompt":
            hook_prompt(a.agente)
        elif a.cmd == "hook-stop":
            hook_stop(a.agente)
        else:
            ap.print_help()
    except Exception as e:  # hooks nunca devem quebrar o agente
        log(f"erro {a.cmd}: {type(e).__name__}: {e}")
        if a.cmd in ("recall", "registrar", "semear", "reindex", "processar-inbox"):
            raise


if __name__ == "__main__":
    main()
