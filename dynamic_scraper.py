import time
import json
import pandas as pd
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- 1. CONFIGURACIÓN ---
TERMINO_BUSQUEDA = "laptop"
TIEMPO_ESPERA = 20

def limpiar_precio(precio_str):
    if isinstance(precio_str, str):
        # Eliminar S/, PEN, comas y espacios
        p = precio_str.replace('\u00a0', ' ').replace('S/', '').replace('PEN', '').replace('USD', '').replace('$', '').strip()
        p = p.replace(',', '') 
        try:
            return float(p)
        except ValueError:
            return None
    return None

def iniciar_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    options.add_argument('--disable-blink-features=AutomationControlled')
    # User Agent para simular ser un usuario real y evitar bloqueos
    options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def intentar_cerrar_popups(driver):
    print("    🧹 Intentando cerrar popups...")
    # Lista ampliada de botones de cierre comunes
    selectores = [
        "button#onetrust-accept-btn-handler",
        "div.crs-close",
        "div#cookies-consent button",
        "button[class*='closeButton']",
        "div[class*='modal'] button",
        "span[class*='close-icon']"
    ]
    for sel in selectores:
        try:
            # Intentamos encontrar y clickear
            btns = driver.find_elements(By.CSS_SELECTOR, sel)
            for btn in btns:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    print(f"       -> Popup cerrado: {sel}")
                    time.sleep(1)
        except:
            pass

def buscar_texto(elemento, selectores):
    """Busca texto en hijos usando CSS"""
    for sel in selectores:
        try:
            etiqueta = elemento.find_element(By.CSS_SELECTOR, sel)
            if etiqueta.text.strip():
                return etiqueta.text.strip()
        except:
            continue
    return "N/A"

# --- LÓGICA DE EXTRACCIÓN ---
def extraer_tienda(driver, nombre_tienda, url):
    datos = []
    print(f"\n📢 Procesando {nombre_tienda}... URL: {url}")
    driver.get(url)
    time.sleep(6) # Espera inicial para carga de scripts
    
    intentar_cerrar_popups(driver)
    
    print("    ⬇️ Bajando (Scroll) para activar carga...")
    # Hacemos scroll lento para dar tiempo a las imágenes
    for i in range(5): 
        driver.execute_script(f"window.scrollTo(0, {(i+1)*600});")
        time.sleep(1.5)

    # ESTRATEGIA 1: BUSCAR CONTENEDORES CONOCIDOS
    print("    🔍 Buscando productos por estructura...")
    selectores_contenedor = [
        "div.product-item",                         # Coolbox
        "div.vtex-product-summary-2-x-container",   # Plaza Vea (Nuevo VTEX)
        "div[class*='galleryItem']",                # Plaza Vea (Genérico)
        "div.Showcase__item",                       # Plaza Vea (Antiguo)
        "div[class*='product-card']"                # Genérico
    ]
    
    productos = []
    
    for selector in selectores_contenedor:
        elems = driver.find_elements(By.CSS_SELECTOR, selector)
        if len(elems) > 0:
            print(f"    ✅ Estructura detectada: '{selector}' ({len(elems)} items)")
            productos = elems
            break
            
    # ESTRATEGIA 2 (NUCLEAR): SI FALLA, BUSCAR POR PRECIO (XPath)
    if not productos:
        print("    ⚠️ Estructura no encontrada. Activando búsqueda profunda (XPath)...")
        try:
            # Busca elementos que contengan "S/" y toma su contenedor padre (suponiendo estructura div)
            # Esto es un truco avanzado para cuando cambian las clases
            productos = driver.find_elements(By.XPATH, "//div[contains(., 'S/') and string-length(.) < 200 and count(descendant::img)=1]")
            if len(productos) > 5: # Si encontramos varios, asumimos éxito
                 print(f"    ✅ Productos detectados por contenido: {len(productos)} items")
        except:
            pass

    if not productos:
        print(f"❌ Error crítico. No se detectaron productos en {nombre_tienda}. FOTO GUARDADA.")
        driver.save_screenshot(f"error_{nombre_tienda}.png")
        return []

    # Extracción de datos
    print(f"    ⚙️ Extrayendo datos de los primeros 15 productos...")
    contador = 0
    for item in productos:
        if contador >= 15: break
        try:
            # 1. NOMBRE (Varias opciones)
            nombre = buscar_texto(item, [
                "span[class*='productBrand']", 
                "h3",
                ".product-item-link",
                "div[class*='name']",
                ".Showcase__name"
            ])
            
            # 2. PRECIO (Varias opciones)
            precio_texto = buscar_texto(item, [
                "div[class*='sellingPrice']",
                "span[class*='currencyContainer']", 
                ".price",
                ".Showcase__salePrice"
            ])
            
            # Si falla CSS, intenta buscar cualquier texto con "S/" dentro del elemento
            if precio_texto == "N/A":
                texto_completo = item.text
                if "S/" in texto_completo:
                    # Extraer "a la fuerza" la parte del precio
                    partes = texto_completo.split('\n')
                    for p in partes:
                        if "S/" in p:
                            precio_texto = p
                            break
            
            # 3. URL
            try:
                link = item.find_element(By.TAG_NAME, "a").get_attribute("href")
            except:
                link = "N/A"
            
            # 4. IMAGEN
            try:
                img = item.find_element(By.TAG_NAME, "img").get_attribute("src")
            except:
                img = "N/A"

            # VALIDACIÓN Y GUARDADO
            if nombre != "N/A" and precio_texto != "N/A" and len(nombre) > 3:
                # Limpiamos el precio
                p_num = limpiar_precio(precio_texto)
                
                datos.append({
                    "nombre": nombre,
                    "precio_antes": precio_texto, # Para cumplir formato
                    "precio_despues": precio_texto,
                    "descuento": "0%",
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
    
    # 1. COOLBOX
    all_data.extend(extraer_tienda(driver, "Coolbox", f"https://www.coolbox.pe/{TERMINO_BUSQUEDA}"))
    
    # 2. PLAZA VEA (Ruta directa de categoría)
    all_data.extend(extraer_tienda(driver, "Plaza Vea", f"https://www.plazavea.com.pe/{TERMINO_BUSQUEDA}"))
    
    driver.quit()
    
    if all_data:
        print(f"\n✅ ÉXITO TOTAL: {len(all_data)} productos extraídos.")
        
        if not os.path.exists('data'): os.makedirs('data')
        
        # CSV
        df = pd.DataFrame(all_data)
        df.to_csv('data/dinamico_ofertas_filtradas.csv', index=False, encoding='utf-8')
        
        # JSON
        with open('data/dinamico_ofertas.json', 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=4)
            
        print("💾 Datos guardados en carpeta 'data/' (CSV y JSON listos para Werlen)")
        print(df.head()) # Muestra rápida
    else:
        print("\n❌ Error. Revisa las capturas de pantalla.")   