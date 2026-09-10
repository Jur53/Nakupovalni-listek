import requests
from bs4 import BeautifulSoup

def dobi_ceno_mercator(url):
    odgovor = requests.get(url)
    soup = BeautifulSoup(odgovor.text, "html.parser")

    ime_element = soup.find("h1", class_="lib-analytics-product-name")
    cena_element = soup.find("span", class_="price")

    ime = ime_element.get_text(strip=True)
    cena_besedilo = cena_element.get_text(strip=True)

    return ime, cena_besedilo