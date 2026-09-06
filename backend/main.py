from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from sqlalchemy import func
import models
import schemas

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/trgovine", response_model=list[schemas.TrgovinaOut])
def get_trgovine(db: Session = Depends(get_db)):
    return db.query(models.Trgovina).all()

@app.get("/izdelki", response_model=list[schemas.IzdelekOut])
def get_izdelki(db: Session = Depends(get_db)):
    return db.query(models.Izdelek).all()

@app.get("/cene", response_model=list[schemas.CenaDetajlOut])
def get_cene(db: Session = Depends(get_db)):
    return db.query(
        models.Izdelek.ime.label("ime_izdelek"),
        models.Trgovina.ime.label("ime_trgovina"),
        models.Cena.cena,
        models.Cena.datum_zajema
    ).join(models.Izdelek, models.Cena.izdelek_id == models.Izdelek.id
    ).join(models.Trgovina, models.Cena.trgovina_id == models.Trgovina.id
    ).all()


@app.post("/primerjava", response_model=schemas.PrimerjavaOut)
def primerjaj_cene(zahteva: schemas.PrimerjavaIn, db: Session = Depends(get_db)):
    rezultati = db.query(
        models.Trgovina.ime.label("ime_trgovina"),
        func.sum(models.Cena.cena).label("skupna_cena")
    ).join(
        models.Cena, models.Cena.trgovina_id == models.Trgovina.id
    ).filter(
        models.Cena.izdelek_id.in_(zahteva.izdelek_ids)
    ).group_by(
        models.Trgovina.ime
    ).all()

    cene_po_trgovinah = [
        schemas.SkupnaCenaTrgovina(ime_trgovina=r.ime_trgovina, skupna_cena=round(float(r.skupna_cena), 2))
        for r in rezultati 
    ]

    najcenejsa = min(cene_po_trgovinah, key=lambda x: x.skupna_cena)
    najdrazja = max(cene_po_trgovinah, key=lambda x: x.skupna_cena)
    prihranek = round(najdrazja.skupna_cena - najcenejsa.skupna_cena, 2)

    podrobne_cene = db.query(
        models.Izdelek.ime.label("ime_izdelek"),
        models.Trgovina.ime.label("ime_trgovina"),
        models.Cena.cena
    ).join(
        models.Izdelek, models.Cena.izdelek_id == models.Izdelek.id
    ).join(
        models.Trgovina, models.Cena.trgovina_id == models.Trgovina.id
    ).filter(
        models.Cena.izdelek_id.in_(zahteva.izdelek_ids)
    ).all()

    najcenejsi_po_izdelku = {}
    for vrstica in podrobne_cene:
        if vrstica.ime_izdelek not in najcenejsi_po_izdelku:
            najcenejsi_po_izdelku[vrstica.ime_izdelek] = vrstica
        elif vrstica.cena < najcenejsi_po_izdelku[vrstica.ime_izdelek].cena:
            najcenejsi_po_izdelku[vrstica.ime_izdelek] = vrstica

    razdeljen_seznam = [
        schemas.IzdelekNajcenejsi(
            ime_izdelek = v.ime_izdelek,
            ime_trgovina = v.ime_trgovina,
            cena = float(v.cena)
        )
        for v in najcenejsi_po_izdelku.values()
    ]

    skupna_cena_razdeljeno = round(sum(i.cena for i in razdeljen_seznam), 2)

    dodatni_prihranek = round(najcenejsa.skupna_cena - skupna_cena_razdeljeno, 2)

    return schemas.PrimerjavaOut(
        cene_po_trgovinah=cene_po_trgovinah,
        najcenejsa_trgovina=najcenejsa.ime_trgovina,
        prihranek=prihranek,
        razdeljen_seznam=razdeljen_seznam,
        skupna_cena_razdeljeno=skupna_cena_razdeljeno,
        dodatni_prihranek=dodatni_prihranek
    )


@app.post("/seznami", response_model=schemas.SeznamOut, status_code=201)
def ustvari_seznam(zahteva: schemas.SeznamIn, db: Session = Depends(get_db)):
    nov_seznam = models.Seznam(ime=zahteva.ime)
    db.add(nov_seznam)
    db.commit()
    db.refresh(nov_seznam)
    return nov_seznam


@app.post("/seznami/{seznam_id}/izdelki", response_model=schemas.SeznamIzdelekOut, status_code=201)
def dodaj_izdelek_na_seznam(seznam_id: int, zahteva: schemas.SeznamIzdelekIn, db: Session = Depends(get_db)):
    seznam = db.query(models.Seznam).filter(models.Seznam.id == seznam_id).first()
    if not seznam:
        raise HTTPException(status_code=404, detail="Seznam ne obstaja")

    izdelek = db.query(models.Izdelek).filter(models.Izdelek.id == zahteva.izdelek_id).first()
    if not izdelek:
        raise HTTPException(status_code=404, detail="Izdelek ne obstaja")

    nov_vnos = models.Seznam_izdelek(
        seznam_id=seznam_id,
        izdelek_id=zahteva.izdelek_id,
        kolicina=zahteva.kolicina
    )
    db.add(nov_vnos)
    db.commit()
    db.refresh(nov_vnos)
    return nov_vnos


@app.get("/seznami/{seznam_id}", response_model=schemas.SeznamDetajlOut)
def get_seznam(seznam_id: int, db: Session = Depends(get_db)):
    seznam = db.query(models.Seznam).filter(models.Seznam.id == seznam_id).first()
    if not seznam:
        raise HTTPException(status_code=404, detail="Seznam ne obstaja")

    vnosi = db.query(
        models.Izdelek.ime.label("ime_izdelek"),
        models.Izdelek.kategorija,
        models.Izdelek.enota,
        models.Seznam_izdelek.kolicina
    ).join(
        models.Izdelek, models.Seznam_izdelek.izdelek_id == models.Izdelek.id
    ).filter(
        models.Seznam_izdelek.seznam_id == seznam_id
    ).all()

    izdelki = [
        schemas.SeznamIzdelekDetajl(
            ime_izdelek=v.ime_izdelek,
            kategorija=v.kategorija,
            enota=v.enota,
            kolicina=v.kolicina
        )
        for v in vnosi
    ]

    return schemas.SeznamDetajlOut(
        id=seznam.id,
        ime=seznam.ime,
        ustvarjen=seznam.ustvarjen,
        izdelki=izdelki
    )