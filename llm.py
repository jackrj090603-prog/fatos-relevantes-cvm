import time
import urllib.request
import re
from google import genai
from google.genai import types
try:
    from config import GEMINI_API_KEY
except ImportError:
    from agente_cvm.config import GEMINI_API_KEY

# Inicializar o cliente do Gemini
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def request_with_retry(func, *args, **kwargs):
    """Executa uma chamada de API do Gemini com retentativas exponenciais para erros 429/503."""
    max_retries = 5
    delay = 2
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            # Capturar erros HTTP 429 (Too Many Requests) ou 503 (Service Unavailable)
            if e.code in (429, 503) and attempt < max_retries - 1:
                print(f"[Gemini] Erro de API {e.code}. Tentativa {attempt + 1}/{max_retries} em {delay}s...")
                time.sleep(delay)
                delay *= 2
            else:
                raise e
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[Gemini] Erro inesperado: {e}. Tentando novamente em {delay}s...")
                time.sleep(delay)
                delay *= 2
            else:
                raise e

def extrair_texto_url(url):
    """
    UrlContext: Baixa a página HTML do documento da CVM
    e limpa as tags HTML para extrair apenas o texto relevante.
    """
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            html = response.read().decode("utf-8", errors="ignore")
            
        # Remover scripts, CSS e tags HTML
        html_limpo = re.sub(r"<(script|style).*?>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        texto = re.sub(r"<.*?>", " ", html_limpo)
        # Normalizar espaços em branco
        texto = re.sub(r"\s+", " ", texto).strip()
        
        # Limitar o texto para evitar estourar limites se for muito grande
        return texto[:25000]
    except Exception as e:
        # Fallback rápido se a CVM estiver lenta
        return ""

def resumir_documento(doc_info, url):
    """Gera um resumo executivo em português de um documento CVM usando Gemini."""
    if not client:
        return "Gemini API Key não configurada. Resumo indisponível."
        
    # Tentar extrair o contexto do HTML da URL
    contexto_documento = extrair_texto_url(url)
    
    prompt = f"""
Você é o Analista de Relações com Investidores (RI) da Ceará Finance (CF Tech).
Sua missão é sintetizar o documento regulatório oficial da CVM em um Parecer Executivo didático, limpo, analítico e sem enrolação.

DADOS DO DOCUMENTO:
- Empresa: {doc_info.get('company_name')} (Ticker: {doc_info.get('ticker')})
- Categoria: {doc_info.get('category')}
- Tipo: {doc_info.get('doc_type')}
- Assunto/Descrição: {doc_info.get('description')}
- Data de Divulgação: {doc_info.get('delivery_date')}
- Link Oficial: {url}

CONTEÚDO EXTRAÍDO:
\"\"\"{contexto_documento[:20000]}\"\"\"

ESTRUTURA OBRIGATÓRIA DA RESPOSTA (Siga rigorosamente estes cabeçalhos):
NÃO use introduções protocolares (ex: "Como analista de RI...", "Apresento o resumo..."). Comece diretamente pelo conteúdo:

### Síntese do Evento
[1 a 2 frases diretas explicando o fato essencial que a companhia protocolou na CVM].

### Destaques Principais
* **[Título do Ponto 1]:** [Explicação clara do ponto operacional, governança ou valor financeiro].
* **[Título do Ponto 2]:** [Datas, números, condições ou deliberações relevantes].
* **[Título do Ponto 3]:** [Impacto imediato nos negócios ou nas ações].

### Análise para o Investidor de Longo Prazo
Classificação: **[Positivo | Neutro | Atenção / Risco]**. [Análise de 2 a 3 frases sobre o impacto deste documento nos fundamentos da empresa, dividendos, governança ou riscos para o acionista].
"""

    def call_gemini():
        config = types.GenerateContentConfig(
            system_instruction="Você é um especialista em análise financeira e divulgação de documentos da CVM.",
            temperature=0.2
        )
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=config
        )
        return response.text

    try:
        resumo = request_with_retry(call_gemini)
        return resumo
    except Exception as e:
        print(f"[Gemini] Erro no modelo principal: {e}. Tentando fallback...")
        try:
            def call_fallback():
                config = types.GenerateContentConfig(
                    system_instruction="Você é um especialista em análise financeira da CVM.",
                    temperature=0.3
                )
                response = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=prompt,
                    config=config
                )
                return response.text
            return request_with_retry(call_fallback)
        except Exception as fallback_err:
            print(f"[Gemini] Fallback indisponível: {fallback_err}")
            desc = doc_info.get('description') or 'comunicado institucional'
            cat = doc_info.get('category') or 'Documento'
            cia = doc_info.get('company_name') or 'Companhia'
            return f"Documento oficial ({cat}) protocolado por {cia} referente a: {desc}. Para análise e deliberações completas, acesse o documento no link oficial da CVM."

def perguntar_ao_gemini(pergunta, historico_conversas, documentos_relacionados):
    """
    Responde perguntas do usuário em formato chat interativo,
    usando histórico de conversação e documentos relacionados como contexto.
    """
    if not client:
        return "Gemini API Key não configurada. Chat interativo offline."
        
    contexto_docs = ""
    if documentos_relacionados:
        contexto_docs = "Documentos recentes encontrados no banco que podem ser úteis:\n"
        for d in documentos_relacionados:
            contexto_docs += f"- [{d['ticker']}] {d['category']} - {d['doc_type']} ({d['delivery_date']}): {d['description']}\nLink: {d['link']}\nResumo da IA: {d['resumo_ia']}\n\n"

    # Montar histórico de conversação no formato aceito pela API ou texto corrido
    historico_texto = "Histórico da conversa:\n"
    for msg in historico_conversas:
        origem = "Usuário" if msg["role"] == "user" else "Agente"
        historico_texto += f"{origem}: {msg['message']}\n"
        
    prompt = f"""
Você é o Agente de RI da Ceará Finance. Responda a pergunta do usuário com base no histórico da conversa e no contexto dos documentos recentes da CVM fornecidos.
Se precisar de informações atualizadas adicionais, use a ferramenta de busca do Google integrada.

{contexto_docs}

{historico_texto}
Pergunta atual do usuário: {pergunta}

Responda em formato HTML seguro (use apenas as tags permitidas: <b>, <i>, <code>, <a>, <u>). Mantenha a resposta clara, profissional e objetiva.
"""

    def call_chat():
        config = types.GenerateContentConfig(
            system_instruction="Você é o chat bot oficial da Ceará Finance para investidores de ações da B3.",
            tools=[{"google_search": {}}],
            temperature=0.4
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=config
        )
        return response.text

    try:
        return request_with_retry(call_chat)
    except Exception as e:
        return f"Desculpe, tive um problema ao processar sua pergunta: {e}"

def gerar_tese_investimento(ticker, wacc, valor_justo, upside, texto_pdf):
    """Gera um relatório acadêmico de tese de investimento detalhado usando Gemini."""
    if not client:
        return "Tese de investimento baseada em premissas quantitativas de WACC e DCF."
        
    prompt = f"""
Você é um Analista de Investimentos Sênior da Ceará Finance.
Sua missão é elaborar um relatório acadêmico de tese de investimento profissional, completo e detalhado sobre a empresa {ticker}, integrando os resultados quantitativos calculados no nosso motor de valuation com as informações operacionais extraídas do Relatório Anual da companhia.

Resultados Quantitativos Calculados:
- Ativo: {ticker}
- Custo Médio Ponderado de Capital (WACC): {wacc:.2f}%
- Preço Justo Calculado (Cenário Base): R$ {valor_justo:.2f}
- Potencial de Valorização (Upside): {upside:.2f}%

Conteúdo Extraído do Relatório Anual (PDF):
\"\"\"{texto_pdf[:12000]}\"\"\"

Instruções para elaborar a Tese de Investimento (máximo 4 parágrafos pequenos):
1. **Sumário Executivo e Posicionamento de Mercado**: Apresente a empresa, seu core business, sua relevância e o posicionamento competitivo dela com base nas informações do relatório anual.
2. **Análise de Fundamentos & Resultados**: Discuta as forças operacionais, vantagens competitivas (ex: rentabilidade, eficiência, portfólio de produtos ou projetos) identificadas no relatório anual.
3. **Valuation & Análise do Custo de Capital**: Justifique o valuation. Interprete o WACC de {wacc:.2f}% frente às condições de mercado e fundamente o preço justo de R$ {valor_justo:.2f} (Upside de {upside:.2f}%), destacando o potencial de valorização do ativo.
4. **Recomendação e Riscos**: Finalize com uma recomendação clara e mencione os principais riscos (macro ou específicos do setor) para o investidor de longo prazo.

Escreva a resposta formatada em parágrafos de texto corrido em português, de forma profissional e sem usar bullet points (tópicos).
"""
    try:
        config = types.GenerateContentConfig(
            system_instruction="Você é o analista sênior de equity research oficial da Ceará Finance.",
            temperature=0.3
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=config
        )
        return response.text
    except Exception as e:
        print(f"[Gemini] Erro ao gerar tese de investimento: {e}")
        return "Tese de investimento baseada em premissas quantitativas de WACC e DCF."
