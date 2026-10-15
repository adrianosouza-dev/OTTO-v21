"""
Assistente de voz local com memória permanente (Supabase).

Fluxo:
  1. Escuta o microfone e transcreve (SpeechRecognition + Google Web Speech)
  2. Coloca o comando numa fila e volta a escutar na hora
  3. Em segundo plano: o cérebro (Claude com ferramentas) decide o que fazer, age no notebook,
     vê o resultado e responde em voz; o pedido é salvo na memória
"""

import io
import json
import os
import platform
import queue
import re
import threading
import time
import wave

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


def separar_ativacao(texto):
    """Retorna (disse_ativacao, comando). O comando é o que vem depois da palavra de ativação."""
    achou = _PADRAO_ATIVACAO.search(texto)
    if not achou:
        return False, texto
    return True, texto[achou.end():].strip(" ,.")


# ---------------------------------------------------------------------------
# Configuração inicial
# ---------------------------------------------------------------------------

recognizer = sr.Recognizer()
microphone = sr.Microphone()

# Filas: uma para o que deve ser falado, outra para as tarefas a executar
fila_falas = queue.Queue()
fila_tarefas = queue.Queue()
fila_confirmacoes = queue.Queue()   # respostas de "sim/não" quando uma ação pede confirmação

falando = threading.Event()      # ligado enquanto o assistente está falando
ocupado = threading.Event()      # ligado enquanto uma tarefa está sendo executada
aguardando_confirmacao = threading.Event()
ultima_fala_fim = 0.0            # quando a última fala terminou

APPS = []        # programas instalados (preenchido ao iniciar, só no Windows)
cerebro = None   # criado no main() (não existe no TEST_MODE)


# ---------------------------------------------------------------------------
# Voz
# ---------------------------------------------------------------------------

CAMINHO_VOZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pt_BR-faber-medium.onnx")
VELOCIDADE_VOZ = 0.9   # menor = mais rápido (ex: 0.8), maior = mais devagar (ex: 1.1)

def _pedaco_para_som(pedaco):
    """Embrulha o áudio do Piper num WAV na memória, para o pygame converter o formato sozinho."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(pedaco.sample_channels)
        wav.setsampwidth(pedaco.sample_width)
        wav.setframerate(pedaco.sample_rate)
        wav.writeframes(pedaco.audio_int16_bytes)
    buffer.seek(0)
    return pygame.mixer.Sound(file=buffer)


def _falar_piper(voz, texto, estado):
    """Gera a voz frase por frase e já vai tocando, sem esperar o áudio inteiro."""
    config_voz = SynthesisConfig(length_scale=VELOCIDADE_VOZ)
    canal = None
    t = time.time()
    for pedaco in voz.synthesize(texto, syn_config=config_voz):
        som = _pedaco_para_som(pedaco)
        if canal is None:
            print(f"[tempo] Piper (primeira frase): {time.time() - t:.1f}s")
            canal = som.play()
            estado["tocou"] = True
        else:
            while canal.get_queue() is not None:   # espera a fila liberar
                time.sleep(0.01)
            canal.queue(som)                        # toca logo depois da frase atual
    while canal is not None and canal.get_busy():
        time.sleep(0.05)


def _thread_voz():
    """Única thread que fala. Usa o Piper; se der problema, usa o pyttsx3."""
    global ultima_fala_fim

    try:
        voz_piper = PiperVoice.load(CAMINHO_VOZ)
        pygame.mixer.init()   # o pygame converte o áudio da voz para o formato da placa de som
    except Exception as e:
        print(f"[voz] Não consegui carregar a voz do Piper ({e}). Usando pyttsx3.")
        voz_piper = None

    engine = None
    while True:
        texto = fila_falas.get()
        falando.set()
        estado = {"tocou": False}
        try:
            if voz_piper is not None:
                _falar_piper(voz_piper, texto, estado)
            else:
                raise RuntimeError("Piper indisponível")
        except Exception as e:
            if voz_piper is not None:
                print(f"[voz] Piper falhou ({e}).")
            if not estado["tocou"]:   # só repete no pyttsx3 se nada foi falado ainda
                try:
                    if engine is None:
                        engine = pyttsx3.init()
                        engine.setProperty("rate", 175)
                    engine.say(texto)
                    engine.runAndWait()
                except Exception as e2:
                    print(f"Erro na voz: {e2}")
        finally:
            ultima_fala_fim = time.time()
            falando.clear()
            fila_falas.task_done()


def falar(texto, esperar=False):
    """Mostra o texto e manda para a fila de voz. Não trava quem chamou (a não ser com esperar=True)."""
    print(f"{ASSISTANT_NAME}: {texto}")
    if VOICE_ENABLED and texto:
        fila_falas.put(texto)
        if esperar:
            fila_falas.join()


def calibrar_microfone():
    with microphone as source:
        print("Calibrando o microfone (fique em silêncio)...")
        recognizer.adjust_for_ambient_noise(source, duration=1)


def ouvir():
    with microphone as source:
        print("Ouvindo...")
        try:
            # phrase_time_limit: com barulho constante, a gravação não fica presa para sempre
            audio = recognizer.listen(source, timeout=10, phrase_time_limit=15)
        except sr.WaitTimeoutError:
            return ""
    try:
        t = time.time()
        texto = recognizer.recognize_google(audio, language="pt-BR")
        print(f"[tempo] Google (voz → texto): {time.time() - t:.1f}s")
        print(f"Você disse: {texto}")
        return texto.lower()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        falar("Não consegui acessar o serviço de reconhecimento de voz.")
        print(f"Erro no reconhecimento: {e}")
        return ""


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
        return f"Modo de teste. Eu te ouvi dizer: {texto}.", []

    resultado, _ = acoes.executar(acao, entrada, APPS, confirmar)
    return resultado, [{"ferramenta": acao, "entrada": entrada}]


# ---------------------------------------------------------------------------
# Tarefas em segundo plano
# ---------------------------------------------------------------------------

def _thread_tarefas():
    """Pega os comandos da fila, um por vez, e executa enquanto o microfone continua ouvindo."""
    while True:
        comando_texto, deve_salvar = fila_tarefas.get()
        ocupado.set()
        try:
            if TEST_MODE:
                fala, feitas = responder_teste(comando_texto)
            else:
                fala, feitas = cerebro.responder(comando_texto, confirmar, avisar=falar)
            falar(fala)
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


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def main():
    global APPS, cerebro
    APPS = inventario.listar_apps()
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

    threading.Thread(target=_thread_voz, daemon=True).start()
    threading.Thread(target=_thread_tarefas, daemon=True).start()

    calibrar_microfone()
    # A palavra de ativação só aparece no terminal: se fosse falada, o microfone poderia captá-la
    print(f"Diga '{WAKE_WORD}' seguido do comando. Ctrl+C para sair.")
    falar(f"{ASSISTANT_NAME} online. Às suas ordens.")

    JANELA_SEGUNDOS = 60    # tempo em que aceita comandos sem a palavra de ativação
    ativo_ate = 0
    modo_continuo = False   # True = escuta tudo até você dizer "pode dormir"

    while True:
        try:
            inicio_escuta = time.time()
            texto = ouvir()
            if not texto:
                continue

            # Se o assistente falou enquanto o microfone gravava, o áudio pode ser a própria voz dele.
            # Nesse caso só aceita se tiver a palavra de ativação.
            ouviu_a_propria_voz = falando.is_set() or ultima_fala_fim > inicio_escuta

            disse_wake_word, depois_da_ativacao = separar_ativacao(texto)

            # Uma ação está esperando "sim" ou "não": a resposta vai para ela, não vira comando
            if aguardando_confirmacao.is_set():
                if disse_wake_word or not ouviu_a_propria_voz:
                    fila_confirmacoes.put(depois_da_ativacao if disse_wake_word else texto)
                continue

            if disse_wake_word:
                comando_texto = depois_da_ativacao
            elif ouviu_a_propria_voz:
                continue
            elif modo_continuo or time.time() < ativo_ate:
                comando_texto = texto
            else:
                continue

            # Comandos de controle (não gastam API)
            if "modo contínuo" in comando_texto or "modo continuo" in comando_texto:
                modo_continuo = True
                falar("Modo contínuo ativado. Vou ouvir até você dizer: pode dormir.")
                continue

            if "pode dormir" in comando_texto:
                modo_continuo = False
                ativo_ate = 0
                falar("Certo, só volto a responder quando você me chamar.")
                continue

            if not comando_texto:
                falar("Pode falar, estou ouvindo.")
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
            break


if __name__ == "__main__":
    main()
