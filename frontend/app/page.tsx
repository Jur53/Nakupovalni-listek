"use client";

import { useEffect, useState } from "react";

type Trgovina = {
  id: number;
  ime: string;
};

type Izdelek = {
  id: number;
  ime: string;
  kategorija: string | null;
  enota: string | null;
};

type SkupnaCenaTrgovina = {
  ime_trgovina: string;
  skupna_cena: number;
};

type IzdelekNajcenejsi = {
  ime_izdelek: string;
  ime_trgovina: string;
  cena: number;
};

type PrimerjavaOut = {
  cene_po_trgovinah: SkupnaCenaTrgovina[];
  najcenejsa_trgovina: string;
  prihranek: number;
  razdeljen_seznam: IzdelekNajcenejsi[];
  skupna_cena_razdeljeno: number;
  dodatni_prihranek: number;
};

export default function Home() {
  const [trgovine, setTrgovine] = useState<Trgovina[]>([]);
  const [izdelki, setIzdelki] = useState<Izdelek[]>([]);
  const [izbrani, setIzbrani] = useState<number[]>([]);
  const [rezultat, setRezultat] = useState<PrimerjavaOut | null>(null);

  useEffect(() => {
    fetch("http://localhost:8000/trgovine")
      .then((res) => res.json())
      .then((data) => setTrgovine(data));
  }, []);

  useEffect(() => {
    fetch("http://localhost:8000/izdelki")
      .then((res) => res.json())
      .then((data) => setIzdelki(data));
  }, []);

  function preklopiIzbiro(id: number) {
    if (izbrani.includes(id)) {
      setIzbrani(izbrani.filter((x) => x !== id));
    } else {
      setIzbrani([...izbrani, id]);
    }
  }

  function primerjajCene() {
    fetch("http://localhost:8000/primerjava", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ izdelek_ids: izbrani }),
    })
      .then((res) => res.json())
      .then((data) => setRezultat(data));
  }

  return (
    <div>
      <h1>Trgovine</h1>
      <ul>
        {trgovine.map((t) => (
          <li key={t.id}>{t.ime}</li>
        ))}
      </ul>

      <h1>Izdelki</h1>
      <ul>
        {izdelki.map((i) => (
          <li key={i.id}>
            <input
              type="checkbox"
              checked={izbrani.includes(i.id)}
              onChange={() => preklopiIzbiro(i.id)}
            />
            {i.ime}
          </li>
        ))}
      </ul>

      <button onClick={primerjajCene} disabled={izbrani.length === 0}>
        Primerjaj cene
      </button>

      {rezultat && (
        <div>
          <h2>Rezultat</h2>
          <ul>
            {rezultat.cene_po_trgovinah.map((c) => (
              <li key={c.ime_trgovina}>
                {c.ime_trgovina}: {c.skupna_cena}€
              </li>
            ))}
          </ul>
          <p>
            Najcenejša trgovina: {rezultat.najcenejsa_trgovina} (prihranek{" "}
            {rezultat.prihranek}€)
          </p>
          <p>
            Razdeljen nakup: {rezultat.skupna_cena_razdeljeno}€ (dodatni
            prihranek {rezultat.dodatni_prihranek}€)
          </p>
        </div>
      )}
    </div>
  );
}