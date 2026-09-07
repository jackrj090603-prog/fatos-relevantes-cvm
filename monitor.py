import datetime
import time
from config import carregar_empresas, TELEGRAM_CHAT_ID_ALERTAS, MONITOR_INTERVAL
from cvm import buscar_documentos_cvm
import storage
import llm
import telegram_bot

def executar_monitoramento():
    """Lógica principal do monitor: busca novos documentos, filtra, resume e notifica."""
    print(f"\n[Monitor] Iniciando ciclo de monitoramento às {datetime.datetime.now()}...")
    
    # Garantir que o banco de dados está inicializado
    storage.init_db()
    
    # Carregar empresas cadastradas no excel
    target_companies = carregar_empresas()
    if not target_companies:
        print("[Monitor] Nenhuma empresa cadastrada no empresas.xlsx. Ciclo abortado.")
        return
        
    print(f"[Monitor] Monitorando {len(target_companies)} empresas do empresas.xlsx: {[t['ticker'] for t in target_companies]}")
    
    # Decidir o período da busca
    ultimo_sucesso = storage.get_ultimo_timestamp()
    hoje_dt = datetime.date.today()
    
    if ultimo_sucesso:
        # Se já buscou antes, busca do dia da última busca até hoje
        try:
            de_dt = datetime.datetime.strptime(ultimo_sucesso, "%Y-%m-%d").date()
            # Retroceder 1 dia por segurança de fuso horário/atrasos na CVM
            de_dt = de_dt - datetime.timedelta(days=1)
        except Exception:
            de_dt = hoje_dt - datetime.timedelta(days=2)
    else:
        # Catch-up inicial: busca os últimos 7 dias
        de_dt = hoje_dt - datetime.timedelta(days=7)
        
    data_de = de_dt.strftime("%d/%m/%Y")
    data_ate = hoje_dt.strftime("%d/%m/%Y")
    
    # Realizar busca de documentos
    todos_docs = buscar_documentos_cvm(data_de, data_ate)
    print(f"[Monitor] Total de {len(todos_docs)} documentos entregues na CVM no período de {data_de} a {data_ate}.")
    
    novos_documentos_alertados = 0
    
    for doc in todos_docs:
        link = doc.get("link")
        if not link:
            continue
            
        # 1. Mapear documento para ver se pertence a alguma empresa monitorada
        empresa_mapeada = match_company(doc["company_name"], doc["cvm_code"], target_companies)
        if not empresa_mapeada:
            continue  # Não monitorada
            
        # Preencher ticker correspondente
        ticker = empresa_mapeada["ticker"]
        doc["ticker"] = ticker
        
        # 2. Dedup: Verificar se já processamos este link
        if storage.doc_existe(link):
            continue
            
        print(f"[Monitor] Novo documento detectado para #{ticker} - {doc['category']} | Link: {link}")
        
        # Enviar aviso de "digitando" para o chat de alertas (opcional)
        telegram_bot.send_chat_action(TELEGRAM_CHAT_ID_ALERTAS, action="typing")
        
        # 3. Gerar Resumo de IA usando o SDK google-genai
        print(f"[Monitor] Gerando resumo automático para {ticker} via Gemini...")
        resumo = llm.resumir_documento(doc, link)
        doc["resumo_ia"] = resumo
        
        # 4. Salvar no banco SQLite
        salvo = storage.salvar_documento(doc)
        if salvo:
            novos_documentos_alertados += 1
            
            # 5. Formatar alerta com HTML seguro para o Telegram
            alert_text = formatar_alerta_telegram(doc, resumo)
            
            # Enviar para o canal de alertas
            print(f"[Monitor] Enviando alerta Telegram para #{ticker}...")
            telegram_bot.send_message(TELEGRAM_CHAT_ID_ALERTAS, alert_text)
            
            # 6. Despachar alerta para usuários inscritos no WhatsApp
            try:
                import whatsapp_bot
                total_wpp = whatsapp_bot.disparar_alerta_para_inscritos(doc, resumo)
                if total_wpp > 0:
                    print(f"[Monitor] {total_wpp} alertas enviados via WhatsApp para #{ticker}.")
            except Exception as e_wpp:
                print(f"[Monitor] Erro ao despachar WhatsApp: {e_wpp}")
            
            # Pequena pausa para evitar sobrecarga no bot e rate-limits
            time.sleep(2)
            
    # Salvar o estado da última busca bem sucedida
    storage.set_ultimo_timestamp(hoje_dt.strftime("%Y-%m-%d"))
    print(f"[Monitor] Ciclo finalizado. {novos_documentos_alertados} novos alertas emitidos.")

def match_company(doc_company_name, doc_cvm_code, target_list):
    """
    Fuzzy match para verificar se o documento pertence a um ticker monitorado.
    Valida por CVM Code numérico ou proximidade do nome da empresa.
    """
    doc_cvm_clean = "".join(filter(str.isdigit, doc_cvm_code))
    
    for target in target_list:
        # Comparação por Código CVM numérico (removendo zeros à esquerda e traços)
        target_cvm_clean = target["cvm_limpo"]
        if target_cvm_clean and doc_cvm_clean:
            try:
                if int(target_cvm_clean) == int(doc_cvm_clean):
                    return target
            except ValueError:
                pass
                
        # Comparação por substring do nome da empresa
        nome_target = target["nome"].lower().strip()
        nome_doc = doc_company_name.lower().strip()
        
        # Se um nome estiver contido no outro ou vice-versa
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
    
    # Garantir que caracteres especiais HTML na descrição sejam escapados
    descricao_escapada = (
        descricao.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    
    mensagem = f"""🔔 <b>NOVO DOCUMENTO DIVULGADO NA CVM</b>

🏢 <b>Empresa:</b> {empresa} (Ticker: #{ticker})
📂 <b>Categoria:</b> {categoria}
📄 <b>Tipo:</b> {tipo}
📝 <b>Assunto:</b> {descricao_escapada}
📅 <b>Data Divulgação:</b> {data_entrega}

💡 <b>Resumo Executivo (Agente de RI):</b>
{resumo}

🔗 <a href="{link}">Visualizar Documento Oficial (CVM)</a>"""
    return mensagem
