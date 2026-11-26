"""Testa o ciclo completo: registrar uma entrega e recuperá-la em outro projeto."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def cofre_temporario(tmp_path):
    sistema = tmp_path / "_Sistema"
    sistema.mkdir()
    shutil.copy(RAIZ / "_Sistema" / "cerebro.py", sistema / "cerebro.py")
    return sistema / "cerebro.py"


def rodar(script, *args, entrada=None):
    r = subprocess.run([sys.executable, str(script), *args], input=entrada,
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_registra_e_recupera_em_outro_projeto(tmp_path):
    script = cofre_temporario(tmp_path)
    entrega = {
        "projeto": "projeto-a", "agente": "claude", "titulo": "Scraper do TikTok",
        "resumo": "Coleta de perfis do TikTok com navegador automatizado.",
        "aprendizados": [{"titulo": "TikTok bloqueia o IP com HTTP 403",
                          "descricao": "Depois de ~10 páginas seguidas o TikTok devolve 403; espaçar as requisições."}],
        "decisoes": [{"titulo": "Usar Playwright", "decisao": "Playwright no lugar de requests",
                      "motivo": "as páginas são renderizadas por JavaScript"}],
    }
    assert "registrado" in rodar(script, "registrar", "--stdin", entrada=json.dumps(entrega))

    notas = list((tmp_path / "06-Aprendizados").glob("*.md"))
    assert len(notas) == 1 and "403" in notas[0].read_text(encoding="utf-8")

    saida = rodar(script, "recall", "baixar vídeos do tiktok sem levar bloqueio 403",
                  "--cwd", str(tmp_path / "projeto-b"))
    assert "TikTok bloqueia o IP" in saida


def test_recall_sem_relacao_nao_inventa(tmp_path):
    script = cofre_temporario(tmp_path)
    assert "Nenhuma nota" in rodar(script, "recall", "receita de bolo de cenoura")


def test_le_tags_em_lista_multilinha_do_obsidian(tmp_path):
    script = cofre_temporario(tmp_path)
    nota = tmp_path / "06-Aprendizados" / "Cache do navegador esconde dados.md"
    nota.parent.mkdir()
    for i, tema in enumerate(["receita de bolo", "jardinagem", "futebol", "viagem", "musica"]):
        (nota.parent / f"Outro {i}.md").write_text(f"---\ntipo: aprendizado\n---\n{tema}\n", encoding="utf-8")
    nota.write_text("---\ntipo: aprendizado\ntags:\n  - fastapi\n  - deploy\nresumo: \"x\"\n---\nTexto curto.\n",
                    encoding="utf-8")
    assert "Cache do navegador" in rodar(script, "recall", "fastapi deploy")


def test_licao_nova_substitui_antiga_sem_apagar(tmp_path):
    script = cofre_temporario(tmp_path)
    antiga = {"projeto": "projeto-a", "titulo": "Cache",
              "aprendizados": [{"titulo": "Cache de sessão em SQLite",
                                "descricao": "Guardar o cache de sessão em SQLite local basta."}]}
    nova = {"projeto": "projeto-a", "titulo": "Cache 2",
            "aprendizados": [{"titulo": "Cache de sessão em Redis",
                              "descricao": "SQLite travou com escrita concorrente no cache de sessão; usar Redis.",
                              "substitui": "Cache de sessão em SQLite"}]}
    rodar(script, "registrar", "--stdin", entrada=json.dumps(antiga))
    rodar(script, "registrar", "--stdin", entrada=json.dumps(nova))

    texto_antigo = (tmp_path / "06-Aprendizados" / "Cache de sessão em SQLite.md").read_text(encoding="utf-8")
    assert 'substituida_por: "[[Cache de sessão em Redis]]"' in texto_antigo
    assert "Guardar o cache de sessão em SQLite local basta." in texto_antigo  # histórico mantido
    texto_novo = (tmp_path / "06-Aprendizados" / "Cache de sessão em Redis.md").read_text(encoding="utf-8")
    assert "[[Cache de sessão em SQLite]]" in texto_novo

    saida = rodar(script, "recall", "cache de sessão sqlite", "--cwd", str(tmp_path / "projeto-b"))
    assert saida.index("Cache de sessão em Redis") < saida.index("Cache de sessão em SQLite")
    assert "SUBSTITUÍDA por Cache de sessão em Redis" in saida
