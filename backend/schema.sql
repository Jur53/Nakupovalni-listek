-- Nakupovalni listek — osnovna shema za MVP (Spar + Mercator, ~20-30 osnovnih izdelkov)

-- Trgovine (npr. Spar, Mercator)
CREATE TABLE trgovine (
    id SERIAL PRIMARY KEY,
    ime VARCHAR(100) NOT NULL UNIQUE
);

-- Izdelki — kanonični (normaliziran) izdelek, neodvisen od trgovine
-- npr. "Mleko 1L" je en zapis, ki ga potem povežemo s ceno pri Sparu in ceno pri Mercatorju
CREATE TABLE izdelki (
    id SERIAL PRIMARY KEY,
    ime VARCHAR(200) NOT NULL,
    kategorija VARCHAR(100),      -- npr. 'mlečni izdelki', 'pekovski izdelki', 'sadje in zelenjava'
    enota VARCHAR(20)             -- npr. '1L', '500g', 'kos'
);

-- Cene — cena izdelka pri določeni trgovini na določen datum zajema
CREATE TABLE cene (
    id SERIAL PRIMARY KEY,
    izdelek_id INTEGER NOT NULL REFERENCES izdelki(id) ON DELETE CASCADE,
    trgovina_id INTEGER NOT NULL REFERENCES trgovine(id) ON DELETE CASCADE,
    cena NUMERIC(6,2) NOT NULL,
    datum_zajema DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (izdelek_id, trgovina_id, datum_zajema)
);

-- Seznami — uporabnikovi nakupovalni seznami
CREATE TABLE seznami (
    id SERIAL PRIMARY KEY,
    ime VARCHAR(100),
    ustvarjen TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Seznam_izdelki — kateri izdelki (in koliko) so na posameznem seznamu
CREATE TABLE seznam_izdelki (
    id SERIAL PRIMARY KEY,
    seznam_id INTEGER NOT NULL REFERENCES seznami(id) ON DELETE CASCADE,
    izdelek_id INTEGER NOT NULL REFERENCES izdelki(id),
    kolicina INTEGER NOT NULL DEFAULT 1
);

-- Začetni podatki za trgovine
INSERT INTO trgovine (ime) VALUES ('Spar'), ('Mercator');

-- Koristen pogled: zadnja znana cena vsakega izdelka pri vsaki trgovini
CREATE VIEW zadnje_cene AS
SELECT DISTINCT ON (izdelek_id, trgovina_id)
    izdelek_id, trgovina_id, cena, datum_zajema
FROM cene
ORDER BY izdelek_id, trgovina_id, datum_zajema DESC;