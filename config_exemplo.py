"""
Configurações do assistente.

Você pode colocar sua chave de API aqui OU (mais seguro) definir a variável
de ambiente ANTHROPIC_API_KEY no seu sistema e deixar ANTHROPIC_API_KEY = ""
"""

ANTHROPIC_API_KEY = ""  # cole sua chave aqui, ou deixe em branco e use variável de ambiente

WAKE_WORD = "storm"     # palavra que ativa o assistente (tudo em minúsculo)
ASSISTANT_NAME = "OTTO-V21"
VOICE_ENABLED = True     # False = só responde por texto no terminal, sem falar

TEST_MODE = False        # false = usa a API de verdade

SUPABASE_URL = ""    # cole a sua URL do supabase 
SUPABASE_KEY = ""   # cole a sua chave do supabase