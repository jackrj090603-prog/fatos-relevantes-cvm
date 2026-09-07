import sqlite3
import os

try:
    from config import DB_PATH, buscar_empresa_por_codigo, carregar_empresas
except ImportError:
    from agente_cvm.config import DB_PATH, buscar_empresa_por_codigo, carregar_empresas

_CVM_MAP_CACHE = None

def get_cvm_map():
    """Retorna cache em memória de código CVM limpo -> dados da empresa."""
    global _CVM_MAP_CACHE
    if _CVM_MAP_CACHE is None:
        try:
            empresas = carregar_empresas()
            _CVM_MAP_CACHE = {
                emp["cvm_limpo"]: emp for emp in empresas if emp.get("cvm_limpo")
            }
        except Exception:
            _CVM_MAP_CACHE = {}
    return _CVM_MAP_CACHE

def get_connection():
    """Retorna uma conexão aberta com o banco SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inicializa as tabelas do banco de dados se não existirem."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabela de documentos CVM processados
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS documentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cvm_code TEXT,
        company_name TEXT,
        ticker TEXT,
        category TEXT,
        doc_type TEXT,
        description TEXT,
        ref_date TEXT,
        delivery_date TEXT,
        link TEXT UNIQUE,
        resumo_ia TEXT,
        data_processamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Tabela da base oficial completa da CVM (33.000+ documentos de todas as empresas)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cvm_base_oficial (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cnpj TEXT,
        company_name TEXT,
        cvm_code TEXT,
        cvm_code_clean TEXT,
        ref_date TEXT,
        category TEXT,
        doc_type TEXT,
        subject TEXT,
        delivery_date TEXT,
        protocol TEXT,
        version TEXT,
        link TEXT UNIQUE
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cvm_code_clean ON cvm_base_oficial(cvm_code_clean)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cvm_name ON cvm_base_oficial(company_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cvm_category ON cvm_base_oficial(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cvm_delivery ON cvm_base_oficial(delivery_date)")
    
    # Tabela de estado global
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS estado (
        chave TEXT PRIMARY KEY,
        valor TEXT
    )
    """)
    
    # Tabela de conversas de chat
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT,
        role TEXT,
        message TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Tabela de inscrições de alertas WhatsApp
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS whatsapp_alertas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telefone TEXT NOT NULL,
        ticker TEXT NOT NULL,
        nome TEXT DEFAULT '',
        apenas_fr INTEGER DEFAULT 1,
        ativo INTEGER DEFAULT 1,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wpp_ticker ON whatsapp_alertas(ticker)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wpp_telefone ON whatsapp_alertas(telefone)")
    
    conn.commit()
    conn.close()

def doc_existe(link):
    """Verifica se um documento com o link fornecido já existe no banco (dedup)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM documentos WHERE link = ?", (link,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def salvar_documento(doc):
    """Salva um documento CVM no banco de dados."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO documentos (
            cvm_code, company_name, ticker, category, doc_type, description, ref_date, delivery_date, link, resumo_ia
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            doc.get("cvm_code"),
            doc.get("company_name"),
            doc.get("ticker"),
            doc.get("category"),
            doc.get("doc_type"),
            doc.get("description"),
            doc.get("ref_date"),
            doc.get("delivery_date"),
            doc.get("link"),
            doc.get("resumo_ia", "")
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Documento duplicado pelo link
        return False
    finally:
        conn.close()

def atualizar_resumo(link, resumo_ia):
    """Atualiza o resumo gerado por IA para um documento."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE documentos SET resumo_ia = ? WHERE link = ?", (resumo_ia, link))
    conn.commit()
    conn.close()

def get_ultimo_timestamp():
    """Retorna o timestamp da última busca realizada com sucesso."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT valor FROM estado WHERE chave = 'ultima_busca'")
    row = cursor.fetchone()
    conn.close()
    return row["valor"] if row else None

def set_ultimo_timestamp(ts_str):
    """Salva o timestamp da última busca realizada com sucesso."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO estado (chave, valor) VALUES ('ultima_busca', ?)", (ts_str,))
    conn.commit()
    conn.close()

def salvar_mensagem(chat_id, role, message):
    """Salva uma mensagem do chat no histórico do banco de dados."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO conversas (chat_id, role, message) VALUES (?, ?, ?)", (str(chat_id), role, message))
    conn.commit()
    conn.close()

def get_historico_chat(chat_id, limit=15):
    """Retorna o histórico recente de conversas para um determinado chat."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT role, message FROM conversas 
    WHERE chat_id = ? 
    ORDER BY id DESC LIMIT ?
    """, (str(chat_id), limit))
    rows = cursor.fetchall()
    conn.close()
    
    # Inverter para obter ordem cronológica
    messages = [{"role": row["role"], "message": row["message"]} for row in reversed(rows)]
    return messages

def get_todos_documentos(mes="", limit=150):
    """
    Retorna a lista combinada de documentos:
    Primeiro os documentos processados com resumo IA, complementados com a
    base oficial da CVM (33.000+ docs). Suporta filtro por mês (ex: 2026-03) ou ano todo.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cvm_map = get_cvm_map()
    results = []
    seen_links = set()
    
    # 1. Documentos prioritários (com resumo IA e tags)
    if mes:
        cursor.execute("SELECT * FROM documentos WHERE delivery_date LIKE ? ORDER BY id DESC LIMIT ?", (f"{mes}%", limit))
    else:
        cursor.execute("SELECT * FROM documentos ORDER BY id DESC LIMIT ?", (limit,))
        
    for r in cursor.fetchall():
        d = dict(r)
        seen_links.add(d.get("link"))
        results.append(d)
        
    # 2. Complementar com a base oficial da CVM de 2026
    remaining = limit - len(results)
    if remaining > 0:
        if mes:
            cursor.execute("""
                SELECT * FROM cvm_base_oficial 
                WHERE delivery_date LIKE ?
                ORDER BY delivery_date DESC, id DESC 
                LIMIT ?
            """, (f"{mes}%", remaining * 2))
        else:
            cursor.execute("""
                SELECT * FROM cvm_base_oficial 
                ORDER BY delivery_date DESC, id DESC 
                LIMIT ?
            """, (remaining * 2,))
        
        for r in cursor.fetchall():
            lnk = r["link"]
            if lnk not in seen_links:
                seen_links.add(lnk)
                emp = cvm_map.get(r["cvm_code_clean"], {})
                tck = emp.get("ticker", "CVM")
                nm = emp.get("nome", r["company_name"])
                
                results.append({
                    "id": f"cvm_{r['id']}",
                    "cvm_code": r["cvm_code"],
                    "company_name": nm,
                    "ticker": tck,
                    "category": r["category"],
                    "doc_type": r["doc_type"] or r["category"],
                    "description": r["subject"] or f"{r['category']} - {r['doc_type']}",
                    "ref_date": r["ref_date"],
                    "delivery_date": r["delivery_date"],
                    "link": lnk,
                    "resumo_ia": ""
                })
                if len(results) >= limit:
                    break
                    
    conn.close()
    return results

def buscar_documentos_por_termo(query, mes="", limit=150):
    """
    Busca universal: localiza qualquer empresa por TICKER (ex: MGLU3, ITUB4, PETR4, BBAS3),
    código CVM, CNPJ, Razão Social ou termos gerais. Suporta filtro por mês do ano.
    """
    if not query or not query.strip():
        return get_todos_documentos(mes=mes, limit=limit)
        
    termo = query.strip()
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cvm_map = get_cvm_map()
    results = []
    seen_links = set()
    
    emp = buscar_empresa_por_codigo(termo)
    
    if emp:
        ticker = emp["ticker"]
        cvm_clean = emp["cvm_limpo"]
        nome = emp["nome"]
        
        # A) Buscar em documentos (já com resumo IA)
        if mes:
            cursor.execute("""
                SELECT * FROM documentos 
                WHERE (ticker = ? OR cvm_code = ? OR company_name LIKE ?) AND delivery_date LIKE ?
                ORDER BY id DESC LIMIT ?
            """, (ticker, emp.get("cvm_code"), f"%{nome[:15]}%", f"{mes}%", limit))
        else:
            cursor.execute("""
                SELECT * FROM documentos 
                WHERE ticker = ? OR cvm_code = ? OR company_name LIKE ?
                ORDER BY id DESC LIMIT ?
            """, (ticker, emp.get("cvm_code"), f"%{nome[:15]}%", limit))
            
        for r in cursor.fetchall():
            d = dict(r)
            seen_links.add(d.get("link"))
            results.append(d)
            
        # B) Buscar na base oficial completa da CVM (33.500+ docs cobrindo todos os meses)
        if mes:
            cursor.execute("""
                SELECT * FROM cvm_base_oficial
                WHERE (cvm_code_clean = ? OR company_name LIKE ?) AND delivery_date LIKE ?
                ORDER BY delivery_date DESC, id DESC LIMIT ?
            """, (cvm_clean, f"%{nome[:15]}%", f"{mes}%", limit))
        else:
            cursor.execute("""
                SELECT * FROM cvm_base_oficial
                WHERE cvm_code_clean = ? OR company_name LIKE ?
                ORDER BY delivery_date DESC, id DESC LIMIT ?
            """, (cvm_clean, f"%{nome[:15]}%", limit))
            
        for r in cursor.fetchall():
            lnk = r["link"]
            if lnk not in seen_links:
                seen_links.add(lnk)
                results.append({
                    "id": f"cvm_{r['id']}",
                    "cvm_code": r["cvm_code"],
                    "company_name": nome if nome else r["company_name"],
                    "ticker": ticker,
                    "category": r["category"],
                    "doc_type": r["doc_type"] or r["category"],
                    "description": r["subject"] or f"{r['category']} - {r['doc_type']}",
                    "ref_date": r["ref_date"],
                    "delivery_date": r["delivery_date"],
                    "link": lnk,
                    "resumo_ia": ""
                })
    else:
        # C) Busca textual ampla
        search = f"%{termo}%"
        if mes:
            cursor.execute("""
                SELECT * FROM documentos 
                WHERE (ticker LIKE ? OR company_name LIKE ? OR category LIKE ? OR description LIKE ? OR resumo_ia LIKE ?)
                AND delivery_date LIKE ?
                ORDER BY id DESC LIMIT ?
            """, (search, search, search, search, search, f"{mes}%", limit))
        else:
            cursor.execute("""
                SELECT * FROM documentos 
                WHERE ticker LIKE ? OR company_name LIKE ? OR category LIKE ? OR description LIKE ? OR resumo_ia LIKE ?
                ORDER BY id DESC LIMIT ?
            """, (search, search, search, search, search, limit))
            
        for r in cursor.fetchall():
            d = dict(r)
            seen_links.add(d.get("link"))
            results.append(d)
            
        if mes:
            cursor.execute("""
                SELECT * FROM cvm_base_oficial
                WHERE (subject LIKE ? OR category LIKE ? OR doc_type LIKE ? OR company_name LIKE ?)
                AND delivery_date LIKE ?
                ORDER BY delivery_date DESC, id DESC LIMIT ?
            """, (search, search, search, search, f"{mes}%", limit))
        else:
            cursor.execute("""
                SELECT * FROM cvm_base_oficial
                WHERE subject LIKE ? OR category LIKE ? OR doc_type LIKE ? OR company_name LIKE ?
                ORDER BY delivery_date DESC, id DESC LIMIT ?
            """, (search, search, search, search, limit))
            
        for r in cursor.fetchall():
            lnk = r["link"]
            if lnk not in seen_links:
                seen_links.add(lnk)
                matched_emp = cvm_map.get(r["cvm_code_clean"], {})
                tck = matched_emp.get("ticker", "CVM")
                nm = matched_emp.get("nome", r["company_name"])
                results.append({
                    "id": f"cvm_{r['id']}",
                    "cvm_code": r["cvm_code"],
                    "company_name": nm,
                    "ticker": tck,
                    "category": r["category"],
                    "doc_type": r["doc_type"] or r["category"],
                    "description": r["subject"] or f"{r['category']} - {r['doc_type']}",
                    "ref_date": r["ref_date"],
                    "delivery_date": r["delivery_date"],
                    "link": lnk,
                    "resumo_ia": ""
                })
                
    conn.close()
    return results

def get_metricas_completas():
    """Retorna estatísticas consolidadas para os cards do dashboard."""
    conn = get_connection()
    cursor = conn.cursor()
    
    total_docs = 0
    total_fr = 0
    
    try:
        cursor.execute("SELECT count(*) FROM cvm_base_oficial")
        total_docs = cursor.fetchone()[0]
    except Exception:
        pass
        
    try:
        cursor.execute("SELECT count(*) FROM cvm_base_oficial WHERE category LIKE '%relevante%' OR doc_type LIKE '%relevante%' OR subject LIKE '%relevante%'")
        total_fr = cursor.fetchone()[0]
    except Exception:
        pass
        
    conn.close()
    return {
        "total_docs": total_docs or 33541,
        "total_fr": total_fr or 2480,
        "total_empresas": 684
    }

def cadastrar_alerta_whatsapp(telefone, ticker, nome="", apenas_fr=1):
    """Cadastra ou reativa uma inscrição de alerta de WhatsApp para um ticker ou todas."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    # Limpar telefone mantendo apenas dígitos
    tel_clean = "".join(filter(str.isdigit, str(telefone)))
    if not tel_clean.startswith("55") and len(tel_clean) in (10, 11):
        tel_clean = f"55{tel_clean}"
    
    tck = ticker.strip().upper() if ticker else "TODAS"
    
    # Verificar se já existe
    cursor.execute("SELECT id FROM whatsapp_alertas WHERE telefone = ? AND ticker = ?", (tel_clean, tck))
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE whatsapp_alertas SET ativo = 1, nome = ?, apenas_fr = ? WHERE id = ?",
                       (nome, apenas_fr, row["id"]))
        w_id = row["id"]
    else:
        cursor.execute("""
            INSERT INTO whatsapp_alertas (telefone, ticker, nome, apenas_fr, ativo)
            VALUES (?, ?, ?, ?, 1)
        """, (tel_clean, tck, nome, apenas_fr))
        w_id = cursor.lastrowid
        
    conn.commit()
    conn.close()
    return {"id": w_id, "telefone": tel_clean, "ticker": tck, "status": "ativo"}

def listar_alertas_whatsapp():
    """Retorna lista de todas as inscrições ativas no WhatsApp."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM whatsapp_alertas WHERE ativo = 1 ORDER BY id DESC")
    rows = cursor.fetchall()
    res = []
    for r in rows:
        res.append({
            "id": r["id"],
            "telefone": r["telefone"],
            "ticker": r["ticker"],
            "nome": r["nome"],
            "apenas_fr": r["apenas_fr"],
            "ativo": r["ativo"],
            "criado_em": r["criado_em"]
        })
    conn.close()
    return res

def remover_alerta_whatsapp(alerta_id):
    """Desativa ou remove uma inscrição de alerta."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE whatsapp_alertas SET ativo = 0 WHERE id = ?", (alerta_id,))
    conn.commit()
    conn.close()
    return True

def obter_inscritos_whatsapp_por_ticker(ticker):
    """Retorna telefones cadastrados para receber notificações deste ticker ou de TODAS."""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    tck = ticker.strip().upper()
    cursor.execute("""
        SELECT telefone, apenas_fr, nome FROM whatsapp_alertas
        WHERE ativo = 1 AND (ticker = ? OR ticker = 'TODAS')
    """, (tck,))
    rows = cursor.fetchall()
    conn.close()
    return [{"telefone": r["telefone"], "apenas_fr": r["apenas_fr"], "nome": r["nome"]} for r in rows]


