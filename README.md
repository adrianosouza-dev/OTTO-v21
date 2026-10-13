# OTTO-V21 — Assistente de Voz para Windows

Assistente de voz que roda no seu notebook. Você fala um comando, ele entende
usando o Claude (API da Anthropic), executa a ação no computador e responde com
uma voz natural em português (Piper).

Ele abre qualquer programa do Menu Iniciar (inclusive apps da Microsoft Store),
abre pastas e telas de configuração do Windows, pesquisa na web, responde perguntas
e lembra das conversas anteriores.

> Feito para **Windows**. Em Mac/Linux a parte de voz e IA funciona, mas a abertura
> de programas usa só uma lista básica e as telas de configuração não funcionam.

---

## Como funciona

```
Microfone ──► Google Speech (fala → texto)
                │
                ▼
     Tem a palavra de ativação "storm"?  (ou está na janela de 60 s / modo contínuo)
                │ sim
                ▼
     Fila de tarefas ──► (em segundo plano)
                           1. Busca contexto na memória (Supabase ou memory.json)
                           2. Envia ao Claude: regras + programas instalados + histórico + pedido
                           3. Claude escolhe UMA ação e uma frase de resposta (JSON)
                           4. Executa a ação no notebook
                           5. Fala a resposta (Piper) e salva na memória
```

- O microfone **continua ouvindo enquanto ele executa**. Pedidos novos entram numa fila.
- A voz e as tarefas rodam em threads separadas.
- A voz é gerada **frase por frase**: ele começa a falar antes de terminar de gerar o áudio todo.
- Se ele estava falando enquanto o microfone gravava, o áudio é descartado
  (para não responder à própria voz), a não ser que contenha a palavra de ativação.
- O terminal mostra o tempo de cada etapa (`[tempo] Google`, `[tempo] Supabase`,
  `[tempo] Claude`, `[tempo] Piper`) para ajudar a achar o que está lento.

### Arquivos

| Arquivo | Função |
|---|---|
| `assistant.py` | Núcleo: microfone, voz, conversa com o Claude, ações e loop principal |
| `inventario.py` | Lista os programas do Menu Iniciar e abre programas, pastas e configurações |
| `memoria.py` | Memória permanente no Supabase, com `memory.json` como reserva |
| `config_exemplo.py` | Modelo de configuração. Copie para `config.py` |
| `config.py` | Suas configurações e chaves (**não vai para o git**) |
| `pt_BR-faber-medium.onnx` + `.onnx.json` | Voz do Piper (**não vai para o git**, baixe no passo 5) |
| `requirements.txt` | Dependências Python |

---

## O que ele faz

| Ação | Exemplo de fala | O que acontece |
|---|---|---|
| Responder | "storm, quem descobriu o Brasil?" | Responde em voz |
| Abrir programa | "storm, abre o WhatsApp" | Abre qualquer app do Menu Iniciar |
| Abrir pasta | "storm, abre meus downloads" | Abre a pasta no Explorer |
| Abrir configuração | "storm, abre o bluetooth" | Abre a tela do Windows |
| Pesquisar | "storm, pesquisa receita de bolo" | Abre a pesquisa no Google |
| Abrir site | "storm, abre o YouTube" | Abre o site no navegador |
| Comando de terminal | "storm, mostra meu IP" | Executa um comando simples (a saída aparece só no terminal) |

### Programas
Ao iniciar, ele lê a lista de programas do **Menu Iniciar** (até 400) e envia ao Claude.
Abre programas tradicionais e **apps da Microsoft Store** (Fotos, WhatsApp, Spotify,
Calculadora, Xbox…). Ele aceita nomes aproximados ("galeria" → Fotos).

Não abre programas sem atalho no Menu Iniciar (um `.exe` solto numa pasta, por exemplo).

### Pastas
Downloads, Documentos, Área de Trabalho, Imagens, Vídeos e Músicas (também dentro
da OneDrive), ou um caminho completo.

### Configurações do Windows
Wi-Fi, rede, Bluetooth, som, tela, bateria, Windows Update, aplicativos,
notificações, impressoras e geral. Outros pedidos abrem a tela geral.

### Memória
Cada comando é salvo. Antes de responder, ele busca as 5 últimas falas e até 5 falas
parecidas com o pedido atual, e assim entende referências como "aquela pesquisa".

---

## Como ativar

| Forma | Como usar |
|---|---|
| **Palavra de ativação** | "**storm**, abre o Chrome". Também aceita "estorm", "istorm" e "storme", que são erros comuns de transcrição |
| **Só a palavra** | "storm" → ele responde "Pode falar" e espera o comando |
| **Janela de 60 s** | Depois de cada comando, aceita outro **sem** dizer "storm" por 60 segundos |
| **Modo contínuo** | Diga "storm, **modo contínuo**": ele ouve tudo até você dizer "**pode dormir**" |

Para sair: `Ctrl+C` no terminal.

---

## Instalação

### 1. Python
Python **3.10 ou mais novo** (o projeto foi testado com 3.12): https://www.python.org/downloads/

### 2. Ambiente virtual
Na pasta do projeto:
```powershell
python -m venv venv
venv\Scripts\activate
```

### 3. Dependências
```powershell
pip install -r requirements.txt
```
No Windows o `PyAudio` costuma instalar direto pelo pip.

### 4. Configuração
Copie o modelo e edite:
```powershell
copy config_exemplo.py config.py
```

### 5. Voz do Piper
Na pasta do projeto, com o ambiente virtual ativado:
```powershell
python -m piper.download_voices pt_BR-faber-medium
```
Isso baixa `pt_BR-faber-medium.onnx` e `pt_BR-faber-medium.onnx.json` (cerca de 60 MB).
Os dois arquivos precisam ficar **na mesma pasta do `assistant.py`**.

Se a voz não for encontrada, ele avisa no terminal e usa a voz do Windows (`pyttsx3`).

### 6. Chave da Anthropic
Crie uma chave em https://console.anthropic.com.

**Recomendado:** defina a chave como variável de ambiente e deixe `ANTHROPIC_API_KEY = ""` no `config.py`:
```powershell
setx ANTHROPIC_API_KEY "sua-chave-aqui"
```
Feche e abra o terminal depois do `setx`.

### 7. Memória no Supabase (opcional)
Sem Supabase, ele guarda a memória em `memory.json`, na pasta de onde você rodar o script.

Para usar o Supabase:

1. Crie um projeto em https://supabase.com.
2. No **SQL Editor**, crie a tabela:
   ```sql
   create table falas (
     id         bigint generated always as identity primary key,
     comando    text,
     acao       text,
     argumento  text,
     resposta   text,
     criado_em  timestamptz not null default now()
   );
   ```
3. Defina as variáveis de ambiente (e deixe `SUPABASE_URL`/`SUPABASE_KEY` vazios no `config.py`):
   ```powershell
   setx SUPABASE_URL "https://SEU-PROJETO.supabase.co"
   setx SUPABASE_KEY "sua-chave"
   ```

Se o Supabase falhar, ele usa o `memory.json` automaticamente e continua funcionando.

### 8. Rodar
Com o ambiente virtual ativado:
```powershell
python assistant.py
```

---

## Configuração

### `config.py`

| Opção | Para que serve |
|---|---|
| `WAKE_WORD` | Palavra de ativação (minúsculas). Padrão: `"storm"` |
| `ASSISTANT_NAME` | Nome que ele usa para se apresentar. Padrão: `"OTTO-V21"` |
| `VOICE_ENABLED` | `False` = responde só por texto no terminal |
| `TEST_MODE` | `True` = não chama a API; usa palavras-chave simples (navegador, calculadora, pesquisa) |
| `ANTHROPIC_API_KEY` | Chave da Anthropic (prefira a variável de ambiente) |
| `SUPABASE_URL` / `SUPABASE_KEY` | Dados do Supabase (prefira variáveis de ambiente) |

### No início do `assistant.py`

| Opção | Para que serve |
|---|---|
| `MODELO` | Modelo do Claude usado. Padrão: `claude-haiku-5-5` (rápido e barato) |
| `VARIACOES_ATIVACAO` | Variações aceitas da palavra de ativação. Se trocar o `WAKE_WORD`, troque aqui também |
| `CAMINHO_VOZ` | Arquivo `.onnx` da voz do Piper |
| `VELOCIDADE_VOZ` | Velocidade da fala: menor = mais rápido (`0.8`), maior = mais devagar (`1.1`). Padrão: `0.9` |

---

## ⚠️ Segurança e privacidade

- **Não deixe chaves dentro do `config.py`** se for compartilhar a pasta. O `config.py`
  já está no `.gitignore`, mas variáveis de ambiente são mais seguras.
  A chave secreta do Supabase (`sb_secret_...`) dá acesso total ao banco.
- O `memory.json` guarda tudo o que você falou. Ele **ainda não está no `.gitignore`**:
  não faça commit dele.
- A ação de **comando de terminal** executa o que o Claude decidir. O prompt proíbe
  comandos destrutivos, mas **não há bloqueio no código**.
- No **modo contínuo** e na **janela de 60 s**, qualquer voz perto do microfone (TV,
  outras pessoas) pode virar comando. Os comandos ditos no modo contínuo sem a palavra
  de ativação são executados, mas não são salvos na memória.
- Tudo o que o microfone capta enquanto ele está ouvindo é enviado ao Google
  (transcrição); os comandos vão para a Anthropic (IA) e, se configurado, para o Supabase.

---

## Limitações conhecidas

- **Precisa de internet** para transcrever a voz, chamar o Claude e usar o Supabase.
  A voz (Piper) funciona offline.
- **Uma ação por pedido**: "abre o Chrome e pesquisa X" executa só uma delas.
- Não **fecha** programas e não controla **volume, brilho ou música**.
- Não cria **timers, alarmes ou lembretes**.
- Não sabe **data, hora, clima nem notícias** (a pesquisa só abre o Google, sem ler o resultado).
- Não **fala o resultado** de comandos de terminal.
- Termos de pesquisa com `&` ou `#` são cortados.
- Se o Claude responder com texto fora do JSON, o pedido vira "Não entendi o comando".
- A mensagem de abertura contém a palavra "storm" e pode ser captada pelo próprio
  microfone como um comando.

---

## Próximos passos

- **Segurança**: confirmação por voz antes de comandos de terminal; aceitar só
  `http(s)` em "abrir site"; `memory.json` no `.gitignore`.
- **Virar um agente**: tool use nativo da API, com várias ações por pedido e respostas
  baseadas no resultado do que foi feito.
- **Busca na web com resposta falada** e **data/hora** no prompt.
- **Reconhecimento offline**: faster-whisper, e um detector de palavra de ativação
  (openWakeWord / Porcupine).
- **Novas ações**: fechar programas, volume/mídia, timers, abrir arquivos.
- **Prompt caching** para a lista de programas, reduzindo custo e tempo de resposta.
