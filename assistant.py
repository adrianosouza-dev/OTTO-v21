"""
Assistente de voz local com memória permanente (Supabase).

Fluxo (cada etapa numa thread, ligadas por filas):
  escuta → transcrição (Google) → loop principal → tarefas (cérebro) → síntese (Piper) → reprodução

- O microfone fica desligado enquanto o assistente fala (assim ele não ouve a própria voz)
  e grava de novo assim que ele termina, mesmo que o Google ainda esteja transcrevendo.
- A resposta do Claude é falada frase por frase, enquanto ainda está sendo escrita.
"""

import io
import json
import math
import os
import platform
import queue
import re
import threading
import time
import wave
from array import array

import speech_recognition as sr
import pyttsx3
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
from piper import PiperVoice, SynthesisConfig

import acoes
import config
import inventario
import memoria
from config import ANTHROPIC_API_KEY, WAKE_WORD, VOICE_ENABLED, ASSISTANT_NAME

TEST_MODE = getattr(config, "TEST_MODE", False)
NOME_USUARIO = getattr(config, "NOME_USUARIO", "")

# Variações que o reconhecimento de voz costuma produzir para a palavra de ativação
VARIACOES_ATIVACAO = {WAKE_WORD.lower(), "estorm", "istorm", "storme"}
_PADRAO_ATIVACAO = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in VARIACOES_ATIVACAO) + r")\b"
)
# Comandos de controle: aceitam a palavra cortada pela transcrição ("modo contín", "pode dorm")
_MODO_CONTINUO = re.compile(r"\bmodo cont[ií]n")
_PODE_DORMIR = re.compile(r"\bpode dorm")

# Escuta
PAUSA_FIM_FRASE = 1.3     # segundos de silêncio para considerar que você terminou de falar
PAUSA_APOS_FALA = 0.25    # espera depois que ele fala, antes de voltar a gravar (evita o eco)
LIMITE_FRASE = 20         # uma gravação nunca passa disso (segundos)
SENSIBILIDADE_MINIMA = 10  # energia mínima para contar como voz. No microfone deste notebook o ruído
                           # fica em 1-6 e a voz em 12-70: abaixo de 10 o ruído vira "fala" e a gravação
                           # não termina; muito acima disso, a voz normal não é ouvida

# Voz
CAMINHO_VOZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pt_BR-faber-medium.onnx")
VELOCIDADE_VOZ = 0.9   # menor = mais rápido (ex: 0.8), maior = mais devagar (ex: 1.1)


def separar_ativacao(texto):
    """Retorna (disse_ativacao, comando). O comando é o que vem depois da palavra de ativação."""
    achou = _PADRAO_ATIVACAO.search(texto)
    if not achou:
        return False, texto
    return True, texto[achou.end():].strip(" ,.")


# ---------------------------------------------------------------------------
# Estado compartilhado
# ---------------------------------------------------------------------------

recognizer = sr.Recognizer()
# 16 kHz é o que o Google usa: menos dados para o processador. Bloco maior: se o PC engasgar,
# o Windows guarda mais áudio antes de descartar pedaços da sua fala.
microphone = sr.Microphone(sample_rate=16000, chunk_size=2048)

fila_falas = queue.Queue()         # frases a sintetizar
fila_sons = queue.Queue()          # áudios prontos para tocar
fila_audios = queue.Queue()        # gravações do microfone a transcrever
fila_textos = queue.Queue()        # o que você disse, já em texto
fila_tarefas = queue.Queue()       # pedidos para o cérebro
fila_confirmacoes = queue.Queue()  # respostas de "sim/não" quando uma ação pede confirmação

falando = threading.Event()      # ligado do momento em que algo entra na fila de voz até terminar de tocar
ocupado = threading.Event()      # ligado enquanto uma tarefa está sendo executada
aguardando_confirmacao = threading.Event()
ultima_fala_fim = 0.0            # quando a última fala terminou

_fala_mudou = threading.Condition()
_falas_pendentes = 0             # frases na fila de voz que ainda não terminaram de tocar
_espera_desde = None             # quando a voz começou a ser pedida (para medir a demora)

APPS = []        # programas instalados (preenchido ao iniciar, só no Windows)
cerebro = None   # criado no main() (não existe no TEST_MODE)
BIP = None       # som curto que avisa "pode falar"


# ---------------------------------------------------------------------------
# Voz
# ---------------------------------------------------------------------------

def _dividir_em_frases(texto):
    """Quebra o texto em pedaços curtos: o primeiro fica pronto rápido e já começa a tocar."""
    pedacos = []
    for frase in re.split(r"(?<=[.!?…])\s+", texto.strip()):
        while len(frase) > 60 and "," in frase[5:]:
            corte = frase.index(",", 5) + 1
            pedacos.append(frase[:corte].strip())
            frase = frase[corte:].strip()
        if frase:
            pedacos.append(frase)
    return pedacos


def _som_de_pcm(pcm, taxa, canais=1):
    """Embrulha áudio PCM 16 bits num WAV na memória, para o pygame converter o formato sozinho."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(canais)
        wav.setsampwidth(2)
        wav.setframerate(taxa)
        wav.writeframes(pcm)
    buffer.seek(0)
    return pygame.mixer.Sound(file=buffer)


def _gerar_bip(frequencia=880, duracao=0.09, volume=0.25):
    taxa = 22050
    n = int(taxa * duracao)
    rampa = taxa * 0.01   # entra e sai suave, sem estalo
    amostras = array("h", (
        int(volume * 32767 * math.sin(2 * math.pi * frequencia * i / taxa) * min(1.0, i / rampa, (n - i) / rampa))
        for i in range(n)
    ))
    return _som_de_pcm(amostras.tobytes(), taxa)


def _sintetizar(voz, texto):
    pedacos = list(voz.synthesize(texto, syn_config=SynthesisConfig(length_scale=VELOCIDADE_VOZ)))
    pcm = b"".join(p.audio_int16_bytes for p in pedacos)
    return _som_de_pcm(pcm, pedacos[0].sample_rate, pedacos[0].sample_channels)


def _enfileirar_voz(tipo, conteudo):
    global _falas_pendentes, _espera_desde
    with _fala_mudou:
        if _falas_pendentes == 0:
            _espera_desde = time.time() if tipo == "texto" else None
        _falas_pendentes += 1
        falando.set()
    fila_falas.put((tipo, conteudo))


def _terminou_de_tocar():
    global _falas_pendentes, ultima_fala_fim
    with _fala_mudou:
        _falas_pendentes -= 1
        if _falas_pendentes == 0:
            ultima_fala_fim = time.time()
            falando.clear()
            _fala_mudou.notify_all()


def esperar_fala_terminar():
    with _fala_mudou:
        _fala_mudou.wait_for(lambda: _falas_pendentes == 0)


def _thread_sintese():
    """Transforma as frases em áudio. Enquanto uma frase toca, a próxima já está sendo gerada."""
    try:
        t = time.time()
        voz = PiperVoice.load(CAMINHO_VOZ)
        _sintetizar(voz, "Olá.")   # a primeira síntese é mais lenta: faz uma de aquecimento
        print(f"[voz] Piper pronto em {time.time() - t:.1f}s.")
    except Exception as e:
        print(f"[voz] Não consegui carregar a voz do Piper ({e}). Usando pyttsx3.")
        voz = None

    while True:
        tipo, conteudo = fila_falas.get()
        if tipo == "texto":
            try:
                if voz is None:
                    raise RuntimeError("Piper indisponível")
                fila_sons.put(("som", _sintetizar(voz, conteudo)))
            except Exception as e:
                if voz is not None:
                    print(f"[voz] Piper falhou ({e}), usando pyttsx3.")
                fila_sons.put(("pyttsx3", conteudo))
        else:
            fila_sons.put((tipo, conteudo))


def _thread_reproducao():
    """Única thread que toca som. Toca um áudio de cada vez, na ordem da fila."""
    global _espera_desde
    engine = None
    while True:
        tipo, conteudo = fila_sons.get()
        try:
            if _espera_desde is not None:
                print(f"[tempo] Voz: {time.time() - _espera_desde:.1f}s até começar a falar")
                _espera_desde = None
            if tipo in ("som", "bip"):
                canal = conteudo.play()
                while canal is not None and canal.get_busy():
                    time.sleep(0.02)
            else:
                if engine is None:
                    engine = pyttsx3.init()
                    engine.setProperty("rate", 175)
                engine.say(conteudo)
                engine.runAndWait()
        except Exception as e:
            print(f"Erro na voz: {e}")
        finally:
            _terminou_de_tocar()


def falar(texto, esperar=False):
    """Mostra o texto e manda para a fila de voz. Não trava quem chamou (a não ser com esperar=True)."""
    print(f"{ASSISTANT_NAME}: {texto}")
    if VOICE_ENABLED and texto:
        for frase in _dividir_em_frases(texto):
            _enfileirar_voz("texto", frase)
        if esperar:
            esperar_fala_terminar()


def tocar_bip():
    if VOICE_ENABLED and BIP is not None:
        _enfileirar_voz("bip", BIP)


# ---------------------------------------------------------------------------
# Escuta
# ---------------------------------------------------------------------------

class _FalaComecou(Exception):
    pass


class _MicrofoneInterrompivel:
    """Envolve o microfone: se o assistente começar a falar no meio da gravação, ela é abandonada."""

    def __init__(self, stream):
        self._stream = stream

    def read(self, tamanho):
        if falando.is_set():
            raise _FalaComecou
        return self._stream.read(tamanho)

    def close(self):
        self._stream.close()


def calibrar_microfone():
    with microphone as source:
        print("Calibrando o microfone (fique em silêncio)...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
    # A sensibilidade continua se ajustando sozinha ao ruído do ambiente (padrão da biblioteca),
    # mas nunca abaixo do mínimo
    recognizer.energy_threshold = max(recognizer.energy_threshold, SENSIBILIDADE_MINIMA)
    recognizer.pause_threshold = PAUSA_FIM_FRASE
    print(f"[microfone] sensibilidade {recognizer.energy_threshold:.0f}")


def _thread_escuta():
    """Grava frases sem parar, exceto enquanto o assistente fala."""
    avisar = True
    while True:
        while falando.is_set() or time.time() - ultima_fala_fim < PAUSA_APOS_FALA:
            time.sleep(0.05)
            avisar = True
        if avisar:
            print("Ouvindo...")
            avisar = False
        recognizer.energy_threshold = max(recognizer.energy_threshold, SENSIBILIDADE_MINIMA)
        try:
            with microphone as source:
                source.stream = _MicrofoneInterrompivel(source.stream)
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=LIMITE_FRASE)
        except (sr.WaitTimeoutError, _FalaComecou):
            continue
        except Exception as e:
            print(f"[microfone] Erro: {e}")
            time.sleep(1)
            continue
        fila_audios.put(audio)
        avisar = True


def _thread_transcricao():
    """Manda as gravações para o Google, uma de cada vez, sem atrasar o microfone."""
    while True:
        audio = fila_audios.get()
        try:
            t = time.time()
            texto = recognizer.recognize_google(audio, language="pt-BR")
            print(f"[tempo] Google (voz → texto): {time.time() - t:.1f}s")
            print(f"Você disse: {texto}")
            fila_textos.put(texto.lower())
        except sr.UnknownValueError:
            duracao = len(audio.frame_data) / (audio.sample_rate * audio.sample_width)
            print(f"[escuta] Não entendi a gravação ({duracao:.1f}s de áudio).")
        except sr.RequestError as e:
            print(f"Erro no reconhecimento: {e}")
            falar("Não consegui acessar o serviço de reconhecimento de voz.")


# ---------------------------------------------------------------------------
# Confirmação por voz
# ---------------------------------------------------------------------------

_NEGATIVAS = {"não", "nao", "cancela", "cancelar", "negativo", "para", "pare", "nunca"}
_POSITIVAS = {"sim", "pode", "confirmo", "confirma", "claro", "manda", "executa", "positivo", "ok", "isso"}


def confirmar(pergunta, espera_segundos=20):
    """Pergunta em voz e espera um sim/não. Sem resposta clara, considera não."""
    while not fila_confirmacoes.empty():
        fila_confirmacoes.get_nowait()

    falar(pergunta, esperar=True)
    aguardando_confirmacao.set()
    tocar_bip()
    try:
        resposta = fila_confirmacoes.get(timeout=espera_segundos)
    except queue.Empty:
        resposta = ""
    finally:
        aguardando_confirmacao.clear()

    palavras = set(re.findall(r"\w+", resposta.lower()))
    aceitou = bool(palavras & _POSITIVAS) and not (palavras & _NEGATIVAS)
    print(f"[confirmação] '{resposta}' → {'sim' if aceitou else 'não'}")
    return aceitou


# ---------------------------------------------------------------------------
# Modo de teste (sem API)
# ---------------------------------------------------------------------------

def responder_teste(texto):
    """Interpretador por palavras-chave, usado com TEST_MODE = True (não chama a API)."""
    if "navegador" in texto or "chrome" in texto:
        acao, entrada = "abrir_programa", {"nome": "chrome"}
    elif "calculadora" in texto:
        acao, entrada = "abrir_programa", {"nome": "calculadora"}
    elif "pesquis" in texto:
        termo = texto.replace("pesquisa", "").replace("pesquise", "").strip() or "clima hoje"
        acao, entrada = "pesquisar_no_navegador", {"termo": termo}
    else:
        fala = f"Modo de teste. Eu te ouvi dizer: {texto}."
        falar(fala)
        return fala, []

    resultado, _ = acoes.executar(acao, entrada, APPS, confirmar)
    falar(resultado)
    return resultado, [{"ferramenta": acao, "entrada": entrada}]


# ---------------------------------------------------------------------------
# Tarefas em segundo plano
# ---------------------------------------------------------------------------

def _thread_tarefas():
    """Pega os pedidos da fila, um por vez, e executa enquanto o microfone continua ouvindo."""
    while True:
        comando_texto, deve_salvar = fila_tarefas.get()
        ocupado.set()
        try:
            if TEST_MODE:
                fala, feitas = responder_teste(comando_texto)
            else:
                fala, feitas = cerebro.responder(comando_texto, confirmar, falar)
            if deve_salvar:
                memoria.salvar(comando_texto, {
                    "action": ",".join(a["ferramenta"] for a in feitas) or "conversa",
                    "argument": json.dumps([a["entrada"] for a in feitas], ensure_ascii=False) if feitas else "",
                    "reply": fala,
                })
        except Exception as e:
            print(f"Erro na tarefa '{comando_texto}': {e}")
            falar("Tive um problema com essa tarefa.")
        finally:
            ocupado.clear()
            fila_tarefas.task_done()
        if fila_tarefas.empty():
            tocar_bip()   # terminou: pode falar de novo


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def _prioridade_alta():
    """No Windows, dá prioridade ao assistente: com o navegador carregando, a voz não trava."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
        kernel32 = ctypes.windll.kernel32
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), ABOVE_NORMAL_PRIORITY_CLASS)
    except Exception as e:
        print(f"[sistema] Não consegui aumentar a prioridade ({e}).")


def main():
    global APPS, cerebro, BIP
    _prioridade_alta()

    if VOICE_ENABLED:
        try:
            pygame.mixer.init()
            BIP = _gerar_bip()
        except Exception as e:
            print(f"[voz] Sem saída de som pelo pygame ({e}).")
    # A voz carrega em paralelo com o resto (o Piper leva alguns segundos)
    threading.Thread(target=_thread_sintese, daemon=True).start()
    threading.Thread(target=_thread_reproducao, daemon=True).start()

    APPS = inventario.listar_apps_rapido()
    if APPS:
        print(f"[apps] {len(APPS)} programas encontrados no Menu Iniciar.")
    elif platform.system() == "Windows":
        print("[apps] Nenhum programa listado. Usando a lista básica (Chrome, Word, Excel...).")

    if not TEST_MODE:
        import cerebro as modulo_cerebro
        cerebro = modulo_cerebro.Cerebro(
            ASSISTANT_NAME, APPS, NOME_USUARIO,
            api_key=ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY"),
        )
        threading.Thread(target=cerebro.aquecer, daemon=True).start()

    threading.Thread(target=_thread_tarefas, daemon=True).start()

    calibrar_microfone()
    # A palavra de ativação só aparece no terminal: se fosse falada, o microfone poderia captá-la
    print(f"Diga '{WAKE_WORD}' seguido do comando. Ctrl+C para sair.")
    falar(f"{ASSISTANT_NAME} online. Às suas ordens.")

    threading.Thread(target=_thread_escuta, daemon=True).start()
    threading.Thread(target=_thread_transcricao, daemon=True).start()

    JANELA_SEGUNDOS = 60    # tempo em que aceita comandos sem a palavra de ativação
    ativo_ate = 0
    modo_continuo = False   # True = escuta tudo até você dizer "pode dormir"

    try:
        while True:
            try:
                texto = fila_textos.get(timeout=0.5)   # com timeout, o Ctrl+C funciona no Windows
            except queue.Empty:
                continue

            disse_wake_word, depois_da_ativacao = separar_ativacao(texto)

            # Uma ação está esperando "sim" ou "não": a resposta vai para ela, não vira comando
            if aguardando_confirmacao.is_set():
                fila_confirmacoes.put(depois_da_ativacao if disse_wake_word else texto)
                continue

            if disse_wake_word:
                comando_texto = depois_da_ativacao
            elif modo_continuo or time.time() < ativo_ate:
                comando_texto = texto
            else:
                continue

            # Comandos de controle (não gastam API)
            if _MODO_CONTINUO.search(comando_texto):
                modo_continuo = True
                falar("Modo contínuo ativado. Vou ouvir até você dizer: pode dormir.")
                continue

            if _PODE_DORMIR.search(comando_texto):
                modo_continuo = False
                ativo_ate = 0
                falar("Certo, só volto a responder quando você me chamar.")
                continue

            if not comando_texto:
                tocar_bip()   # só a palavra de ativação: o bip avisa que pode falar
                ativo_ate = time.time() + JANELA_SEGUNDOS
                continue

            # Se já tem tarefa rodando, avisa que entrou na fila
            if ocupado.is_set() or not fila_tarefas.empty():
                falar("Pode deixar, já coloquei na fila.")

            # No modo contínuo, só vai para a nuvem o que começou com a palavra de ativação
            # (evita guardar conversas de outras pessoas captadas pelo microfone).
            deve_salvar = disse_wake_word or not modo_continuo
            fila_tarefas.put((comando_texto, deve_salvar))
            ativo_ate = time.time() + JANELA_SEGUNDOS

    except KeyboardInterrupt:
        falar("Até logo!", esperar=True)


if __name__ == "__main__":
    main()
