# OTTO-V21 — Assistente de Voz para Windows

Assistente de voz que roda no seu notebook, no estilo do JARVIS. Você fala um pedido,
o Claude (API da Anthropic) decide o que fazer, usa as ferramentas que precisar no
computador, vê o resultado e responde com uma voz natural em português (Piper).

Ele abre qualquer programa do Menu Iniciar (inclusive apps da Microsoft Store),
abre pastas e telas de configuração do Windows, pesquisa na internet e **responde com
o que encontrou**, roda comandos simples no terminal (com sua confirmação por voz),
sabe a data e a hora, mantém a conversa e lembra das conversas anteriores.

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
                           1. Conversa nova? Busca contexto na memória (Supabase ou memory.json)
                           2. Envia ao Claude: data/hora + histórico + pedido
                           3. O Claude usa ferramentas (abrir app, buscar na web, terminal...)
                              ◄── vê o resultado de cada uma e decide o próximo passo
                           4. Fala a resposta final (Piper) e salva na memória
```

- **Várias ações por pedido**: "abre a calculadora e o bloco de notas" abre os dois.
- **Ele vê o resultado do que fez**: "qual é o meu IP?" roda o comando e fala o IP.
- **Conversa contínua**: depois de "como está o tempo hoje?", basta dizer "e amanhã?".
  A conversa recomeça depois de 5 minutos parada.
- O microfone **continua ouvindo enquanto ele trabalha**. Pedidos novos entram numa fila.
- A voz é gerada **frase por frase**: ele começa a falar antes de terminar de gerar o áudio todo.
- Se ele estava falando enquanto o microfone gravava, o áudio é descartado
  (para não responder à própria voz), a não ser que contenha a palavra de ativação.
- O terminal mostra o tempo de cada etapa (`[tempo] Google`, `[tempo] Claude`,
  `[tempo] Piper`) e cada ação feita (`[ação] ...`).

### Arquivos

| Arquivo | Função |
|---|---|
| `assistant.py` | Microfone, voz, confirmação por voz, filas e loop principal |
| `cerebro.py` | Conversa com o Claude: prompt, ferramentas, histórico da conversa |
| `acoes.py` | As ferramentas que o Claude pode usar, com as regras de segurança |
| `inventario.py` | Lista os programas do Menu Iniciar e abre programas, pastas e configurações |
| `memoria.py` | Memória permanente no Supabase, com `memory.json` como reserva |
| `config_exemplo.py` | Modelo de configuração. Copie para `config.py` |
| `config.py` | Suas configurações e chaves (**não vai para o git**) |
| `pt_BR-faber-medium.onnx` + `.onnx.json` | Voz do Piper (**não vai para o git**, baixe no passo 5) |
| `requirements.txt` | Dependências Python |

---

## O que ele faz

| Ferramenta | Exemplo de fala | O que acontece |
|---|---|---|
| Conversar | "storm, quem descobriu o Brasil?" | Responde em voz |
| Buscar na web | "storm, como está o tempo em São Paulo?" | Pesquisa na internet e **fala a resposta** |
| Abrir programa | "storm, abre o WhatsApp" | Abre qualquer app do Menu Iniciar |
| Abrir pasta | "storm, abre meus downloads" | Abre a pasta no Explorer |
| Abrir configuração | "storm, abre o bluetooth" | Abre a tela do Windows |
| Abrir site | "storm, abre o YouTube" | Abre o site no navegador |
| Pesquisar no navegador | "storm, abre no Google receitas de bolo" | Abre a pesquisa na tela |
| Comando de terminal | "storm, qual é o meu IP?" | Pede confirmação, executa e fala o resultado |

Ele também sabe **a data e a hora**, e pode combinar ferramentas num mesmo pedido.

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
notificações, impressoras e geral.

### Comandos de terminal
Antes de rodar qualquer comando, ele pergunta: *"Posso executar um comando para ...?"*.
Responda **"sim"** (ou "pode", "claro", "confirmo") em até 20 segundos. Qualquer outra
resposta, ou silêncio, cancela.

Alguns comandos são **bloqueados sempre**, mesmo com confirmação: os que apagam, movem,
copiam ou renomeiam arquivos, mexem no registro, em usuários, em serviços ou em tarefas
agendadas, desligam o computador, baixam arquivos, abrem outro PowerShell, gravam em
arquivo (`>`) ou encadeiam comandos (`&`).

### Memória
Cada pedido é salvo, com as ferramentas usadas. Ao começar uma conversa nova, ele busca
as 5 últimas falas e até 5 falas parecidas com o pedido, e assim entende referências
como "aquela pesquisa de ontem".

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

A busca na web é cobrada à parte pela Anthropic, por pesquisa feita. Se ela não estiver
liberada na sua organização, ative em https://console.anthropic.com (configurações de
privacidade / ferramentas).

### 7. Memória no Supabase (opcional)
Sem Supabase, ele guarda a memória em `memory.json`, na pasta do projeto.

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
Ao iniciar, ele calibra o microfone por 1 segundo: fique em silêncio.

---

## Configuração

### `config.py`

| Opção | Para que serve |
|---|---|
| `WAKE_WORD` | Palavra de ativação (minúsculas). Padrão: `"storm"` |
| `ASSISTANT_NAME` | Nome que ele usa para se apresentar. Padrão: `"OTTO-V21"` |
| `NOME_USUARIO` | Opcional: como ele deve te chamar |
| `VOICE_ENABLED` | `False` = responde só por texto no terminal |
| `TEST_MODE` | `True` = não chama a API; usa palavras-chave simples (navegador, calculadora, pesquisa) |
| `ANTHROPIC_API_KEY` | Chave da Anthropic (prefira a variável de ambiente) |
| `SUPABASE_URL` / `SUPABASE_KEY` | Dados do Supabase (prefira variáveis de ambiente) |

### No início do `cerebro.py`

| Opção | Para que serve |
|---|---|
| `MODELO` | Modelo do Claude. Padrão: `claude-haiku-5-5` (rápido e barato) |
| `ESFORCO` | Quanto o modelo pensa antes de responder: `low` (padrão, mais rápido), `medium` ou `high` |
| `CONVERSA_EXPIRA_SEGUNDOS` | Depois de quanto tempo parado ele começa uma conversa nova. Padrão: 300 |
| `MAX_PASSOS` | Limite de idas e voltas com ferramentas por pedido. Padrão: 8 |

### No início do `assistant.py`

| Opção | Para que serve |
|---|---|
| `VARIACOES_ATIVACAO` | Variações aceitas da palavra de ativação. Se trocar o `WAKE_WORD`, troque aqui também |
| `CAMINHO_VOZ` | Arquivo `.onnx` da voz do Piper |
| `VELOCIDADE_VOZ` | Velocidade da fala: menor = mais rápido (`0.8`), maior = mais devagar (`1.1`). Padrão: `0.9` |

### Custo e velocidade
O prompt (com a lista de programas) e a conversa ficam em **cache** na Anthropic. O
primeiro pedido depois de ligar demora mais (cerca de 10 s); os seguintes costumam
levar de 1 a 3 s, e as buscas na web de 5 a 6 s. O terminal mostra quantos tokens vieram
do cache em cada chamada.

---

## ⚠️ Segurança e privacidade

- **Não deixe chaves dentro do `config.py`** se for compartilhar a pasta. O `config.py`
  já está no `.gitignore`, mas variáveis de ambiente são mais seguras.
  A chave secreta do Supabase (`sb_secret_...`) dá acesso total ao banco.
- O `memory.json` guarda tudo o que você falou. Ele está no `.gitignore`.
- **Comandos de terminal** sempre pedem confirmação por voz, e os perigosos são
  bloqueados no código (veja *Comandos de terminal*). A lista de bloqueio reduz o risco,
  mas não é perfeita: confirme só o que você entendeu.
- "Abrir site" aceita só endereços `http://` e `https://`.
- No **modo contínuo** e na **janela de 60 s**, qualquer voz perto do microfone (TV,
  outras pessoas) pode virar pedido. Os pedidos ditos no modo contínuo sem a palavra
  de ativação são executados, mas não são salvos na memória.
- Tudo o que o microfone capta enquanto ele está ouvindo é enviado ao Google
  (transcrição); os pedidos vão para a Anthropic (IA) e, se configurado, para o Supabase.

---

## Limitações conhecidas

- **Precisa de internet** para transcrever a voz, chamar o Claude e usar o Supabase.
  A voz (Piper) funciona offline.
- Não **fecha** programas e não controla **volume, brilho ou música**.
- Não cria **timers, alarmes ou lembretes**.
- Não **vê a tela** e não lê arquivos.
- Não pode ser **interrompido** enquanto fala.
- A confirmação de comandos depende do reconhecimento de voz: se ele não entender o
  "sim", o comando é cancelado.

---

## Próximos passos

- **Ouvido**: palavra de ativação detectada no próprio PC (openWakeWord), transcrição
  offline mais rápida (faster-whisper) e interrupção enquanto ele fala.
- **Controle do PC**: volume e mídia, fechar programas, janelas, timers e lembretes,
  achar arquivos, ver a tela.
- **Memória de verdade**: fatos sobre você ("lembra que...") e busca por significado.
- **Proatividade e integrações**: resumo da manhã, agenda, e-mail, Spotify, casa inteligente.
- **Presença**: ícone na bandeja, painel visual e início junto com o Windows.
