import os
import re
import json
import asyncio
import time
import shutil
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
# 1. DICIONÁRIO DE IDIOMAS E VOZES NEURAIS
# ==========================================
IDIOMAS_CONFIG = {
    "ar": {"nome": "Arabe", "code": "ar", "voz": "ar-SA-HamedNeural", "translit": True},
    "zh": {"nome": "Chines", "code": "zh-CN", "voz": "zh-CN-YunxiNeural", "translit": True},
    "ja": {"nome": "Japones", "code": "ja", "voz": "ja-JP-KeitaNeural", "translit": True},
    "ru": {"nome": "Russo", "code": "ru", "voz": "ru-RU-DmitryNeural", "translit": True},
    "de": {"nome": "Alemao", "code": "de", "voz": "de-DE-ConradNeural", "translit": False},
    "fr": {"nome": "Frances", "code": "fr", "voz": "fr-FR-HenriNeural", "translit": False},
    "es": {"nome": "Espanhol", "code": "es", "voz": "es-ES-AlvaroNeural", "translit": False},
    "it": {"nome": "Italiano", "code": "it", "voz": "it-IT-DiegoNeural", "translit": False},
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
        {'name': 'Palavra'},
        {'name': 'IdiomaAlvo'},
        {'name': 'Transliteracao'},
        {'name': 'AudioAlvo'},
        {'name': 'Portugues'},
        {'name': 'FrasePortugues'}
    ],
    templates=[{
        'name': 'Card Poliglota Direto',
        'qfmt': '''
            <div style="font-family: Arial; text-align: center; margin-top: 20px;">
                <div style="font-size: 14px; color: #7f8c8d; margin-bottom: 15px; font-weight: bold;">🧾 {{Tema}}</div>
                <div style="font-size: 24px; margin-bottom: 15px;">{{Palavra}}</div>
                <div style="font-size: 24px;">{{IdiomaAlvo}}</div>
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
            <div style="font-size: 22px; color: #e65729; text-align: center;">{{Portugues}}</div>
            <br>
            <div style="font-size: 22px; color: #2ecc71; text-align: center;">{{FrasePortugues}}</div>
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
            if lazy_pinyin is None:
                return ""
            out = " ".join(lazy_pinyin(texto))
        elif lang == "ja":
            if pykakasi is None:
                return ""
            kks = pykakasi.kakasi()
            out = " ".join([item['hepburn'] for item in kks.convert(texto)])
        elif lang == "ru":
            if translit is None:
                return ""
            out = translit(texto, 'ru', reversed=True)
        elif lang == "ar": return romanizar_arabe(texto)
    except Exception:
        return ""
    return limpar_texto(out)

# ==========================================
# 4. MOTORES COM CACHE E TIMEOUT (ANTIFREEZE)
# ==========================================
CACHE_ARQUIVO = "cache_traducoes.json"
CACHE_BACKUP = f"{CACHE_ARQUIVO}.bak"


def carregar_cache():
    if not os.path.exists(CACHE_ARQUIVO):
        return {}

    try:
        with open(CACHE_ARQUIVO, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        if isinstance(cache, dict):
            return cache
        return {}
    except (json.JSONDecodeError, OSError, ValueError):
        print(f"[!] Cache corrompido em {CACHE_ARQUIVO}. Reiniciando cache em memória.")
        try:
            if os.path.exists(CACHE_ARQUIVO):
                shutil.copy2(CACHE_ARQUIVO, CACHE_BACKUP)
        except OSError:
            pass
        return {}


def salvar_cache(cache):
    temp_path = f"{CACHE_ARQUIVO}.tmp"

    for tentativa in range(1, 7):
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_path, CACHE_ARQUIVO)
            return
        except PermissionError:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            if tentativa == 6:
                raise
            time.sleep(0.5 * tentativa)
        except OSError:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            if tentativa == 6:
                raise
            time.sleep(0.5 * tentativa)

    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def obter_cache_compativel(cache, numero_registro, index, frase_en, lang):
    chave_nova = f"{numero_registro}_{frase_en}_{lang}"
    chave_legacy = f"{index}_{frase_en}_{lang}"

    if chave_nova in cache:
        return cache[chave_nova]

    if chave_legacy in cache:
        valor = cache[chave_legacy]
        cache[chave_nova] = valor
        if chave_nova != chave_legacy:
            del cache[chave_legacy]
        salvar_cache(cache)
        return valor

    return None

async def traduzir_com_timeout(texto: str, config_code: str, timeout=15):
    def _traduzir():
        return GoogleTranslator(source='en', target=config_code).translate(texto)
    try:
        await asyncio.sleep(0.5) # Proteção anti-bloqueio de IP do Google
        return await asyncio.wait_for(asyncio.to_thread(_traduzir), timeout=timeout)
    except Exception:
        return None
    
async def gerar_audio_com_timeout(texto: str, caminho: str, voz: str, timeout=20):
    if os.path.exists(caminho): return True
    for _ in range(3):
        try:
            comunicador = edge_tts.Communicate(texto, voz)
            await asyncio.wait_for(comunicador.save(caminho), timeout=timeout)
            return True
        except Exception:
            await asyncio.sleep(2)
    return False

# ==========================================
# 5. LOOP CENTRAL ASSÍNCRONO
# ==========================================
async def processar_banco_dados(caminho_arquivo: str):
    # --- SISTEMA ANTI-CORTE DA NUVEM ---
    tempo_inicio = time.time()
    tempo_limite = 5.5 * 3600 # Limite seguro de 5 horas e meia
    
    arquivo_progresso = "linha_progresso.txt"
    linha_inicial = 0
    if os.path.exists(arquivo_progresso):
        with open(arquivo_progresso, "r") as f:
            conteudo = f.read().strip()
            if conteudo.isdigit():
                linha_inicial = int(conteudo)
    # -----------------------------------

    pasta_audios = "audios_poliglota"
    os.makedirs(pasta_audios, exist_ok=True)
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
        # Pula as linhas que já foram empacotadas no lote anterior
        if index < linha_inicial:
            continue
            
        # Verifica o cronômetro para não ser morto pelo GitHub
        if time.time() - tempo_inicio > tempo_limite:
            print(f"\n[ALERTA] Limite de 5h30 atingido! Pausando no registro {index}.")
            with open(arquivo_progresso, "w") as f:
                f.write(str(index))
            break

        linha = linha.strip()
        if not linha: continue
        linha = linha.strip()
        if not linha: continue

        partes = extrair_partes_linha(linha)

        # Preserva o número, o tema e a palavra do TSV para montar o cartão completo.
        if len(partes) >= 9:
            numero_registro = int(partes[0].strip()) if partes[0].strip().isdigit() else index + 1
            tema = partes[1].strip()
            palavra_en = partes[2].strip()
            traducao_palavra_pt = partes[3].strip()
            frase_en = partes[4].strip()
            frase_pt = partes[6].strip()
        else:
            continue

        if "Tema:" in frase_en or len(frase_en) < 2: continue

        chave_cache_base = f"{numero_registro}_{frase_en}"
        print(f"[{numero_registro}/{len(linhas)}] Processando: {frase_en[:50]}...")

        for lang, config in IDIOMAS_CONFIG.items():
            chave_lang = f"{chave_cache_base}_{lang}"
            chave_legacy = f"{index}_{frase_en}_{lang}"
            chave_palavra_lang = f"palavra_{numero_registro}_{palavra_en}_{lang}"
# === 1. AUDITORIA E TRADUÇÃO DA FRASE ===
            frase_cache = cache.get(chave_lang) or cache.get(chave_legacy)
            resultado_frase = await traduzir_com_timeout(frase_en, config['code'])
            
            if resultado_frase and "Erro de Tradução" not in resultado_frase:
                frase_alvo = limpar_texto(resultado_frase)
                
                # Se a versão do Google atual for diferente do Cache, atualiza e avisa no terminal
                if frase_cache and frase_cache != frase_alvo and frase_cache != "Erro de Tradução":
                    print(f"\n[AUDITORIA FRASE | Linha {numero_registro} | Idioma: {lang.upper()}]")
                    print(f"  [-] Errado no Cache: {frase_cache}")
                    print(f"  [+] Corrigido (Google): {frase_alvo}")
                
                cache[chave_lang] = frase_alvo
                salvar_cache(cache)
            else:
                frase_alvo = frase_cache if (frase_cache and frase_cache != "Erro de Tradução") else "Erro de Tradução"

            # === 2. AUDITORIA E TRADUÇÃO DA PALAVRA ISOLADA ===
            if lang == "en":
                palavra_alvo = palavra_en
            else:
                palavra_cache = cache.get(chave_palavra_lang)
                resultado_palavra = await traduzir_com_timeout(palavra_en, config['code'])
                
                if resultado_palavra and "Erro de Tradução" not in resultado_palavra:
                    palavra_alvo = limpar_texto(resultado_palavra)
                    
                    # Compara a palavra solta do Google com o Cache
                    if palavra_cache and palavra_cache != palavra_alvo and palavra_cache != "Erro de Tradução":
                        print(f"\n[AUDITORIA PALAVRA | Linha {numero_registro} | Idioma: {lang.upper()}]")
                        print(f"  [-] Errado no Cache: {palavra_cache}")
                        print(f"  [+] Corrigido (Google): {palavra_alvo}")
                    
                    cache[chave_palavra_lang] = palavra_alvo
                    salvar_cache(cache)
                else:
                    palavra_alvo = palavra_cache if (palavra_cache and palavra_cache != "Erro de Tradução") else "Erro de Tradução"
           
            # ROMANIZAÇÃO
            translit_str = gerar_transliteracao(frase_alvo, lang)

            # ÁUDIO
            nome_audio = f"{lang}_{numero_registro}.mp3"
            caminho_audio = os.path.join(pasta_audios, nome_audio)

            if frase_alvo != "Erro de Tradução":
                await gerar_audio_com_timeout(frase_alvo, caminho_audio, config['voz'])

            campo_audio = f"[sound:{nome_audio}]" if os.path.exists(caminho_audio) else ""
            if os.path.exists(caminho_audio): midias[lang].append(caminho_audio)

            # O áudio em português e o IPA inglês não fazem parte deste modelo.
            nota = genanki.Note(
                model=MODELO_POLIGLOTA,
                fields=[
                    str(numero_registro), tema, palavra_alvo, frase_alvo,
                    translit_str, campo_audio, traducao_palavra_pt, frase_pt
                ]
            )
            baralhos[lang].add_note(nota)
else:
        # Se o loop processar todas as 6070 linhas sem estourar o tempo
        print("\n[SUCESSO] Todo o banco de dados foi processado e finalizado!")
        with open(arquivo_progresso, "w") as f:
            f.write("0")

    # ==========================================
    # 6. EMPACOTAMENTO FINAL
    # ==========================================
    print("\n=================================")
    print("Processamento Finalizado. Empacotando Decks .apkg...")
    for lang, baralho in baralhos.items():
        if len(baralho.notes) > 0:
            nome_pacote = f"Pacote_{IDIOMAS_CONFIG[lang]['nome']}.apkg"
            pacote = genanki.Package(baralho)
            pacote.media_files = midias[lang]
            try:
                pacote.write_to_file(nome_pacote)
                print(f"  [+] SUCESSO: {nome_pacote} gerado!")
            except Exception as e:
                print(f"  [-] Erro ao salvar {nome_pacote}: {e}")

if __name__ == "__main__":
    ARQUIVO_ALVO = "anki_principal_v2.tsv"
    
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(processar_banco_dados(ARQUIVO_ALVO))
