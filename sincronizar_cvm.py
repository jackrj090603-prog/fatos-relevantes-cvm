# -*- coding: utf-8 -*-
# ==============================================================================
# CF TECH · SINCRONIZADOR DE DADOS ABERTOS DA CVM (ANO 2026)
# ==============================================================================
import os
import io
import csv
import zipfile
import sqlite3
import requests
import storage
from config import DB_PATH

CVM_ZIP_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_2026.zip"

def sincronizar_base_cvm():
    """Baixa o arquivo IPE oficial do portal Dados Abertos CVM e popula o SQLite."""
    print(f"[CVM Sync] Baixando base oficial de 2026 da CVM em: {CVM_ZIP_URL}...")
    storage.init_db()
    
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(CVM_ZIP_URL, headers=headers, timeout=60)
    if resp.status_code != 200:
        print(f"[CVM Sync] Erro no download: HTTP {resp.status_code}")
        return False
        
    print("[CVM Sync] Arquivo baixado com sucesso. Extraindo e indexando registros...")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        csv_name = [name for name in z.namelist() if name.endswith(".csv")][0]
        with z.open(csv_name) as f:
            content = f.read().decode("latin1")
            reader = csv.DictReader(io.StringIO(content), delimiter=";")
            
            rows_to_insert = []
            for r in reader:
                cd = r.get("Codigo_CVM", "").strip()
                cd_clean = "".join(filter(str.isdigit, cd))
                try:
                    cd_clean = str(int(cd_clean)) if cd_clean else ""
                except ValueError:
                    pass
                    
                rows_to_insert.append((
                    r.get("CNPJ_Companhia", "").strip(),
                    r.get("Nome_Companhia", "").strip(),
                    cd,
                    cd_clean,
                    r.get("Data_Referencia", "").strip(),
                    r.get("Categoria", "").strip(),
                    r.get("Tipo", "").strip(),
                    r.get("Assunto", "").strip(),
                    r.get("Data_Entrega", "").strip(),
                    r.get("Protocolo_Entrega", "").strip(),
                    r.get("Versao", "").strip(),
                    r.get("Link_Download", "").strip()
                ))
                
            conn = storage.get_connection()
            c = conn.cursor()
            c.executemany("""
            INSERT OR IGNORE INTO cvm_base_oficial (
                cnpj, company_name, cvm_code, cvm_code_clean, ref_date, category, doc_type, subject, delivery_date, protocol, version, link
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows_to_insert)
            conn.commit()
            total = c.execute("SELECT count(*) FROM cvm_base_oficial").fetchone()[0]
            conn.close()
            
    print(f"[CVM Sync] Sincronizacao concluida! Total de {total} documentos indexados.")
    return True

if __name__ == "__main__":
    sincronizar_base_cvm()
