import { describe, expect, it, vi } from "vitest";
import { api, formatEur, parseCategoryTree, parseComparison, parseProductPage, parseProducts } from "@/lib/api";

describe("API response parsing", () => {
  it("accepts decimal strings and validates the complete comparison", () => {
    const result = parseComparison({
      celoten_nakup_na_voljo: true,
      cene_po_trgovinah: [{ ime_trgovina: "Tržnica", skupna_cena: "12.40" }],
      najcenejsa_trgovina: "Tržnica",
      prihranek: "2.10",
      razdeljen_seznam: [
        {
          izdelek_id: 3,
          ime_izdelek: "Jabolka",
          ime_trgovina: "Tržnica",
          cena_na_enoto: "1.25",
          kolicina: 2,
          skupna_cena: "2.50",
        },
      ],
      skupna_cena_razdeljeno: "10.30",
      dodatni_prihranek: "2.10",
    });

    expect(result.storeTotals[0].total).toBe(12.4);
    expect(result.splitItems[0]).toMatchObject({
      productId: 3,
      quantity: 2,
      unitPrice: 1.25,
      total: 2.5,
    });
    expect(formatEur(result.splitTotal)).toMatch(/10,30/);
  });

  it("accepts a split-only comparison without one-store totals", () => {
    const result = parseComparison({
      celoten_nakup_na_voljo: false,
      cene_po_trgovinah: [],
      najcenejsa_trgovina: null,
      prihranek: null,
      razdeljen_seznam: [
        {
          izdelek_id: 3,
          ime_izdelek: "Jabolka",
          ime_trgovina: "SPAR",
          cena_na_enoto: "1.25",
          kolicina: 2,
          skupna_cena: "2.50",
        },
      ],
      skupna_cena_razdeljeno: "2.50",
      dodatni_prihranek: null,
    });
    expect(result.completeBasketAvailable).toBe(false);
    expect(result.cheapestStore).toBeNull();
    expect(result.additionalSavings).toBeNull();
  });

  it("rejects error objects where a product array is expected", () => {
    expect(() => parseProducts({ detail: "Database unavailable" })).toThrow();
  });

  it("validates paginated catalog metadata", () => {
    const page = parseProductPage({
      items: [{
        id: 1,
        ime: "Kruh",
        kategorija: "Pekarna",
        kategorija_id: 12,
        kategorija_pot: ["Hrana", "Pekarna"],
        enota: "kos",
        najcenejsa_ponudba: {
          trgovina_id: 4,
          ime_trgovina: "Lidl",
          cena: "1.29",
          datum_zajema: "2026-09-19",
        },
        ponudbe: [
          {
            trgovina_id: 4,
            ime_trgovina: "Lidl",
            cena: "1.29",
            datum_zajema: "2026-09-19",
          },
          {
            trgovina_id: 5,
            ime_trgovina: "SPAR",
            cena: "1.39",
            datum_zajema: "2026-09-19",
          },
        ],
      }],
      total: 12,
      offset: 0,
      limit: 24,
      categories: ["Pekarna"],
      category_tree: [{
        id: 10,
        slug: "hrana",
        name: "Hrana",
        product_count: 12,
        children: [{
          id: 12,
          slug: "pekarna",
          name: "Pekarna",
          product_count: 4,
          children: [],
        }],
      }],
    });
    expect(page.total).toBe(12);
    expect(page.items[0].name).toBe("Kruh");
    expect(page.items[0].lowestOffer).toEqual({
      storeId: 4,
      store: "Lidl",
      price: 1.29,
      capturedOn: "2026-09-19",
    });
    expect(page.items[0].offers.map((offer) => offer.store)).toEqual(["Lidl", "SPAR"]);
    expect(page.items[0]).toMatchObject({
      categoryId: 12,
      categoryPath: ["Hrana", "Pekarna"],
    });
    expect(page.categoryTree[0]).toMatchObject({
      id: 10,
      slug: "hrana",
      name: "Hrana",
      productCount: 12,
    });
    expect(page.categoryTree[0].children[0].productCount).toBe(4);
    expect(() => parseProductPage({ items: [], total: -1, offset: 0, limit: 24, categories: [] })).toThrow();
  });

  it("keeps old catalog responses compatible while validating new category fields", () => {
    const page = parseProductPage({
      items: [{ id: 1, ime: "Kruh", kategorija: "Pekarna", enota: "kos" }],
      total: 1,
      offset: 0,
      limit: 24,
      categories: ["Pekarna"],
    });

    expect(page.categoryTree).toEqual([]);
    expect(page.items[0]).toMatchObject({ categoryId: null, categoryPath: [] });
    expect(() => parseCategoryTree([{ id: 1, slug: "hrana", name: "Hrana", product_count: -1, children: [] }])).toThrow();
    expect(() => parseProducts([{ id: 1, ime: "Kruh", kategorija_pot: ["Hrana", 2] }])).toThrow();
  });

  it("rejects incomplete split entries before rendering", () => {
    expect(() =>
      parseComparison({
        celoten_nakup_na_voljo: true,
        cene_po_trgovinah: [],
        najcenejsa_trgovina: "Trgovina",
        prihranek: 0,
        razdeljen_seznam: [{ izdelek_id: 1, ime: "Kruh" }],
        skupna_cena_razdeljeno: 1,
        dodatni_prihranek: 0,
      }),
    ).toThrow();
  });

  it("serializes a numeric category id in product queries", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({
      items: [],
      total: 0,
      offset: 0,
      limit: 24,
      categories: [],
      category_tree: [],
    }));
    vi.stubGlobal("fetch", fetchMock);

    try {
      await api.getProducts({
        search: " mleko ",
        categoryId: 12,
        storeIds: [3, 5],
      });
    } finally {
      vi.unstubAllGlobals();
    }

    expect(fetchMock).toHaveBeenCalledOnce();
    const url = new URL(String(fetchMock.mock.calls[0][0]), "http://localhost");
    expect(Object.fromEntries(url.searchParams)).toMatchObject({
      offset: "0",
      limit: "24",
      q: "mleko",
      kategorija_id: "12",
    });
    expect(url.searchParams.getAll("trgovina_ids")).toEqual(["3", "5"]);
    expect(url.searchParams.has("kategorija")).toBe(false);
  });
});
