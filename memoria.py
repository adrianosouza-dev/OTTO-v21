"""
Memória permanente do Jarvis.

- Se o Supabase estiver configurado, guarda cada comando na tabela "falas".
- Se não estiver (ou se der erro), usa o arquivo local memory.json.
  O Jarvis nunca para de funcionar por causa da memória.
"""

import json
import os
import re

import config

SUPABASE_URL = getattr(config, "SUPABASE_URL", "") or os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = getattr(config, "SUPABASE_KEY", "") or os.environ.get("SUPABASE_KEY", "")

TABELA = "falas"
ARQUIVO_LOCAL = "memory.json"
COLUNAS = "comando,resposta,criado_em"

_client = None
_ja_tentou = False

PALAVRAS_IGNORADAS = {
    "jarvis", "quero", "preciso", "pode", "fazer", "sobre", "para", "isso",
    "aquele", "aquela", "algo", "agora", "favor", "qual", "como", "onde",
}


def _supabase():
    """Cria o cliente do Supabase uma única vez. Devolve None se não der."""
    global _client, _ja_tentou
    if _client is not None or _ja_tentou:
        return _client
    _ja_tentou = True

    if not (SUPABASE_URL and SUPABASE_KEY):
        print("[memória] Supabase não configurado. Usando memory.json local.")
        return None
    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[memória] Conectado ao Supabase.")
    except Exception as e:
        print(f"[memória] Não consegui conectar ao Supabase ({e}). Usando memory.json local.")
        _client = None
    return _client


# ---------------------------------------------------------------------------
# Salvar
# ---------------------------------------------------------------------------

def salvar(comando_texto, comando_ia):
    registro = {
        "comando": comando_texto,
        "acao": comando_ia.get("action"),
        "argumento": comando_ia.get("argument"),
        "resposta": comando_ia.get("reply"),
    }
    cliente = _supabase()
    if cliente:
        try:
            cliente.table(TABELA).insert(registro).execute()
            return
        except Exception as e:
            print(f"[memória] Falha ao salvar no Supabase ({e}). Salvando localmente.")
    _salvar_local(registro)


def _ler_local():
    if os.path.exists(ARQUIVO_LOCAL):
        try:
            with open(ARQUIVO_LOCAL, "r", encoding="utf-8") as f:
                return json.load(f).get("historico", [])
        except Exception:
            return []
    return []


def _salvar_local(registro):
    historico = _ler_local()
    historico.append(registro)
    with open(ARQUIVO_LOCAL, "w", encoding="utf-8") as f:
        json.dump({"historico": historico}, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Buscar contexto
# ---------------------------------------------------------------------------

def _palavras_chave(texto):
    palavras = re.findall(r"[a-zà-ú0-9]{5,}", texto.lower())
    unicas = []
    for p in palavras:
        if p not in PALAVRAS_IGNORADAS and p not in unicas:
            unicas.append(p)
    return unicas[:4]


def _texto_resposta(item):
    resposta = item.get("resposta")
    if isinstance(resposta, dict):  # formato antigo do memory.json
        resposta = resposta.get("reply")
    return resposta or ""


def _unir(recentes, relevantes):
    """Junta as duas listas sem repetir e devolve em ordem cronológica."""
    vistos = set()
    todos = []
    for item in list(relevantes) + list(recentes):
        chave = (item.get("criado_em"), item.get("comando"))
        if chave in vistos:
            continue
        vistos.add(chave)
        todos.append(item)
    todos.sort(key=lambda i: i.get("criado_em") or "")
    return todos


def buscar_contexto(texto, recentes=5, relevantes=5):
    """
    Devolve um texto com as últimas falas e as falas que têm palavras em comum
    com o comando atual. Devolve "" se não houver nada.
    """
    itens = []
    cliente = _supabase()

    if cliente:
        try:
            recentes_db = (
                cliente.table(TABELA).select(COLUNAS)
                .order("criado_em", desc=True).limit(recentes).execute().data
            ) or []

            relevantes_db = []
            palavras = _palavras_chave(texto)
            if palavras:
                filtro = ",".join(f"comando.ilike.*{p}*" for p in palavras)
                relevantes_db = (
                    cliente.table(TABELA).select(COLUNAS)
                    .or_(filtro)
                    .order("criado_em", desc=True).limit(relevantes).execute().data
                ) or []

            itens = _unir(recentes_db, relevantes_db)
        except Exception as e:
            print(f"[memória] Falha ao buscar no Supabase ({e}). Usando memory.json.")
            itens = _ler_local()[-recentes:]
    else:
        itens = _ler_local()[-recentes:]

    linhas = [f"- Você: {i.get('comando', '')} | Jarvis: {_texto_resposta(i)}" for i in itens]
    return "\n".join(linhas)
