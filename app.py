import os
import sys
import json
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

import storage
import config
import llm
import whatsapp_bot

PORT = int(os.getenv("PORT", 8001))

class CVMHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        
        if parsed.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.render_cvm_dashboard().encode("utf-8"))
            
        elif parsed.path in ["/LOGO_CF_TECH.png", "/LOGO_CF.png", "/logo.png"]:
            self.serve_logo()
            
        elif parsed.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "app": "cvm"}')
            
        elif parsed.path == "/api/empresas":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            empresas = config.carregar_empresas()
            self.wfile.write(json.dumps(empresas).encode("utf-8"))

        elif parsed.path == "/api/metricas":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            metricas = storage.get_metricas_completas()
            self.wfile.write(json.dumps(metricas).encode("utf-8"))

        elif parsed.path == "/api/meses":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            meses = storage.get_meses_disponiveis()
            self.wfile.write(json.dumps(meses).encode("utf-8"))
            
        elif parsed.path == "/api/documentos":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            
            q = params.get("q", [""])[0].strip()
            mes = params.get("mes", [""])[0].strip()
            docs = storage.buscar_documentos_por_termo(q, mes=mes, limit=160)
            self.wfile.write(json.dumps(docs).encode("utf-8"))

        elif parsed.path == "/api/sincronizar":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            import threading
            import sincronizar_cvm
            threading.Thread(target=sincronizar_cvm.sincronizar_base_cvm, daemon=True).start()
            self.wfile.write(b'{"status": "ok", "message": "Sincronizacao CVM iniciada"}')

        elif parsed.path == "/api/whatsapp/listar":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            alertas = storage.listar_alertas_whatsapp()
            self.wfile.write(json.dumps(alertas).encode("utf-8"))
            
        elif parsed.path == "/api/resumir":
            link = params.get("link", [""])[0].strip()
            ticker = params.get("ticker", [""])[0].strip()
            
            if not link:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"error": "Parametro link obrigatorio"}')
                return
                
            conn = storage.get_connection()
            c = conn.cursor()
            c.execute("SELECT * FROM documentos WHERE link = ?", (link,))
            row = c.fetchone()
            
            resumo = ""
            if row and row["resumo_ia"] and "404 NOT_FOUND" not in row["resumo_ia"] and "error" not in row["resumo_ia"].lower():
                resumo = row["resumo_ia"]
            else:
                c.execute("SELECT * FROM cvm_base_oficial WHERE link = ?", (link,))
                oficial = c.fetchone()
                emp = config.buscar_empresa_por_codigo(ticker)
                
                doc_obj = {
                    "ticker": ticker or (emp["ticker"] if emp else "B3"),
                    "company_name": oficial["company_name"] if oficial else (emp["nome"] if emp else "Companhia Aberta"),
                    "category": oficial["category"] if oficial else "Documento CVM",
                    "doc_type": oficial["doc_type"] if oficial else "",
                    "description": oficial["subject"] if oficial else "",
                    "delivery_date": oficial["delivery_date"] if oficial else "",
                    "link": link
                }
                
                try:
                    resumo = llm.resumir_documento(doc_obj, link)
                except Exception as e:
                    resumo = f"### Síntese do Evento\nDocumento oficial ({doc_obj['category']}) protocolado por {doc_obj['company_name']} ({doc_obj['ticker']}) na CVM.\n\n### Destaques Principais\n* **Assunto:** {doc_obj['description']}\n* **Data:** Divulgado em {doc_obj['delivery_date']}\n* **Protocolo:** Disponível na íntegra nos sistemas da CVM.\n\n### Análise para o Investidor de Longo Prazo\nClassificação: **Neutro**. Trata-se de divulgação regulatória que não altera de imediato os fundamentos estruturais da companhia."
                    
                doc_obj["resumo_ia"] = resumo
                storage.salvar_documento(doc_obj)
                storage.atualizar_resumo(link, resumo)
                
            conn.close()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "resumo": resumo}).encode("utf-8"))
            
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
        
        try:
            data = json.loads(post_data)
        except Exception:
            data = {}
            
        if False:
            pass
        elif parsed.path == "/api/telegram/testar":
            ticker = data.get("ticker", "PETR4").strip().upper() or "PETR4"
            import telegram_bot
            docs = storage.buscar_documentos_por_termo(ticker, limit=1)
            doc = docs[0] if docs else {}
            empresa = doc.get("company_name", "PETROLEO BRASILEIRO S.A. PETROBRAS")
            categoria = doc.get("category", "Fato Relevante")
            assunto = doc.get("description", "Relatorio Operacional e Comunicado ao Mercado / CVM")
            data_doc = doc.get("delivery_date", "17/10/2026")
            
            texto = f"""🚨 <b>ALERTA OFICIAL CVM · CEARÁ FINANCE</b> 🚨\n\n🏢 <b>Empresa:</b> {empresa} (<b>{ticker}</b>)\n📂 <b>Categoria:</b> {categoria}\n📝 <b>Assunto:</b> {assunto}\n📅 <b>Data CVM:</b> {data_doc}\n\n💡 <b>PARECER EXECUTIVO RI (Gemini 3.1)</b>\n• <b>Classificação:</b> Positivo / Neutro\n• <b>Análise:</b> Divulgação regulatória que reforça a transparência institucional, higidez operacional e previsibilidade perante o mercado.\n\n🔗 <b>Portal de Fatos Relevantes:</b> <a href="https://fatos-relevantes-cvm.onrender.com">Acessar CF Tech CVM</a>\n\n━━━━━━━━━━━━━━━━━━━━\n🐂 <i>CF Tech · Front Office de Tecnologia</i>\n<i>Ceará Finance Investment Group</i>"""
            
            res = telegram_bot.send_message(config.TELEGRAM_CHAT_ID_ALERTAS, texto, parse_mode="HTML")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            if res and res.get("ok"):
                self.wfile.write(json.dumps({"status": "ok", "canal": "CEARA_FINANCE_CANAL", "message_id": res["result"]["message_id"]}).encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"status": "erro", "erro": str(res) if res else "Falha na comunicacao com API Telegram"}).encode("utf-8"))
                
        elif parsed.path == "/api/whatsapp/cadastrar":
            telefone = data.get("telefone", "").strip()
            ticker = data.get("ticker", "TODAS").strip().upper() or "TODAS"
            nome = data.get("nome", "").strip()
            apenas_fr = 1 if data.get("apenas_fr", True) else 0
            
            if not telefone:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"error": "Telefone obrigatorio"}')
                return
                
            res = storage.cadastrar_alerta_whatsapp(telefone, ticker, nome, apenas_fr)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "registro": res}).encode("utf-8"))
            
        elif parsed.path == "/api/whatsapp/remover":
            alerta_id = data.get("id")
            if not alerta_id:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"error": "ID obrigatorio"}')
                return
                
            storage.remover_alerta_whatsapp(alerta_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            
        elif parsed.path == "/api/whatsapp/testar":
            telefone = data.get("telefone", "").strip()
            ticker = data.get("ticker", "MDIA3").strip().upper() or "MDIA3"
            if not telefone:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"error": "Telefone obrigatorio"}')
                return
                
            res_envio = whatsapp_bot.enviar_alerta_teste(telefone, ticker)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "resultado": res_envio}).encode("utf-8"))
            
        else:
            self.send_response(404)
            self.end_headers()

    def serve_logo(self):
        paths_to_try = [
            os.path.join(BASE_DIR, "LOGO_CF_TECH.png"),
            os.path.join(BASE_DIR, "LOGO_CF.png"),
            os.path.join(BASE_DIR, "logo.png")
        ]
        for p in paths_to_try:
            if os.path.exists(p):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                with open(p, "rb") as f:
                    self.wfile.write(f.read())
                return
        self.send_response(404)
        self.end_headers()

    def render_cvm_dashboard(self):
        html = r"""<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CF TECH — Fatos Relevantes CVM | Ceará Finance</title>
    <!-- Tipografia Oficial Manual de Marca CF Tech v2 -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Familjen+Grotesk:wght@400;500;600;700&family=Space+Grotesk:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            /* Paleta Oficial do Manual de Marca v2 */
            --c-tinta: #0A0A0B;
            --c-papel: #F5F3EF;
            --c-papel-alt: #E9E7E2;
            --c-roxo-profundo: #3B0764;
            --c-roxo-fume: #8C79C0;
            --c-grafite: #5A5A62;
            --c-grafite-light: #8A8A93;
            --c-hairline: #222228;
            --c-hairline-light: #D8D4CB;
            --c-card-bg: #111115;
            --c-card-hover: #15151B;
            --c-summary-bg: #0D0C13;
            
            /* Fontes */
            --font-title: 'Familjen Grotesk', sans-serif;
            --font-body: 'Space Grotesk', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: var(--font-body);
            background: var(--c-tinta);
            color: var(--c-papel);
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
            text-wrap: pretty;
            line-height: 1.5;
        }
        
        ::selection {
            background: var(--c-roxo-profundo);
            color: var(--c-papel);
        }
        
        a {
            color: var(--c-roxo-fume);
            text-decoration: none;
            transition: all 0.2s;
        }
        a:hover {
            color: var(--c-papel);
        }

        /* ================= TICKER TAPE / MARQUEE ================= */
        .marquee-bar {
            background: var(--c-papel);
            color: var(--c-tinta);
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 0.2em;
            padding: 7px 0;
            text-transform: uppercase;
            overflow: hidden;
            white-space: nowrap;
            display: flex;
            border-bottom: 1px solid var(--c-tinta);
            font-weight: 500;
        }
        .marquee-track {
            display: inline-flex;
            animation: marquee 35s linear infinite;
        }
        .marquee-track span {
            padding: 0 20px;
        }
        @keyframes marquee {
            0% { transform: translateX(0); }
            100% { transform: translateX(-50%); }
        }

        /* ================= CONTAINER & HEADER ================= */
        .container {
            max-width: 1240px;
            margin: 0 auto;
            padding: 0 24px 80px;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 22px 0;
            border-bottom: 1px solid var(--c-hairline);
            margin-bottom: 32px;
        }

        .brand-lockup {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .logo-cf-banner {
            height: 75px;
            max-width: 390px;
            object-fit: contain;
            display: block;
            filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.5));
            transition: transform 0.2s;
        }
        .logo-cf-banner:hover {
            transform: scale(1.02);
        }

        .header-actions {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        .btn-top {
            font-family: var(--font-mono);
            font-size: 11px;
            letter-spacing: 0.14em;
            color: var(--c-papel);
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--c-hairline);
            padding: 8px 16px;
            border-radius: 6px;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-top:hover {
            background: rgba(140, 121, 192, 0.15);
            border-color: var(--c-roxo-fume);
            color: var(--c-papel);
            transform: translateY(-1px);
        }

        /* ================= HERO SECTION ================= */
        .hero-section {
            padding: 15px 0 30px;
            border-bottom: 1px solid var(--c-hairline);
            margin-bottom: 30px;
        }
        .hero-tag {
            font-family: var(--font-mono);
            font-size: 11px;
            letter-spacing: 0.24em;
            color: var(--c-roxo-fume);
            margin-bottom: 12px;
            text-transform: uppercase;
        }
        .hero-title {
            font-family: var(--font-title);
            font-weight: 600;
            font-size: 48px;
            line-height: 1.05;
            letter-spacing: -0.02em;
            margin-bottom: 12px;
            color: var(--c-papel);
        }
        .hero-subtitle {
            font-size: 15px;
            line-height: 1.6;
            color: var(--c-grafite-light);
            max-width: 760px;
        }

        /* ================= METRICS GRID ================= */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            border: 1px solid var(--c-hairline);
            background: var(--c-card-bg);
            margin-bottom: 28px;
        }
        .metric-cell {
            padding: 18px 22px;
            border-right: 1px solid var(--c-hairline);
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .metric-cell:last-child {
            border-right: none;
        }
        .metric-cell-label {
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 0.18em;
            color: var(--c-roxo-fume);
            text-transform: uppercase;
        }
        .metric-cell-val {
            font-family: var(--font-mono);
            font-size: 24px;
            font-weight: 600;
            color: var(--c-papel);
        }
        .metric-cell-sub {
            font-size: 11px;
            color: var(--c-grafite-light);
        }

        /* ================= SEARCH & CONTROLS ================= */
        .search-container {
            border: 1px solid var(--c-hairline);
            background: var(--c-card-bg);
            padding: 20px 22px;
            margin-bottom: 25px;
        }
        .search-label {
            font-family: var(--font-mono);
            font-size: 10.5px;
            letter-spacing: 0.2em;
            color: var(--c-roxo-fume);
            margin-bottom: 12px;
            text-transform: uppercase;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .search-inputs-row {
            display: grid;
            grid-template-columns: 1fr 280px;
            gap: 12px;
            margin-bottom: 16px;
        }
        .search-box-wrap {
            position: relative;
        }
        .search-box-wrap i {
            position: absolute;
            left: 16px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--c-roxo-fume);
            font-size: 14px;
        }
        .search-box-wrap input {
            width: 100%;
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid var(--c-hairline);
            padding: 12px 16px 12px 44px;
            font-family: var(--font-body);
            font-size: 14px;
            color: var(--c-papel);
            border-radius: 6px;
            outline: none;
            transition: all 0.2s;
        }
        .search-box-wrap input:focus {
            border-color: var(--c-roxo-fume);
            box-shadow: 0 0 0 2px rgba(140, 121, 192, 0.25);
        }
        .select-company-dropdown {
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid var(--c-hairline);
            padding: 0 14px;
            font-family: var(--font-body);
            font-size: 13.5px;
            color: var(--c-papel);
            border-radius: 6px;
            outline: none;
            cursor: pointer;
        }
        .select-company-dropdown:focus {
            border-color: var(--c-roxo-fume);
        }

        /* Barra de Seleção de Meses (Ano Todo) */
        .month-selector-bar {
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
            padding: 12px 0;
            border-top: 1px solid var(--c-hairline);
            border-bottom: 1px solid var(--c-hairline);
            margin-bottom: 14px;
        }
        .month-label {
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 0.16em;
            color: var(--c-roxo-fume);
            margin-right: 6px;
            text-transform: uppercase;
        }
        .month-pill {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--c-hairline);
            color: var(--c-grafite-light);
            padding: 4px 11px;
            font-family: var(--font-mono);
            font-size: 11px;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .month-pill:hover, .month-pill.active {
            background: var(--c-roxo-profundo);
            border-color: var(--c-roxo-fume);
            color: #ffffff;
            font-weight: 600;
        }

        .filter-pills-row {
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
        }
        .pills-prefix {
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 0.15em;
            color: var(--c-grafite-light);
            margin-right: 4px;
        }
        .pill-btn {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--c-hairline);
            color: var(--c-grafite-light);
            padding: 4px 12px;
            font-family: var(--font-mono);
            font-size: 11px;
            border-radius: 9999px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .pill-btn:hover, .pill-btn.active {
            background: rgba(140, 121, 192, 0.18);
            border-color: var(--c-roxo-fume);
            color: var(--c-papel);
        }

        /* ================= COMPANY PROFILE BANNER ================= */
        .company-profile-banner {
            border: 1px solid var(--c-roxo-fume);
            background: linear-gradient(135deg, rgba(59, 7, 100, 0.25) 0%, rgba(17, 17, 21, 0.95) 100%);
            padding: 16px 20px;
            margin-bottom: 22px;
            border-radius: 6px;
            display: none;
            animation: fadeIn 0.2s ease-out;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-4px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .profile-flex {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }
        .profile-company-info {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .profile-ticker-tag {
            font-family: var(--font-mono);
            font-size: 16px;
            font-weight: 700;
            background: var(--c-roxo-profundo);
            color: var(--c-papel);
            border: 1px solid var(--c-roxo-fume);
            padding: 4px 12px;
            border-radius: 4px;
        }
        .profile-names h2 {
            font-family: var(--font-title);
            font-size: 18px;
            font-weight: 600;
            color: var(--c-papel);
        }
        .profile-names p {
            font-size: 12.5px;
            color: var(--c-roxo-fume);
        }
        .profile-tags-row {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .profile-data-chip {
            font-family: var(--font-mono);
            font-size: 10.5px;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--c-hairline);
            padding: 4px 10px;
            border-radius: 4px;
            color: var(--c-grafite-light);
        }
        .profile-data-chip strong {
            color: var(--c-papel);
        }

        /* ================= VIEWPORT COM OPÇÃO DE DESCER (SCROLL INTERNO) ================= */
        .docs-viewport-card {
            border: 1px solid var(--c-hairline);
            background: var(--c-card-bg);
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 40px;
        }
        .docs-viewport-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 20px;
            background: rgba(255, 255, 255, 0.02);
            border-bottom: 1px solid var(--c-hairline);
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--c-grafite-light);
        }
        .docs-count-badge {
            color: var(--c-roxo-fume);
            font-weight: 600;
        }
        .docs-scroll-indicator {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 10px;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }

        /* Container Rolável de Dimensão Menor */
        .docs-viewport-content {
            max-height: 680px;
            overflow-y: auto;
            padding: 16px;
            scrollbar-width: thin;
            scrollbar-color: var(--c-roxo-fume) var(--c-tinta);
        }
        .docs-viewport-content::-webkit-scrollbar {
            width: 6px;
        }
        .docs-viewport-content::-webkit-scrollbar-track {
            background: #0A0A0B;
        }
        .docs-viewport-content::-webkit-scrollbar-thumb {
            background: var(--c-roxo-fume);
            border-radius: 3px;
        }

        /* Layout de 1 Coluna Dentro do Viewport de Rolagem (Conforme Solicitado) */
        .docs-grid-layout {
            display: flex;
            flex-direction: column;
            gap: 14px;
            width: 100%;
        }

        /* Cards em Dimensão Menor e Largura Completa */
        .doc-item-compact {
            border: 1px solid var(--c-hairline);
            background: #0d0d11;
            border-radius: 6px;
            padding: 16px 22px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: all 0.2s;
            width: 100%;
            box-sizing: border-box;
        }
        .doc-item-compact:hover {
            border-color: rgba(140, 121, 192, 0.45);
            background: #13131a;
        }
        .doc-item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
            flex-wrap: wrap;
            gap: 8px;
        }
        .doc-tags-left {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .doc-ticker-pill {
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 600;
            color: var(--c-roxo-fume);
            background: rgba(59, 7, 100, 0.35);
            border: 1px solid rgba(140, 121, 192, 0.3);
            padding: 2px 8px;
            border-radius: 3px;
        }
        .doc-company-title {
            font-family: var(--font-title);
            font-size: 15px;
            font-weight: 600;
            color: var(--c-papel);
        }
        .doc-category-badge {
            font-family: var(--font-mono);
            font-size: 10px;
            text-transform: uppercase;
            padding: 2px 7px;
            border-radius: 3px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--c-hairline);
            color: var(--c-grafite-light);
        }
        .doc-category-badge.fr {
            background: rgba(244, 63, 94, 0.12);
            border-color: rgba(244, 63, 94, 0.35);
            color: #fb7185;
            font-weight: 600;
        }
        .doc-date-stamp {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--c-grafite-light);
        }
        .doc-subject-line {
            font-size: 13.5px;
            color: #d1d5db;
            margin-bottom: 12px;
            line-height: 1.5;
        }

        /* Resumo IA Compacto e Estruturado */
        .ai-summary-compact {
            background: #09080e;
            border: 1px solid rgba(140, 121, 192, 0.25);
            border-left: 3px solid var(--c-roxo-fume);
            border-radius: 4px;
            padding: 12px 14px;
            margin-bottom: 12px;
        }
        .ai-summary-top-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 8px;
            margin-bottom: 10px;
        }
        .ai-label-wrap {
            font-family: var(--font-mono);
            font-size: 9.5px;
            letter-spacing: 0.18em;
            color: var(--c-roxo-fume);
            font-weight: 600;
            text-transform: uppercase;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .impact-pill {
            font-family: var(--font-mono);
            font-size: 9.5px;
            letter-spacing: 0.12em;
            padding: 2px 9px;
            border-radius: 9999px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .impact-positive {
            background: rgba(34, 197, 94, 0.12);
            color: #4ade80;
            border: 1px solid rgba(34, 197, 94, 0.3);
        }
        .impact-neutral {
            background: rgba(140, 121, 192, 0.12);
            color: #c4b5fd;
            border: 1px solid rgba(140, 121, 192, 0.3);
        }
        .impact-risk {
            background: rgba(244, 63, 94, 0.12);
            color: #fb7185;
            border: 1px solid rgba(244, 63, 94, 0.3);
        }
        .summary-content-intro {
            font-size: 13px;
            line-height: 1.55;
            color: var(--c-papel);
            margin-bottom: 10px;
        }
        .summary-bullets-box {
            display: flex;
            flex-direction: column;
            gap: 6px;
            margin-bottom: 10px;
        }
        .summary-bullet-row {
            display: flex;
            align-items: flex-start;
            gap: 8px;
            font-size: 12.5px;
            line-height: 1.5;
            color: #e2e8f0;
        }
        .bullet-dot-mini {
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: var(--c-roxo-fume);
            margin-top: 7px;
            flex-shrink: 0;
        }
        .summary-analysis-callout {
            background: rgba(59, 7, 100, 0.2);
            border: 1px solid rgba(140, 121, 192, 0.2);
            border-radius: 4px;
            padding: 8px 12px;
            font-size: 12.5px;
            line-height: 1.5;
            color: #e2e8f0;
        }
        .analysis-label-mini {
            font-family: var(--font-mono);
            font-size: 9px;
            letter-spacing: 0.16em;
            color: var(--c-roxo-fume);
            margin-bottom: 4px;
            text-transform: uppercase;
        }

        .doc-item-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            padding-top: 10px;
            flex-wrap: wrap;
            gap: 8px;
        }
        .btn-gen-ai {
            font-family: var(--font-mono);
            font-size: 10.5px;
            letter-spacing: 0.1em;
            background: rgba(59, 7, 100, 0.35);
            border: 1px solid var(--c-roxo-fume);
            color: #d8b4fe;
            padding: 5px 12px;
            border-radius: 4px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
        }
        .btn-gen-ai:hover {
            background: var(--c-roxo-profundo);
            color: #ffffff;
        }
        .cvm-link-mini {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--c-roxo-fume);
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }
        .cvm-link-mini:hover {
            color: var(--c-papel);
            text-decoration: underline;
        }

        
        /* ================= BANNER E MODAL TELEGRAM ================= */
        .btn-tg-nav {
            background: rgba(0, 136, 204, 0.14) !important;
            border-color: rgba(0, 136, 204, 0.45) !important;
            color: #38bdf8 !important;
            font-weight: 600 !important;
        }
        .btn-tg-nav:hover {
            background: rgba(0, 136, 204, 0.3) !important;
            border-color: #38bdf8 !important;
            color: #ffffff !important;
        }

        .tg-promo-banner {
            border: 1px solid rgba(0, 136, 204, 0.35);
            background: linear-gradient(135deg, rgba(0, 100, 180, 0.18) 0%, rgba(13, 13, 17, 0.95) 100%);
            border-radius: 8px;
            padding: 14px 20px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
            cursor: pointer;
            transition: all 0.2s;
        }
        .tg-promo-banner:hover {
            border-color: rgba(56, 189, 248, 0.7);
            transform: translateY(-1px);
        }
        .tg-promo-left {
            display: flex;
            align-items: center;
            gap: 14px;
        }
        .tg-promo-icon {
            font-size: 24px;
            color: #38bdf8;
            background: rgba(0, 136, 204, 0.2);
            width: 44px;
            height: 44px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }
        .tg-promo-title {
            font-family: var(--font-title);
            font-size: 14.5px;
            font-weight: 700;
            color: var(--c-papel);
            letter-spacing: 0.04em;
        }
        .tg-promo-desc {
            font-size: 12.5px;
            color: var(--c-grafite-light);
            margin-top: 2px;
        }
        .tg-btn-group {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }
        .btn-tg-bot {
            background: linear-gradient(135deg, #7c3aed 0%, #3b0764 100%);
            border: 1px solid var(--c-roxo-fume);
            color: #ffffff !important;
            padding: 8px 16px;
            font-family: var(--font-mono);
            font-size: 11px;
            letter-spacing: 0.1em;
            font-weight: 600;
            border-radius: 4px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 7px;
            transition: all 0.2s;
            text-decoration: none;
            white-space: nowrap;
        }
        .btn-tg-bot:hover {
            background: linear-gradient(135deg, #8b5cf6 0%, #4c1d95 100%);
            box-shadow: 0 0 14px rgba(140, 121, 192, 0.5);
            color: #ffffff;
            transform: translateY(-1px);
        }
        .btn-tg-action {
            background: #0088cc;
            color: #ffffff !important;
            border: none;
            padding: 8px 16px;
            font-family: var(--font-mono);
            font-size: 11px;
            letter-spacing: 0.1em;
            font-weight: 600;
            border-radius: 4px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 7px;
            transition: all 0.2s;
            text-decoration: none;
        }
        .btn-tg-action:hover {
            background: #0099e6;
            box-shadow: 0 0 14px rgba(0, 136, 204, 0.5);
            color: #ffffff;
        }
        .btn-tg-test-pill {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(0, 136, 204, 0.5);
            color: #38bdf8;
            padding: 7px 14px;
            font-family: var(--font-mono);
            font-size: 11px;
            border-radius: 4px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
        }
        .btn-tg-test-pill:hover {
            background: rgba(0, 136, 204, 0.2);
            color: #ffffff;
        }
        .btn-tg-send-test {
            width: 100%;
            background: #0088cc;
            color: #fff;
            border: none;
            padding: 12px;
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.1em;
            border-radius: 4px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: all 0.2s;
        }
        .btn-tg-send-test:hover {
            background: #0099e6;
            box-shadow: 0 0 16px rgba(0, 136, 204, 0.4);
        }
        .btn-open-tg-now {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #0088cc;
            color: #fff !important;
            padding: 9px 18px;
            border-radius: 4px;
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 600;
            text-decoration: none;
            margin-top: 8px;
            transition: all 0.2s;
        }
        .btn-open-tg-now:hover {
            background: #0099e6;
            box-shadow: 0 0 12px rgba(0, 136, 204, 0.5);
        }

        /* ================= BANNER E MODAL WHATSAPP ================= */
        .btn-wpp-nav {
            background: rgba(37, 211, 102, 0.12) !important;
            border-color: rgba(37, 211, 102, 0.45) !important;
            color: #4ade80 !important;
            font-weight: 600 !important;
        }
        .btn-wpp-nav:hover {
            background: rgba(37, 211, 102, 0.28) !important;
            border-color: #4ade80 !important;
            color: #ffffff !important;
        }

        .wpp-promo-banner {
            border: 1px solid rgba(37, 211, 102, 0.35);
            background: linear-gradient(135deg, rgba(20, 83, 45, 0.22) 0%, rgba(13, 13, 17, 0.95) 100%);
            border-radius: 8px;
            padding: 14px 20px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
            cursor: pointer;
            transition: all 0.2s;
        }
        .wpp-promo-banner:hover {
            border-color: rgba(74, 222, 128, 0.65);
            transform: translateY(-1px);
        }
        .wpp-promo-left {
            display: flex;
            align-items: center;
            gap: 14px;
        }
        .wpp-promo-icon {
            font-size: 24px;
            color: #4ade80;
            background: rgba(37, 211, 102, 0.15);
            width: 44px;
            height: 44px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }
        .wpp-promo-title {
            font-family: var(--font-title);
            font-size: 14.5px;
            font-weight: 700;
            color: var(--c-papel);
            letter-spacing: 0.04em;
        }
        .wpp-promo-desc {
            font-size: 12.5px;
            color: var(--c-grafite-light);
            margin-top: 2px;
        }
        .btn-wpp-action {
            background: #16a34a;
            color: #ffffff;
            border: none;
            padding: 8px 16px;
            font-family: var(--font-mono);
            font-size: 11px;
            letter-spacing: 0.1em;
            font-weight: 600;
            border-radius: 4px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 7px;
            transition: all 0.2s;
        }
        .btn-wpp-action:hover {
            background: #22c55e;
            box-shadow: 0 0 14px rgba(34, 197, 94, 0.4);
        }

        /* Modal Styles */
        .modal-backdrop {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(0, 0, 0, 0.78);
            backdrop-filter: blur(4px);
            z-index: 9999;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .modal-card {
            background: #101015;
            border: 1px solid var(--c-roxo-fume);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.7);
            border-radius: 8px;
            max-width: 580px;
            width: 100%;
            overflow: hidden;
            animation: modalFadeIn 0.2s ease-out;
        }
        @keyframes modalFadeIn {
            from { opacity: 0; transform: scale(0.97); }
            to { opacity: 1; transform: scale(1); }
        }
        .modal-header {
            background: rgba(59, 7, 100, 0.25);
            border-bottom: 1px solid var(--c-hairline);
            padding: 16px 22px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .modal-header h3 {
            font-family: var(--font-title);
            font-size: 16px;
            font-weight: 700;
            color: var(--c-papel);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .modal-close-btn {
            background: none;
            border: none;
            color: var(--c-grafite-light);
            font-size: 18px;
            cursor: pointer;
            transition: color 0.2s;
        }
        .modal-close-btn:hover {
            color: #ffffff;
        }
        .modal-body {
            padding: 22px;
        }
        .wpp-form-group {
            margin-bottom: 16px;
        }
        .wpp-form-label {
            display: block;
            font-family: var(--font-mono);
            font-size: 10.5px;
            letter-spacing: 0.14em;
            color: var(--c-roxo-fume);
            margin-bottom: 6px;
            text-transform: uppercase;
        }
        .wpp-input {
            width: 100%;
            background: #08080a;
            border: 1px solid var(--c-hairline);
            color: var(--c-papel);
            padding: 10px 14px;
            font-family: var(--font-body);
            font-size: 13.5px;
            border-radius: 4px;
            box-sizing: border-box;
            outline: none;
            transition: border-color 0.2s;
        }
        .wpp-input:focus {
            border-color: #22c55e;
        }
        .wpp-checkbox-wrap {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12.5px;
            color: var(--c-papel);
            cursor: pointer;
            margin-top: 6px;
        }
        .wpp-checkbox-wrap input {
            accent-color: #22c55e;
            width: 16px;
            height: 16px;
            cursor: pointer;
        }
        .wpp-modal-actions {
            display: flex;
            gap: 10px;
            margin-top: 22px;
            flex-wrap: wrap;
        }
        .btn-wpp-save {
            flex: 1;
            background: #16a34a;
            color: #ffffff;
            border: none;
            padding: 11px 16px;
            font-family: var(--font-mono);
            font-size: 11.5px;
            font-weight: 600;
            letter-spacing: 0.08em;
            border-radius: 4px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: all 0.2s;
        }
        .btn-wpp-save:hover {
            background: #22c55e;
        }
        .btn-wpp-test {
            background: rgba(255, 255, 255, 0.06);
            color: var(--c-papel);
            border: 1px solid var(--c-hairline);
            padding: 11px 16px;
            font-family: var(--font-mono);
            font-size: 11.5px;
            border-radius: 4px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s;
        }
        .btn-wpp-test:hover {
            background: rgba(255, 255, 255, 0.12);
            border-color: var(--c-roxo-fume);
        }
        .wpp-alert-box {
            margin-top: 16px;
            padding: 10px 14px;
            border-radius: 4px;
            font-size: 12.5px;
            line-height: 1.5;
            display: none;
        }
        .wpp-alert-box.success {
            display: block;
            background: rgba(34, 197, 94, 0.15);
            border: 1px solid rgba(34, 197, 94, 0.4);
            color: #86efac;
        }
        .wpp-alert-box.info {
            display: block;
            background: rgba(140, 121, 192, 0.12);
            border: 1px solid rgba(140, 121, 192, 0.35);
            color: var(--c-papel);
        }
        .wpp-alert-box.error {
            display: block;
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.4);
            color: #fca5a5;
        }
        .btn-open-wpp-now {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #22c55e;
            color: #ffffff !important;
            text-decoration: none !important;
            padding: 9px 16px;
            font-family: var(--font-mono);
            font-size: 11.5px;
            font-weight: 700;
            letter-spacing: 0.05em;
            border-radius: 4px;
            box-shadow: 0 3px 12px rgba(34, 197, 94, 0.4);
            transition: all 0.2s;
            margin-top: 10px;
        }
        .btn-open-wpp-now:hover {
            background: #16a34a;
            transform: translateY(-1px);
            box-shadow: 0 5px 16px rgba(34, 197, 94, 0.6);
        }
        .wpp-guide-box {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--c-hairline);
            border-radius: 4px;
            padding: 10px 14px;
            margin-top: 14px;
            font-size: 11.5px;
            line-height: 1.5;
            color: var(--c-grafite-light);
        }
        .wpp-guide-title {
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 0.14em;
            color: var(--c-roxo-fume);
            margin-bottom: 4px;
            text-transform: uppercase;
            font-weight: 600;
        }
        .wpp-registered-list {
            margin-top: 20px;
            border-top: 1px solid var(--c-hairline);
            padding-top: 14px;
        }
        .wpp-registered-title {
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 0.18em;
            color: var(--c-roxo-fume);
            margin-bottom: 8px;
            text-transform: uppercase;
        }
        .wpp-item-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--c-hairline);
            padding: 8px 12px;
            border-radius: 4px;
            margin-bottom: 6px;
            font-size: 12px;
        }
        .wpp-item-tag {
            font-family: var(--font-mono);
            font-weight: 700;
            color: var(--c-roxo-fume);
            margin-left: 8px;
        }
        .btn-wpp-del {
            background: none;
            border: none;
            color: #f87171;
            cursor: pointer;
            padding: 2px 6px;
            font-size: 12px;
            transition: color 0.2s;
        }
        .btn-wpp-del:hover {
            color: #ef4444;
        }

        /* ================= RODAPÉ OFICIAL CF TECH (IMAGEM 2) ================= */
        .footer-system {
            margin-top: 40px;
            border-top: 1px solid var(--c-hairline);
            padding-top: 35px;
        }
        .footer-brand-box {
            display: grid;
            grid-template-columns: 1fr 340px;
            border: 1px solid var(--c-hairline);
            background: var(--c-card-bg);
            margin-bottom: 20px;
        }
        .footer-left {
            padding: 28px 30px;
            border-right: 1px solid var(--c-hairline);
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .footer-label {
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 0.2em;
            color: var(--c-roxo-fume);
            text-transform: uppercase;
        }
        .footer-desc {
            font-size: 13.5px;
            line-height: 1.65;
            color: var(--c-papel);
        }
        .footer-disclaimer {
            font-size: 11.5px;
            line-height: 1.55;
            color: var(--c-grafite-light);
            border-top: 1px solid var(--c-hairline);
            padding-top: 10px;
            margin-top: 4px;
        }

        .footer-right {
            background: #070709;
            padding: 28px 24px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .social-nav-title {
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 0.24em;
            color: var(--c-roxo-fume);
            margin-bottom: 16px;
            text-transform: uppercase;
        }
        .social-links-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .social-btn {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 14px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--c-hairline);
            border-radius: 5px;
            color: var(--c-papel);
            font-family: var(--font-body);
            font-size: 13.5px;
            font-weight: 500;
            transition: all 0.2s;
        }
        .social-btn-inner {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .social-btn i {
            font-size: 15px;
            color: var(--c-roxo-fume);
        }
        .social-arrow {
            font-family: var(--font-mono);
            color: var(--c-roxo-fume);
            transition: transform 0.2s;
        }
        .social-btn:hover {
            background: rgba(59, 7, 100, 0.35);
            border-color: var(--c-roxo-fume);
            color: #ffffff;
            transform: translateX(3px);
        }
        .social-btn:hover .social-arrow {
            transform: translateX(3px);
            color: #ffffff;
        }

        .bottom-line {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-family: var(--font-mono);
            font-size: 9.5px;
            letter-spacing: 0.16em;
            color: var(--c-grafite-light);
            text-transform: uppercase;
            padding: 12px 0 25px;
        }

        .empty-state {
            text-align: center;
            padding: 50px 20px;
            color: var(--c-grafite-light);
            font-size: 14px;
            border: 1px dashed var(--c-hairline);
            border-radius: 6px;
            grid-column: 1 / -1;
        }

        /* ================= MOBILE RESPONSIVE MASTER DESIGN (CF TECH v2) ================= */
        @media (max-width: 900px) {
            .logo-cf-banner { height: 50px; max-width: 260px; }
            .metrics-grid {
                grid-template-columns: 1fr 1fr;
            }
            .metric-cell:nth-child(1), .metric-cell:nth-child(2) {
                border-bottom: 1px solid var(--c-hairline);
            }
            .metric-cell:nth-child(2) {
                border-right: none;
            }
            .search-inputs-row { grid-template-columns: 1fr; }
            .docs-grid-layout { grid-template-columns: 1fr; }
            .footer-brand-box { grid-template-columns: 1fr; }
            .footer-left { border-right: none; border-bottom: 1px solid var(--c-hairline); }
            .hero-title { font-size: 38px; }
        }

        @media (max-width: 640px) {
            /* Container & espaçamentos mobile */
            .container {
                padding: 0 14px 50px;
            }
            
            /* Header limpo e harmonioso */
            header {
                flex-direction: column;
                align-items: center;
                gap: 14px;
                padding: 16px 0;
                margin-bottom: 20px;
            }
            .brand-lockup {
                width: 100%;
                justify-content: center;
            }
            .logo-cf-banner {
                height: 44px;
                max-width: 220px;
            }
            .header-actions {
                display: flex;
                width: 100%;
                gap: 6px;
                justify-content: stretch;
            }
            .btn-top {
                flex: 1;
                font-size: 9.5px;
                letter-spacing: 0.08em;
                padding: 9px 6px;
                justify-content: center;
                text-align: center;
                white-space: nowrap;
                gap: 5px;
            }
            .btn-top i {
                font-size: 11px;
            }

            /* Capa / Hero Mobile */
            .hero-section {
                padding: 10px 0 20px;
                margin-bottom: 20px;
            }
            .hero-tag {
                font-size: 9.5px;
                letter-spacing: 0.18em;
                margin-bottom: 8px;
            }
            .hero-title {
                font-size: 28px;
                line-height: 1.15;
                margin-bottom: 10px;
            }
            .hero-subtitle {
                font-size: 13px;
                line-height: 1.55;
            }

            /* Grid de Métricas 2x2 harmonioso */
            .metrics-grid {
                grid-template-columns: 1fr 1fr;
                margin-bottom: 18px;
                border-radius: 6px;
                overflow: hidden;
            }
            .metric-cell {
                padding: 12px 14px;
                gap: 4px;
            }
            .metric-cell-label {
                font-size: 9px;
                letter-spacing: 0.12em;
            }
            .metric-cell-val {
                font-size: 20px;
            }
            .metric-cell-sub {
                font-size: 10px;
            }

            /* Caixa de Busca Mobile */
            .search-container {
                padding: 14px 14px;
                margin-bottom: 18px;
                border-radius: 6px;
            }
            .search-label {
                font-size: 9.5px;
                letter-spacing: 0.14em;
                margin-bottom: 10px;
            }
            .search-inputs-row {
                gap: 8px;
                margin-bottom: 12px;
            }
            .search-box-wrap input {
                font-size: 13px;
                padding: 11px 14px 11px 38px;
                border-radius: 5px;
            }
            .search-box-wrap i {
                left: 13px;
                font-size: 13px;
            }
            .select-company-dropdown {
                height: 42px;
                font-size: 12.5px;
                padding: 8px 12px;
                width: 100%;
                border-radius: 5px;
            }

            /* Barra de Meses deslizável (horizontal scroll nativo) */
            .month-selector-bar {
                display: flex;
                align-items: center;
                gap: 6px;
                flex-wrap: nowrap;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
                scrollbar-width: none;
                padding: 10px 0;
                margin-bottom: 12px;
            }
            .month-selector-bar::-webkit-scrollbar {
                display: none;
            }
            .month-label {
                flex-shrink: 0;
                font-size: 9px;
                letter-spacing: 0.12em;
            }
            .month-pill {
                flex-shrink: 0;
                white-space: nowrap;
                font-size: 10.5px;
                padding: 5px 11px;
            }

            /* Atalhos de Filtro deslizáveis */
            .filter-pills-row {
                display: flex;
                align-items: center;
                gap: 6px;
                flex-wrap: nowrap;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
                scrollbar-width: none;
                padding-bottom: 2px;
            }
            .filter-pills-row::-webkit-scrollbar {
                display: none;
            }
            .pills-prefix {
                flex-shrink: 0;
                font-size: 9px;
            }
            .pill-btn {
                flex-shrink: 0;
                white-space: nowrap;
                font-size: 10.5px;
                padding: 5px 12px;
            }

            /* Card de Perfil da Empresa Mobile */
            .company-profile-banner {
                padding: 14px 14px;
                margin-bottom: 16px;
            }
            .profile-flex {
                flex-direction: column;
                align-items: flex-start;
                gap: 10px;
            }
            .profile-company-info {
                gap: 10px;
            }
            .profile-ticker-tag {
                font-size: 14px;
                padding: 3px 10px;
            }
            .profile-names h2 {
                font-size: 16px;
            }
            .profile-names p {
                font-size: 12px;
            }
            .profile-tags-row {
                width: 100%;
                gap: 6px;
            }
            .profile-data-chip {
                font-size: 9.5px;
                padding: 3px 8px;
            }

            /* Banner Telegram Mobile */
            .tg-promo-banner {
                flex-direction: column;
                align-items: stretch;
                gap: 12px;
                padding: 14px;
                margin-bottom: 16px;
            }
            .tg-promo-left {
                gap: 12px;
            }
            .tg-promo-icon {
                width: 38px;
                height: 38px;
                font-size: 20px;
            }
            .tg-promo-title {
                font-size: 13.5px;
                line-height: 1.3;
            }
            .tg-promo-desc {
                font-size: 12px;
                line-height: 1.45;
            }
            .tg-btn-group {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                width: 100%;
            }
            .btn-tg-action, .btn-tg-test-pill {
                width: 100%;
                justify-content: center;
                padding: 9px 8px;
                font-size: 10.5px;
                text-align: center;
            }

            /* Viewport de Documentos Mobile (Sem armadilha de scroll duplo) */
            .docs-viewport-card {
                border-radius: 6px;
                margin-bottom: 25px;
            }
            .docs-viewport-header {
                padding: 10px 14px;
                font-size: 10px;
            }
            .docs-scroll-indicator {
                display: none;
            }
            .docs-viewport-content {
                max-height: none;
                overflow-y: visible;
                padding: 10px;
            }
            .docs-grid-layout {
                gap: 10px;
            }

            /* Card do Documento CVM no Celular */
            .doc-item-compact {
                padding: 14px 12px;
                border-radius: 6px;
            }
            .doc-item-header {
                flex-direction: column;
                align-items: flex-start;
                gap: 6px;
                margin-bottom: 8px;
            }
            .doc-tags-left {
                width: 100%;
                gap: 6px;
            }
            .doc-ticker-pill {
                font-size: 11px;
                padding: 2px 7px;
            }
            .doc-company-title {
                font-size: 13.5px;
                line-height: 1.3;
            }
            .doc-category-badge {
                font-size: 9px;
                padding: 2px 6px;
            }
            .doc-date-stamp {
                font-size: 10.5px;
                color: var(--c-grafite-light);
            }
            .doc-subject-line {
                font-size: 12.5px;
                line-height: 1.45;
                margin-bottom: 10px;
            }

            /* Parecer IA Gemini Mobile */
            .ai-summary-compact {
                padding: 10px 10px;
                margin-bottom: 10px;
            }
            .ai-summary-top-row {
                flex-wrap: wrap;
                gap: 6px;
                padding-bottom: 6px;
                margin-bottom: 8px;
            }
            .ai-label-wrap {
                font-size: 8.5px;
                letter-spacing: 0.12em;
            }
            .impact-pill {
                font-size: 8.5px;
                padding: 2px 7px;
            }
            .summary-content-intro {
                font-size: 12px;
                line-height: 1.5;
                margin-bottom: 8px;
            }
            .summary-bullet-row {
                font-size: 11.5px;
                line-height: 1.45;
                gap: 6px;
            }
            .summary-analysis-callout {
                padding: 8px 10px;
                font-size: 11.5px;
                line-height: 1.45;
            }

            /* Rodapé do Card Mobile */
            .doc-item-footer {
                padding-top: 8px;
                flex-direction: row;
                justify-content: space-between;
                align-items: center;
                gap: 8px;
            }
            .btn-gen-ai {
                font-size: 10px;
                padding: 6px 10px;
            }
            .cvm-link-mini {
                font-size: 10.5px;
            }

            /* Modais Mobile */
            .modal-backdrop {
                padding: 12px;
            }
            .modal-card {
                max-height: 92vh;
                display: flex;
                flex-direction: column;
                border-radius: 6px;
            }
            .modal-header {
                padding: 12px 16px;
            }
            .modal-header h3 {
                font-size: 13px;
                line-height: 1.3;
            }
            .modal-body {
                padding: 14px 14px;
                overflow-y: auto;
                -webkit-overflow-scrolling: touch;
            }
            .wpp-modal-actions {
                flex-direction: column;
                gap: 8px;
            }
            .btn-wpp-save, .btn-wpp-test {
                width: 100%;
                justify-content: center;
            }

            /* Rodapé Oficial CF Tech Mobile */
            .footer-brand-box {
                grid-template-columns: 1fr;
            }
            .footer-left {
                padding: 20px 16px;
            }
            .footer-right {
                padding: 20px 16px;
            }
            .footer-desc {
                font-size: 12.5px;
            }
            .footer-disclaimer {
                font-size: 10.5px;
            }
            .bottom-line {
                flex-direction: column;
                gap: 6px;
                text-align: center;
                font-size: 8.5px;
                padding: 12px 0 20px;
            }
        }

        @media (max-width: 400px) {
            .header-actions {
                flex-direction: column;
            }
            .btn-top {
                width: 100%;
            }
            .tg-btn-group {
                grid-template-columns: 1fr;
            }
            .metrics-grid {
                grid-template-columns: 1fr;
            }
            .metric-cell {
                border-right: none !important;
                border-bottom: 1px solid var(--c-hairline);
            }
            .metric-cell:last-child {
                border-bottom: none;
            }
        }
    </style>
</head>
<body>

    <!-- Faixa Técnica / Marquee Tape Oficial -->
    <div class="marquee-bar">
        <div class="marquee-track">
            <span>DADOS DIRETO DA CVM &bull; ESCALA ORIGINAL, SEM ABREVIAÇÃO &bull; 680+ EMPRESAS B3 &bull; SEM CADASTRO &bull; SEM ARMAZENAMENTO &bull; IA GEMINI 3.1 FLASH LITE &bull; CEARÁ FINANCE &bull; FRONT OFFICE DE TECNOLOGIA &bull;</span>
            <span>DADOS DIRETO DA CVM &bull; ESCALA ORIGINAL, SEM ABREVIAÇÃO &bull; 680+ EMPRESAS B3 &bull; SEM CADASTRO &bull; SEM ARMAZENAMENTO &bull; IA GEMINI 3.1 FLASH LITE &bull; CEARÁ FINANCE &bull; FRONT OFFICE DE TECNOLOGIA &bull;</span>
        </div>
    </div>

    <div class="container">
        <!-- Header Oficial com o Logo Novo Enviado -->
        <header>
            <div class="brand-lockup">
                <a href="http://localhost:8001" style="display:inline-flex;align-items:center;">
                    <img src="/LOGO_CF_TECH.png" alt="CF TECH — Ceará Finance" class="logo-cf-banner" onerror="this.onerror=null;this.src='/LOGO_CF.png';">
                </a>
            </div>

            <div class="header-actions">
                <button onclick="abrirModalTelegram()" class="btn-top btn-tg-nav"><i class="fab fa-telegram"></i> ALERTAS TELEGRAM</button>
                <button onclick="carregarDocs()" class="btn-top"><i class="fas fa-rotate"></i> ATUALIZAR</button>
            </div>
        </header>

        <!-- Capa Conceitual -->
        <section class="hero-section">
            <div class="hero-tag">01 &bull; REGULATÓRIO & PARECERES DE RI</div>
            <h1 class="hero-title">Fatos relevantes,<br>direto da CVM.</h1>
            <p class="hero-subtitle">
                Busque uma empresa listada por ticker ou código CVM. Resumos executivos sintetizados por inteligência artificial, dados sem filtro, sem ruído e em escala original de todos os meses do ano.
            </p>
        </section>

        <!-- Métricas em Grid Técnico (Manual de Marca) -->
        <div class="metrics-grid">
            <div class="metric-cell">
                <div class="metric-cell-label">01 &bull; Documentos Oficiais 2026</div>
                <div class="metric-cell-val" id="metric-total">33.541</div>
                <div class="metric-cell-sub">Todos os meses catalogados</div>
            </div>
            <div class="metric-cell">
                <div class="metric-cell-label">02 &bull; Fatos Relevantes</div>
                <div class="metric-cell-val" id="metric-fr">4.041</div>
                <div class="metric-cell-sub">Eventos de impacto no mercado</div>
            </div>
            <div class="metric-cell">
                <div class="metric-cell-label">03 &bull; Universo B3 & CVM</div>
                <div class="metric-cell-val" id="metric-cia">684</div>
                <div class="metric-cell-sub">Empresas com cobertura ativa</div>
            </div>
            <div class="metric-cell">
                <div class="metric-cell-label">04 &bull; Inteligência Artificial</div>
                <div class="metric-cell-val" style="color: var(--c-roxo-fume); font-size: 19px; display:flex; align-items:center; gap:8px;">
                    <i class="fas fa-brain"></i> Gemini 3.1
                </div>
                <div class="metric-cell-sub">Pareceres didáticos & síntese</div>
            </div>
        </div>

        <!-- Seção de Busca e Filtros -->
        <div class="search-container">
            <div class="search-label">
                <i class="fas fa-terminal"></i> Consulta por Ticker, Razão Social ou Código CVM
            </div>
            <div class="search-inputs-row">
                <div class="search-box-wrap">
                    <i class="fas fa-search"></i>
                    <input type="text" id="input-search" list="lista-empresas" placeholder="Buscar por nome, CNPJ, ticker ou código CVM (ex: ITUB4, MGLU3, PETR4, BBAS3, VALE3)..." oninput="debounceSearch()">
                    <datalist id="lista-empresas"></datalist>
                </div>
                <select class="select-company-dropdown" id="select-empresa" onchange="selecionarDropdown(this.value)">
                    <option value="">-- Selecionar Empresa (680+ B3) --</option>
                </select>
            </div>

            <!-- Barra de Seleção de Meses do Ano (Todos os Meses de 2026) -->
            <div class="month-selector-bar" id="month-bar">
                <span class="month-label"><i class="far fa-calendar-check"></i> MESES 2026:</span>
                <button class="month-pill active" onclick="selecionarMes('', this)">Ano Todo (Jan a Out)</button>
                <button class="month-pill" onclick="selecionarMes('2026-10', this)">Out/26</button>
                <button class="month-pill" onclick="selecionarMes('2026-09', this)">Set/26</button>
                <button class="month-pill" onclick="selecionarMes('2026-08', this)">Ago/26</button>
                <button class="month-pill" onclick="selecionarMes('2026-07', this)">Jul/26</button>
                <button class="month-pill" onclick="selecionarMes('2026-06', this)">Jun/26</button>
                <button class="month-pill" onclick="selecionarMes('2026-05', this)">Mai/26</button>
                <button class="month-pill" onclick="selecionarMes('2026-04', this)">Abr/26</button>
                <button class="month-pill" onclick="selecionarMes('2026-03', this)">Mar/26</button>
                <button class="month-pill" onclick="selecionarMes('2026-02', this)">Fev/26</button>
                <button class="month-pill" onclick="selecionarMes('2026-01', this)">Jan/26</button>
            </div>

            <div class="filter-pills-row">
                <span class="pills-prefix">ATALHOS B3:</span>
                <button class="pill-btn active" onclick="filtrarPill('', this)">Todas</button>
                <button class="pill-btn" onclick="filtrarPill('Fato Relevante', this)">Fatos Relevantes</button>
                <button class="pill-btn" onclick="filtrarPill('Comunicado', this)">Comunicados</button>
                <button class="pill-btn" onclick="filtrarPill('PETR4', this)">PETR4</button>
                <button class="pill-btn" onclick="filtrarPill('VALE3', this)">VALE3</button>
                <button class="pill-btn" onclick="filtrarPill('ITUB4', this)">ITUB4</button>
                <button class="pill-btn" onclick="filtrarPill('BBAS3', this)">BBAS3</button>
                <button class="pill-btn" onclick="filtrarPill('MGLU3', this)">MGLU3</button>
                <button class="pill-btn" onclick="filtrarPill('RENT3', this)">RENT3</button>
                <button class="pill-btn" onclick="filtrarPill('WEGE3', this)">WEGE3</button>
                <button class="pill-btn" onclick="filtrarPill('DIRR3', this)">DIRR3</button>
                <button class="pill-btn" onclick="filtrarPill('PRIO3', this)">PRIO3</button>
            </div>
        </div>

        <!-- Card de Perfil da Empresa Selecionada -->
        <div id="company-profile" class="company-profile-banner">
            <div class="profile-flex">
                <div class="profile-company-info">
                    <div class="profile-ticker-tag" id="p-ticker">B3</div>
                    <div class="profile-names">
                        <h2 id="p-name">Companhia Aberta</h2>
                        <p id="p-sector">Setor de Atuação</p>
                    </div>
                </div>
                <div class="profile-tags-row">
                    <div class="profile-data-chip">CVM: <strong id="p-cvm">-</strong></div>
                    <div class="profile-data-chip">CNPJ: <strong id="p-cnpj">-</strong></div>
                    <div class="profile-data-chip" style="color: #4ade80;"><i class="fas fa-circle-check"></i> <strong>100% Monitorado</strong></div>
                </div>
            </div>
        </div>

        <!-- Banner Destaque Telegram -->
        <div class="tg-promo-banner" onclick="abrirModalTelegram()">
            <div class="tg-promo-left">
                <div class="tg-promo-icon"><i class="fab fa-telegram-plane"></i></div>
                <div>
                    <div class="tg-promo-title">CONEXÃO OFICIAL TELEGRAM · CEARÁ FINANCE</div>
                    <div class="tg-promo-desc">Converse no privado com nosso <strong>Robô IA (@CEARA_FINANCE_BOT)</strong> para pedir resumos de qualquer empresa ou receba o feed no <strong>Canal de Alertas</strong>.</div>
                </div>
            </div>
            <div class="tg-btn-group">
                <a href="https://t.me/CEARA_FINANCE_BOT" target="_blank" class="btn-tg-bot" onclick="event.stopPropagation()">
                    <i class="fas fa-robot"></i> CONVERSAR COM O BOT
                </a>
                <a href="https://t.me/+T1V2m44be_Q3MjYx" target="_blank" class="btn-tg-action" onclick="event.stopPropagation()">
                    <i class="fab fa-telegram-plane"></i> ENTRAR NO CANAL
                </a>
            </div>
        </div>

        <!-- VIEWPORT COM OPÇÃO DE DESCER (SCROLL INTERNO COM 1 COLUNA AMPLA) -->
        <div class="docs-viewport-card">
            <div class="docs-viewport-header">
                <div>
                    <span>REGISTROS ENCONTRADOS: </span>
                    <strong class="docs-count-badge" id="visible-count">0</strong>
                </div>
                <div class="docs-scroll-indicator">
                    <span>Role para descer e ver mais</span>
                    <i class="fas fa-arrow-down" style="color: var(--c-roxo-fume);"></i>
                </div>
            </div>

            <div class="docs-viewport-content" id="docs-scroll-area">
                <div id="docs-list" class="docs-grid-layout">
                    <div class="empty-state"><i class="fas fa-spinner fa-spin"></i> Carregando base de comunicados oficiais da CVM...</div>
                </div>
            </div>
        </div>

        <!-- ================= RODAPÉ OFICIAL CF TECH (IMAGEM 2) ================= -->
        <footer class="footer-system">
            <div class="footer-brand-box">
                <!-- Lado Esquerdo -->
                <div class="footer-left">
                    <div class="footer-label">O QUE É O CF TECH</div>
                    <div class="footer-desc">
                        <strong>CF Tech</strong> é o <strong>Front Office de tecnologia</strong> da Ceará Finance — construído sobre três pilares: <strong>didática, criatividade e tecnologia</strong>. Esse hub é um dos nossos experimentos: pegar dado público e denso (como as demonstrações e fatos relevantes da CVM) e deixar acessível, sem cadastro e sem fricção.
                    </div>
                    <div class="footer-disclaimer">
                        Projeto independente de tecnologia da Ceará Finance. Os dados vêm direto da CVM (Comissão de Valores Mobiliários); não há vínculo, afiliação ou verificação por parte do órgão regulador.
                    </div>
                </div>

                <!-- Lado Direito (SIGA A LIGA) -->
                <div class="footer-right">
                    <div>
                        <div class="social-nav-title">SIGA A LIGA</div>
                        <div class="social-links-list">
                            <a href="https://www.instagram.com/cearafinance/" target="_blank" class="social-btn">
                                <div class="social-btn-inner">
                                    <i class="fab fa-instagram"></i>
                                    <span>Instagram</span>
                                </div>
                                <span class="social-arrow">→</span>
                            </a>
                            <a href="https://www.linkedin.com/company/ceara-finance/posts/?feedView=all" target="_blank" class="social-btn">
                                <div class="social-btn-inner">
                                    <i class="fab fa-linkedin"></i>
                                    <span>LinkedIn</span>
                                </div>
                                <span class="social-arrow">→</span>
                            </a>
                        </div>
                    </div>
                </div>
            </div>

            <div class="bottom-line">
                <div>CF TECH &bull; CEARÁ FINANCE &bull; DADOS PÚBLICOS DA CVM &bull; MANUAL DE MARCA v2</div>
                <div>EDIÇÃO 2026 &bull; USO INTERNO</div>
            </div>
        </footer>
    </div>

    <!-- Modal de Vinculação WhatsApp -->
    
    <!-- Modal Oficial Telegram -->
    <div id="modal-tg" class="modal-backdrop" onclick="fecharModalTgOverlay(event)">
        <div class="modal-card">
            <div class="modal-header" style="background: rgba(0, 136, 204, 0.18);">
                <h3><i class="fab fa-telegram" style="color:#0088cc;"></i> Conexão Oficial Telegram · Ceará Finance</h3>
                <button class="modal-close-btn" onclick="fecharModalTg()">&times;</button>
            </div>
            <div class="modal-body">
                <p style="font-size: 13px; color: var(--c-grafite-light); margin-bottom: 16px; line-height: 1.55;">
                    Escolha como deseja se conectar com o sistema de Inteligência Artificial da <strong>Ceará Finance</strong> no Telegram:
                </p>

                <!-- CARD 1: ROBÔ INDIVIDUAL (1-A-1) -->
                <div style="background: rgba(124, 58, 237, 0.1); border: 1px solid rgba(140, 121, 192, 0.35); border-radius: 6px; padding: 15px 18px; margin-bottom: 12px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
                        <div>
                            <div style="font-size:10px; font-family:var(--font-mono); color:#c4b5fd; text-transform:uppercase; letter-spacing:0.12em;"><i class="fas fa-robot"></i> Atendimento Individual Privado</div>
                            <div style="font-size:16px; font-weight:700; color:var(--c-papel);">@CEARA_FINANCE_BOT</div>
                            <div style="font-size:11.5px; color:var(--c-grafite-light); margin-top:2px;">Envie qualquer ticker (ex: <code>PETR4</code>, <code>VALE3</code>, <code>DIRR3</code>) e receba o parecer da IA no privado.</div>
                        </div>
                        <a href="https://t.me/CEARA_FINANCE_BOT" target="_blank" class="btn-tg-bot" style="padding:10px 18px; font-size:11.5px;">
                            <i class="fas fa-comment-dots"></i> CONVERSAR COM O BOT
                        </a>
                    </div>
                </div>

                <!-- CARD 2: CANAL COLETIVO DE ALERTAS -->
                <div style="background: rgba(0, 136, 204, 0.08); border: 1px solid rgba(0, 136, 204, 0.3); border-radius: 6px; padding: 15px 18px; margin-bottom: 18px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
                        <div>
                            <div style="font-size:10px; font-family:var(--font-mono); color:#38bdf8; text-transform:uppercase; letter-spacing:0.12em;"><i class="fab fa-telegram-plane"></i> Feed Contínuo de Alertas</div>
                            <div style="font-size:16px; font-weight:700; color:var(--c-papel);">CEARA_FINANCE_CANAL</div>
                            <div style="font-size:11.5px; color:var(--c-grafite-light); margin-top:2px;">Transmissão automática com notificação sonora a cada novo documento protocolado na CVM.</div>
                        </div>
                        <a href="https://t.me/+T1V2m44be_Q3MjYx" target="_blank" class="btn-tg-action" style="padding:10px 18px; font-size:11.5px;">
                            <i class="fab fa-telegram-plane"></i> ENTRAR NO CANAL
                        </a>
                    </div>
                </div>

                <div class="wpp-form-group">
                    <label class="wpp-form-label">Ação / Ticker para Disparar Alerta de Teste</label>
                    <input type="text" id="tg-input-ticker" class="wpp-input" style="border-color: rgba(0, 136, 204, 0.4);" placeholder="Ex: PETR4, VALE3, MDIA3, ITUB4..." value="PETR4">
                </div>

                <div id="tg-feedback" class="wpp-alert-box" style="display:none;"></div>

                <div style="margin-top: 14px;">
                    <button class="btn-tg-send-test" onclick="dispararTesteTelegram()" id="btn-disparar-tg">
                        <i class="fas fa-paper-plane"></i> DISPARAR ALERTA DE TESTE NO TELEGRAM
                    </button>
                </div>

                <div class="wpp-guide-box" style="margin-top: 20px; border-color: rgba(0, 136, 204, 0.25);">
                    <div class="wpp-guide-title" style="color:#38bdf8;"><i class="fas fa-circle-check"></i> 100% Automático e Gratuito</div>
                    <div style="font-size:12px; color:var(--c-grafite-light); line-height:1.5;">
                        O robô da Ceará Finance monitora a CVM 24h por dia. Assim que qualquer empresa monitorada protocola um documento oficial, a IA sintetiza o parecer executivo e publica no canal imediatamente com notificação sonora no seu celular!
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div id="modal-wpp" class="modal-backdrop" onclick="fecharModalWppOverlay(event)">
        <div class="modal-card">
            <div class="modal-header">
                <h3><i class="fab fa-whatsapp" style="color:#22c55e;"></i> Alertas CVM no WhatsApp</h3>
                <button class="modal-close-btn" onclick="fecharModalWpp()">&times;</button>
            </div>
            <div class="modal-body">
                <p style="font-size: 13px; color: var(--c-grafite-light); margin-bottom: 18px; line-height: 1.55;">
                    Vincule seu número para receber os comunicados de uma ação (ex: <strong>MDIA3</strong>, <strong>PETR4</strong>, <strong>VALE3</strong>) ou de <strong>TODAS</strong> com o parecer executivo do Gemini diretamente no WhatsApp assim que protocolados na CVM.
                </p>

                <div class="wpp-form-group">
                    <label class="wpp-form-label">Seu Número de WhatsApp (com DDD)</label>
                    <input type="text" id="wpp-input-phone" class="wpp-input" placeholder="(85) 99999-9999" maxlength="20">
                </div>

                <div class="wpp-form-group">
                    <label class="wpp-form-label">Ticker da Ação de Interesse</label>
                    <input type="text" id="wpp-input-ticker" class="wpp-input" placeholder="Ex: MDIA3, PETR4, VALE3 ou TODAS" value="MDIA3">
                </div>

                <div class="wpp-form-group">
                    <label class="wpp-form-label">Seu Nome / Apelido (Opcional)</label>
                    <input type="text" id="wpp-input-nome" class="wpp-input" placeholder="Ex: Investidor">
                </div>

                <label class="wpp-checkbox-wrap">
                    <input type="checkbox" id="wpp-input-fr-only" checked>
                    <span>Receber prioritariamente Fatos Relevantes e Comunicados de impacto</span>
                </label>

                <div id="wpp-feedback" class="wpp-alert-box"></div>

                <div class="wpp-modal-actions">
                    <button class="btn-wpp-save" onclick="salvarInscricaoWpp()">
                        <i class="fas fa-check-circle"></i> ATIVAR ALERTA
                    </button>
                    <button class="btn-wpp-test" onclick="testarEnvioWpp()">
                        <i class="fas fa-paper-plane"></i> TESTAR NOTIFICAÇÃO
                    </button>
                </div>

                <div class="wpp-registered-list" id="wpp-list-container">
                    <div class="wpp-registered-title">Números Conectados para Alertas</div>
                    <div id="wpp-active-list">
                        <div style="font-size:12px; color:var(--c-grafite-light); opacity:0.6;">Carregando números...</div>
                    </div>
                </div>

                <div class="wpp-guide-box">
                    <div class="wpp-guide-title"><i class="fas fa-circle-info"></i> Como receber automaticamente 24h?</div>
                    <div>
                        O envio 100% autônomo (direto no seu celular sem precisar clicar) requer conectar um Gateway de envio no arquivo <code>agente_cvm/.env</code>:
                        <ul style="margin: 6px 0 0 16px; padding: 0;">
                            <li><strong>Z-API:</strong> Crie uma conta teste gratuita em <em>z-api.io</em>, escaneie o QR Code e preencha <code>ZAPI_TOKEN</code>.</li>
                            <li><strong>Evolution API:</strong> Conexão local gratuita via Docker.</li>
                            <li><strong>Telegram:</strong> Já está 100% configurado no projeto!</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let todosDocumentos = [];
        let catalogoEmpresas = [];
        let filtroAtivo = '';
        let mesAtivo = '';
        let timerSearch = null;

        async function carregarCatalogoEmpresas() {
            try {
                const res = await fetch('/api/empresas');
                catalogoEmpresas = await res.json();
                
                const datalist = document.getElementById('lista-empresas');
                const select = document.getElementById('select-empresa');
                
                datalist.innerHTML = '';
                select.innerHTML = '<option value="">-- Selecionar Empresa (680+ B3) --</option>';
                
                catalogoEmpresas.forEach(emp => {
                    const optList = document.createElement('option');
                    optList.value = emp.ticker;
                    optList.label = `${emp.nome} (CVM: ${emp.cvm_code || '-'})`;
                    datalist.appendChild(optList);

                    const optSel = document.createElement('option');
                    optSel.value = emp.ticker;
                    optSel.textContent = `${emp.ticker} — ${emp.nome}`;
                    select.appendChild(optSel);
                });
            } catch (err) {
                console.error('Erro ao carregar catálogo de empresas:', err);
            }
        }

        async function carregarMetricas() {
            try {
                const res = await fetch('/api/metricas');
                const m = await res.json();
                if (m.total_docs) document.getElementById('metric-total').innerText = Number(m.total_docs).toLocaleString('pt-BR');
                if (m.total_fr) document.getElementById('metric-fr').innerText = Number(m.total_fr).toLocaleString('pt-BR');
                if (m.total_empresas) document.getElementById('metric-cia').innerText = m.total_empresas;
            } catch (e) {}
        }

        async function carregarDocs() {
            const listEl = document.getElementById('docs-list');
            const termo = document.getElementById('input-search').value.trim();
            try {
                let url = '/api/documentos?';
                if (termo) url += `q=${encodeURIComponent(termo)}&`;
                if (mesAtivo) url += `mes=${encodeURIComponent(mesAtivo)}&`;
                
                const res = await fetch(url);
                todosDocumentos = await res.json();
                atualizarPerfilEmpresa(termo);
                renderizarDocs();
            } catch (err) {
                listEl.innerHTML = `<div class="empty-state" style="color: #ff6b6b;">Erro ao carregar documentos: ${err.message}</div>`;
            }
        }

        const NOMES_MESES = {
            '01': 'Jan', '02': 'Fev', '03': 'Mar', '04': 'Abr',
            '05': 'Mai', '06': 'Jun', '07': 'Jul', '08': 'Ago',
            '09': 'Set', '10': 'Out', '11': 'Nov', '12': 'Dez'
        };

        async function carregarBarraMeses() {
            try {
                const res = await fetch('/api/meses');
                const meses = await res.json();
                if (!meses || meses.length === 0) return;
                
                const barEl = document.getElementById('month-bar');
                if (!barEl) return;
                
                const ultimoMesNum = meses[0].split('-')[1];
                const nomeUltimoMes = NOMES_MESES[ultimoMesNum] || ultimoMesNum;
                
                let html = `<span class="month-label"><i class="far fa-calendar-check"></i> MESES 2026:</span>`;
                html += `<button class="month-pill ${!mesAtivo ? 'active' : ''}" onclick="selecionarMes('', this)">Ano Todo (Jan a ${nomeUltimoMes})</button>`;
                
                meses.forEach(m => {
                    const partes = m.split('-');
                    const anoCurto = partes[0].slice(-2);
                    const label = `${NOMES_MESES[partes[1]] || partes[1]}/${anoCurto}`;
                    html += `<button class="month-pill ${mesAtivo === m ? 'active' : ''}" onclick="selecionarMes('${m}', this)">${label}</button>`;
                });
                
                barEl.innerHTML = html;
            } catch(e) {}
        }

        function selecionarMes(mes, btn) {
            mesAtivo = mes;
            document.querySelectorAll('.month-selector-bar .month-pill').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            carregarDocs();
        }

        function atualizarPerfilEmpresa(termo) {
            const profEl = document.getElementById('company-profile');
            if (!termo) {
                profEl.style.display = 'none';
                return;
            }

            const clean = termo.trim().toUpperCase();
            const emp = catalogoEmpresas.find(e => 
                e.ticker === clean || 
                (e.cvm_limpo && e.cvm_limpo === clean.replace(/\\D/g, '')) ||
                (e.nome && e.nome.toUpperCase().includes(clean))
            );

            if (emp) {
                document.getElementById('p-ticker').innerText = emp.ticker;
                document.getElementById('p-name').innerText = emp.nome;
                document.getElementById('p-sector').innerText = emp.setor || 'Companhia Aberta B3';
                document.getElementById('p-cvm').innerText = emp.cvm_code || '-';
                document.getElementById('p-cnpj').innerText = emp.cnpj || '-';
                profEl.style.display = 'block';
            } else {
                profEl.style.display = 'none';
            }
        }

        function filtrarPill(cat, btn) {
            filtroAtivo = cat;
            document.querySelectorAll('.filter-pills-row .pill-btn').forEach(b => b.classList.remove('active'));
            if (btn) btn.classList.add('active');
            
            document.getElementById('input-search').value = cat;
            carregarDocs();
        }

        function selecionarDropdown(ticker) {
            if (!ticker) return;
            document.getElementById('input-search').value = ticker;
            filtroAtivo = ticker;
            document.querySelectorAll('.filter-pills-row .pill-btn').forEach(b => b.classList.remove('active'));
            carregarDocs();
        }

        function debounceSearch() {
            clearTimeout(timerSearch);
            timerSearch = setTimeout(() => {
                carregarDocs();
            }, 300);
        }

        /* ================= FORMATADOR DE RESUMO EXECUTIVO DIDÁTICO ================= */
        function formatarResumoExecutivo(textoBruto) {
            if (!textoBruto || textoBruto.includes('404 NOT_FOUND') || textoBruto.toLowerCase().includes('error')) {
                return '';
            }

            let text = textoBruto.trim();

            // Detectar Classificação de Impacto
            let impacto = 'NEUTRO';
            let impactoClass = 'impact-neutral';

            const lower = text.toLowerCase();
            if (lower.includes('classificado como **positivo') || lower.includes('classificação: **positivo') || lower.includes('impacto positivo')) {
                impacto = 'POSITIVO';
                impactoClass = 'impact-positive';
            } else if (lower.includes('classificado como **negativo') || lower.includes('atenção') || lower.includes('risco')) {
                impacto = 'ATENÇÃO / RISCO';
                impactoClass = 'impact-risk';
            } else if (lower.includes('classificado como **neutro') || lower.includes('classificação: **neutro')) {
                impacto = 'NEUTRO';
                impactoClass = 'impact-neutral';
            }

            // Limpar introduções redundantes de prompt antigo
            text = text.replace(/^Como Analista de RI[^:]*:\s*/i, '');
            text = text.replace(/^Prezado\(a\)[^:]*:\s*/i, '');

            // Agrupar seções por linhas com marcadores ### (evita quebra de negrito e asteriscos)
            const lines = text.split('\n');
            const sections = [];
            let currentHeader = '';
            let currentBodyLines = [];

            for (let rawLine of lines) {
                const trimmed = rawLine.trim();
                if (trimmed.startsWith('###')) {
                    if (currentHeader || currentBodyLines.length > 0) {
                        sections.push({
                            header: currentHeader,
                            body: currentBodyLines.join('\n').trim()
                        });
                        currentBodyLines = [];
                    }
                    currentHeader = trimmed.replace(/^###\s*/, '').replace(/[*#]/g, '').trim();
                } else {
                    currentBodyLines.push(rawLine);
                }
            }
            if (currentHeader || currentBodyLines.length > 0) {
                sections.push({
                    header: currentHeader,
                    body: currentBodyLines.join('\n').trim()
                });
            }

            let html = `
            <div class="ai-summary-compact">
                <div class="ai-summary-top-row">
                    <div class="ai-label-wrap">
                        <i class="fas fa-brain" style="color:var(--c-roxo-fume);"></i>
                        <span>PARECER EXECUTIVO RI &bull; GEMINI</span>
                    </div>
                    <div class="impact-pill ${impactoClass}">${impacto}</div>
                </div>
            `;

            for (let sec of sections) {
                const header = sec.header;
                const body = sec.body;
                if (!header && !body) continue;

                if (!header && body) {
                    html += `<div class="summary-content-intro">${formatarNegrito(body)}</div>`;
                    continue;
                }

                const isAnalysis = header.toLowerCase().includes('investidor') || 
                                   header.toLowerCase().includes('análise') || 
                                   header.toLowerCase().includes('impacto');

                if (isAnalysis) {
                    const bodyFmt = formatarNegrito(body);
                    html += `
                    <div class="summary-analysis-callout">
                        <div class="analysis-label-mini"><i class="fas fa-compass"></i> ${header.toUpperCase()}</div>
                        <div>${bodyFmt}</div>
                    </div>
                    `;
                } else {
                    html += `
                    <div class="summary-section-label" style="font-family:var(--font-mono); font-size:9.5px; letter-spacing:0.16em; color:var(--c-roxo-fume); margin:6px 0 4px; text-transform:uppercase;">
                        <i class="fas fa-angle-right"></i> ${header.toUpperCase()}
                    </div>
                    <div class="summary-bullets-box">
                    `;
                    const bLines = body.split('\n');
                    for (let bLine of bLines) {
                        bLine = bLine.trim();
                        if (!bLine) continue;

                        if (bLine.startsWith('*') || bLine.startsWith('-')) {
                            let bullet = bLine.replace(/^[\*\-]\s*/, '').trim();
                            bullet = formatarNegrito(bullet);
                            html += `
                            <div class="summary-bullet-row">
                                <span class="bullet-dot-mini"></span>
                                <div>${bullet}</div>
                            </div>
                            `;
                        } else {
                            html += `<div class="summary-content-intro">${formatarNegrito(bLine)}</div>`;
                        }
                    }
                    html += `</div>`;
                }
            }

            html += `</div>`;
            return html;
        }

        function formatarNegrito(str) {
            if (!str) return '';
            return str
                .replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>')
                .replace(/\*([^\*]+)\*/g, '<em>$1</em>')
                .replace(/\*\*/g, '');
        }

        async function gerarResumo(link, ticker, btnEl) {
            btnEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Gerando Parecer RI...';
            btnEl.disabled = true;
            try {
                const res = await fetch(`/api/resumir?link=${encodeURIComponent(link)}&ticker=${encodeURIComponent(ticker)}`);
                const data = await res.json();
                if (data.status === 'ok' && data.resumo) {
                    const card = btnEl.closest('.doc-item-compact');
                    const summaryHtml = formatarResumoExecutivo(data.resumo);
                    const temp = document.createElement('div');
                    temp.innerHTML = summaryHtml;
                    card.insertBefore(temp.firstElementChild, card.querySelector('.doc-item-footer'));
                    btnEl.remove();
                } else {
                    btnEl.innerText = 'Falha ao resumir. Tentar novamente';
                    btnEl.disabled = false;
                }
            } catch (err) {
                btnEl.innerText = 'Erro na geração de IA';
                btnEl.disabled = false;
            }
        }

        async function sincronizarBaseCVM() {
            const listEl = document.getElementById('docs-list');
            listEl.innerHTML = '<div class="empty-state"><i class="fas fa-spinner fa-spin" style="font-size: 32px; margin-bottom: 12px; display:block; color:var(--c-roxo-fume);"></i>Conectando aos Dados Abertos da CVM e indexando comunicados... Aguarde alguns instantes.</div>';
            try {
                await fetch('/api/sincronizar');
                setTimeout(() => { carregarDocs(); carregarMetricas(); }, 4000);
                setTimeout(() => { carregarDocs(); carregarMetricas(); }, 10000);
                setTimeout(() => { carregarDocs(); carregarMetricas(); }, 18000);
            } catch(e) {
                carregarDocs();
            }
        }

        function renderizarDocs() {
            const listEl = document.getElementById('docs-list');
            const countEl = document.getElementById('visible-count');
            let docs = [...todosDocumentos];

            countEl.innerText = `${docs.length} fatos/documentos`;

            if (docs.length === 0) {
                listEl.innerHTML = `
                    <div class="empty-state">
                        <i class="fas fa-folder-open" style="font-size: 32px; margin-bottom: 10px; display:block; opacity:0.4;"></i>
                        Nenhum documento encontrado na base para este critério ou período.
                        <div style="margin-top: 14px;">
                            <button onclick="sincronizarBaseCVM()" class="btn-gen-ai" style="padding: 7px 16px; font-size: 11px;">
                                <i class="fas fa-rotate"></i> Puxar Dados Oficiais da CVM Agora
                            </button>
                        </div>
                    </div>
                `;
                return;
            }

            let html = '';
            for (const d of docs) {
                const ticker = d.ticker || 'B3';
                const comp = d.company_name || 'Companhia Aberta';
                const cat = d.category || d.doc_type || 'Documento CVM';
                const data = d.delivery_date || d.ref_date || '-';
                const desc = d.description || 'Divulgação oficial registrada no sistema da CVM.';
                const isFR = cat.toLowerCase().includes('relevante') || (d.doc_type || '').toLowerCase().includes('relevante');

                const resumoHtml = d.resumo_ia ? formatarResumoExecutivo(d.resumo_ia) : '';
                const btnResumo = !resumoHtml && d.link ? `<button class="btn-gen-ai" onclick="gerarResumo('${d.link}', '${ticker}', this)"><i class="fas fa-wand-magic-sparkles"></i> Parecer IA</button>` : '';
                const link = d.link ? `<a href="${d.link}" target="_blank" class="cvm-link-mini">CVM Oficial <i class="fas fa-arrow-up-right-from-square"></i></a>` : '';

                html += `
                <div class="doc-item-compact">
                    <div>
                        <div class="doc-item-header">
                            <div class="doc-tags-left">
                                <span class="doc-ticker-pill">${ticker}</span>
                                <span class="doc-company-title">${comp}</span>
                                <span class="doc-category-badge ${isFR ? 'fr' : ''}">${cat}</span>
                            </div>
                            <div class="doc-date-stamp"><i class="far fa-calendar"></i> ${data}</div>
                        </div>
                        <div class="doc-subject-line">${desc}</div>
                        ${resumoHtml}
                    </div>
                    <div class="doc-item-footer">
                        ${btnResumo}
                        ${link}
                    </div>
                </div>
                `;
            }
            listEl.innerHTML = html;
        }

        // ================= FUNÇÕES WHATSAPP =================
        
        function abrirModalTelegram() {
            document.getElementById('modal-tg').style.display = 'flex';
        }
        function fecharModalTg() {
            document.getElementById('modal-tg').style.display = 'none';
        }
        function fecharModalTgOverlay(e) {
            if (e.target.id === 'modal-tg') fecharModalTg();
        }
        async function dispararTesteTelegram() {
            const ticker = document.getElementById('tg-input-ticker').value.trim().toUpperCase() || 'PETR4';
            const feedback = document.getElementById('tg-feedback');
            const btn = document.getElementById('btn-disparar-tg');

            feedback.className = 'wpp-alert-box info';
            feedback.style.display = 'block';
            feedback.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Gerando parecer do Gemini e transmitindo alerta para o Telegram...';
            btn.disabled = true;

            try {
                const res = await fetch('/api/telegram/testar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ticker: ticker })
                });
                const data = await res.json();
                btn.disabled = false;

                if (data.status === 'ok') {
                    feedback.className = 'wpp-alert-box success';
                    feedback.innerHTML = `
                        <div style="margin-bottom:6px;"><strong style="color:#38bdf8;"><i class="fas fa-circle-check"></i> Alerta Enviado com Sucesso!</strong></div>
                        <div style="font-size:12px; line-height:1.5; color:var(--c-papel); margin-bottom:10px;">
                            O comunicado oficial de <strong>${ticker}</strong> com parecer do Gemini foi entregue no canal <strong>CEARA_FINANCE_CANAL</strong>!
                        </div>
                        <a href="https://t.me/+T1V2m44be_Q3MjYx" target="_blank" class="btn-open-tg-now">
                            <i class="fab fa-telegram"></i> VER NO TELEGRAM AGORA
                        </a>
                    `;
                } else {
                    feedback.className = 'wpp-alert-box error';
                    feedback.innerText = 'Erro ao enviar: ' + (data.erro || 'Falha na API');
                }
            } catch(err) {
                btn.disabled = false;
                feedback.className = 'wpp-alert-box error';
                feedback.innerText = 'Falha na comunicação: ' + err.message;
            }
        }

        function abrirModalWpp() {
            document.getElementById('modal-wpp').style.display = 'flex';
            carregarInscritosWpp();
            const searchVal = document.getElementById('input-search').value.trim().toUpperCase();
            if (searchVal && searchVal.length <= 6 && !searchVal.includes(' ')) {
                document.getElementById('wpp-input-ticker').value = searchVal;
            }
        }

        function fecharModalWpp() {
            document.getElementById('modal-wpp').style.display = 'none';
            const feedback = document.getElementById('wpp-feedback');
            feedback.className = 'wpp-alert-box';
            feedback.style.display = 'none';
        }

        function fecharModalWppOverlay(e) {
            if (e.target.id === 'modal-wpp') {
                fecharModalWpp();
            }
        }

        async function carregarInscritosWpp() {
            const listEl = document.getElementById('wpp-active-list');
            try {
                const res = await fetch('/api/whatsapp/listar');
                const inscritos = await res.json();
                if (!inscritos || inscritos.length === 0) {
                    listEl.innerHTML = '<div style="font-size:12px; color:var(--c-grafite-light); opacity:0.6;">Nenhum número cadastrado ainda. Cadastre acima para receber.</div>';
                    return;
                }
                let html = '';
                for (let item of inscritos) {
                    html += `
                    <div class="wpp-item-row">
                        <div>
                            <span>+${item.telefone}</span>
                            <span class="wpp-item-tag">[ ${item.ticker} ]</span>
                            ${item.nome ? `<span style="color:var(--c-grafite-light); font-size:11px; margin-left:6px;">(${item.nome})</span>` : ''}
                        </div>
                        <button class="btn-wpp-del" onclick="removerInscricaoWpp(${item.id})" title="Desativar Alerta">
                            <i class="fas fa-trash-can"></i>
                        </button>
                    </div>
                    `;
                }
                listEl.innerHTML = html;
            } catch (err) {
                listEl.innerHTML = '<div style="font-size:12px; color:#f87171;">Erro ao carregar lista.</div>';
            }
        }

        async function salvarInscricaoWpp() {
            const phone = document.getElementById('wpp-input-phone').value.trim();
            const ticker = document.getElementById('wpp-input-ticker').value.trim().toUpperCase() || 'TODAS';
            const nome = document.getElementById('wpp-input-nome').value.trim();
            const apenasFr = document.getElementById('wpp-input-fr-only').checked;
            const feedback = document.getElementById('wpp-feedback');

            if (!phone) {
                feedback.className = 'wpp-alert-box error';
                feedback.innerText = 'Por favor, informe seu número de WhatsApp com DDD.';
                return;
            }

            feedback.className = 'wpp-alert-box';
            feedback.style.display = 'block';
            feedback.innerText = 'Conectando número ao sistema...';

            try {
                const res = await fetch('/api/whatsapp/cadastrar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ telefone: phone, ticker: ticker, nome: nome, apenas_fr: apenasFr })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    feedback.className = 'wpp-alert-box success';
                    feedback.innerHTML = `<strong>Sucesso!</strong> WhatsApp vinculado para receber alertas de <strong>${ticker}</strong>.`;
                    carregarInscritosWpp();
                } else {
                    feedback.className = 'wpp-alert-box error';
                    feedback.innerText = data.error || 'Erro ao cadastrar número.';
                }
            } catch (err) {
                feedback.className = 'wpp-alert-box error';
                feedback.innerText = 'Falha de comunicação com o servidor.';
            }
        }

        async function testarEnvioWpp() {
            const phone = document.getElementById('wpp-input-phone').value.trim();
            const ticker = document.getElementById('wpp-input-ticker').value.trim().toUpperCase() || 'MDIA3';
            const feedback = document.getElementById('wpp-feedback');

            if (!phone) {
                feedback.className = 'wpp-alert-box error';
                feedback.innerText = 'Informe um número para enviar o teste.';
                return;
            }

            feedback.className = 'wpp-alert-box';
            feedback.style.display = 'block';
            feedback.innerText = 'Disparando notificação de teste CVM...';

            try {
                const res = await fetch('/api/whatsapp/testar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ telefone: phone, ticker: ticker })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    const resInfo = data.resultado || {};
                    const isMock = resInfo.status === 'simulado' || resInfo.provedor === 'mock_cf_tech';
                    const cleanPhone = phone.replace(/\D/g, '');
                    const wppUrl = resInfo.whatsapp_url || `https://api.whatsapp.com/send?phone=55${cleanPhone}&text=${encodeURIComponent(resInfo.texto_formatado || '')}`;

                    if (isMock) {
                        feedback.className = 'wpp-alert-box info';
                        feedback.innerHTML = `
                            <div style="margin-bottom: 6px;">
                                <strong style="color:#4ade80;"><i class="fas fa-circle-check"></i> Mensagem Formatada com Sucesso!</strong>
                            </div>
                            <div style="font-size:12px; color:var(--c-papel); line-height:1.5; margin-bottom:10px;">
                                O parecer executivo do Gemini para <strong>${ticker}</strong> foi gerado. Como seu computador ainda não possui uma chave de envio autônomo (Z-API/Evolution) no <code>.env</code>, você pode abrir o WhatsApp agora mesmo para ver e receber a notificação pronta:
                            </div>
                            <div>
                                <a href="${wppUrl}" target="_blank" class="btn-open-wpp-now">
                                    <i class="fab fa-whatsapp"></i> ABRIR E ENVIAR NO MEU WHATSAPP AGORA
                                </a>
                            </div>
                        `;
                    } else {
                        feedback.className = 'wpp-alert-box success';
                        feedback.innerHTML = `<strong>Enviado com sucesso!</strong> Transmitido via ${resInfo.provedor} para +${resInfo.telefone} (${ticker}).`;
                    }
                } else {
                    feedback.className = 'wpp-alert-box error';
                    feedback.innerText = data.error || 'Erro no envio do teste.';
                }
            } catch (err) {
                feedback.className = 'wpp-alert-box error';
                feedback.innerText = 'Falha ao testar envio.';
            }
        }

        async function removerInscricaoWpp(id) {
            try {
                await fetch('/api/whatsapp/remover', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: id })
                });
                carregarInscritosWpp();
            } catch (err) {
                alert('Erro ao remover inscrição.');
            }
        }

        window.addEventListener('DOMContentLoaded', () => {
            carregarCatalogoEmpresas();
            carregarMetricas();
            carregarBarraMeses();
            carregarDocs();
        });
    </script>
</body>
</html>
"""
        return html

def iniciar_servidor(port=PORT):
    storage.init_db()
    
    def auto_sync_se_necessario():
        import time
        time.sleep(2)
        try:
            conn = storage.get_connection()
            c = conn.cursor()
            total = c.execute("SELECT count(*) FROM cvm_base_oficial").fetchone()[0]
            conn.close()
            if total == 0:
                print("[CVM Server] Base oficial CVM vazia. Iniciando download dos dados abertos CVM em segundo plano...")
                import sincronizar_cvm
                sincronizar_cvm.sincronizar_base_cvm()
            else:
                print(f"[CVM Server] Base CVM carregada com {total} documentos.")
        except Exception as e:
            print(f"[CVM Server] Verificacao da base: {e}")
            
    import threading
    threading.Thread(target=auto_sync_se_necessario, daemon=True, name="CVMAutoSync").start()

    # Thread 24/7: Bot Interativo do Telegram (@CEARA_FINANCE_BOT)
    def telegram_chat_loop():
        import time
        import chat
        print("[Telegram Bot] Thread do Chat Interativo iniciada 24/7 (@CEARA_FINANCE_BOT).")
        time.sleep(3)
        while True:
            try:
                chat.responder_updates()
            except Exception as e:
                print(f"[Telegram Bot] Erro na leitura de updates: {e}")
            time.sleep(2)

    threading.Thread(target=telegram_chat_loop, daemon=True, name="TelegramChatWorker").start()

    # Thread 24/7: Monitoramento Contínuo da CVM e Alertas com IA
    def cvm_monitor_loop():
        import time
        import monitor
        print("[Monitor CVM] Thread de Monitoramento Contínuo CVM iniciada 24/7.")
        time.sleep(15)
        while True:
            try:
                monitor.executar_monitoramento()
            except Exception as e:
                print(f"[Monitor CVM] Erro no ciclo de monitoramento: {e}")
            time.sleep(config.MONITOR_INTERVAL)

    threading.Thread(target=cvm_monitor_loop, daemon=True, name="CVMMonitorWorker").start()

    # Thread 24/7: Self-Ping Keep-Alive (Evita o sleep de 15 min do Render)
    def keep_alive_loop():
        import time
        import urllib.request
        time.sleep(60)
        url = "https://fatos-relevantes-cvm.onrender.com/health"
        print("[Keep-Alive] Thread de auto-ping iniciada 24/7.")
        while True:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "CFTech-KeepAlive-Worker/1.0"}
                )
                with urllib.request.urlopen(req, timeout=15) as res:
                    print(f"[Keep-Alive] Ping executado: HTTP {res.getcode()}")
            except Exception as e:
                print(f"[Keep-Alive] Tentativa de ping: {e}")
            # Ping a cada 9 minutos (540s), garantindo que nunca atinja os 15 min de inatividade do Render
            time.sleep(540)

    threading.Thread(target=keep_alive_loop, daemon=True, name="KeepAliveWorker").start()

    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, CVMHandler)
    print(f"[CVM Server] Alertas CVM ativos em http://localhost:{port}")
    httpd.serve_forever()

if __name__ == "__main__":
    iniciar_servidor()
