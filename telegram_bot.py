import requests
import time
import re
from config import TELEGRAM_BOT_TOKEN

def request_telegram_with_retry(method, url, **kwargs):
    """Executa requisições HTTP para o Telegram Bot API tratando erros 429/503."""
    max_retries = 5
    delay = 2
    for attempt in range(max_retries):
        try:
            res = requests.post(url, **kwargs) if method.upper() == "POST" else requests.get(url, **kwargs)
            
            # Tratar erro de limite de requisições do Telegram (429)
            if res.status_code == 429:
                retry_after = int(res.json().get("parameters", {}).get("retry_after", delay))
                print(f"[Telegram] Rate limit atingido. Aguardando {retry_after}s antes de tentar novamente...")
                time.sleep(retry_after)
                continue
                
            # Tratar erro de servidor (503)
            if res.status_code == 503 and attempt < max_retries - 1:
                print(f"[Telegram] Servidor instável (503). Retentando em {delay}s...")
                time.sleep(delay)
                delay *= 2
                continue
                
            return res
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[Telegram] Falha na conexão: {e}. Retentando em {delay}s...")
                time.sleep(delay)
                delay *= 2
            else:
                raise e
    return None

def send_chat_action(chat_id, action="typing"):
    """Exibe o status de 'digitando' (typing) ou outra ação no chat do Telegram."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction"
    payload = {
        "chat_id": str(chat_id),
        "action": action
    }
    try:
        request_telegram_with_retry("POST", url, json=payload, timeout=10)
    except Exception as e:
        print(f"[Telegram] Erro ao enviar chat action: {e}")

def send_message(chat_id, text, parse_mode="HTML"):
    """
    Envia uma mensagem no chat com tags HTML seguras.
    Se o Telegram recusar devido a tags HTML malformadas, envia em texto simples de fallback.
    """
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return None
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False
    }
    
    try:
        res = request_telegram_with_retry("POST", url, json=payload, timeout=15)
        if not res:
            return None
            
        # Caso o parse de HTML falhe (erro 400 por tags HTML inválidas)
        if res.status_code == 400 and "can't parse entities" in res.text:
            print("[Telegram] Erro de parse HTML. Enviando versão limpa em texto simples...")
            # Limpar tags HTML do texto usando regex
            texto_simples = re.sub(r"<[^>]*>", "", text)
            payload["text"] = texto_simples
            payload["parse_mode"] = ""  # Sem parse_mode
            res = request_telegram_with_retry("POST", url, json=payload, timeout=15)
            
        return res.json() if res and res.status_code == 200 else None
        
    except Exception as e:
        print(f"[Telegram] Falha ao enviar mensagem para chat {chat_id}: {e}")
        return None

def ler_updates(offset=None):
    """Lê novas mensagens e atualizações enviadas ao bot."""
    if not TELEGRAM_BOT_TOKEN:
        return []
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 10}
    if offset:
        params["offset"] = offset
        
    try:
        res = request_telegram_with_retry("GET", url, params=params, timeout=15)
        if res and res.status_code == 200:
            data = res.json()
            if data.get("ok"):
                return data.get("result", [])
        return []
    except Exception as e:
        print(f"[Telegram] Erro ao ler updates: {e}")
        return []
