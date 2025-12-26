import time
import json
import pandas as pd
import os
import re # Importamos expresiones regulares para limpieza profunda
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- 1. CONFIGURACIÓN ---
TERMINO_BUSQUEDA = "laptop"
TIEMPO_ESPERA = 20

def limpiar_texto_precio(texto_sucio):
    """
    Convierte 'S/\n 2\n,\n799' en 'S/ 2799' y luego en el número 2799.0
    """
    if not isinstance(texto_sucio, str):
        return None, "N/A"
    
    # 1. Quitar saltos de línea y espacios extraños
    texto_plano = texto_sucio.replace('\n', '').replace('\r', '').replace('\t', '').strip()
    
    # 2. Quitar símbolos de moneda para el cálculo matemático
    # Eliminamos todo lo que no sea dígito o punto
    solo_numeros = re.sub(r'[^\d.]', '', texto_plano.replace(',', '')) 
    
    valor_float = None
    try:
        valor_float = float(solo_numeros)
    except ValueError:
        pass
        
    return valor_float, texto_plano # Devolvemos el número (para restar) y el texto limpio

def iniciar_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def intentar_cerrar_popups(driver):
    print("    🧹 Intentando cerrar popups...")
    selectores = [
        "button#onetrust-accept-btn-handler",
        "div.crs-close",
        "div#cookies-consent button",
        "button[class*='closeButton']",
        "div[class*='modal'] button",
        "div#dy-modal-contents button.close", # Popup típico de Falabella
        "span[class*='close-icon']"
    ]
    for sel in selectores:
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, sel)
            for btn in btns:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.5)
        except:
            pass

def buscar_texto(elemento, selectores):
    for sel in selectores:
        try:
            etiqueta = elemento.find_element(By.CSS_SELECTOR, sel)
            texto = etiqueta.text.strip()
            if texto:
                return texto
        except:
            continue
    return "N/A"

# --- LÓGICA DE EXTRACCIÓN MEJORADA ---
def extraer_tienda(driver, nombre_tienda, url):
    datos = []
    print(f"\n📢 Procesando {nombre_tienda}... URL: {url}")
    driver.get(url)
    time.sleep(6) 
    
    intentar_cerrar_popups(driver)
    
    print("    ⬇️ Bajando (Scroll) para activar carga...")
    for i in range(5): 
        driver.execute_script(f"window.scrollTo(0, {(i+1)*800});")
        time.sleep(1.5)

    # BUSCAR CONTENEDORES (Agregamos los de Falabella aquí)
    selectores_contenedor = [
        "div[id^='testId-pod-display']",            # Falabella (ID específico)
        "div.pod-item",                             # Falabella (Clase genérica)
        "div.vtex-product-summary-2-x-container",   # Coolbox Moderno
        "div.product-item",                         # Coolbox Clásico
        "div.Showcase__item",                       # Otros VTEX
        "div[class*='galleryItem']",
    ]
    
    productos = []
    for selector in selectores_contenedor:
        elems = driver.find_elements(By.CSS_SELECTOR, selector)
        if len(elems) > 0:
            print(f"    ✅ Estructura detectada: '{selector}' ({len(elems)} items)")
            productos = elems
            break
            
    if not productos:
        # Intento XPath (Plan B)
        try:
            productos = driver.find_elements(By.XPATH, "//div[contains(., 'S/') and string-length(.) < 400 and count(descendant::img)=1]")
        except: pass

    if not productos:
        print(f"❌ No se encontraron productos en {nombre_tienda}.")
        return []

    print(f"    ⚙️ Analizando precios de los primeros 15 productos...")
    contador = 0
    for item in productos:
        if contador >= 15: break
        try:
            # 1. NOMBRE (Agregamos selectores de Falabella)
            nombre = buscar_texto(item, [
                "b[id^='testId-pod-display-product-title']", # Falabella Título
                "b[class*='pod-subTitle']",                  # Falabella Subtítulo
                "span[class*='productBrand']",               # Coolbox
                "h3", ".product-item-link", 
                "div[class*='name']"
            ])
            
            # 2. PRECIOS (Texto Crudo - Agregamos Falabella)
            precio_actual_raw = buscar_texto(item, [
                "span[id^='testId-pod-display-price']",      # Falabella Precio
                "div[class*='sellingPrice']",                # Coolbox
                "span[class*='sellingPrice']",
                ".price", ".Showcase__salePrice"
            ])
            
            # Para el precio antiguo, Falabella a veces usa el mismo ID pero tachado,
            # o una clase secundaria. Agregamos opciones.
            precio_antes_raw = buscar_texto(item, [
                "span[class*='copy10']",                     # Falabella Texto Tachado (a veces)
                "ol li[class*='price-old']",                 # Falabella Lista Antigua
                "div[class*='listPrice']",                   # Coolbox
                "span[class*='listPrice']", 
                ".old-price", 
                "span[style*='line-through']" 
            ])
            
            # 3. LIMPIEZA PROFUNDA
            val_actual, txt_actual_limpio = limpiar_texto_precio(precio_actual_raw)
            val_antes, txt_antes_limpio = limpiar_texto_precio(precio_antes_raw)
            
            # --- PARCHE FALABELLA: A veces Falabella pone todos los precios juntos ---
            # Si no encontró precio con selectores, buscamos en el texto completo
            if val_actual is None:
                numeros = re.findall(r'S/\s*[\d,]+(?:\.\d+)?', item.text)
                if numeros:
                    # Limpiamos todos los encontrados
                    precios_limpios = []
                    for n in numeros:
                        v, t = limpiar_texto_precio(n)
                        if v: precios_limpios.append(v)
                    
                    if precios_limpios:
                        precios_limpios.sort(reverse=True) # Mayor a menor
                        # Asumimos: Mayor = Antes, Menor = Actual
                        if len(precios_limpios) > 1:
                            val_antes = precios_limpios[0]
                            val_actual = precios_limpios[-1]
                            txt_antes_limpio = f"S/ {val_antes:,.2f}"
                            txt_actual_limpio = f"S/ {val_actual:,.2f}"
                        else:
                            val_actual = precios_limpios[0]
                            txt_actual_limpio = f"S/ {val_actual:,.2f}"

            # Si no hay precio tachado ("N/A"), asumimos que es igual al actual
            if val_antes is None:
                val_antes = val_actual
                txt_antes_limpio = txt_actual_limpio

            # 4. CÁLCULO DESCUENTO
            descuento = "0%"
            if val_antes and val_actual and val_antes > val_actual:
                diff = val_antes - val_actual
                porc = (diff / val_antes) * 100
                descuento = f"{porc:.0f}%"

            # 5. URL e IMAGEN
            try: link = item.find_element(By.TAG_NAME, "a").get_attribute("href")
            except: link = "N/A"
            try: img = item.find_element(By.TAG_NAME, "img").get_attribute("src")
            except: img = "N/A"

            if nombre != "N/A" and val_actual is not None:
                datos.append({
                    "nombre": nombre.replace('\n', ' '), 
                    "precio_antes": txt_antes_limpio,    
                    "precio_despues": txt_actual_limpio, 
                    "descuento": descuento,
                    "url_image": img,
                    "tienda": nombre_tienda,
                    "url": link
                })
                contador += 1
        except Exception as e:
            continue
            
    return datos

if __name__ == "__main__":
    driver = iniciar_driver()
    all_data = []
    
    # 1. COOLBOX (Se mantiene igual)
    all_data.extend(extraer_tienda(driver, "Coolbox", f"https://www.coolbox.pe/{TERMINO_BUSQUEDA}"))
    
    # 2. FALABELLA (Reemplazamos a Plaza Vea)
    # Usamos la URL directa de categoría que suele ser más estable
    url_falabella = "https://www.falabella.com.pe/falabella-pe/category/cat40712/Laptops"
    all_data.extend(extraer_tienda(driver, "Falabella", url_falabella))
    
    driver.quit()
    
    if all_data:
        print(f"\n✅ ÉXITO TOTAL: {len(all_data)} productos extraídos.")
        
        if not os.path.exists('data'): os.makedirs('data')
        
        df = pd.DataFrame(all_data)
        df.to_csv('data/dinamico_ofertas_filtradas.csv', index=False, encoding='utf-8')
        
        with open('data/dinamico_ofertas.json', 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=4)
            
        print("💾 Datos guardados y LIMPIOS en carpeta 'data/'")
        print(df.head())
    else:
        print("\n❌ Error. Revisa las capturas de pantalla.")   