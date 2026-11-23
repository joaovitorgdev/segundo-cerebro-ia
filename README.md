# 🧠 Segundo Cérebro para Agentes de IA

> Memória de longo prazo para o **Claude Code** (e o Codex), guardada num cofre do **Obsidian**.
> Python puro: um arquivo e zero dependências.

![testes](https://github.com/joaovitorgdev/segundo-cerebro-ia/actions/workflows/ci.yml/badge.svg)

## O problema

Agentes de IA esquecem tudo a cada sessão. Por isso eles:
- repetem erros que você já resolveu **em outro projeto**;
- pedem de novo as mesmas preferências;
- perdem decisões de arquitetura tomadas semanas atrás.

## A solução

Três hooks do Claude Code ligam o agente a um cofre de notas Markdown:

```
 ┌──────────────┐  SessionStart      ┌──────────────────────────────┐
 │              │ ─────────────────▶ │ perfil + resumo do projeto   │
 │  Claude Code │  UserPromptSubmit  │ busca as 5 notas mais        │
 │   (agente)   │ ─────────────────▶ │ relevantes de TODOS projetos │
 │              │  Stop              │ obriga a registrar decisões, │
 │              │ ─────────────────▶ │ padrões e erros da entrega   │
 └──────────────┘                    └──────────────┬───────────────┘
                                                    ▼
                                   Cofre Obsidian (notas + grafo)
```

- **Recuperação (antes de cada pedido):** busca TF-IDF com stemming em português sobre todas as notas. Título, tags, resumo e corpo têm pesos diferentes, e há um bônus para notas do projeto atual. Não usa banco vetorial nem API paga.
- **Registro (ao fim de cada entrega):** o hook `Stop` detecta se houve edição de código e pede ao agente um JSON com o que é **reutilizável**. O script transforma o JSON em notas atômicas ligadas por `[[wikilinks]]`.
- **Organização:** projetos, decisões (com motivo), padrões, preferências, stack, aprendizados e sessões, cada tipo com uma cor no grafo do Obsidian.

## Em uso real

Depois de ~5 semanas de uso diário em 20 projetos (Python, FastAPI, automação de vídeo, jogos), o cofre tem:

| Tipo | Notas |
|---|---|
| Aprendizados (armadilha → causa → solução) | 532 |
| Padrões reutilizáveis | 430 |
| Decisões com motivo | 311 |
| Sessões registradas | 251 |

**Exemplo:** num projeto, o agente descobriu que o TikTok bloqueia o IP depois de ~10 páginas seguidas. Semanas depois, em outro projeto, o aviso chegou **antes** da primeira requisição.

## Como usar

```bash
git clone https://github.com/joaovitorgdev/segundo-cerebro-ia.git MeuCerebro
# abra a pasta MeuCerebro como cofre no Obsidian (opcional; são só arquivos .md)
```

Adicione os hooks no `~/.claude/settings.json`, trocando o caminho pelo seu:

```json
{
  "hooks": {
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "python \"/caminho/MeuCerebro/_Sistema/cerebro.py\" hook-session" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python \"/caminho/MeuCerebro/_Sistema/cerebro.py\" hook-prompt" }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "python \"/caminho/MeuCerebro/_Sistema/cerebro.py\" hook-stop" }] }]
  }
}
```

Para o Codex, use `--agente codex`. Comandos manuais:

```bash
python _Sistema/cerebro.py recall "deploy fastapi ubuntu"   # o que eu já sei sobre isso?
python _Sistema/cerebro.py registrar --arquivo entrega.json # grava uma entrega
python _Sistema/cerebro.py semear ~/projetos/*              # cria notas de projetos existentes
python _Sistema/cerebro.py reindex                          # regenera o Painel.md
```

## Decisões de projeto

- **Por que TF-IDF e não embeddings?** Com ~2 mil notas curtas, a busca léxica com pesos por campo acerta o que importa: nomes de ferramentas, erros e projetos. Ela roda em milissegundos e funciona offline. Embeddings entram quando o volume ou a busca por sinônimos pedirem.
- **Por que hooks e não uma ferramenta MCP?** O agente não precisa *lembrar de lembrar*. A memória é injetada sempre, e o registro é cobrado no fim de cada entrega.
- **Por que só a biblioteca padrão do Python?** Um único arquivo que roda em qualquer máquina com Python 3.10+, sem `pip install`.
- **Hooks nunca quebram o agente:** qualquer erro vai para o `_Sistema/log.txt` e o hook sai em silêncio.

## Testes

```bash
pip install pytest && pytest -q
```

O teste principal faz o ciclo completo: registra uma entrega no *projeto A* e confere que a lição aparece ao pedir algo parecido no *projeto B*.

## Licença

MIT
