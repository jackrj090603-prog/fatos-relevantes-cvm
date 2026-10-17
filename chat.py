import re
import os
import storage
import llm
import telegram_bot
import config

BOT_USERNAME = "@CEARA_FINANCE_BOT"

def extrair_ticker_ou_empresa(texto):
    """
    Identifica tickers (ex: PETR4, VALE3, DIRR3) ou nomes de empresas brasileiras
    mencionados no texto da mensagem do usuário.
    """
    if not texto:
        return ""
        
    # 1. Regex de ticker da B3 (4 letras + 1 ou 2 números)
    match_ticker = re.search(r"\b([A-Z]{4}(?:3|4|5|6|11|34))\b", texto.upper())
    if match_ticker:
        return match_ticker.group(1)
        
    # 2. Mapeamento de termos comuns / apelidos populares
    apelidos = {
        "PETROBRAS": "PETR4",
        "PETRO": "PETR4",
        "VALE": "VALE3",
        "ITAU": "ITUB4",
        "ITAÚ": "ITUB4",
        "BRADESCO": "BBDC4",
        "BANCO DO BRASIL": "BBAS3",
        "MAGALU": "MGLU3",
        "MAGAZINE LUIZA": "MGLU3",
        "DIRECIONAL": "DIRR3",
        "WEG": "WEGE3",
        "LOCALIZA": "RENT3",
        "PRIO": "PRIO3",
        "PETRORIO": "PRIO3",
        "SUZANO": "SUZB3",
        "AMBEV": "ABEV3",
        "HAPVIDA": "HAPV3",
        "JBS": "JBSS3",
        "EMBRAER": "EMBR3",
        "M. DIAS": "MDIA3",
        "MDIAS": "MDIA3",
        "DIAS BRANCO": "MDIA3",
        "TAESA": "TAEE11",
        "ENGIE": "EGIE3",
        "ELETROBRAS": "ELET3",
        "SANTANDER": "SANB11"
    }
    
    texto_upper = texto.upper()
    for nome, ticker in apelidos.items():
        if nome in texto_upper:
            return ticker
            
    # 3. Busca nas empresas cadastradas no catálogo
    try:
        empresas = config.carregar_empresas()
        for emp in empresas:
            nome_emp = emp.get("nome", "").upper()
            if len(nome_emp) > 5 and nome_emp[:12] in texto_upper:
                return emp.get("ticker", "")
    except Exception:
        pass
        
    return ""

def buscar_documentos_relacionados(pergunta, limit=4):
    """
    Localiza os documentos regulatórios mais relevantes na base oficial da CVM (36.000+ docs)
    e na base de Fatos Relevantes processados com IA.
    """
    termo = extrair_ticker_ou_empresa(pergunta)
    
    if termo:
        docs = storage.buscar_documentos_por_termo(termo, limit=limit)
        if docs:
            return docs
            
    # Se não identificou ticker específico, faz busca por palavras-chave
    palavras = [p.lower().strip() for p in re.findall(r"\w{4,}", pergunta) if p.lower() not in ["quais", "qual", "como", "sobre", "últimos", "ultimos", "fatos", "fato", "relevante", "resumo"]]
    
    if palavras:
        termo_busca = palavras[0]
        docs = storage.buscar_documentos_por_termo(termo_busca, limit=limit)
        if docs:
            return docs
            
    # Fallback: retorna os documentos mais recentes do banco
    return storage.get_todos_documentos(limit=limit)

def get_start_inline_keyboard():
    """Retorna os botões de 1 clique para iniciar e consultar rapidamente."""
    return {
        "inline_keyboard": [
            [
                {"text": "🏢 PETR4 (Petrobras)", "callback_data": "PETR4"},
                {"text": "🪨 VALE3 (Vale)", "callback_data": "VALE3"}
            ],
            [
                {"text": "🏗️ DIRR3 (Direcional)", "callback_data": "DIRR3"},
                {"text": "⚡ WEGE3 (WEG)", "callback_data": "WEGE3"}
            ],
            [
                {"text": "🏦 ITUB4 (Itaú)", "callback_data": "ITUB4"},
                {"text": "🌾 JBSS3 (JBS)", "callback_data": "JBSS3"}
            ],
            [
                {"text": "📢 Canal Oficial de Alertas", "url": "https://t.me/+T1V2m44be_Q3MjYx"}
            ],
            [
                {"text": "🌐 Portal Web CVM", "url": "https://fatos-relevantes-cvm.onrender.com"}
            ]
        ]
    }

def get_ticker_inline_keyboard():
    """Botões de 1 clique para consultas rápidas seguintes."""
    return {
        "inline_keyboard": [
            [
                {"text": "🏢 PETR4", "callback_data": "PETR4"},
                {"text": "🪨 VALE3", "callback_data": "VALE3"},
                {"text": "🏗️ DIRR3", "callback_data": "DIRR3"}
            ],
            [
                {"text": "⚡ WEGE3", "callback_data": "WEGE3"},
                {"text": "🏦 ITUB4", "callback_data": "ITUB4"},
                {"text": "🌾 JBSS3", "callback_data": "JBSS3"}
            ],
            [
                {"text": "📢 Canal Alertas", "url": "https://t.me/+T1V2m44be_Q3MjYx"},
                {"text": "🌐 Portal Web", "url": "https://fatos-relevantes-cvm.onrender.com"}
            ]
        ]
    }

def responder_updates():
    """
    Lê novas mensagens e cliques de botões enviados ao @CEARA_FINANCE_BOT,
    interpreta o pedido, consulta a base da CVM e responde via IA (Gemini 3.1).
    """
    ultimo_offset_chave = "telegram_chat_offset"
    conn = storage.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT valor FROM estado WHERE chave = ?", (ultimo_offset_chave,))
    row = cursor.fetchone()
    offset = int(row["valor"]) if row and row["valor"] else None
    
    updates = telegram_bot.ler_updates(offset=offset)
    if not updates:
        conn.close()
        return 0
        
    respostas_enviadas = 0
    
    for update in updates:
        update_id = update.get("update_id")
        
        # Incrementar e persistir offset imediatamente para evitar loops
        next_offset = update_id + 1
        cursor.execute("INSERT OR REPLACE INTO estado (chave, valor) VALUES (?, ?)", (ultimo_offset_chave, str(next_offset)))
        conn.commit()
        
        # Ignorar posts de canais (onde o bot publica comunicados) para não criar loops
        if "channel_post" in update or "edited_channel_post" in update:
            continue
            
        # Suporte a cliques de botões interativos (callback_query)
        if "callback_query" in update:
            cq = update["callback_query"]
            cq_id = cq.get("id")
            cq_data = cq.get("data", "").strip()
            msg_obj = cq.get("message", {})
            chat = msg_obj.get("chat", {})
            chat_id = chat.get("id")
            chat_type = chat.get("type", "private")
            user_info = cq.get("from", {})
            first_name = user_info.get("first_name", "Investidor")
            
            telegram_bot.answer_callback_query(cq_id, f"Consultando {cq_data} na CVM...")
            text = cq_data
        elif "message" in update or "edited_message" in update:
            message = update.get("message") or update.get("edited_message")
            if not message:
                continue
            chat = message.get("chat", {})
            chat_id = chat.get("id")
            chat_type = chat.get("type", "private") # private, group, supergroup
            user_info = message.get("from", {})
            first_name = user_info.get("first_name", "Investidor")
            text = message.get("text", "").strip()
        else:
            continue
            
        if not text or not chat_id:
            continue
            
        # Tratamento especial para Grupos: só responder se o bot for mencionado ou for comando
        if chat_type in ["group", "supergroup"]:
            mencionado = BOT_USERNAME.lower() in text.lower() or text.startswith("/")
            reply_to = message.get("reply_to_message", {}) if "message" in locals() and message else {}
            reply_bot = reply_to.get("from", {}).get("is_bot", False) if reply_to else False
            
            if not (mencionado or reply_bot):
                continue
                
            # Limpar menção do texto para processamento limpo
            text = text.replace(BOT_USERNAME, "").replace(BOT_USERNAME.lower(), "").strip()
            
        print(f"[Telegram Chat] Mensagem/Ação de {first_name} ({chat_id}): '{text}'")
        
        # Feedback visual imediato: ação de 'digitando' no Telegram
        telegram_bot.send_chat_action(chat_id, action="typing")
        
        # 1. Comandos /start, /ajuda, /help (ou parâmetro de deep link ?start=iniciar)
        if text.startswith("/start") or text.startswith("/ajuda") or text.startswith("/help") or text.lower() in ["começar", "iniciar", "start", "menu"]:
            welcome = f"""👋 <b>Olá, {first_name}! Eu sou o Robô de Inteligência de RI da Ceará Finance.</b>

Estou conectado 24 horas por dia à base de dados abertos da <b>CVM</b> e à IA <b>Gemini 3.1</b> para sintetizar divulgações oficiais de mais de 680 companhias da B3.

👇 <b>Toque em uma empresa abaixo para consultar em 1 clique:</b>
<i>Ou digite qualquer ticker/pergunta diretamente no chat.</i>"""

            telegram_bot.send_message(chat_id, welcome, reply_markup=get_start_inline_keyboard())
            storage.salvar_mensagem(str(chat_id), "user", text)
            storage.salvar_mensagem(str(chat_id), "assistant", welcome)
            respostas_enviadas += 1
            continue

        # 2. Comandos /alertas ou /canal
        if text.startswith("/alerta") or text.startswith("/canal"):
            msg_canal = """📢 <b>Canal Oficial de Alertas em Tempo Real · Ceará Finance</b>

Receba notificações instantâneas com som e análise de IA assim que um Fato Relevante ou Comunicado ao Mercado for protocolado na CVM."""
            markup_canal = {
                "inline_keyboard": [
                    [{"text": "📢 Entrar no Canal de Alertas", "url": "https://t.me/+T1V2m44be_Q3MjYx"}],
                    [{"text": "🌐 Acessar Portal Web CVM", "url": "https://fatos-relevantes-cvm.onrender.com"}]
                ]
            }
            telegram_bot.send_message(chat_id, msg_canal, reply_markup=markup_canal)
            respostas_enviadas += 1
            continue

        # 3. Comandos /portal ou /site
        if text.startswith("/portal") or text.startswith("/site"):
            msg_portal = """🌐 <b>Portal Web Oficial · CF Tech CVM</b>

Acesse a interface completa para explorar comunicados por mês, filtrar por tickers B3, fazer busca livre e visualizar o histórico completo da CVM."""
            markup_portal = {
                "inline_keyboard": [
                    [{"text": "🌐 Abrir Portal Web CVM", "url": "https://fatos-relevantes-cvm.onrender.com"}],
                    [{"text": "📢 Entrar no Canal de Alertas", "url": "https://t.me/+T1V2m44be_Q3MjYx"}]
                ]
            }
            telegram_bot.send_message(chat_id, msg_portal, reply_markup=markup_portal)
            respostas_enviadas += 1
            continue

        # 4. Comando /status
        if text.startswith("/status"):
            msg_status = """⚡ <b>Status Operacional · Ceará Finance</b>
• <b>Robô Telegram:</b> Operacional 24/7 ✅
• <b>Motor Cognitivo:</b> Gemini 3.1 Flash-Lite (Ativo) 🧠
• <b>Base Regulatória CVM:</b> Sincronizada em Nuvem ☁️
• <b>Canal de Alertas:</b> Transmitindo em Tempo Real 📢"""
            telegram_bot.send_message(chat_id, msg_status, reply_markup=get_ticker_inline_keyboard())
            respostas_enviadas += 1
            continue
            
        # 5. RAG: Buscar documentos oficiais relacionados à pergunta
        docs_relacionados = buscar_documentos_relacionados(text, limit=4)
        
        # 6. Histórico recente de conversas do usuário para dar contexto
        historico = storage.get_historico_chat(str(chat_id), limit=6)
        
        # 7. Enviar ação de digitando novamente antes da chamada de IA
        telegram_bot.send_chat_action(chat_id, action="typing")
        
        # 8. Gerar parecer inteligente com o Gemini 3.1
        try:
            resposta_ia = llm.perguntar_ao_gemini(text, historico, docs_relacionados)
        except Exception as err:
            print(f"[Telegram Chat] Erro no Gemini: {err}")
            resposta_ia = "Desculpe, ocorreu uma oscilação momentânea ao sintetizar a resposta com o Gemini. Por favor, tente novamente em instantes."
            
        # Adicionar assinatura institucional padronizada
        resposta_formatada = f"""{resposta_ia}

━━━━━━━━━━━━━━━━━━━━
🐂 <i>CF Tech · Front Office de Tecnologia</i>
<i>Ceará Finance Investment Group</i>"""

        # 9. Enviar resposta no Telegram com teclado rápido para a próxima consulta
        telegram_bot.send_message(chat_id, resposta_formatada, reply_markup=get_ticker_inline_keyboard())
        
        # 10. Persistir histórico
        storage.salvar_mensagem(str(chat_id), "user", text)
        storage.salvar_mensagem(str(chat_id), "assistant", resposta_formatada)
        respostas_enviadas += 1
        
    conn.close()
    return respostas_enviadas
