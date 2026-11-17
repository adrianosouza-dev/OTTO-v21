"""
Ferramentas que o Claude pode usar no notebook.

Cada ferramenta tem uma definição (o que o Claude vê) e uma função (o que roda de verdade).
A função devolve um texto curto com o resultado, que volta para o Claude decidir o próximo passo.
"""

import platform
import re
import subprocess
import urllib.parse
import webbrowser

import inventario

# ---------------------------------------------------------------------------
# Definições (o que o Claude vê)
# ---------------------------------------------------------------------------

def _ferramenta(nome, descricao, propriedades, obrigatorios):
    return {
        "name": nome,
        "description": descricao,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": propriedades,
            "required": obrigatorios,
            "additionalProperties": False,
        },
    }


FERRAMENTAS = [
    _ferramenta(
        "abrir_programa",
        "Abre um programa ou app instalado no notebook (inclusive apps da Microsoft Store). "
        "Use o nome exato da lista de programas instalados que melhor combina com o pedido.",
        {"nome": {"type": "string", "description": "Nome do programa, de preferência igual ao da lista"}},
        ["nome"],
    ),
    _ferramenta(
        "abrir_pasta",
        "Abre uma pasta no Explorador de Arquivos.",
        {"pasta": {"type": "string", "description":
                   "downloads, documentos, area de trabalho, imagens, videos, musicas ou um caminho completo"}},
        ["pasta"],
    ),
    _ferramenta(
        "abrir_configuracao",
        "Abre uma tela de configurações do Windows.",
        {"tela": {"type": "string", "enum": sorted(inventario.CONFIGURACOES)}},
        ["tela"],
    ),
    _ferramenta(
        "abrir_site",
        "Abre um site no navegador.",
        {"url": {"type": "string", "description": "Endereço completo começando com https://"}},
        ["url"],
    ),
    _ferramenta(
        "pesquisar_no_navegador",
        "Abre uma pesquisa do Google no navegador, para o usuário ver os resultados na tela. "
        "Para RESPONDER perguntas sobre fatos atuais, use web_search em vez desta.",
        {"termo": {"type": "string"}},
        ["termo"],
    ),
    _ferramenta(
        "executar_comando",
        "Executa um comando simples no terminal do Windows (cmd) e devolve a saída. "
        "Só use quando nenhuma outra ferramenta resolve. O usuário vai confirmar por voz antes. "
        "Comandos que apagam, movem, alteram o sistema ou desligam o computador são bloqueados.",
        {
            "comando": {"type": "string"},
            "motivo": {"type": "string", "description": "Frase curta dizendo o que o comando faz, para pedir a confirmação"},
        },
        ["comando", "motivo"],
    ),
]

# Busca na web feita pelos servidores da Anthropic (o Claude lê os resultados e responde)
BUSCA_WEB = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 3,
    "user_location": {"type": "approximate", "country": "BR"},
}

# ---------------------------------------------------------------------------
# Segurança do terminal
# ---------------------------------------------------------------------------

# Comandos que nunca rodam, mesmo com confirmação
_BLOQUEADOS = re.compile(
    r"(?ix)"
    r"\b(del|erase|rd|rmdir|rm|format|diskpart|shutdown|restart-computer|stop-computer|"
    r"remove-item|move|move-item|ren|rename|rename-item|mv|cipher|bcdedit|takeown|icacls|cacls|"
    r"reg|regedit|schtasks|sc|net|netsh|wmic|vssadmin|attrib|mklink|set-executionpolicy|"
    r"invoke-webrequest|invoke-expression|iex|iwr|curl|wget|bitsadmin|certutil|powershell|pwsh|"
    r"runas|taskkill|stop-process|copy|xcopy|robocopy)\b"
    r"|[<>&^`]"   # redirecionar para arquivo, encadear comandos e escapar letras ("d^el")
)


def comando_bloqueado(comando):
    return bool(_BLOQUEADOS.search(comando))


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def _abrir_programa(nome, apps):
    if apps:
        app = inventario.encontrar(nome, apps)
        if not app:
            return f"Não encontrei nenhum programa instalado parecido com '{nome}'."
        inventario.abrir_app(app["id"])
        return f"Abri {app['nome']}."
    return _abrir_programa_basico(nome)


def _abrir_programa_basico(nome):
    """Usado só quando não há lista de programas (fora do Windows ou se a listagem falhar)."""
    nome = nome.lower().strip()
    if not re.fullmatch(r"[\w .+-]{1,60}", nome):
        return f"Nome de programa inválido: '{nome}'."

    sistema = platform.system()
    apps_windows = {
        "chrome": "chrome", "navegador": "chrome",
        "bloco de notas": "notepad", "notepad": "notepad",
        "calculadora": "calc", "explorador": "explorer",
        "word": "winword", "excel": "excel",
        "vscode": "code", "vs code": "code", "spotify": "spotify",
    }
    apps_mac = {
        "chrome": "Google Chrome", "navegador": "Google Chrome",
        "calculadora": "Calculator", "notas": "Notes",
        "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
        "spotify": "Spotify",
    }
    apps_linux = {
        "chrome": "google-chrome", "navegador": "firefox",
        "calculadora": "gnome-calculator",
        "vscode": "code", "vs code": "code", "spotify": "spotify",
    }
    if sistema == "Windows":
        subprocess.Popen(["cmd", "/c", "start", "", apps_windows.get(nome, nome)],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    elif sistema == "Darwin":
        subprocess.Popen(["open", "-a", apps_mac.get(nome, nome)])
    else:
        subprocess.Popen([apps_linux.get(nome, nome)])
    return f"Tentei abrir {nome}."


def _abrir_pasta(pasta):
    caminho = inventario.pasta_conhecida(pasta)
    if not caminho:
        return f"Não encontrei a pasta '{pasta}'."
    inventario.abrir_caminho(caminho)
    return f"Abri a pasta {caminho}."


def _abrir_configuracao(tela):
    if not inventario.abrir_configuracao(tela):
        return "As telas de configuração só funcionam no Windows."
    return f"Abri as configurações de {tela}."


def _abrir_site(url):
    url = url.strip()
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        return "Só abro endereços que começam com http:// ou https://."
    webbrowser.open(url)
    return f"Abri {url}."


def _pesquisar_no_navegador(termo):
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(termo))
    return f"Abri a pesquisa por '{termo}' no navegador."


def _executar_comando(comando, motivo, confirmar):
    if comando_bloqueado(comando):
        return "Comando bloqueado por segurança: ele pode apagar, alterar ou desligar algo. Não foi executado."
    motivo = motivo.strip().rstrip(".")
    motivo = motivo[:1].lower() + motivo[1:]
    if not confirmar(f"Posso executar um comando para {motivo}?"):
        return "O usuário não confirmou. O comando não foi executado."

    print(f"[terminal] {comando}")
    windows = platform.system() == "Windows"
    try:
        r = subprocess.run(
            comando, shell=True, capture_output=True, timeout=15,
            text=True, encoding="oem" if windows else "utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return "O comando demorou mais de 15 segundos e foi interrompido."
    saida = (r.stdout + r.stderr).strip()
    print(saida)
    if len(saida) > 3000:
        saida = saida[:3000] + "\n[saída cortada]"
    return f"Código de saída {r.returncode}.\n{saida or '(sem saída)'}"


def executar(nome, entrada, apps, confirmar):
    """Roda a ferramenta pedida pelo Claude. Devolve (texto_resultado, deu_erro)."""
    try:
        if nome == "abrir_programa":
            return _abrir_programa(entrada["nome"], apps), False
        if nome == "abrir_pasta":
            return _abrir_pasta(entrada["pasta"]), False
        if nome == "abrir_configuracao":
            return _abrir_configuracao(entrada["tela"]), False
        if nome == "abrir_site":
            return _abrir_site(entrada["url"]), False
        if nome == "pesquisar_no_navegador":
            return _pesquisar_no_navegador(entrada["termo"]), False
        if nome == "executar_comando":
            return _executar_comando(entrada["comando"], entrada["motivo"], confirmar), False
        return f"Ferramenta desconhecida: {nome}", True
    except Exception as e:
        print(f"[ação] Erro em {nome}: {e}")
        return f"Erro ao executar {nome}: {e}", True
