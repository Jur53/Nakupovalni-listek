import requests
from bs4 import BeautifulSoup
import time


def dobi_ceno_mercator(url):
    odgovor = requests.get(url)
    soup = BeautifulSoup(odgovor.text, "html.parser")

    ime_element = soup.find("h1", class_="lib-analytics-product-name")
    cena_element = soup.find("span", class_="price")

    ime = ime_element.get_text(strip=True)
    cena_besedilo = cena_element.get_text(strip=True)

    return ime, cena_besedilo


def dobi_izdelke_kategorija(category_id, limit=100, offset=0):
    url = "https://mercatoronline.si/products/browseProducts/getProducts"
    parametri = {
        "limit": limit,
        "offset": offset,
        "filterData[categories]": category_id,
        "from": offset,
    }
    odgovor = requests.get(url, params=parametri)
    podatki = odgovor.json()
    return podatki["products"]


def pretvori_izdelek(surov_izdelek):
    data = surov_izdelek["data"]
    gtin = data["gtins"][0]["gtin"] if data.get("gtins") else None

    return {
        "ime": data["name"],
        "cena": float(data["current_price"]),
        "cena_na_enoto": data.get("price_per_unit"),
        "enota_baza": data.get("price_per_unit_base"),
        "kategorija": data.get("category2"),
        "gtin": gtin,
        "mercator_id": data.get("cinv"),
        "url": "https://mercatoronline.si" + surov_izdelek.get("url", ""),
    }


def dobi_vse_izdelke_kategorija(category_id, limit=100):
    vsi_izdelki = []
    offset = 0

    while True:
        surovi = dobi_izdelke_kategorija(category_id, limit=limit, offset=offset)
        if not surovi:
            break

        vsi_izdelki.extend(surovi)

        skupaj = surovi[0].get("total", 0)
        offset += limit

        if offset >= skupaj:
            break

        time.sleep(1)

    return [pretvori_izdelek(s) for s in vsi_izdelki if "data" in s]