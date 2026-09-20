export type Store = {
  id: number;
  name: string;
};

export type Product = {
  id: number;
  name: string;
  category: string | null;
  categoryId: number | null;
  categoryPath: string[];
  unit: string | null;
  lowestOffer: {
    storeId: number;
    store: string;
    price: number;
    capturedOn: string;
  } | null;
  offers: {
    storeId: number;
    store: string;
    price: number;
    capturedOn: string;
  }[];
};

export type CategoryNode = {
  id: number;
  slug: string;
  name: string;
  productCount: number;
  children: CategoryNode[];
};

export type ProductPage = {
  items: Product[];
  total: number;
  offset: number;
  limit: number;
  categories: string[];
  categoryTree: CategoryNode[];
};

export type SelectedItem = {
  izdelek_id: number;
  kolicina: number;
};

export type StoreTotal = {
  store: string;
  total: number;
};

export type SplitItem = {
  productId: number;
  name: string;
  store: string;
  unitPrice: number;
  quantity: number;
  total: number;
};

export type Comparison = {
  completeBasketAvailable: boolean;
  storeTotals: StoreTotal[];
  cheapestStore: string | null;
  savings: number | null;
  splitItems: SplitItem[];
  splitTotal: number;
  additionalSavings: number | null;
};

export type User = {
  id: number | string | null;
  email: string;
};

export type SavedList = {
  id: number;
  name: string;
  createdAt: string | null;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Parser<T> = (value: unknown) => T;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Invalid ${field}`);
  }
  return value.trim();
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function nullableDateString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const date = requiredString(value, "created date");
  if (Number.isNaN(Date.parse(date))) throw new Error("Invalid created date");
  return date;
}

function positiveInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value <= 0) {
    throw new Error(`Invalid ${field}`);
  }
  return value;
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`Invalid ${field}`);
  }
  return value;
}

function optionalStringArray(value: unknown, field: string): string[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`Invalid ${field}`);
  }
  return value.map((item) => item.trim()).filter(Boolean);
}

function money(value: unknown, field: string): number {
  const parsed =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim()
        ? Number(value)
        : Number.NaN;

  if (!Number.isFinite(parsed)) {
    throw new Error(`Invalid ${field}`);
  }
  return parsed;
}

function nullableMoney(value: unknown, field: string): number | null {
  return value === null || value === undefined ? null : money(value, field);
}

function first(value: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (key in value) return value[key];
  }
  return undefined;
}

export function parseStores(value: unknown): Store[] {
  if (!Array.isArray(value)) throw new Error("Invalid stores response");
  return value
    .map((item) => {
      if (!isRecord(item)) throw new Error("Invalid store");
      return {
        id: positiveInteger(item.id, "store id"),
        name: requiredString(first(item, ["ime", "name"]), "store name"),
      };
    })
    .sort((left, right) => left.name.localeCompare(right.name, "sl") || left.id - right.id);
}

function parseCategoryNode(value: unknown, depth: number): CategoryNode {
  if (!isRecord(value) || depth > 20) throw new Error("Invalid category node");
  const rawChildren = value.children ?? [];
  if (!Array.isArray(rawChildren)) throw new Error("Invalid category children");
  return {
    id: positiveInteger(value.id, "category id"),
    slug: requiredString(value.slug, "category slug"),
    name: requiredString(value.name, "category name"),
    productCount: nonNegativeInteger(value.product_count, "category product count"),
    children: rawChildren.map((child) => parseCategoryNode(child, depth + 1)),
  };
}

export function parseCategoryTree(value: unknown): CategoryNode[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw new Error("Invalid category tree");
  return value.map((node) => parseCategoryNode(node, 0));
}

export function parseProducts(value: unknown): Product[] {
  if (!Array.isArray(value)) throw new Error("Invalid products response");
  return value
    .map((item) => {
      if (!isRecord(item)) throw new Error("Invalid product");
      const rawOffer = item.najcenejsa_ponudba;
      let lowestOffer: Product["lowestOffer"] = null;
      if (rawOffer !== null && rawOffer !== undefined) {
        if (!isRecord(rawOffer)) throw new Error("Invalid lowest offer");
        lowestOffer = {
          storeId: positiveInteger(rawOffer.trgovina_id, "offer store id"),
          store: requiredString(rawOffer.ime_trgovina, "offer store name"),
          price: money(rawOffer.cena, "offer price"),
          capturedOn: requiredString(rawOffer.datum_zajema, "offer capture date"),
        };
      }
      const rawOffers = item.ponudbe ?? (rawOffer ? [rawOffer] : []);
      if (!Array.isArray(rawOffers)) throw new Error("Invalid product offers");
      const offers = rawOffers.map((offer) => {
        if (!isRecord(offer)) throw new Error("Invalid product offer");
        return {
          storeId: positiveInteger(offer.trgovina_id, "offer store id"),
          store: requiredString(offer.ime_trgovina, "offer store name"),
          price: money(offer.cena, "offer price"),
          capturedOn: requiredString(offer.datum_zajema, "offer capture date"),
        };
      });
      return {
        id: positiveInteger(item.id, "product id"),
        name: requiredString(first(item, ["ime", "name"]), "product name"),
        category: nullableString(first(item, ["kategorija", "category"])),
        categoryId:
          item.kategorija_id === undefined || item.kategorija_id === null
            ? null
            : positiveInteger(item.kategorija_id, "product category id"),
        categoryPath: optionalStringArray(item.kategorija_pot, "product category path"),
        unit: nullableString(first(item, ["enota", "unit"])),
        lowestOffer,
        offers,
      };
    })
    .sort(
      (left, right) =>
        (left.category ?? "").localeCompare(right.category ?? "", "sl") ||
        left.name.localeCompare(right.name, "sl") ||
        left.id - right.id,
    );
}

export function parseProductPage(value: unknown): ProductPage {
  if (!isRecord(value)) throw new Error("Invalid product page response");
  const total = value.total;
  const offset = value.offset;
  const limit = value.limit;
  const categories = value.categories;
  if (
    typeof total !== "number" ||
    !Number.isInteger(total) ||
    total < 0 ||
    typeof offset !== "number" ||
    !Number.isInteger(offset) ||
    offset < 0 ||
    typeof limit !== "number" ||
    !Number.isInteger(limit) ||
    limit <= 0 ||
    !Array.isArray(categories) ||
    categories.some((category) => typeof category !== "string")
  ) {
    throw new Error("Invalid product page metadata");
  }
  return {
    items: parseProducts(value.items),
    total,
    offset,
    limit,
    categories: categories.map((category) => category.trim()).filter(Boolean),
    categoryTree: parseCategoryTree(value.category_tree),
  };
}

export function parseComparison(value: unknown): Comparison {
  if (!isRecord(value)) throw new Error("Invalid comparison response");

  const totals = value.cene_po_trgovinah;
  const split = value.razdeljen_seznam;
  if (!Array.isArray(totals) || !Array.isArray(split)) {
    throw new Error("Invalid comparison lists");
  }
  if (typeof value.celoten_nakup_na_voljo !== "boolean") {
    throw new Error("Invalid complete basket availability");
  }
  const cheapestStore = nullableString(value.najcenejsa_trgovina);
  const savings = nullableMoney(value.prihranek, "savings");
  const additionalSavings = nullableMoney(value.dodatni_prihranek, "additional savings");
  if (value.celoten_nakup_na_voljo && (!cheapestStore || savings === null || additionalSavings === null)) {
    throw new Error("Incomplete one-store comparison");
  }

  return {
    completeBasketAvailable: value.celoten_nakup_na_voljo,
    storeTotals: totals
      .map((item) => {
        if (!isRecord(item)) throw new Error("Invalid store total");
        return {
          store: requiredString(
            first(item, ["ime_trgovina", "trgovina", "store"]),
            "store total name",
          ),
          total: money(first(item, ["skupna_cena", "cena", "total"]), "store total"),
        };
      })
      .sort((left, right) => left.total - right.total || left.store.localeCompare(right.store, "sl")),
    cheapestStore,
    savings,
    splitItems: split.map((item) => {
      if (!isRecord(item)) throw new Error("Invalid split item");
      return {
        productId: positiveInteger(item.izdelek_id, "split product id"),
        name: requiredString(
          first(item, ["ime_izdelek", "ime", "name"]),
          "split product name",
        ),
        store: requiredString(
          first(item, ["ime_trgovina", "trgovina", "store"]),
          "split store",
        ),
        unitPrice: money(
          first(item, ["cena_na_enoto", "cena", "unit_price"]),
          "split unit price",
        ),
        quantity: positiveInteger(first(item, ["kolicina", "quantity"]), "split quantity"),
        total: money(first(item, ["skupna_cena", "total"]), "split total"),
      };
    }),
    splitTotal: money(
      first(value, ["skupna_cena_razdeljeno", "razdeljen_skupaj", "split_total"]),
      "split total",
    ),
    additionalSavings,
  };
}

export function parseUser(value: unknown): User {
  if (!isRecord(value)) throw new Error("Invalid user response");
  const id = value.id;
  if (id !== undefined && typeof id !== "number" && typeof id !== "string") {
    throw new Error("Invalid user id");
  }
  return {
    id: id ?? null,
    email: requiredString(value.email, "user email"),
  };
}

function parseSavedList(value: unknown): SavedList {
  if (!isRecord(value)) throw new Error("Invalid saved list");
  return {
    id: positiveInteger(value.id, "list id"),
    name: requiredString(first(value, ["ime", "name"]), "list name"),
    createdAt: nullableDateString(first(value, ["ustvarjen", "created_at"])),
  };
}

export function parseSavedLists(value: unknown): SavedList[] {
  if (!Array.isArray(value)) throw new Error("Invalid lists response");
  return value.map(parseSavedList);
}

function errorMessage(value: unknown, status: number): string {
  if (isRecord(value)) {
    if (typeof value.message === "string" && value.message.trim()) return value.message;
    if (typeof value.detail === "string" && value.detail.trim()) return value.detail;
    if (isRecord(value.detail) && typeof value.detail.message === "string") {
      return value.detail.message;
    }
    if (Array.isArray(value.detail)) {
      const firstDetail = value.detail.find(isRecord);
      if (firstDetail && typeof firstDetail.msg === "string") return firstDetail.msg;
    }
  }

  if (status === 401) return "Za to dejanje se morate prijaviti.";
  if (status === 404) return "Zahtevani podatek ni bil najden.";
  if (status >= 500) return "Storitev trenutno ni dosegljiva. Poskusite znova.";
  return "Zahteve ni bilo mogoče dokončati.";
}

async function request<T>(path: string, parser: Parser<T>, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("Povezava s storitvijo ni uspela.", 0);
  }

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      if (!response.ok) throw new ApiError(errorMessage(null, response.status), response.status);
      throw new ApiError("Strežnik je vrnil neveljaven odgovor.", 502);
    }
  }

  if (!response.ok) throw new ApiError(errorMessage(data, response.status), response.status);

  try {
    return parser(data);
  } catch {
    throw new ApiError("Strežnik je vrnil nepričakovano obliko podatkov.", 502);
  }
}

const parseSuccess = (value: unknown) => {
  if (!isRecord(value) || value.ok !== true) throw new Error("Invalid success response");
  return true;
};

async function getAllPages<T>(
  path: string,
  parser: Parser<T[]>,
  signal?: AbortSignal,
): Promise<T[]> {
  const pageSize = 100;
  const result: T[] = [];

  for (let page = 0; page < 20; page += 1) {
    const separator = path.includes("?") ? "&" : "?";
    const values = await request(
      `${path}${separator}offset=${page * pageSize}&limit=${pageSize}`,
      parser,
      { signal },
    );
    result.push(...values);
    if (values.length < pageSize) return result;
  }

  throw new ApiError("Katalog je prevelik za prikaz. Uporabite ozji izbor.", 422);
}

export const api = {
  getStores(signal?: AbortSignal) {
    return getAllPages("/api/backend/trgovine", parseStores, signal);
  },
  getProducts(
    options: { search?: string; categoryId?: number | null; storeIds?: number[]; offset?: number; limit?: number } = {},
    signal?: AbortSignal,
  ) {
    const parameters = new URLSearchParams({
      offset: String(options.offset ?? 0),
      limit: String(options.limit ?? 24),
    });
    if (options.search?.trim()) parameters.set("q", options.search.trim());
    if (options.categoryId !== undefined && options.categoryId !== null) {
      parameters.set("kategorija_id", String(options.categoryId));
    }
    options.storeIds?.forEach((storeId) => parameters.append("trgovina_ids", String(storeId)));
    return request(`/api/backend/izdelki?${parameters}`, parseProductPage, { signal });
  },
  compare(items: SelectedItem[], storeIds: number[], signal?: AbortSignal) {
    return request("/api/backend/primerjava", parseComparison, {
      method: "POST",
      body: JSON.stringify({ items, trgovina_ids: storeIds }),
      signal,
    });
  },
  login(email: string, password: string) {
    return request("/api/backend/auth/login", parseSuccess, {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },
  register(email: string, password: string) {
    return request("/api/backend/auth/register", parseSuccess, {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },
  logout() {
    return request("/api/backend/auth/logout", parseSuccess, { method: "POST" });
  },
  me(signal?: AbortSignal) {
    return request("/api/backend/auth/me", parseUser, { signal });
  },
  getSavedLists(signal?: AbortSignal) {
    return request("/api/backend/seznami", parseSavedLists, { signal });
  },
  saveList(name: string, items: SelectedItem[]) {
    return request("/api/backend/seznami", parseSavedList, {
      method: "POST",
      body: JSON.stringify({ ime: name, items }),
    });
  },
};

export function formatEur(value: number): string {
  return new Intl.NumberFormat("sl-SI", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function getErrorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Prišlo je do nepričakovane napake.";
}
