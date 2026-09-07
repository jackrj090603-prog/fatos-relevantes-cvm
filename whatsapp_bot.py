import os
import re
import time
import urllib.parse
import requests

try:
    from config import (
        WHATSAPP_PROVIDER,
        EVOLUTION_API_URL,
        EVOLUTION_API_KEY,
        EVOLUTION_INSTANCE,
        ZAPI_INSTANCE_ID,
        ZAPI_TOKEN,
        ZAPI_CLIENT_TOKEN,
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN,
        TWILIO_WHATSAPP_NUMBER
    )
    import storage
except ImportError:
    from agente_cvm.config import (
        WHATSAPP_PROVIDER,
        EVOLUTION_API_URL,
        EVOLUTION_API_KEY,
        EVOLUTION_INSTANCE,
        ZAPI_INSTANCE_ID,
        ZAPI_TOKEN,
        ZAPI_CLIENT_TOKEN,
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN,
        TWILIO_WHATSAPP_NUMBER
    )
    from agente_cvm import storage

def limpar_numero_whatsapp(telefone):
    """Limpa e formata o telefone para o padrão internacional (ex: 5585999998888)."""
    tel = "".join(filter(str.isdigit, str(telefone)))
    if not tel.startswith("55") and len(tel) in (10, 11):
        tel = f"55{tel}"
    return tel

def formatar_alerta_whatsapp(doc, resumo=""):
    """
    Formata o comunicado e o parecer de IA no padrão aceito pelo WhatsApp:
    *negrito*, _itálico_, emojis e links claros.
    """
    ticker = doc.get("ticker", "B3").upper()
    empresa = doc.get("company_name", "Companhia Aberta")
    categoria = doc.get("category", "Geral")
    tipo = doc.get("doc_type", "Fato Relevante")
    descricao = doc.get("description", "Aviso ao mercado")
    data_entrega = doc.get("delivery_date", "Hoje")
    link = doc.get("link", "#")

    # Formatar resumo de IA se existir
    resumo_fmt = ""
    if resumo:
        # Limpar cabeçalhos markdown e converter para sintaxe WhatsApp
        r = resumo
        r = re.sub(r"^###\s*", "\n📌 *", r, flags=re.MULTILINE)
        r = re.sub(r"\n📌 \*([^\n]+)", r"\n📌 *\1*", r)
        r = re.sub(r"\*\*([^\*]+)\*\*", r"*\1*", r)
        r = re.sub(r"^[\*\-]\s*", " • ", r, flags=re.MULTILINE)
        r = re.sub(r"<[^>]+>", "", r)  # remove HTML
        r = r.strip()
        resumo_fmt = f"\n💡 *PARECER EXECUTIVO RI (Gemini)*\n{r}\n"

    mensagem = f"""🚨 *ALERTA CVM · CEARÁ FINANCE* 🚨

🏢 *Empresa:* {empresa} (*{ticker}*)
📂 *Categoria:* {categoria}
📄 *Tipo:* {tipo}
📝 *Assunto:* {descricao}
📅 *Data CVM:* {data_entrega}
{resumo_fmt}
🔗 *Documento Oficial CVM:*
{link}

━━━━━━━━━━━━━━━━━━━━
🐂 _CF Tech · Front Office de Tecnologia_
_Ceará Finance Investment Group_"""
    return mensagem

def enviar_mensagem_whatsapp(telefone, texto):
    """
    Envia a mensagem para o WhatsApp do destinatário.
    Detecta automaticamente o provedor configurado (.env) ou opera em modo de simulação com log.
    """
    tel = limpar_numero_whatsapp(telefone)
    if not tel:
        return {"status": "erro", "mensagem": "Número de telefone inválido."}

    # 1. Provedor: Evolution API (Padrão Open-Source mais usado no Brasil)
    if EVOLUTION_API_URL and EVOLUTION_API_KEY:
        url = f"{EVOLUTION_API_URL.rstrip('/')}/message/sendText/{EVOLUTION_INSTANCE}"
        headers = {
            "apikey": EVOLUTION_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "number": tel,
            "options": {
                "delay": 1200,
                "presence": "composing"
            },
            "text": texto
        }
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=15)
            if res.status_code in (200, 201):
                return {"status": "sucesso", "provedor": "evolution_api", "detalhe": res.json()}
            else:
                return {"status": "erro", "provedor": "evolution_api", "detalhe": res.text}
        except Exception as e:
            return {"status": "erro", "provedor": "evolution_api", "erro": str(e)}

    # 2. Provedor: Z-API
    elif ZAPI_INSTANCE_ID and ZAPI_TOKEN:
        url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-messages"
        headers = {
            "Content-Type": "application/json"
        }
        if ZAPI_CLIENT_TOKEN:
            headers["Client-Token"] = ZAPI_CLIENT_TOKEN
        payload = {
            "phone": tel,
            "message": texto
        }
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=15)
            if res.status_code in (200, 201):
                return {"status": "sucesso", "provedor": "z_api", "detalhe": res.json()}
            else:
                return {"status": "erro", "provedor": "z_api", "detalhe": res.text}
        except Exception as e:
            return {"status": "erro", "provedor": "z_api", "erro": str(e)}

    # 3. Provedor: Twilio WhatsApp
    elif TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_NUMBER:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
        auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        from_num = TWILIO_WHATSAPP_NUMBER if TWILIO_WHATSAPP_NUMBER.startswith("whatsapp:") else f"whatsapp:{TWILIO_WHATSAPP_NUMBER}"
        to_num = f"whatsapp:+{tel}"
        data = {
            "From": from_num,
            "To": to_num,
            "Body": texto
        }
        try:
            res = requests.post(url, data=data, auth=auth, timeout=15)
            if res.status_code in (200, 201):
                return {"status": "sucesso", "provedor": "twilio", "detalhe": res.json()}
            else:
                return {"status": "erro", "provedor": "twilio", "detalhe": res.text}
        except Exception as e:
            return {"status": "erro", "provedor": "twilio", "erro": str(e)}

    # 4. Modo Simulação / Demonstração (Sem chaves externas conectadas)
    else:
        try:
            print(f"\n[WhatsApp Mock] Simulando envio com sucesso para +{tel}:")
            print("--------------------------------------------------")
            clean_log = texto.encode("ascii", errors="backslashreplace").decode("ascii")
            print(clean_log[:350] + ("..." if len(clean_log) > 350 else ""))
            print("--------------------------------------------------")
        except Exception:
            pass
        return {
            "status": "simulado",
            "provedor": "mock_cf_tech",
            "telefone": tel,
            "mensagem": f"Notificação para +{tel} registrada com sucesso na fila de alertas (Modo Simulação CF Tech)."
        }

def disparar_alerta_para_inscritos(doc, resumo=""):
    """
    Busca todas as pessoas inscritas para receber alertas deste ticker (ou de 'TODAS')
    e despacha as mensagens.
    """
    ticker = doc.get("ticker", "B3").upper()
    cat = doc.get("category", "")
    tipo = doc.get("doc_type", "")
    is_fr = "relevante" in cat.lower() or "relevante" in tipo.lower()

    inscritos = storage.obter_inscritos_whatsapp_por_ticker(ticker)
    if not inscritos:
        return 0

    texto_msg = formatar_alerta_whatsapp(doc, resumo)
    total_enviados = 0

    for insc in inscritos:
        tel = insc["telefone"]
        apenas_fr = insc.get("apenas_fr", 1)

        # Se o usuário optou por apenas Fatos Relevantes e o doc não for FR, pula
        if apenas_fr and not is_fr:
            continue

        try:
            res = enviar_mensagem_whatsapp(tel, texto_msg)
            print(f"[WhatsApp] Alerta de {ticker} despachado para {tel}: {res.get('status')}")
            total_enviados += 1
            time.sleep(1)  # Intervalo de segurança anti-spam
        except Exception as e:
            print(f"[WhatsApp] Falha ao enviar para {tel}: {e}")

    return total_enviados

def enviar_alerta_teste(telefone, ticker="MDIA3"):
    """Envia uma mensagem de teste imediata para o usuário validar seu número."""
    doc_teste = {
        "ticker": ticker.upper(),
        "company_name": "M. DIAS BRANCO S.A. IND E COM DE ALIMENTOS" if ticker.upper() == "MDIA3" else f"COMPANHIA ABERTA ({ticker.upper()})",
        "category": "Fato Relevante",
        "doc_type": "Fato Relevante",
        "description": "Teste de Conexão de Notificações CVM em Tempo Real",
        "delivery_date": time.strftime("%Y-%m-%d"),
        "link": "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx"
    }
    resumo_teste = """### Síntese do Teste
Seu número de WhatsApp foi conectado com sucesso ao sistema de monitoramento CVM da CF Tech.

### Destaques Principais
* **Status:** Conexão Ativa
* **Ativo Monitorado:** #{ticker}
* **Velocidade:** Alertas instantâneos assim que divulgados na CVM

### Análise para o Investidor de Longo Prazo
Classificação: **Positivo**. O canal direto de alertas reduz a assimetria de informação e garante acompanhamento em tempo real.""".replace("{ticker}", ticker.upper())

    texto = formatar_alerta_whatsapp(doc_teste, resumo_teste)
    res = enviar_mensagem_whatsapp(telefone, texto)
    clean_tel = limpar_numero_whatsapp(telefone)
    res["texto_formatado"] = texto
    res["whatsapp_url"] = f"https://api.whatsapp.com/send?phone={clean_tel}&text={urllib.parse.quote(texto)}"
    return res
