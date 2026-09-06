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

export default function Home() {
  const [trgovine, setTrgovine] = useState<Trgovina[]>([]);
  const [izdelki, setIzdelki] = useState<Izdelek[]>([]);
  const [izbrani, setIzbrani] = useState<number[]>([]);

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
    </div>
  );
}