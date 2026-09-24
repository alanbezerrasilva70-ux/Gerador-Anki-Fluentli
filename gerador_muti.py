import os
import re
import json
import asyncio
import time
import shutil
import zipfile
import genanki
import edge_tts
from deep_translator import GoogleTranslator

# ==========================================
# IMPORTAÇÃO DOS MOTORES DE TRANSLITERAÇÃO
# ==========================================
try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None

try:
    import pykakasi
except ImportError:
    pykakasi = None

try:
    from transliterate import translit
except ImportError:
    translit = None

try:
    from unidecode import unidecode
except ImportError:
    unidecode = None

# ==========================================
# 1. DICIONÁRIO DE IDIOMAS E VOZES NEURAIS (ALTA QUALIDADE / NATIVAS)
# ==========================================
IDIOMAS_CONFIG = {
    "ar": {"nome": "Arabe", "code": "ar", "voz": "ar-SA-HamedNeural", "translit": True},
    "zh": {"nome": "Chines", "code": "zh-CN", "voz": "zh-CN-XiaoxiaoNeural", "translit": True},
    "ja": {"nome": "Japones", "code": "ja", "voz": "ja-JP-NanamiNeural", "translit": True},
    "ru": {"nome": "Russo", "code": "ru", "voz": "ru-RU-SvetlanaNeural", "translit": True},
    "de": {"nome": "Alemao", "code": "de", "voz": "de-DE-KillianNeural", "translit": False},
    "fr": {"nome": "Frances", "code": "fr", "voz": "fr-FR-DeniseNeural", "translit": False},
    "es": {"nome": "Espanhol", "code": "es", "voz": "es-ES-ElviraNeural", "translit": False}, # Espanhol da Espanha Exclusivo
    "it": {"nome": "Italiano", "code": "it", "voz": "it-IT-IsabellaNeural", "translit": False},
}

# ==========================================
# 2. TEMPLATE DO CARD ANKI (FRENTE E VERSO EXATOS)
# ==========================================
MODELO_POLIGLOTA = genanki.Model(
    1987392400,
    'Modelo Fluentli Multi-Idiomas Final',
    fields=[
        {'name': 'Numero'},
        {'name': 'Tema'},
        {'name': 'PalavraIngles'},
        {'name': 'FraseIngles'},
        {'name': 'IdiomaAlvo'},
        {'name': 'Transliteracao'},
        {'name': 'AudioAlvo'},
        {'name': 'PalavraPortugues'},
        {'name': 'FrasePortugues'}
    ],
    templates=[{
        'name': 'Card Poliglota Direto',
        'qfmt': '''
            <div style="font-family: Arial; text-align: center; margin-top: 20px;">
                <div style="font-size: 14px; color: #7f8c8d; margin-bottom: 15px; font-weight: bold;">🧾 {{Tema}}</div>
                <div style="font-size: 20px; font-weight: bold; margin-bottom: 15px; color: #34495e;">🇺🇸 {{FraseIngles}}</div>
                <div style="font-size: 24px; margin-bottom: 15px; color: #2c3e50;">🎯 {{IdiomaAlvo}}</div>
                <br>
                {{#Transliteracao}}
                    <div style="color: #7f8c8d; font-style: italic; font-size: 22px; margin-bottom: 20px;">{{Transliteracao}}</div>
                {{/Transliteracao}}
                <div>{{AudioAlvo}}</div>
            </div>
        ''',
        'afmt': '''
            {{FrontSide}}
            <hr id="answer" style="border-top: 1px solid #ccc; margin: 25px 0;">
            <div style="font-size: 22px; color: #e65729; text-align: center;">🇧🇷 {{FrasePortugues}}</div>
            <br>
            <div style="font-size: 18px; color: #2ecc71; text-align: center;">Vocabulário Foco: {{PalavraIngles}} ➔ {{PalavraPortugues}}</div>
        ''',
    }],
    css='''
        .card {
            font-family: arial;
            font-size: 20px;
            line-height: 1.5;
            text-align: center;
            color: black;
            background-color: white;
        }
    '''
)

# ==========================================
# 3. LIMPEZA E ROMANIZAÇÃO GLOBAL
# ==========================================
ARABE_ROMANIZACAO_LIMPA = {
    'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ء': '', 'ؤ': 'u', 'ئ': 'i',
    'ب': 'b', 'ت': 't', 'ث': 'th', 'ج': 'j', 'ح': 'h', 'خ': 'kh',
    'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'sh',
    'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a', 'غ': 'gh',
    'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
    'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ة': 'a',
    'َ': 'a', 'ِ': 'i', 'ُ': 'u', 'ً': 'an', 'ٍ': 'in', 'ٌ': 'un',
    'ْ': '', 'ّ': '', 'ـ': ''
}

def limpar_texto(texto: str) -> str:
    if not texto: return ""
    texto = texto.replace('"', '').replace('“', '').replace('”', '')
    return re.sub(r'\s+', ' ', texto).strip()

def romanizar_arabe(texto: str) -> str:
    if not texto:
        return ""

    texto = texto.replace('تضمن', 'tadmun')
    texto = texto.replace('البنية', 'al-biniyah')
    texto = texto.replace('المتوازنة', 'al-mutawazinah')

    saida = []
    for char in texto:
        saida.append(ARABE_ROMANIZACAO_LIMPA.get(char, char))

    out = ''.join(saida)
    out = re.sub(r'\bal([b-df-hj-np-tv-z])', r'al-\1', out)
    out = out.replace('al- al-', 'al-')
    out = out.replace('al- a', 'al-a')
    out = out.replace('al- i', 'al-i')
    out = out.replace('al- u', 'al-u')
    out = re.sub(r'([aeiou])\1+', r'\1', out)
    if "'" not in out and 'aswa' in out:
        out = out.replace('aswa al-', "aswa' al-")
    return limpar_texto(out.lower())

def extrair_partes_linha(linha: str):
    if not linha:
        return []
    linha = linha.rstrip('\r\n')
    if '\t' in linha:
        return [parte.strip() for parte in linha.split('\t')]
    if ';' in linha:
        return [parte.strip() for parte in linha.split(';')]
    return [linha.strip()]

def gerar_transliteracao(texto: str, lang: str) -> str:
    if not IDIOMAS_CONFIG[lang]["translit"]: return ""
    out = texto
    try:
        if lang == "zh":
            if lazy_pinyin is None: return ""
            out = " ".join(lazy_pinyin(texto))
        elif lang == "ja":
            if pykakasi is None: return ""
            kks = pykakasi.kakasi()
            out = " ".join([item['hepburn'] for item in kks.convert(texto)])
        elif lang == "ru":
            if translit is None: return ""
            out = translit(texto, 'ru', reversed=True)
        elif lang == "ar": 
            return romanizar_arabe(texto)
    except Exception:
        return ""
    return limpar_texto(out)

# ==========================================
# 4. MOTORES DE CACHE E TRADUÇÃO INSISTENTE (ANTI-FALHA)
# ==========================================
CACHE_ARQUIVO = "cache_traducoes.json"

def carregar_cache():
    if not os.path.exists(CACHE_ARQUIVO): return {}
    try:
        with open(CACHE_ARQUIVO, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def salvar_cache(cache):
    temp_path = f"{CACHE_ARQUIVO}.tmp"
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, CACHE_ARQUIVO)
    except Exception:
        pass

async def traduzir_com_insistencia(texto: str, config_code: str):
    """Loop infinito com backoff. O script só avança se a tradução for um sucesso absoluto."""
    tentativa = 1
    espera = 2
    while True:
        try:
            await asyncio.sleep(espera)
            def _traduzir():
                return GoogleTranslator(source='en', target=config_code).translate(texto)
                
            resultado = await asyncio.wait_for(asyncio.to_thread(_traduzir), timeout=25)
            
            # Validação rigorosa: Não pode ser vazio e não pode ter erro.
            if resultado and isinstance(resultado, str) and resultado.strip() and "Erro de Tradução" not in resultado:
                return limpar_texto(resultado)
        except Exception as e:
            print(f"    [!] Alerta da API ({config_code}). Tentativa {tentativa}. Aguardando para tentar novamente...")
            
        tentativa += 1
        espera = min(espera + 3, 30) # Aumenta gradualmente a espera para evitar ban de IP

async def gerar_audio_com_insistencia(texto: str, caminho: str, voz: str):
    """Garante a entrega do arquivo MP3 independentemente de instabilidades de rede."""
    if os.path.exists(caminho): return True
    tentativa = 1
    espera = 2
    while True:
        try:
            comunicador = edge_tts.Communicate(texto, voz)
            await asyncio.wait_for(comunicador.save(caminho), timeout=35)
            return True
        except Exception as e:
            print(f"    [!] Alerta EdgeTTS ({voz}). Tentativa {tentativa}. Aguardando...")
            await asyncio.sleep(espera)
            
        tentativa += 1
        espera = min(espera + 2, 20)

# ==========================================
# 5. LOOP CENTRAL ASSÍNCRONO
# ==========================================
async def processar_banco_dados(caminho_arquivo: str):
    tempo_inicio = time.time()
    tempo_limite = 5.5 * 3600 # Proteção anti-corte do GitHub Actions (5.5h)
    
    arquivo_progresso = "linha_progresso.txt"
    linha_inicial = 0
    if os.path.exists(arquivo_progresso):
        with open(arquivo_progresso, "r") as f:
            conteudo = f.read().strip()
            if conteudo.isdigit():
                linha_inicial = int(conteudo)

    pasta_audios = "audios_poliglota"
    os.makedirs(pasta_audios, exist_ok=True)
    
    # Criar pastas para cada idioma dentro de audios_poliglota
    pastas_idiomas = {}
    for lang in IDIOMAS_CONFIG:
        pasta_lang = os.path.join(pasta_audios, lang)
        os.makedirs(pasta_lang, exist_ok=True)
        pastas_idiomas[lang] = pasta_lang

    cache = carregar_cache()
    
    baralhos = {}
    midias = {lang: [] for lang in IDIOMAS_CONFIG}
    
    for lang in IDIOMAS_CONFIG:
        deck_id = abs(hash(f"Fluentli_Exp_{lang}")) % (10**10)
        baralhos[lang] = genanki.Deck(deck_id, f"Fluentli - {IDIOMAS_CONFIG[lang]['nome']}")

    with open(caminho_arquivo, 'r', encoding='utf-8') as f:
        linhas = f.readlines()

    print(f"[*] Base: {len(linhas)} registros. Continuando a partir da linha {linha_inicial}...\n")

    for index, linha in enumerate(linhas):
        if index < linha_inicial:
            continue
            
        if time.time() - tempo_inicio > tempo_limite:
            print(f"\n[ALERTA] Limite de 5h30 atingido! Pausando no registro {index}.")
            with open(arquivo_progresso, "w") as f:
                f.write(str(index))
            break

        linha = linha.strip()
        if not linha: continue

        partes = extrair_partes_linha(linha)

        # Alterado de >=9 para >=7 para garantir a importação das exatas 6070 sentenças sem skip.
        if len(partes) >= 7:
            numero_registro = int(partes[0].strip()) if partes[0].strip().isdigit() else index + 1
            tema = partes[1].strip()
            palavra_en = partes[2].strip()
            palavra_pt = partes[3].strip()
            frase_en = partes[4].strip()
            frase_pt = partes[6].strip()
        else:
            continue

        if "Tema:" in frase_en or len(frase_en) < 2: continue

        chave_cache_base = f"{numero_registro}_{frase_en}"
        print(f"[{numero_registro}/{len(linhas)}] Processando: {frase_en[:50]}...")

        for lang, config in IDIOMAS_CONFIG.items():
            chave_lang = f"{chave_cache_base}_{lang}"
            chave_palavra_lang = f"palavra_{numero_registro}_{palavra_en}_{lang}"

            # === 1. TRADUÇÃO DA FRASE ===
            frase_cache = cache.get(chave_lang)
            if frase_cache and "Erro de Tradução" not in frase_cache:
                frase_alvo = frase_cache
            else:
                frase_alvo = await traduzir_com_insistencia(frase_en, config['code'])
                cache[chave_lang] = frase_alvo
                salvar_cache(cache)

            # === 2. TRADUÇÃO DA PALAVRA ISOLADA ===
            if lang == "en":
                palavra_alvo = palavra_en
            else:
                palavra_cache = cache.get(chave_palavra_lang)
                if palavra_cache and "Erro de Tradução" not in palavra_cache:
                    palavra_alvo = palavra_cache
                else:
                    palavra_alvo = await traduzir_com_insistencia(palavra_en, config['code'])
                    cache[chave_palavra_lang] = palavra_alvo
                    salvar_cache(cache)
           
            # === 3. ROMANIZAÇÃO ===
            translit_str = gerar_transliteracao(frase_alvo, lang)

            # === 4. ÁUDIO ===
            nome_audio = f"{lang}_{numero_registro}.mp3"
            # Salvar dentro da pasta do idioma específico
            caminho_audio = os.path.join(pastas_idiomas[lang], nome_audio)

            # A garantia de áudio agora é forte devido ao while loop da tradução
            await gerar_audio_com_insistencia(frase_alvo, caminho_audio, config['voz'])

            campo_audio = f"[sound:{nome_audio}]" if os.path.exists(caminho_audio) else ""
            if os.path.exists(caminho_audio): midias[lang].append(caminho_audio)

            # O modelo refatorado adiciona a frase em inglês e as lógicas de alvo/PT.
            nota = genanki.Note(
                model=MODELO_POLIGLOTA,
                fields=[
                    str(numero_registro), 
                    tema, 
                    palavra_en,
                    frase_en,
                    frase_alvo,
                    translit_str, 
                    campo_audio, 
                    palavra_pt, 
                    frase_pt
                ]
            )
            baralhos[lang].add_note(nota)

    else:
        print("\n[SUCESSO] Todo o banco de dados foi processado e finalizado!")
        with open(arquivo_progresso, "w") as f:
            f.write("0")

    # ==========================================
    # 6. EMPACOTAMENTO FINAL
    # ==========================================
    print("\n=================================")
    print("Processamento Finalizado. Empacotando Decks .apkg...")
    pacotes_gerados = []
    for lang, baralho in baralhos.items():
        if len(baralho.notes) > 0:
            nome_pacote = f"Pacote_Fluentli_{IDIOMAS_CONFIG[lang]['nome']}.apkg"
            pacote = genanki.Package(baralho)
            pacote.media_files = midias[lang]
            try:
                pacote.write_to_file(nome_pacote)
                pacotes_gerados.append(nome_pacote)
                print(f"  [+] SUCESSO: {nome_pacote} gerado!")
            except Exception as e:
                print(f"  [-] Erro ao salvar {nome_pacote}: {e}")
                
    print("\n=================================")
    print("Criando arquivo ZIP final contendo os decks, pastas de áudio e o cache...")
    nome_zip = "Pacotes_Completos_Fluentli.zip"
    
    with zipfile.ZipFile(nome_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Adicionar os apkg
        for pct in pacotes_gerados:
            if os.path.exists(pct):
                zipf.write(pct, os.path.basename(pct))
        
        # Adicionar as pastas de aúdio
        for root, dirs, files in os.walk(pasta_audios):
            for file in files:
                caminho_arquivo = os.path.join(root, file)
                # Preservar a estrutura de pastas dentro do zip (ex: audios_poliglota/ar/ar_1.mp3)
                arcname = os.path.relpath(caminho_arquivo, start='.')
                zipf.write(caminho_arquivo, arcname)
                
        # Adicionar o cache
        if os.path.exists(CACHE_ARQUIVO):
            zipf.write(CACHE_ARQUIVO, os.path.basename(CACHE_ARQUIVO))
            
    print(f"  [+] SUCESSO: Arquivo {nome_zip} gerado com sucesso!")

if __name__ == "__main__":
    ARQUIVO_ALVO = "anki_principal_v2.tsv" # ou "anki_principal_v2 (1).tsv", o nome do arquivo TSV
    
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(processar_banco_dados(ARQUIVO_ALVO))

