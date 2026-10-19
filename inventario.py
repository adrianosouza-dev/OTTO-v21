"""
Descobre os programas instalados no Windows (Menu Iniciar) e abre qualquer um deles,
inclusive apps da Microsoft Store (Fotos, Configurações, WhatsApp...).
Também abre pastas conhecidas e telas de configuração do Windows.
"""

import difflib
import json
import os
import platform
import re
import subprocess
import threading
import time
import unicodedata
from pathlib import Path

CACHE_APPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apps_cache.json")

# Atalhos que não são programas de verdade
IGNORAR = re.compile(
    r"(?i)uninstall|desinstal|readme|leia-?me|licen[sç]|release notes|notas de vers|\bhelp\b|\bajuda\b|manual"
)

CONFIGURACOES = {
    "wifi": "ms-settings:network-wifi",
    "rede": "ms-settings:network",
    "bluetooth": "ms-settings:bluetooth",
    "som": "ms-settings:sound",
    "tela": "ms-settings:display",
    "bateria": "ms-settings:batterysaver",
    "atualizacao": "ms-settings:windowsupdate",
    "aplicativos": "ms-settings:appsfeatures",
    "notificacoes": "ms-settings:notifications",
    "impressoras": "ms-settings:printers",
    "geral": "ms-settings:",
}

PASTAS = {
    "downloads": ["Downloads"],
    "documentos": ["Documents", "Documentos"],
    "documents": ["Documents", "Documentos"],
    "area de trabalho": ["Desktop", "Área de Trabalho"],
    "desktop": ["Desktop", "Área de Trabalho"],
    "imagens": ["Pictures", "Imagens"],
    "pictures": ["Pictures", "Imagens"],
    "videos": ["Videos", "Vídeos"],
    "musicas": ["Music", "Músicas"],
    "music": ["Music", "Músicas"],
}


def _norm(texto):
    """Minúsculo, sem acentos e sem espaços nas pontas."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.casefold().strip()


# ---------------------------------------------------------------------------
# Programas instalados
# ---------------------------------------------------------------------------

def _limpar(dados, limite):
    if isinstance(dados, dict):  # o PowerShell devolve um objeto se houver só 1 app
        dados = [dados]
    vistos = set()
    apps = []
    for item in dados or []:
        nome = str(item.get("Name") or "").strip()
        app_id = str(item.get("AppID") or "").strip()
        if not nome or not app_id or IGNORAR.search(nome):
            continue
        chave = nome.casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        apps.append({"nome": nome, "id": app_id})
    apps.sort(key=lambda a: a["nome"].casefold())
    return apps[:limite]


def listar_apps(limite=400):
    """Lê os programas do Menu Iniciar. Devolve [] fora do Windows ou se der erro."""
    if platform.system() != "Windows":
        return []
    comando = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "Get-StartApps | ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando],
            capture_output=True, text=True, encoding="utf-8", timeout=40,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        dados = json.loads(r.stdout) if r.stdout.strip() else []
    except Exception as e:
        print(f"[apps] Não consegui listar os programas instalados ({e}).")
        return []
    return _limpar(dados, limite)


def _salvar_cache(apps):
    try:
        with open(CACHE_APPS, "w", encoding="utf-8") as f:
            json.dump(apps, f, ensure_ascii=False)
    except Exception as e:
        print(f"[apps] Não consegui salvar a lista de programas ({e}).")


def _atualizar_cache(limite, espera):
    time.sleep(espera)   # espera o assistente terminar de ligar, para não disputar o processador
    apps = listar_apps(limite)
    if apps:
        _salvar_cache(apps)


def listar_apps_rapido(limite=400):
    """
    Usa a lista salva da última vez (instantâneo, mesmo com o PC lento) e atualiza o arquivo
    em segundo plano para a próxima vez. Sem lista salva, lista agora.
    """
    try:
        with open(CACHE_APPS, encoding="utf-8") as f:
            apps = json.load(f)
    except Exception:
        apps = None
    if apps:
        threading.Thread(target=_atualizar_cache, args=(limite, 60), daemon=True).start()
        return apps
    apps = listar_apps(limite)
    if apps:
        _salvar_cache(apps)
    return apps


def encontrar(pedido, apps):
    """Acha o programa que melhor combina com o nome falado. Devolve o dict ou None."""
    alvo = _norm(pedido)
    if not alvo or not apps:
        return None
    por_nome = {_norm(a["nome"]): a for a in apps}

    if alvo in por_nome:
        return por_nome[alvo]

    contem = [
        k for k in por_nome
        if (len(alvo) >= 3 and alvo in k) or (len(k) >= 4 and k in alvo)
    ]
    if contem:
        return por_nome[min(contem, key=len)]

    parecido = difflib.get_close_matches(alvo, list(por_nome), n=1, cutoff=0.7)
    return por_nome[parecido[0]] if parecido else None


def abrir_app(app_id):
    """Abre um programa pelo identificador (funciona com apps clássicos e da Store)."""
    if os.path.isfile(app_id):  # alguns apps vêm com o caminho do executável
        os.startfile(app_id)
    else:
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app_id])
    return True


# ---------------------------------------------------------------------------
# Pastas e configurações
# ---------------------------------------------------------------------------

def pasta_conhecida(nome):
    """Resolve 'downloads', 'documentos'... ou um caminho de pasta existente."""
    home = Path.home()
    for candidato in PASTAS.get(_norm(nome), []):
        for base in (home, home / "OneDrive"):
            pasta = base / candidato
            if pasta.is_dir():
                return pasta
    try:
        pasta = Path(str(nome)).expanduser()
        return pasta if pasta.is_dir() else None
    except Exception:
        return None


def abrir_caminho(caminho):
    if platform.system() == "Windows":
        os.startfile(str(caminho))
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(caminho)])
    else:
        subprocess.Popen(["xdg-open", str(caminho)])
    return True


def abrir_configuracao(nome):
    if platform.system() != "Windows":
        return False
    os.startfile(CONFIGURACOES.get(_norm(nome), "ms-settings:"))
    return True
