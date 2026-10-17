import datetime
import time
from config import carregar_empresas, TELEGRAM_CHAT_ID_ALERTAS, MONITOR_INTERVAL
from cvm import buscar_documentos_cvm
import storage
import llm
import telegram_bot

def executar_monitoramento():
    """Lógica principal do monitor: busca novos documentos, filtra, resume e notifica."""
    print(f"\n[Monitor CVM] Iniciando ciclo de monitoramento às {datetime.datetime.now()}...")
    
    # Garantir que o banco de dados está inicializado
    storage.init_db()
    
    # Carregar empresas cadastradas
    target_companies = carregar_empresas()
    if not target_companies:
        print("[Monitor CVM] Nenhuma empresa cadastrada. Ciclo abortado.")
        return
        
    print(f"[Monitor CVM] Monitorando {len(target_companies)} empresas da B3...")
    
    # Decidir o período da busca
    ultimo_sucesso = storage.get_ultimo_timestamp()
    hoje_dt = datetime.date.today()
    
    if ultimo_sucesso:
        try:
            de_dt = datetime.datetime.strptime(ultimo_sucesso, "%Y-%m-%d").date()
            # Retroceder 1 dia por segurança de fuso horário / processamento da CVM
            de_dt = de_dt - datetime.timedelta(days=1)
        except Exception:
            de_dt = hoje_dt - datetime.timedelta(days=1)
    else:
        # Se for primeira execução, monitora as últimas 24-48 horas
        de_dt = hoje_dt - datetime.timedelta(days=1)
        
    data_de = de_dt.strftime("%d/%m/%Y")
    data_ate = hoje_dt.strftime("%d/%m/%Y")
    
    # Realizar busca de documentos
    todos_docs = buscar_documentos_cvm(data_de, data_ate)
    print(f"[Monitor CVM] Total de {len(todos_docs)} documentos entregues na CVM no período de {data_de} a {data_ate}.")
    
    novos_documentos_alertados = 0
    max_alertas_por_ciclo = 10
    
    for doc in todos_docs:
        if novos_documentos_alertados >= max_alertas_por_ciclo:
            print(f"[Monitor CVM] Atingido limite seguro de {max_alertas_por_ciclo} alertas neste ciclo.")
            break
            
        link = doc.get("link")
        if not link:
            continue
            
        # 1. Mapear documento para ver se pertence a alguma empresa monitorada
        empresa_mapeada = match_company(doc.get("company_name", ""), doc.get("cvm_code", ""), target_companies)
        if not empresa_mapeada:
            continue
            
        # 2. Filtrar apenas categorias de real impacto (Fatos Relevantes, Comunicados ao Mercado, Avisos, Resultados)
        cat_lower = (doc.get("category") or "").lower()
        tipo_lower = (doc.get("doc_type") or "").lower()
        eh_relevante = (
            "fato relevante" in cat_lower or "fato relevante" in tipo_lower or
            "comunicado" in cat_lower or "comunicado" in tipo_lower or
            "aviso" in cat_lower or "aviso" in tipo_lower or
            "resultado" in cat_lower or "demonstrações" in cat_lower
        )
        if not eh_relevante:
            continue
            
        ticker = empresa_mapeada["ticker"]
        doc["ticker"] = ticker
        
        # 3. Dedup: Verificar se já processamos este link
        if storage.doc_existe(link):
            continue
            
        print(f"[Monitor CVM] Novo documento detectado para #{ticker} - {doc.get('category')} | Link: {link}")
        
        # Enviar aviso de 'digitando' no canal de alertas
        telegram_bot.send_chat_action(TELEGRAM_CHAT_ID_ALERTAS, action="typing")
        
        # 4. Gerar Resumo de IA usando o Gemini 3.1
        print(f"[Monitor CVM] Gerando parecer executivo para {ticker} via Gemini...")
        try:
            resumo = llm.resumir_documento(doc, link)
        except Exception as e_resumo:
            print(f"[Monitor CVM] Erro ao resumir: {e_resumo}")
            resumo = f"Divulgação oficial registrada na CVM por {doc.get('company_name')} ({ticker}). Consulte o link oficial para íntegra."
            
        doc["resumo_ia"] = resumo
        
        # 5. Salvar no banco SQLite
        salvo = storage.salvar_documento(doc)
        if salvo:
            novos_documentos_alertados += 1
            
            # 6. Formatar alerta com HTML seguro para o Telegram
            alert_text = formatar_alerta_telegram(doc, resumo)
            
            # Enviar para o canal de alertas oficial
            print(f"[Monitor CVM] Enviando alerta Telegram para #{ticker}...")
            telegram_bot.send_message(TELEGRAM_CHAT_ID_ALERTAS, alert_text)
            
            # 7. Despachar alerta para inscritos no WhatsApp (se configurado)
            try:
                import whatsapp_bot
                whatsapp_bot.disparar_alerta_para_inscritos(doc, resumo)
            except Exception:
                pass
            
            # Pausa para evitar rate-limits
            time.sleep(3)
            
    # Salvar o estado da última busca bem sucedida
    storage.set_ultimo_timestamp(hoje_dt.strftime("%Y-%m-%d"))
    print(f"[Monitor CVM] Ciclo finalizado. {novos_documentos_alertados} novos alertas emitidos.")

def match_company(doc_company_name, doc_cvm_code, target_list):
    """
    Fuzzy match para verificar se o documento pertence a um ticker monitorado.
    Valida por CVM Code numérico ou proximidade do nome da empresa.
    """
    doc_cvm_clean = "".join(filter(str.isdigit, doc_cvm_code))
    
    for target in target_list:
        # Comparação por Código CVM numérico
        target_cvm_clean = target.get("cvm_limpo", "")
        if target_cvm_clean and doc_cvm_clean:
            try:
                if int(target_cvm_clean) == int(doc_cvm_clean):
                    return target
            except ValueError:
                pass
                
        # Comparação por substring do nome da empresa
        nome_target = target.get("nome", "").lower().strip()
        nome_doc = doc_company_name.lower().strip()
        
        if nome_target and nome_doc:
            if nome_target in nome_doc or nome_doc in nome_target:
                return target
                
    return None

def formatar_alerta_telegram(doc, resumo):
    """Formata a mensagem de alerta do Telegram com tags HTML válidas."""
    ticker = doc.get("ticker", "B3")
    empresa = doc.get("company_name", "Companhia Aberta")
    categoria = doc.get("category", "Geral")
    tipo = doc.get("doc_type", "Fato Relevante")
    descricao = doc.get("description", "Aviso ao mercado")
    data_entrega = doc.get("delivery_date", "Hoje")
    link = doc.get("link", "#")
    
    descricao_escapada = (
        descricao.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    
    mensagem = f"""🚨 <b>ALERTA OFICIAL CVM · CEARÁ FINANCE</b> 🚨

🏢 <b>Empresa:</b> {empresa} (<b>#{ticker}</b>)
📂 <b>Categoria:</b> {categoria}
📄 <b>Tipo:</b> {tipo}
📝 <b>Assunto:</b> {descricao_escapada}
📅 <b>Data Divulgação:</b> {data_entrega}

💡 <b>PARECER EXECUTIVO RI (Gemini 3.1):</b>
{resumo}

🔗 <a href="{link}">Visualizar Documento Oficial (CVM)</a>
🌐 <a href="https://fatos-relevantes-cvm.onrender.com">Portal CF Tech CVM</a>

━━━━━━━━━━━━━━━━━━━━
🐂 <i>CF Tech · Front Office de Tecnologia</i>
<i>Ceará Finance Investment Group</i>"""
    return mensagem
