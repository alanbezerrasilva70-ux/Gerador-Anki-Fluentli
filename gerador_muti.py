import translators as ts
import random
import os
import re
import json
import asyncio
import time
import shutil
import zipfile
import genanki
import edge_tts
import unicodedata
import google.generativeai as genai
from pydantic import BaseModel
import time
import random
from deep_translator import GoogleTranslator


GEMINI_API_KEY = "AQ.Ab8RN6JtQbtEAnVxctDNaLHMOsUzriCOkFmznvUcsoKisQQRsA"
genai.configure(api_key=GEMINI_API_KEY)

class ResultadoRevisao(BaseModel):
    precisa_corrigir: bool
    nova_frase_traduzida: str
    motivo_correcao: str

modelo_revisor = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    generation_config={
        "temperature": 0.0,
        "response_mime_type": "application/json",
        "response_schema": ResultadoRevisao,
    }
)


# ==========================================
# CHAVE DE CONTROLE DE GERAÇÃO
# ==========================================
APENAS_GERAR_ANKI = False  # Mude para False para voltar a traduzir e gerar áudios

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
    "fr": {"nome": "Frances", "code": "fr", "locale": "fr-FR", "voz": "fr-FR-DeniseNeural", "translit": False},
    "es": {"nome": "Espanhol", "code": "es", "locale": "es-ES", "voz": "es-ES-ElviraNeural", "translit": False},
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
        {'name': 'PalavraAlvo'}, 
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
                <div style="font-size: 24px; margin-bottom: 15px; color: #2c3e50;">🎯 {{IdiomaAlvo}}</div>
                <div style="font-size: 18px; font-weight: bold; color: #e67e22; margin-bottom: 15px;">🔍 {{PalavraAlvo}}</div>
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
            <div style="font-size: 22px; color: #2ecc71; text-align: center;">🇧🇷 {{FrasePortugues}}</div>
            <br>
            <div style="font-size: 18px; color: #e65729; text-align: center;">Tradução Foco: {{PalavraPortugues}}</div>
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


def _substituir_forma(texto: str, origem: str, destino: str) -> str:
    padrao = re.compile(rf'(?<!\w){re.escape(origem)}(?!\w)', re.IGNORECASE)

    def substituir(match):
        encontrado = match.group(0)
        if encontrado.isupper():
            return destino.upper()
        if encontrado[:1].isupper():
            return destino[:1].upper() + destino[1:]
        return destino

    return padrao.sub(substituir, texto)


def aplicar_variante_regional(texto: str, lang: str, texto_origem: str = '') -> str:
    """Prefer France/French and Spain/Spanish vocabulary where variants are explicit."""
    origem_normalizada = texto_origem.casefold()
    def capitalizar_como_match(match, replacement: str) -> str:
        if match.group(0)[:1].isupper():
            return replacement[:1].upper() + replacement[1:]
        return replacement

    if lang == 'fr':
        if re.search(r'\bweek[\s-]?end\b', origem_normalizada):
            texto = re.sub(
                r'\b(en|cette)\s+fin de semaine\b',
                lambda m: capitalizar_como_match(m, 'ce week-end'),
                texto,
                flags=re.IGNORECASE,
            )
            texto = re.sub(
                r'\b(à la|la|une)\s+fin de semaine\b',
                lambda m: capitalizar_como_match(
                    m,
                    'un week-end' if m.group(1).casefold() == 'une' else 'le week-end',
                ),
                texto,
                flags=re.IGNORECASE,
            )
            texto = re.sub(r'\bfin de semaine\b', 'week-end', texto, flags=re.IGNORECASE)
        texto = re.sub(
            r'\b(un|le)\s+dépanneur\b',
            lambda m: 'une supérette' if m.group(1).casefold() in {'un', 'le'} else m.group(0),
            texto,
            flags=re.IGNORECASE,
        )
        substituicoes = (
            ('magasinage', 'shopping'),
            ('magasiner', 'faire du shopping'),
            ('dépanneur', 'supérette'),
            ('tuque', 'bonnet'),
            ('cellulaire', 'portable'),
        )
    elif lang == 'es':
        substituicoes = (
            ('computadoras', 'ordenadores'),
            ('celulares', 'móviles'),
            ('celular', 'móvil'),
            ('albercas', 'piscinas'),
            ('alberca', 'piscina'),
            ('desempacando', 'desembalando'),
            ('desempacaron', 'desembalaron'),
            ('desempacaba', 'desembalaba'),
            ('desempacan', 'desembalan'),
            ('desempaca', 'desembala'),
            ('desempacar', 'desembalar'),
            ('platicando', 'charlando'),
            ('platicaron', 'charlaron'),
            ('platicaba', 'charlaba'),
            ('platican', 'charlan'),
            ('platicó', 'charló'),
            ('platicar', 'charlar'),
            ('chamarras', 'chaquetas'),
            ('chamarra', 'chaqueta'),
        )
    else:
        return texto

    resultado = texto
    if lang == 'es':
        resultado = re.sub(
            r'\b(las|unas|estas|esas)\s+computadoras\b',
            lambda m: capitalizar_como_match(
                m,
                {
                    'las': 'los ordenadores',
                    'unas': 'unos ordenadores',
                    'estas': 'estos ordenadores',
                    'esas': 'esos ordenadores',
                }[m.group(1).casefold()],
            ),
            resultado,
            flags=re.IGNORECASE,
        )
        resultado = re.sub(
            r'\b(la|una|esta|esa)\s+computadora\b',
            lambda m: capitalizar_como_match(
                m,
                {
                    'la': 'el ordenador',
                    'una': 'un ordenador',
                    'esta': 'este ordenador',
                    'esa': 'ese ordenador',
                }[m.group(1).casefold()],
            ),
            resultado,
            flags=re.IGNORECASE,
        )
        resultado = _substituir_forma(resultado, 'computadora', 'ordenador')
    for origem, destino in substituicoes:
        resultado = _substituir_forma(resultado, origem, destino)

    if lang == 'es':
        if re.search(r'\b(?:juice|juices)\b', origem_normalizada):
            resultado = re.sub(r'\bjugos?\b', lambda m: 'zumos' if m.group(0).endswith('s') else 'zumo', resultado, flags=re.IGNORECASE)
        if re.search(r'\b(?:car|cars|vehicle|vehicles|driving|drive)\b', origem_normalizada):
            resultado = re.sub(r'\bcarros?\b', lambda m: 'coches' if m.group(0).endswith('s') else 'coche', resultado, flags=re.IGNORECASE)
        if re.search(r'\b(?:parking lot|parking space|car park|parking)\b', origem_normalizada):
            resultado = re.sub(r'\bestacionamientos?\b', lambda m: 'aparcamientos' if m.group(0).endswith('s') else 'aparcamiento', resultado, flags=re.IGNORECASE)
    elif lang == 'fr' and re.search(r'\b(?:car|cars|vehicle|vehicles)\b', origem_normalizada):
        resultado = re.sub(r'\bchars?\b', lambda m: 'voitures' if m.group(0).endswith('s') else 'voiture', resultado, flags=re.IGNORECASE)

    return limpar_texto(resultado)


def limpar_palavra_unica(texto: str, palavra_en: str) -> str:
    """
    Garante que traduções de palavras soltas fiquem limpas (ex: 'masivo' em vez de 'masivo / masiva').
    Mantém expressões compostas intactas (ex: 'banco de dados').
    """
    if not texto:
        return ""
    
    # Remove barras ou vírgulas se houver opções duplicadas
    if '/' in texto or ',' in texto:
        texto = re.split(r'[/,]', texto)[0].strip()
        
    # Se a palavra original em inglês for 1 única palavra
    if len(palavra_en.strip().split()) == 1:
        partes = texto.strip().split()
        # Se o tradutor retornou 2 palavras da mesma raiz variando gênero (ex: "masivo masiva")
        if len(partes) == 2:
            p1, p2 = partes[0].casefold(), partes[1].casefold()
            if p1[:-1] == p2[:-1] or p1 == p2:
                return partes[0]
                
    return texto.strip()


def normalizar_cache_variantes_genero(cache: dict, registros: list[dict]) -> int:
    palavras_en_por_id = {str(registro['ID']): registro['Palavra_EN'] for registro in registros}
    alteracoes = 0
    for chave, valor in cache.items():
        if not chave.startswith('palavra_') or not isinstance(valor, str):
            continue
        correspondencia = re.match(r'palavra_(\d+)_', chave)
        palavra_en = palavras_en_por_id.get(correspondencia.group(1), '') if correspondencia else ''
        atualizado = limpar_palavra_unica(valor, palavra_en)
        if atualizado != valor:
            cache[chave] = atualizado
            alteracoes += 1
    return alteracoes

def normalizar_variantes_genero(texto: str, lang: str) -> str:
    """Remove duplicatas de gênero retornadas pelo tradutor, como 'masiva masivo'."""
    if not texto:
        return ""
    partes = texto.strip().split()
    # Se retornou duas palavras com a mesma raiz (ex: masiva masivo)
    if len(partes) == 2:
        p1, p2 = partes[0].casefold(), partes[1].casefold()
        if p1[:-1] == p2[:-1] or p1 == p2:
            # Retorna apenas a primeira variação para manter limpo
            return partes[0].capitalize() if texto[0].isupper() else partes[0]
    return texto

def normalizar_cache_variantes_regionais(cache: dict, registros: list[dict]) -> int:
    frases_por_id = {str(registro['ID']): registro['Frase_EN'] for registro in registros}
    alteracoes = 0
    for chave, valor in cache.items():
        if not isinstance(valor, str):
            continue
        lang = chave.rsplit('_', 1)[-1]
        if lang not in {'fr', 'es'}:
            continue
        correspondencia = re.match(r'(?:palavra_)?(\d+)_', chave)
        if not correspondencia:
            continue
        texto_origem = frases_por_id.get(correspondencia.group(1), '')
        atualizado = aplicar_variante_regional(valor, lang, texto_origem)
        if chave.startswith('palavra_'):
            atualizado = normalizar_variantes_genero(atualizado, lang)
        if atualizado != valor:
            cache[chave] = atualizado
            alteracoes += 1
    return alteracoes


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

# ==============================================================================
# 4. FUNÇÃO DE AUDITORIA LINGUÍSTICA
# ==============================================================================
def auditar_frase(ingles: str, traducao_atual: str, idioma_destino: str) -> dict:
    """
    Envia a frase ao Gemini para verificar fluência, erros de gênero, 
    traduções estranhas e variantes regionais (ex: Francês FR vs CA, Árabe Padrão, etc).
    """
    prompt = f"""
    Você é um Revisor Linguístico Sênior especializado em localização de idiomas.
    Sua única tarefa é avaliar se a tradução de uma frase está natural e perfeita no idioma de destino.

    DADOS DA FRASE:
    - Frase Original (Inglês): "{ingles}"
    - Tradução Atual para Avaliar: "{traducao_atual}"
    - Idioma Alvo: "{idioma_destino}"

    REGRAS RÍGIDAS DE REVISÃO:
    1. Se a tradução atual já estiver perfeita, fluida e natural para um nativo de '{idioma_destino}', defina 'precisa_corrigir' como false e mantenha 'nova_frase_traduzida' idêntica à 'Tradução Atual'.
    2. Se a tradução atual contiver erros gramaticais, palavras em inglês misturadas, duplicidade de gênero na mesma frase (ex: "enérgica/enérgico"), ou se for uma variante regional errada (ex: Francês canadense em vez de Francês europeu), defina 'precisa_corrigir' como true e escreva a versão corrigida em 'nova_frase_traduzida'.
    3. Mantenha exatamente o mesmo significado e pontuação da frase original.
    """

    try:
        resposta = modelo_revisor.generate_content(prompt)
        dados = json.loads(resposta.text)
        return dados
    except Exception as e:
        print(f"⚠️ Falha na chamada da API para a frase '{ingles}': {e}")
        # Em caso de erro na rede/API, mantém a tradução original intacta por segurança
        return {
            "precisa_corrigir": False, 
            "nova_frase_traduzida": traducao_atual, 
            "motivo_correcao": "Erro de conexão/API"
        }

# ==========================================
# 4. MOTORES DE CACHE E TRADUÇÃO INSISTENTE (ANTI-FALHA)
# ==========================================
CACHE_ARQUIVO = "cache_traducoes.json"
arquivo_progresso = "progresso.txt"
TOTAL_BLOCOS = 608
FRASES_POR_BLOCO = 10
TOTAL_REGISTROS = TOTAL_BLOCOS * FRASES_POR_BLOCO

def carregar_cache():
    if not os.path.exists(CACHE_ARQUIVO):
        return {}

    with open(CACHE_ARQUIVO, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    if not isinstance(cache, dict):
        raise ValueError(f'O cache precisa ser um objeto JSON: {CACHE_ARQUIVO}')
    return cache

def salvar_cache(cache):
    temp_path = f"{CACHE_ARQUIVO}.tmp"
    for tentativa in range(3):
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, CACHE_ARQUIVO)
            return
        except PermissionError:
            if tentativa == 2:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
            time.sleep(0.2)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise


def validar_base_anki(linhas):
    if len(linhas) != TOTAL_REGISTROS:
        raise ValueError(
            f'A base Anki precisa ter {TOTAL_REGISTROS} linhas; encontrei {len(linhas)}.'
        )

    registros = []
    temas_por_bloco = {}
    for indice, linha in enumerate(linhas, 1):
        partes = extrair_partes_linha(linha)
        if len(partes) != 9 or not partes[0].isdigit():
            raise ValueError(
                f'Linha {indice} inválida: esperava 9 colunas e um ID numérico.'
            )

        numero_registro = int(partes[0])
        if numero_registro != indice:
            raise ValueError(
                f'ID fora de sequência na linha {indice}: encontrei {numero_registro}.'
            )

        tema = partes[1]
        if not tema or 'indefinido' in tema.casefold():
            raise ValueError(f'O registro {numero_registro} não tem tema válido.')
        numero_bloco = (numero_registro - 1) // FRASES_POR_BLOCO + 1
        tema_anterior = temas_por_bloco.setdefault(numero_bloco, tema)
        if tema_anterior != tema:
            raise ValueError(
                f'O bloco {numero_bloco} possui temas diferentes entre suas dez frases.'
            )

        frase_en = partes[4]
        if not frase_en or 'Tema:' in frase_en:
            raise ValueError(f'A frase em inglês do registro {numero_registro} é inválida.')

        registros.append({
            'ID': numero_registro,
            'Tema': tema,
            'Palavra_EN': partes[2],
            'Palavra_PT': partes[3],
            'Frase_EN': frase_en,
            'Frase_PT': partes[6],
        })
    return registros


def validar_cache_completo(registros, cache):
    faltantes_por_idioma = {lang: [] for lang in IDIOMAS_CONFIG}
    for registro in registros:
        numero_registro = registro['ID']
        chave_base = f"{numero_registro}_{registro['Frase_EN']}"
        for lang in IDIOMAS_CONFIG:
            chaves = (
                f'{chave_base}_{lang}',
                f"palavra_{numero_registro}_{registro['Palavra_EN']}_{lang}",
            )
            if any(
                not isinstance(cache.get(chave), str)
                or not cache[chave].strip()
                or 'Erro de Tradução' in cache[chave]
                for chave in chaves
            ):
                faltantes_por_idioma[lang].append(numero_registro)

    idiomas_incompletos = {
        lang: ids
        for lang, ids in faltantes_por_idioma.items()
        if ids
    }
    if idiomas_incompletos:
        resumo = '; '.join(
            f'{lang}: {len(ids)} registros ausentes (ex.: {", ".join(map(str, ids[:5]))})'
            for lang, ids in idiomas_incompletos.items()
        )
        raise ValueError(
            'Cache incompleto; nenhum pacote foi montado no modo somente Anki. '
            f'{resumo}'
        )

# ==========================================
# MOTORES DE CACHE E TRADUÇÃO INSISTENTE (COM RESPIRO DINÂMICO) E CAMUFLAGEM
# ==========================================
USER_AGENTS_CAMUFLAGEM = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0"
]

async def traduzir_com_insistencia(texto: str, config_code: str):
    """
    Realiza a tradução com rotação automática entre Google, Bing, DuckDuckGo e Yandex.
    """
    tentativa = 1
    tempo_base_respiro = 3.0
    
    while True:
        lang_code = config_code
            
        try:
            await asyncio.sleep(random.uniform(1.0, 2.5))
            
            def _traduzir():
                # 1ª opção: Google (via deep_translator)
                try:
                    res = GoogleTranslator(source='en', target=lang_code).translate(texto)
                    if res: return res
                except Exception:
                    pass

                # 2ª opção: Alternativas via biblioteca 'translators'
                motores_fallback = ['bing', 'duckduckgo', 'yandex']
                for motor in motores_fallback:
                    try:
                        res = ts.translate_text(
                            texto, 
                            translator=motor, 
                            from_language='en', 
                            to_language=lang_code
                        )
                        if res: return res
                    except Exception:
                        continue
                
                raise Exception("Todos os motores falharam nesta tentativa.")
                    
            resultado = await asyncio.wait_for(asyncio.to_thread(_traduzir), timeout=25)
            
            if resultado and isinstance(resultado, str):
                texto_limpo = limpar_texto(resultado)
                erros_bloqueados = ['error', 'exception', 'timeout', 'limit exceeded', 'too many requests']
                
                if texto_limpo and not any(err in texto_limpo.casefold() for err in erros_bloqueados):
                    return texto_limpo
                    
            raise ValueError("Resposta vazia ou inválida.") 
                
        except Exception:
            espera_dinamica = min(tempo_base_respiro * (1.3 ** min(tentativa, 8)), 45.0)
            print(f"    [!] Todos os motores falharam/bloquearam ({lang_code}). Tentativa {tentativa}. Pausa de {espera_dinamica:.1f}s...")
            await asyncio.sleep(espera_dinamica)
            
        tentativa += 1


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
    with open(caminho_arquivo, 'r', encoding='utf-8') as f:
        linhas = f.readlines()
    registros = validar_base_anki(linhas)
    cache = carregar_cache()
    variantes_normalizadas = normalizar_cache_variantes_genero(cache, registros)
    variantes_regionais = normalizar_cache_variantes_regionais(cache, registros)
    locales_alvo = ', '.join(
        f'{IDIOMAS_CONFIG[lang]["nome"]}: {IDIOMAS_CONFIG[lang]["locale"]}'
        for lang in ('fr', 'es')
    )
    print(
        f'[i] Variantes regionais desejadas: {locales_alvo}. '
        'Os motores recebem códigos genéricos (fr/es); será aplicada a '
        'normalização lexical conhecida, que não substitui revisão nativa.'
    )
    if variantes_normalizadas:
        print(
            f'[i] Formas de gênero separadas para exibição: '
            f'{variantes_normalizadas} traduções.'
        )
    if variantes_regionais:
        print(
            f'[i] Vocabulário regional ajustado para francês da França/espanhol da Espanha: '
            f'{variantes_regionais} traduções.'
        )
    if variantes_normalizadas or variantes_regionais:
        salvar_cache(cache)
    if APENAS_GERAR_ANKI:
        validar_cache_completo(registros, cache)

    tempo_inicio = time.time()
    tempo_limite = 500.0 * 3600 # Proteção anti-corte do GitHub Actions (5.5h)
    
    # O progresso agora é controlado 100% pelo cache_traducoes.json.
    # Garantimos que a leitura sempre comece da linha 1 para incluir todos os cards no Anki.
    linha_inicial = 0

    pasta_audios = "audios_poliglota"
    os.makedirs(pasta_audios, exist_ok=True)
    
    # Criar pastas para cada idioma dentro de audios_poliglota
    pastas_idiomas = {}
    for lang in IDIOMAS_CONFIG:
        pasta_lang = os.path.join(pasta_audios, lang)
        os.makedirs(pasta_lang, exist_ok=True)
        pastas_idiomas[lang] = pasta_lang

    baralhos = {}
    midias = {lang: [] for lang in IDIOMAS_CONFIG}
    
    for lang in IDIOMAS_CONFIG:
        deck_id = abs(hash(f"Fluentli_Exp_{lang}")) % (10**10)
        baralhos[lang] = genanki.Deck(deck_id, f"Fluentli - {IDIOMAS_CONFIG[lang]['nome']}")

    if APENAS_GERAR_ANKI:
        print(f"[*] MODO GERAR ANKI APENAS ATIVADO. Extraindo do cache...\n")
    else:
        print(
            f"[*] Base validada: {len(registros)} registros. "
            f"Reconstruindo os baralhos completos desde o registro 1; "
            f"checkpoint anterior: {linha_inicial}.\n"
        )

    processamento_incompleto = False
    # Percorre todos os registros do banco de dados a partir da linha 1 (índice 0)
    for index, registro in enumerate(registros):
        # Removido o 'continue' por linha_inicial para garantir que o cache seja verificado
        # desde o início e que todos os cards sejam adicionados ao baralho do Anki.
        if not APENAS_GERAR_ANKI and time.time() - tempo_inicio > tempo_limite:
            print(f"\n[ALERTA] Limite de tempo atingido! Pausando no registro {index}.")
            with open(arquivo_progresso, "w") as f:
                f.write(str(index))
            processamento_incompleto = True
            break

        numero_registro = registro['ID']
        tema = registro['Tema']
        palavra_en = registro['Palavra_EN']
        palavra_pt = registro['Palavra_PT']
        frase_en = registro['Frase_EN']
        frase_pt = registro['Frase_PT']

        chave_cache_base = f"{numero_registro}_{frase_en}"
        if not APENAS_GERAR_ANKI:
            print(f"[{numero_registro}/{len(linhas)}] Processando: {frase_en[:50]}...")

        for lang, config in IDIOMAS_CONFIG.items():
            chave_lang = f"{chave_cache_base}_{lang}"
            chave_palavra_lang = f"palavra_{numero_registro}_{palavra_en}_{lang}"

            frase_alvo = None
            palavra_alvo = None

            if APENAS_GERAR_ANKI:
                frase_alvo = cache[chave_lang]
                palavra_alvo = cache[chave_palavra_lang]
            else:
                # === 1. TRADUÇÃO DA FRASE ===
                frase_cache = cache.get(chave_lang)
                if frase_cache and "Erro de Tradução" not in frase_cache:
                    frase_alvo = aplicar_variante_regional(
                        frase_cache,
                        lang,
                        frase_en,
                    )
                else:
                    frase_bruta = aplicar_variante_regional(
                        await traduzir_com_insistencia(frase_en, config['code']),
                        lang,
                        frase_en,
                    )
                    
                    # Interceptação do Revisor Gemini
                    resultado_revisao = auditar_frase(frase_en, frase_bruta, config['nome'])
                    frase_alvo = resultado_revisao.get("nova_frase_traduzida", frase_bruta)

                    cache[chave_lang] = frase_alvo
                    salvar_cache(cache)

                # === 2. TRADUÇÃO DA PALAVRA ISOLADA ===
                if lang == "en":
                    palavra_alvo = palavra_en
                else:
                    palavra_cache = cache.get(chave_palavra_lang)
                    if palavra_cache and "Erro de Tradução" not in palavra_cache:
                        palavra_alvo = aplicar_variante_regional(
                            palavra_cache,
                            lang,
                            frase_en,
                        )
                        palavra_alvo = limpar_palavra_unica(palavra_alvo, palavra_en)
                    else:
                        palavra_alvo = limpar_palavra_unica(
                            aplicar_variante_regional(
                                await traduzir_com_insistencia(palavra_en, config['code']),
                                lang,
                                frase_en,
                            ),
                            palavra_en,
                        )
                        cache[chave_palavra_lang] = palavra_alvo
                        salvar_cache(cache)
           
            # === 3. ROMANIZAÇÃO ===
            translit_str = gerar_transliteracao(frase_alvo, lang)

            # === 4. ÁUDIO ===
            nome_audio = f"{lang}_{numero_registro}.mp3"
            # Salvar dentro da pasta do idioma específico
            caminho_audio = os.path.join(pastas_idiomas[lang], nome_audio)

            if not APENAS_GERAR_ANKI:
                # A garantia de áudio agora é forte devido ao while loop da tradução
                await gerar_audio_com_insistencia(frase_alvo, caminho_audio, config['voz'])

            campo_audio = f"[sound:{nome_audio}]" if os.path.exists(caminho_audio) else ""
            if os.path.exists(caminho_audio): midias[lang].append(caminho_audio)

            # O modelo refatorado injeta a Frase Alvo e a Palavra Foco isolada
            nota = genanki.Note(
                model=MODELO_POLIGLOTA,
                fields=[
                    str(numero_registro), 
                    tema, 
                    palavra_en,
                    frase_en,
                    frase_alvo,
                    palavra_alvo,
                    translit_str, 
                    campo_audio, 
                    palavra_pt, 
                    frase_pt
                ]
            )
            baralhos[lang].add_note(nota)

    if processamento_incompleto:
        print('[!] Processamento incompleto; pacotes não foram sobrescritos.')
        return

    if not APENAS_GERAR_ANKI:
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
            prefixo = "TESTE_" if APENAS_GERAR_ANKI else "Pacote_Fluentli_"
            nome_pacote = f"{prefixo}{IDIOMAS_CONFIG[lang]['nome']}.apkg"
            pacote = genanki.Package(baralho)
            pacote.media_files = midias[lang]
            try:
                pacote.write_to_file(nome_pacote)
                pacotes_gerados.append(nome_pacote)
                print(f"  [+] SUCESSO: {nome_pacote} gerado! ({len(baralho.notes)} cartas)")
            except Exception as e:
                print(f"  [-] Erro ao salvar {nome_pacote}: {e}")
                
    if APENAS_GERAR_ANKI:
        print("\n[!] Modo de teste concluído. Verifique os arquivos .apkg gerados na sua pasta.")
        return

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

# ==========================================
# PONTO DE ENTRADA DO SCRIPT
# ==========================================
if __name__ == "__main__":
    # Define o nome exato do arquivo TSV contendo os 6.080 registros
    ARQUIVO_ALVO = "anki_principal_v2.tsv" 

    # Ajuste específico para sistemas Windows tratarem loops assíncronos corretamente
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Executa o processamento assíncrono principal enviando o arquivo alvo
    asyncio.run(processar_banco_dados(ARQUIVO_ALVO))
