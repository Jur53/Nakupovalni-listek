import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ShoppingApp } from "@/app/components/shopping-app";

const stores = [{ id: 1, ime: "Tržnica" }, { id: 2, ime: "Druga trgovina" }];
const products = [{
  id: 7,
  ime: "Mleko",
  kategorija: "Mlečni izdelki",
  kategorija_id: 11,
  kategorija_pot: ["Hlajeno", "Mlečni izdelki"],
  enota: "1 l",
  najcenejsa_ponudba: {
    trgovina_id: 1,
    ime_trgovina: "Tržnica",
    cena: "1.60",
    datum_zajema: "2026-09-19",
  },
  ponudbe: [
    {
      trgovina_id: 1,
      ime_trgovina: "Tržnica",
      cena: "1.60",
      datum_zajema: "2026-09-19",
    },
    {
      trgovina_id: 2,
      ime_trgovina: "Druga trgovina",
      cena: "1.75",
      datum_zajema: "2026-09-19",
    },
  ],
}];
const categoryTree = [{
  id: 10,
  slug: "hlajeno",
  name: "Hlajeno",
  product_count: 8,
  children: [{
    id: 11,
    slug: "mlecni-izdelki",
    name: "Mlečni izdelki",
    product_count: 5,
    children: [],
  }],
}, {
  id: 20,
  slug: "pekarna",
  name: "Pekarna",
  product_count: 3,
  children: [],
}];
const productPage = {
  items: products,
  total: 1,
  offset: 0,
  limit: 24,
  categories: ["Mlečni izdelki"],
  category_tree: categoryTree,
};
const comparison = {
  celoten_nakup_na_voljo: true,
  cene_po_trgovinah: [{ ime_trgovina: "Tržnica", skupna_cena: "3.20" }],
  najcenejsa_trgovina: "Tržnica",
  prihranek: "0.80",
  razdeljen_seznam: [
    {
      izdelek_id: 7,
      ime_izdelek: "Mleko",
      ime_trgovina: "Tržnica",
      cena_na_enoto: "1.60",
      kolicina: 2,
      skupna_cena: "3.20",
    },
  ],
  skupna_cena_razdeljeno: "3.20",
  dodatni_prihranek: "0.00",
};

const splitComparison = {
  ...comparison,
  celoten_nakup_na_voljo: false,
  cene_po_trgovinah: [],
  najcenejsa_trgovina_id: null,
  najcenejsa_trgovina: null,
  prihranek: null,
  dodatni_prihranek: null,
};

function json(data: unknown, status = 200) {
  return Response.json(data, { status });
}

function requestPath(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
}

describe("ShoppingApp", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) return json(productPage);
      if (path === "/api/backend/auth/me") return json({ message: "Niste prijavljeni." }, 401);
      if (path === "/api/backend/primerjava") return json(comparison);
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("exposes labels, changes a positive quantity, and sends quantities to comparison", async () => {
    const user = userEvent.setup();
    render(<ShoppingApp />);

    const checkbox = await screen.findByRole("checkbox", { name: /Mleko/ });
    await user.click(checkbox);
    const quantity = screen.getByRole("spinbutton", { name: "Količina za Mleko" });
    expect(quantity).toHaveValue(1);
    await user.click(screen.getByRole("button", { name: "Povečaj količino: Mleko" }));
    expect(quantity).toHaveValue(2);

    await user.click(screen.getByRole("button", { name: "Primerjaj cene" }));
    const resultsHeading = await screen.findByRole("heading", { name: "Vaš najugodnejši nakup" });
    expect(resultsHeading).toBeInTheDocument();
    await waitFor(() => expect(resultsHeading).toHaveFocus());
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent("Primerjava cen je končana.");

    const compareCall = vi.mocked(fetch).mock.calls.find(([input]) => requestPath(input) === "/api/backend/primerjava");
    expect(JSON.parse(String(compareCall?.[1]?.body))).toEqual({
      items: [{ izdelek_id: 7, kolicina: 2 }],
      trgovina_ids: [1, 2],
    });
  });

  it("filters by store and exposes the cheapest offer details", async () => {
    const user = userEvent.setup();
    render(<ShoppingApp />);

    const product = await screen.findByRole("checkbox", { name: /Mleko/ });
    expect(product).toHaveAccessibleDescription(/Aktualne cene.*Tržnica.*1,60.*Druga trgovina.*1,75/);
    await user.click(screen.getByRole("checkbox", { name: "Druga trgovina" }));
    await user.click(await screen.findByRole("checkbox", { name: /Mleko/ }));
    await user.click(screen.getByRole("button", { name: "Primerjaj cene" }));

    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.some(([input]) => requestPath(input) === "/api/backend/primerjava")).toBe(true);
    });
    const compareCall = vi.mocked(fetch).mock.calls.find(([input]) => requestPath(input) === "/api/backend/primerjava");
    expect(JSON.parse(String(compareCall?.[1]?.body)).trgovina_ids).toEqual([1]);
    expect(screen.getByText("1 od 2 trgovin v primerjavi.")).toBeInTheDocument();
  });

  it("selects parent and subcategories by id and displays their product counts", async () => {
    const user = userEvent.setup();
    render(<ShoppingApp />);

    const topLevel = await screen.findByRole("combobox", { name: "Glavna kategorija" });
    expect(screen.getByRole("option", { name: "Vse kategorije (11)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Hlajeno (8)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Pekarna (3)" })).toBeInTheDocument();

    await user.selectOptions(topLevel, "10");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("kategorija_id=10"),
      expect.anything(),
    ));
    const subcategory = screen.getByRole("combobox", { name: "Podkategorija" });
    expect(screen.getByRole("option", { name: "Vse v Hlajeno (8)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Mlečni izdelki (5)" })).toBeInTheDocument();

    await user.selectOptions(subcategory, "11");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("kategorija_id=11"),
      expect.anything(),
    ));
    expect(topLevel).toHaveValue("10");
    expect(subcategory).toHaveValue("11");
    expect(screen.getByText("Hlajeno / Mlečni izdelki · 1 l")).toBeInTheDocument();
  });

  it("resets a category that disappears from a refreshed tree without looping", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) {
        if (path.includes("q=novo")) {
          return json({
            ...productPage,
            items: [],
            total: 0,
            category_tree: [{
              id: 20,
              slug: "pekarna",
              name: "Pekarna",
              product_count: 3,
              children: [],
            }],
          });
        }
        return json(productPage);
      }
      if (path === "/api/backend/auth/me") return json({ message: "Niste prijavljeni." }, 401);
      throw new Error(`Unexpected request: ${path}`);
    });

    const user = userEvent.setup();
    render(<ShoppingApp />);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Glavna kategorija" }), "10");
    await user.type(screen.getByRole("searchbox", { name: "Išči med izdelki" }), "novo");

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "Glavna kategorija" })).toHaveValue("");
      const matchingCalls = vi.mocked(fetch).mock.calls
        .map(([input]) => requestPath(input))
        .filter((path) => path.includes("q=novo"));
      expect(matchingCalls.some((path) => path.includes("kategorija_id=10"))).toBe(true);
      expect(matchingCalls.at(-1)).not.toContain("kategorija_id");
      expect(matchingCalls.length).toBeLessThanOrEqual(2);
    });
  });

  it("renders legacy category text when new catalog fields are absent", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) return json({
        ...productPage,
        items: [{ id: 9, ime: "Žemlja", kategorija: "Pekarna", enota: "kos" }],
        category_tree: undefined,
      });
      if (path === "/api/backend/auth/me") return json({ message: "Niste prijavljeni." }, 401);
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ShoppingApp />);
    expect(await screen.findByText("Pekarna · kos")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Glavna kategorija" })).toBeDisabled();
  });

  it("clears selected products when the store selection changes", async () => {
    const user = userEvent.setup();
    render(<ShoppingApp />);

    await user.click(await screen.findByRole("checkbox", { name: /Mleko/ }));
    expect(screen.getByText("Izbranih izdelkov").nextSibling).toHaveTextContent("1");
    await user.click(screen.getByRole("checkbox", { name: "Druga trgovina" }));

    expect(screen.getByText("Izbranih izdelkov").nextSibling).toHaveTextContent("0");
    expect(screen.getByText("Izbor izdelkov je bil zaradi spremembe trgovin počiščen.")).toBeInTheDocument();
  });

  it("logs in and saves the selected list atomically", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) return json(productPage);
      if (path === "/api/backend/auth/me") {
        const loginAlreadySent = vi.mocked(fetch).mock.calls.some(([item]) => requestPath(item) === "/api/backend/auth/login");
        return loginAlreadySent ? json({ id: 2, email: "ana@example.com" }) : json({ message: "Niste prijavljeni." }, 401);
      }
      if (path === "/api/backend/auth/login") return json({ ok: true });
      if (path === "/api/backend/seznami" && init?.method === "POST") {
        return json({ id: 9, ime: "Vikend", ustvarjen: "2026-09-18T10:00:00Z" }, 201);
      }
      if (path === "/api/backend/seznami") return json([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    const user = userEvent.setup();
    render(<ShoppingApp />);
    await user.click(await screen.findByRole("checkbox", { name: /Mleko/ }));
    await user.click(screen.getByRole("button", { name: /^Prijava/ }));
    await user.type(screen.getByRole("textbox", { name: "E-poštni naslov" }), "ana@example.com");
    await user.type(screen.getByLabelText("Geslo"), "varno-geslo");
    await user.click(screen.getByRole("button", { name: "Prijavi me" }));

    expect(await screen.findByText("ana@example.com")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Ime seznama" }), "Vikend");
    await user.click(screen.getByRole("button", { name: "Shrani seznam" }));
    expect(await screen.findByText("Seznam »Vikend« je shranjen.")).toBeInTheDocument();

    const saveCall = vi.mocked(fetch).mock.calls.find(
      ([input, init]) => requestPath(input) === "/api/backend/seznami" && init?.method === "POST",
    );
    expect(JSON.parse(String(saveCall?.[1]?.body))).toEqual({
      ime: "Vikend",
      items: [{ izdelek_id: 7, kolicina: 1 }],
    });
  });

  it("invalidates a late comparison when the quantity changes", async () => {
    let resolveComparison: ((response: Response) => void) | undefined;
    const pendingComparison = new Promise<Response>((resolve) => {
      resolveComparison = resolve;
    });
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) return json(productPage);
      if (path === "/api/backend/auth/me") return json({ message: "Niste prijavljeni." }, 401);
      if (path === "/api/backend/primerjava") return pendingComparison;
      throw new Error(`Unexpected request: ${path}`);
    });

    const user = userEvent.setup();
    render(<ShoppingApp />);
    await user.click(await screen.findByRole("checkbox", { name: /Mleko/ }));
    await user.click(screen.getByRole("button", { name: "Primerjaj cene" }));
    await user.click(screen.getByRole("button", { name: "Povečaj količino: Mleko" }));
    resolveComparison?.(json(comparison));

    await waitFor(() => expect(screen.getByRole("spinbutton", { name: "Količina za Mleko" })).toHaveValue(2));
    await Promise.resolve();
    await Promise.resolve();
    expect(screen.queryByRole("heading", { name: "Vaš najugodnejši nakup" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Primerjaj cene" })).toBeEnabled();
  });

  it("renders a split result when no store carries the complete basket", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) return json(productPage);
      if (path === "/api/backend/auth/me") return json({ message: "Niste prijavljeni." }, 401);
      if (path === "/api/backend/primerjava") return json(splitComparison);
      throw new Error(`Unexpected request: ${path}`);
    });

    const user = userEvent.setup();
    render(<ShoppingApp />);
    await user.click(await screen.findByRole("checkbox", { name: /Mleko/ }));
    await user.click(screen.getByRole("button", { name: "Primerjaj cene" }));

    expect(await screen.findByText("Ni na voljo")).toBeInTheDocument();
    expect(screen.getByText("Najugodnejša razdelitev po trgovinah.")).toBeInTheDocument();
  });

  it("shows an API failure and successfully retries the catalog", async () => {
    let productAttempts = 0;
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) {
        productAttempts += 1;
        return productAttempts === 1 ? json({ detail: "Napaka" }, 500) : json(productPage);
      }
      if (path === "/api/backend/auth/me") return json({ message: "Niste prijavljeni." }, 401);
      throw new Error(`Unexpected request: ${path}`);
    });

    const user = userEvent.setup();
    render(<ShoppingApp />);
    expect(await screen.findByRole("heading", { name: "Izdelkov ni bilo mogoče naložiti" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Poskusi znova" }));
    expect(await screen.findByRole("checkbox", { name: /Mleko/ })).toBeInTheDocument();
  });

  it("makes failed and empty store loading retryable", async () => {
    let storeAttempts = 0;
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) {
        storeAttempts += 1;
        return json(storeAttempts === 1 ? [] : stores);
      }
      if (path.startsWith("/api/backend/izdelki")) return json(productPage);
      if (path === "/api/backend/auth/me") return json({ message: "Niste prijavljeni." }, 401);
      throw new Error(`Unexpected request: ${path}`);
    });

    const user = userEvent.setup();
    render(<ShoppingApp />);
    expect(await screen.findByRole("heading", { name: "Izdelkov ni bilo mogoče naložiti" })).toBeInTheDocument();
    expect(screen.getAllByText("Trgovine trenutno niso na voljo.").length).toBeGreaterThan(0);
    await user.click(screen.getAllByRole("button", { name: "Poskusi znova" })[0]);
    expect(await screen.findByRole("checkbox", { name: /Mleko/ })).toBeInTheDocument();
  });

  it("limits search input to 100 characters", async () => {
    const user = userEvent.setup();
    render(<ShoppingApp />);
    const search = await screen.findByRole("searchbox", { name: "Išči med izdelki" });
    await user.type(search, "x".repeat(101));
    expect(search).toHaveValue("x".repeat(100));
    expect(search).toHaveAttribute("maxlength", "100");
  });

  it("surfaces a failed session check and allows retry", async () => {
    let sessionAttempts = 0;
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) return json(productPage);
      if (path === "/api/backend/auth/me") {
        sessionAttempts += 1;
        return sessionAttempts === 1
          ? json({ message: "Storitev trenutno ni dosegljiva." }, 503)
          : json({ message: "Niste prijavljeni." }, 401);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    const user = userEvent.setup();
    render(<ShoppingApp />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Prijave ni bilo mogoče preveriti");
    await user.click(screen.getByRole("button", { name: "Poskusi znova" }));
    expect(await screen.findByRole("button", { name: /^Prijava/ })).toBeInTheDocument();
  });

  it("becomes logged out when loading lists returns 401", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) return json(productPage);
      if (path === "/api/backend/auth/me") return json({ id: 2, email: "ana@example.com" });
      if (path === "/api/backend/seznami") return json({ message: "Niste prijavljeni." }, 401);
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ShoppingApp />);
    expect(await screen.findByRole("button", { name: /^Prijava/ })).toBeInTheDocument();
    expect(screen.queryByText("ana@example.com")).not.toBeInTheDocument();
  });

  it("retains the logged-in state and reports a failed logout", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) return json(productPage);
      if (path === "/api/backend/auth/me") return json({ id: 2, email: "ana@example.com" });
      if (path === "/api/backend/seznami") return json([]);
      if (path === "/api/backend/auth/logout") return json({ message: "Odjava ni uspela." }, 503);
      throw new Error(`Unexpected request: ${path}`);
    });

    const user = userEvent.setup();
    render(<ShoppingApp />);
    await user.click(await screen.findByRole("button", { name: "Odjava" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Odjava ni uspela.");
    expect(screen.getByText("ana@example.com")).toBeInTheDocument();
    expect(screen.queryByText("Uspešno ste se odjavili.")).not.toBeInTheDocument();
  });

  it("treats the auth panel as a keyboard dialog and restores focus", async () => {
    const user = userEvent.setup();
    render(<ShoppingApp />);
    const trigger = await screen.findByRole("button", { name: /^Prijava/ });
    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "Dobrodošli nazaj" })).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "E-poštni naslov" }), "ana@example.com");
    await user.type(screen.getByLabelText("Geslo"), "skrivnost");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(trigger);
    expect(screen.getByRole("textbox", { name: "E-poštni naslov" })).toHaveValue("");
    expect(screen.getByLabelText("Geslo")).toHaveValue("");
  });

  it("keeps selected products while moving between catalog pages", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const path = requestPath(input);
      if (path.startsWith("/api/backend/trgovine")) return json(stores);
      if (path.startsWith("/api/backend/izdelki")) {
        const secondPage = path.includes("offset=24");
        return json({
          items: secondPage
            ? [{ id: 8, ime: "Kruh", kategorija: "Pekarna", enota: "kos" }]
            : products,
          total: 25,
          offset: secondPage ? 24 : 0,
          limit: 24,
           categories: ["Mlečni izdelki", "Pekarna"],
           category_tree: categoryTree,
         });
      }
      if (path === "/api/backend/auth/me") return json({ message: "Niste prijavljeni." }, 401);
      throw new Error(`Unexpected request: ${path}`);
    });

    const user = userEvent.setup();
    render(<ShoppingApp />);
    await user.click(await screen.findByRole("checkbox", { name: /Mleko/ }));
    await user.click(screen.getByRole("button", { name: "Naslednja" }));
    await user.click(await screen.findByRole("checkbox", { name: /Kruh/ }));

    expect(screen.getByText("Izbranih izdelkov").nextSibling).toHaveTextContent("2");
  });
});
