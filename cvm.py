import requests
import json
import re
import warnings

def buscar_documentos_cvm(data_de: str, data_ate: str) -> list:
    """
    Realiza a requisição POST para a API do ENET/CVM e retorna
    uma lista de documentos estruturada.
    
    Parâmetros:
      data_de: data inicial em formato dd/mm/aaaa
      data_ate: data final em formato dd/mm/aaaa
    """
    url = "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx/ListarDocumentos"
    
    payload = {
        "dataDe": data_de,
        "dataAte": data_ate,
        "empresa": "",
        "setorAtividade": "-1",
        "categoriaEmissor": "-1",
        "situacaoEmissor": "-1",
        "tipoParticipante": "-1",
        "dataReferencia": "",
        "categoria": "-1",
        "tipo": "-1",
        "especie": "-1",
        "periodo": "0",
        "horaIni": "",
        "horaFim": "",
        "palavraChave": "",
        "ultimaDtRef": "false",
        "tipoEmpresa": "0",
        "token": "",
        "versaoCaptcha": ""
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    try:
        print(f"[CVM] Buscando documentos divulgados entre {data_de} e {data_ate}...")
        response = requests.post(url, json=payload, headers=headers, timeout=25)
        
        if response.status_code != 200:
            print(f"[CVM] Erro na requisição. Código HTTP: {response.status_code}")
            return []
            
        res_data = response.json()
        d_val = res_data.get("d", {})
        
        # Verificar se houve erro retornado no corpo do WebService
        if d_val.get("temErro", False):
            print(f"[CVM] Erro no WebService da CVM: {d_val.get('msgErro')}")
            return []
            
        # Verificar se está exigindo captcha
        if d_val.get("SolicitarCaptcha") == "S":
            warnings.warn("[CVM] O servidor da CVM solicitou validação por Captcha. Requisição ignorada.")
            return []
            
        dados_str = d_val.get("dados", "")
        if not dados_str:
            print("[CVM] Nenhum documento retornado na resposta do período.")
            return []
            
        return parse_cvm_dados(dados_str)
        
    except Exception as e:
        print(f"[CVM] Falha crítica ao consultar API da CVM: {e}")
        return []

def parse_cvm_dados(dados_str: str) -> list:
    """
    Decodifica o formato de string delimitada retornado pela CVM.
    Linhas são separadas por '&*' e colunas dentro da linha por '$&'.
    """
    if not dados_str:
        return []
        
    rows = dados_str.split("&*")
    parsed_docs = []
    
    for row in rows:
        row = row.strip()
        if not row:
            continue
            
        parts = row.split("$&")
        if len(parts) < 11:
            continue
            
        cvm_code = parts[0].strip()
        company_name = parts[1].strip()
        category = parts[2].strip()
        doc_type = parts[3].strip()
        
        # Limpar descrição (remover tags HTML caso existam, como <spanOrder>)
        description_raw = parts[4].strip()
        description = re.sub(r"<[^>]*>", "", description_raw).strip()
        
        # Limpar datas
        ref_date_raw = parts[5].strip()
        ref_date = re.sub(r"<[^>]*>", "", ref_date_raw).strip()
        
        delivery_date_raw = parts[6].strip()
        delivery_date = re.sub(r"<[^>]*>", "", delivery_date_raw).strip()
        
        status = parts[7].strip()
        version = parts[8].strip()
        
        # Extrair link do visualizador a partir do onclick do botão de visualizar
        actions_html = parts[10]
        link = ""
        
        # Tentar capturar a URL exata do iframe de exibição
        url_match = re.search(r"OpenPopUpVer\('([^']+)'\)", actions_html)
        if url_match:
            sub_url = url_match.group(1)
            # Montar a URL completa de acesso
            link = f"https://www.rad.cvm.gov.br/ENET/{sub_url}"
        else:
            # Fallback usando o número de protocolo de entrega se disponível
            protocol_match = re.search(r"NumeroProtocoloEntrega=(\d+)", actions_html)
            if protocol_match:
                protocolo = protocol_match.group(1)
                link = f"https://www.rad.cvm.gov.br/ENET/frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega={protocolo}"
                
        parsed_docs.append({
            "cvm_code": cvm_code,
            "company_name": company_name,
            "category": category,
            "doc_type": doc_type,
            "description": description,
            "ref_date": ref_date,
            "delivery_date": delivery_date,
            "status": status,
            "version": version,
            "link": link
        })
        
    return parsed_docs
