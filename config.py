import os
import openpyxl
from dotenv import load_dotenv

# Caminhos do projeto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path)

DB_PATH = os.path.join(BASE_DIR, "agente_cvm.db")
EMPRESAS_XLSX = os.path.join(BASE_DIR, "empresas.xlsx")
UNIVERSO_JSON = os.path.join(BASE_DIR, "empresas_universo.json")

# Variáveis do Telegram e Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID_ALERTAS = os.getenv("TELEGRAM_CHAT_ID_ALERTAS", "")
TELEGRAM_CHAT_ID_CONVERSA = os.getenv("TELEGRAM_CHAT_ID_CONVERSA", "")

# Configurações de Notificação WhatsApp
WHATSAPP_PROVIDER = os.getenv("WHATSAPP_PROVIDER", "simulacao")
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "cftech")
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "")

# Configuração do Heartbeat
HEARTBEAT_INTERVAL = 300  # 5 minutos
MONITOR_INTERVAL = 900    # 15 minutos

# Lista padrão de empresas para criar o empresas.xlsx caso não exista
EMPRESAS_PADRAO = [
    {"TICKER": "DIRR3", "CNPJ": "03.141.011/0001-34", "COD_CVM": "02182-2", "NOME": "DIRECIONAL ENGENHARIA S.A."},
    {"TICKER": "PETR4", "CNPJ": "33.000.167/0001-01", "COD_CVM": "00951-2", "NOME": "PETROLEO BRASILEIRO S.A. PETROBRAS"},
    {"TICKER": "VALE3", "CNPJ": "15.031.206/0001-55", "COD_CVM": "00417-0", "NOME": "VALE S.A."},
    {"TICKER": "WEGE3", "CNPJ": "84.429.695/0001-11", "COD_CVM": "01540-7", "NOME": "WEG S.A."}
]

def inicializar_empresas_xlsx():
    """Cria o arquivo empresas.xlsx se ele não existir."""
    if not os.path.exists(EMPRESAS_XLSX):
        print(f"[Config] Criando arquivo de empresas padrão em: {EMPRESAS_XLSX}")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Empresas"
        
        headers = ["TICKER", "CNPJ", "COD_CVM", "NOME"]
        ws.append(headers)
        
        for emp in EMPRESAS_PADRAO:
            ws.append([emp["TICKER"], emp["CNPJ"], emp["COD_CVM"], emp["NOME"]])
            
        wb.save(EMPRESAS_XLSX)
        wb.close()

def carregar_empresas():
    """
    Carrega o catálogo completo de empresas brasileiras (680+ tickers da B3 e CVM).
    Prioriza empresas_universo.json e faz fallback para empresas.xlsx.
    """
    import json
    empresas = []

    if os.path.exists(UNIVERSO_JSON):
        try:
            with open(UNIVERSO_JSON, "r", encoding="utf-8") as f:
                universo = json.load(f)
                for ticker, data in universo.items():
                    cnpj = str(data.get("cnpj", "")).strip()
                    cod_cvm = str(data.get("cvm_code", "")).strip()
                    nome = str(data.get("nome", "")).strip()
                    setor = str(data.get("setor", "")).strip()
                    
                    cnpj_limpo = "".join(filter(str.isdigit, cnpj))
                    cvm_limpo = "".join(filter(str.isdigit, cod_cvm))
                    
                    empresas.append({
                        "ticker": ticker.upper(),
                        "cnpj": cnpj,
                        "cnpj_limpo": cnpj_limpo,
                        "cvm_code": cod_cvm,
                        "cvm_limpo": cvm_limpo,
                        "nome": nome,
                        "setor": setor
                    })
            if empresas:
                return sorted(empresas, key=lambda x: x["ticker"])
        except Exception as e:
            print(f"[Config] Aviso ao carregar {UNIVERSO_JSON}: {e}")

    # Fallback para empresas.xlsx
    inicializar_empresas_xlsx()
    try:
        wb = openpyxl.load_workbook(EMPRESAS_XLSX, data_only=True)
        ws = wb.active
        
        header = None
        for row in ws.iter_rows(values_only=True):
            if not header:
                header = [str(cell).upper().strip() for cell in row]
                continue
            
            if not any(row):
                continue
                
            data = dict(zip(header, row))
            ticker = str(data.get("TICKER", "")).strip()
            cnpj = str(data.get("CNPJ", "")).strip()
            cod_cvm = str(data.get("COD_CVM", "")).strip()
            nome = str(data.get("NOME", "")).strip()
            
            if ticker and (cnpj or cod_cvm):
                cnpj_limpo = "".join(filter(str.isdigit, cnpj))
                cvm_limpo = "".join(filter(str.isdigit, cod_cvm))
                
                empresas.append({
                    "ticker": ticker,
                    "cnpj": cnpj,
                    "cnpj_limpo": cnpj_limpo,
                    "cvm_code": cod_cvm,
                    "cvm_limpo": cvm_limpo,
                    "nome": nome,
                    "setor": "Geral"
                })
        wb.close()
    except Exception as e:
        print(f"[Config] Erro ao carregar empresas.xlsx: {e}")
        
    return empresas

def buscar_empresa_por_codigo(termo: str):
    """Localiza os dados cadastrais de uma empresa por ticker, código CVM ou nome."""
    if not termo:
        return None
    termo_clean = termo.strip().upper()
    termo_num = "".join(filter(str.isdigit, termo_clean))
    
    todas = carregar_empresas()
    # 1. Match exato por ticker
    for emp in todas:
        if emp["ticker"] == termo_clean:
            return emp
            
    # 2. Match por código CVM
    if termo_num:
        for emp in todas:
            if emp["cvm_limpo"] and int(emp["cvm_limpo"]) == int(termo_num):
                return emp

    # 3. Match por nome
    for emp in todas:
        if termo_clean in emp["nome"].upper() or emp["nome"].upper() in termo_clean:
            return emp
            
    return None
