# detoate — casa de marcat a magazinului detoatemarket

Aplicația de vânzare a unui singur magazin alimentar, pe un calculator Windows
cu ecran tactil și o casă de marcat **Tremol** (în modul imprimantă fiscală).
Casierul vinde din browser; aplicația ține catalogul, bonurile și rapoartele și
trimite fiecare bon la casa de marcat, care îl tipărește și îl înregistrează
fiscal.

Documentul e scris pentru cine lucrează pe cod: cum e făcută aplicația, de ce
e făcută așa și ce s-a învățat pe casa de marcat reală. Instalarea și folosirea
în magazin (pas cu pas, pentru personal) sunt în
[deploy/windows/README.md](deploy/windows/README.md). Ce s-a schimbat și când:
[CHANGELOG.md](CHANGELOG.md).

**Starea la 3 noiembrie 2026:** aplicația rulează în magazin ca `detoate.exe`;
casa Tremol de pe COM5 a emis bonul de test (numerar) din aplicație. Încă
neîncercate pe casa reală: plata cu cardul, bonul cu CUI și rapoartele X/Z —
vezi [Limitări cunoscute](#16-limitări-cunoscute-și-ce-urmează).

## Cuprins

1. [Ce face aplicația](#1-ce-face-aplicația)
2. [Cum arată sistemul](#2-cum-arată-sistemul)
3. [Structura proiectului](#3-structura-proiectului)
4. [Pornire pe un calculator de dezvoltare](#4-pornire-pe-un-calculator-de-dezvoltare)
5. [Teste](#5-teste)
6. [Regulile de bază ale codului](#6-regulile-de-bază-ale-codului)
7. [Baza de date](#7-baza-de-date)
8. [API](#8-api)
9. [Fluxul unei vânzări](#9-fluxul-unei-vânzări)
10. [Rapoarte](#10-rapoarte)
11. [Import și export Excel / CSV](#11-import-și-export-excel--csv)
12. [Casa de marcat Tremol](#12-casa-de-marcat-tremol)
13. [Setări](#13-setări)
14. [În magazin: detoate.exe](#14-în-magazin-detoateexe)
15. [Decizii luate](#15-decizii-luate)
16. [Limitări cunoscute și ce urmează](#16-limitări-cunoscute-și-ce-urmează)

---

## 1. Ce face aplicația

Patru ecrane, cu taburile din bara de sus:

| Ecran | Ce face |
|---|---|
| **Casa** | Vânzarea. Căutare după cod, nume sau cod de bare (scanner); produsele la bucată ca plăci mari; butonul **La kilogram** cu greutatea tastată pe tastatura de pe ecran. Bonul curent în dreapta: −/+ pe fiecare linie, atingerea unei linii deschide editorul (cantitate și, pe două file, **Modificare preț** și **Reducere (%)**, care se combină: 120 → preț nou 100 → −30% → 70), cumpărător firmă (CUI), anulare bon. Plata: **Numerar** (F8, cu bancnote și rest) sau **Card** (F9). |
| **Bonuri** | Bonurile plătite și anulate, pe zile; căutare după numărul bonului fiscal, al comenzii sau după CUI; detaliul unui bon (linii, plată, rest, firmă, raport Z). Doar citire. |
| **Produse** | Catalogul produselor la bucată (adăugare, modificare, ștergere — sau dezactivare, dacă produsul are istoric); **prețul unic pe kilogram**; import și export Excel / CSV. |
| **Rapoarte** | Vânzări pe perioadă (total, numerar / card, TVA, pe categorii, pe zile, cele mai vândute produse, export Excel); rapoartele fiscale **X**, **Z** și raportul pe perioadă din memoria fiscală, cu jurnalul lor. |

Scurtături la casă: `Enter` caută / adaugă, `3*200` + Enter = 3 bucăți din
produsul cu codul 200, `1,25*KG` + Enter = 1,250 kg la prețul pe kilogram,
F8 / F9 = plata, `Esc` închide un dialog.

**Ce NU face, intenționat** (vezi [Decizii luate](#15-decizii-luate)):
recepția mărfii cu ecran propriu, clienți salvați, mai multe cote TVA, mai
multe case sau calculatoare, utilizatori și parole.

## 2. Cum arată sistemul

```
calculatorul casei (Windows, ecran tactil)
┌───────────────────────────────────────────────────────────────────────────┐
│  Browser  ──►  http://127.0.0.1:5000                                       │
│                     │  interfața (Vue) + API-ul /api/...                   │
│                     ▼                                                      │
│  detoate.exe  (un singur proces, pornit odată cu Windows)                  │
│    serve.py    serverul web waitress, jurnalul, copiile de siguranță      │
│    app.py      Flask: rutele /api (routes/*.py) și interfața construită   │
│    database.py SQLite — un singur fișier, detoate.db                      │
│    fiscal.py   „casa de marcat” pentru restul aplicației: simulare/Tremol │
│    tremol.py   protocolul Tremol ZFP, direct pe portul COM                │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │ cablu USB = port COM virtual (ex. COM5)
                                   ▼
                          casa de marcat Tremol
```

- **Un proces, o casă, un calculator.** Toate modificările de bonuri trec pe
  rând printr-un singur lock (`routes/orders.orders_lock`), deci un dublu-clic
  pe „Plătește” nu poate tipări două bonuri.
- **Doar local.** Serverul ascultă numai pe `127.0.0.1`, fără parolă și fără
  CORS: interfața și API-ul sunt pe aceeași origine (în dezvoltare, prin
  proxy-ul Vite).
- **Fără driverul Tremol.** `tremol.py` vorbește direct protocolul casei pe
  portul COM. Driverul oficial (ZFPLabServer) nu e necesar și nici nu trebuie
  să ruleze pe același calculator — ține portul ocupat
  ([detalii](#126-zfplabserver-driverul-tremol)).
- **Restul aplicației nu știe ce casă e dedesubt.** Totul trece prin
  `fiscal.send_receipt / daily_report / period_report`; în modul simulare nimic
  nu se tipărește.

În dezvoltare sunt două procese: Vite (interfața, port 5173) și Flask (API-ul,
port 5000); Vite trimite `/api` către Flask.

## 3. Structura proiectului

```
backend/            Python 3.9+ — Flask, SQLite, adaptorul casei, detoate.exe
frontend/           Vue 3 + Vite — interfața
deploy/windows/     construirea lui detoate.exe și ghidul pentru magazin
README.md           acest document
CHANGELOG.md        istoricul modificărilor
```

### backend/

| Fișier | Rol |
|---|---|
| `app.py` | Aplicația Flask: înregistrează rutele, transformă erorile în JSON, `/api/health`, servește interfața construită (`frontend/dist`). Rulat direct = server de dezvoltare. |
| `serve.py` | Pornirea în producție: waitress pe `127.0.0.1:DETOATE_PORT`, jurnal rotativ (`logs/detoate.log`), o copie a bazei la pornire și apoi la câteva ore. |
| `detoate_exe.py` | Intrarea lui `detoate.exe`: citește `config.txt`, alege dosarul de date, pornirea automată cu Windows, comenzile `check-till`, `backup`, `restore`. |
| `database.py` | Schema, crearea și actualizarea bazei (`init_db`), conexiunea pe cerere. Convențiile de stocare sunt scrise în comentariile de la început. |
| `fiscal.py` | Interfața spre casa de marcat: `Receipt` / `SaleLine` intră, `FiscalResult` iese. Alege modul din variabile (simulare / Tremol), ține cota TVA fixă. |
| `tremol.py` | Adaptorul Tremol ZFP: cadre, sume de control, coduri de eroare, `TremolPrinter` (bon, rapoarte), transportul serial. Fără Flask și fără bază de date. |
| `tremol_check.py` | Verificarea casei înainte de prima vânzare (`detoate.exe check-till`). |
| `backup.py` | Copii de siguranță (API-ul de backup SQLite + verificare de integritate), listare, restaurare. |
| `validation.py` | Citirea și validarea câmpurilor din cereri (întregi, texte, date, CUI) — mesajele de eroare în română. |
| `errors.py` | `ApiError`: eroarea pentru utilizator → `{"error": "..."}` cu statusul HTTP. |
| `search.py` | Cheia de căutare: fără diacritice, litere mici (`search_key`). |
| `requirements.txt` | flask, waitress, openpyxl, defusedxml, pyserial. |

| `routes/` | Rute |
|---|---|
| `products.py` | `/api/products` — catalogul la bucată, prețul pe kg (`/kg`), căutarea după cod (`/lookup`), mișcări de stoc. |
| `orders.py` | `/api/orders` — bonul: creare, linii (adăugare, cantitate, reducere, preț nou), cumpărător, anulare, **plata** (emite bonul fiscal). |
| `fiscal.py` | `/api/fiscal` — modul casei, rapoartele X / Z / pe perioadă și jurnalul lor. |
| `reports.py` | `/api/reports/sales` — raportul de vânzări. |
| `excel.py` | `/api/excel` — import catalog (.xlsx / .csv), export catalog și vânzări. |

| `tests/` | Ce acoperă |
|---|---|
| `helpers.py` | Bază de test temporară, client Flask, utilitare. |
| `fake_tremol.py` | **O casă Tremol falsă, la nivel de octeți**, scrisă după PDF-ul protocolului, independent de `tremol.py` — cu defecte la cerere (vezi [Teste](#5-teste)). |
| `test_tremol.py` | Cadre, coduri de eroare, bonul complet, recuperarea după legătura pierdută, câmpurile cu lungime fixă. |
| `test_tremol_check.py` | Verificarea casei (`check-till`), pas cu pas. |
| `test_fiscal.py`, `test_fiscal_reports.py` | Alegerea modului, rapoartele X / Z / perioadă. |
| `test_orders.py`, `test_payment.py` | Bonul, liniile, reducerea, prețul nou, plata, stocul la plată. |
| `test_products.py`, `test_stock.py` | Catalogul, prețul pe kg, mișcările de stoc. |
| `test_excel.py`, `test_reports.py` | Import / export, raportul de vânzări. |
| `test_schema.py`, `test_foundation.py` | Schema, migrările, bazele vechi, convențiile. |
| `test_production.py`, `test_exe.py` | Serverul de producție, copiile de siguranță, `config.txt`, comenzile exe-ului. |

### frontend/src/

| Fișier | Rol |
|---|---|
| `main.js`, `App.vue` | Pornirea; bara de sus (logo, taburi, avertismentul casei); navigarea prin `#casa`, `#bonuri`, `#produse`, `#rapoarte`. |
| `api.js` | Toate apelurile către backend, într-un singur loc. |
| `store.js` | Bonul curent și starea casei, comune tuturor componentelor; **o coadă**: acțiunile pe bon rulează strict pe rând (scanări rapide nu se încurcă). |
| `money.js` | Bani și cantități: formatare, citire „12,50”, tastatura numerică (`applyKey`), totalul liniei și reducerea — **identic cu backend-ul**. Teste în `money.test.js`. |
| `style.css` | Culorile și fontul detoatemarket (Poppins inclus în aplicație, merge fără internet), mărimile pentru ecran tactil. |
| `views/` | `CashierView` (Casa), `ReceiptsView` (Bonuri), `ProductsView` (Produse), `ReportsView` (Rapoarte). |
| `components/` | `CartPanel` (bonul), `LineEditor` (linia: cantitate, reducere, preț nou), `ProductBrowser` (căutare + plăci), `QuantityDialog` (greutatea la kg), `PaymentDialog` (plata), `ProductEditor`, `KgPricePanel`, `ExcelPanel`, `BarTable` (grafice), `NumPad`, `SegmentedControl` (file), `AppDialog`, `Icon`. |

### deploy/windows/

| Fișier | Rol |
|---|---|
| `README.md` | Ghidul pentru magazin: construire, instalare, verificarea casei, zilnic, copii, probleme. |
| `build-exe.bat` | Construiește `dist\detoate.exe` pe Windows (interfața cu Node.js, apoi PyInstaller într-un mediu Python separat). |
| `detoate.spec` | Rețeta PyInstaller: backend-ul + `frontend/dist`, un singur fișier, cu fereastră de consolă. |

## 4. Pornire pe un calculator de dezvoltare

Necesar: **Python 3.9+** și **Node.js 22+**.

```
cd backend
python3 -m pip install -r requirements.txt     # prima dată
DETOATE_DB_PATH=dev.db DETOATE_FISCAL_SIMULATE=1 python3 app.py
```

- `DETOATE_FISCAL_SIMULATE=1` — **modul simulare**: plățile reușesc, dar nimic
  nu se tipărește; bonul apare în jurnalul serverului, cu numărul `SIM-<comandă>`,
  iar sus apare banda galbenă *MOD SIMULARE*.
- `dev.db` pornește **goală**, ca în magazin: setați prețul în *Produse → La
  kilogram* și adăugați câteva produse. Pentru o bază nouă, ștergeți `dev.db`
  (și `dev.db-wal`, `dev.db-shm`).

Interfața, în alt terminal:

```
cd frontend
npm install        # prima dată
npm run dev
```

Apoi <http://localhost:5173>.

**Ca în magazin**, fără Vite: `cd frontend && npm run build`, apoi
`cd backend && DETOATE_DB_PATH=dev.db DETOATE_FISCAL_SIMULATE=1 python3 serve.py`
→ <http://127.0.0.1:5000>.

## 5. Teste

```
cd backend && python3 -m unittest      # 265 de teste
cd frontend && npm test                # money.js
```

Un test se sare dacă `waitress` nu e instalat — instalați `requirements.txt`.

**Casa falsă** (`backend/tests/fake_tremol.py`) răspunde ca o casă reală, octet
cu octet, inclusiv sumele de control. Defecte la cerere:

| Atribut | Ce simulează |
|---|---|
| `refuse[cmd] = "04"` | următoarea comandă `cmd` e refuzată cu acești doi octeți de stare |
| `nack_next = n` / `busy_next = n` | următoarele n cadre primesc NACK / RETRY |
| `silent = {cmd}` | comanda se execută, dar răspunsul se pierde (o dată) |
| `vanish = {cmd}` | comanda se execută, apoi portul dispare (cablul USB cade) până la `gone = False` |
| `busy_polls = n` | următoarele n întrebări `09h` primesc `41h` (ocupată, tipărește) |
| `no_units = True` | casa refuză unitatea de măsură în numele articolului |
| `round_down = True` | casa rotunjește liniile în jos (alt total decât aplicația) |
| `unreachable = True` | portul nu se poate deschide |
| `password = "0"` | parola operatorului (casa cere exact 4 caractere: `"0   "`) |

`TremolPrinter(FakeTremol())` merge direct — casa falsă e și transportul.

Scenariile de browser folosite la dezvoltare (puppeteer, ecran tactil emulat
la 1024×768 și 1366×768) **nu sunt în proiect**. Înainte de o versiune nouă,
parcurgeți de mână fluxul din [secțiunea 9](#9-fluxul-unei-vânzări) în modul
simulare.

## 6. Regulile de bază ale codului

Reguli care trebuie păstrate la orice modificare; testele le verifică.

**Bani și cantități — doar numere întregi, niciodată float:**

| Sufix | Unitate | Exemplu |
|---|---|---|
| `*_bani` | bani (1 leu = 100) | 12,50 lei = `1250` |
| `*_milli` | miimi (cantitatea pe bon) | 1,250 kg = `1250`; 3 buc = `3000` |
| `*_qty` | bucăți întregi (stoc) | `12` |
| `*_bp` | sutimi de procent | 12,5% = `1250` |

- **Totalul liniei** = `(quantity_milli * unit_price_bani + 500) // 1000` —
  rotunjit comercial, de la 0,5 bani în sus, **ca pe casa de marcat**.
  Niciodată `round()` din Python (rotunjește 0,5 spre par). Aceeași formulă în
  `routes/orders.line_total_bani` și `money.js / lineTotalBani`.
- **Prețul redus** = `(preț_de_bază * (10000 − discount_bp) + 5000) // 10000`
  (`discounted_price` / `discountedPrice`). Casa primește prețul unitar deja
  redus, deci totalul de pe bon iese identic cu cel din aplicație.
- Conversia în zecimale („12.99”, „1.250”) se face **doar** în `tremol.py`.

**Prețul unei linii** are două părți, care se combină. Exemplu: produsul A are
120 lei în catalog; casierul îi dă prețul nou 100, apoi o reducere de 30%, iar
pe bon iese **70 lei**.

| Coloana | Ce ține | Exemplul |
|---|---|---|
| `list_price_bani` | prețul din catalog în momentul adăugării; nu se mai schimbă | 12000 |
| `manual_price_bani` | prețul nou tastat la *Modificare preț*; `NULL` = nu e | 10000 |
| `discount_bp` | reducerea (0–99,99%), aplicată prețului de bază | 3000 |
| `unit_price_bani` | prețul încasat = prețul de bază minus reducerea | **7000** |
| `price_overridden` | calculat (coloană în bază + API): linia nu e la prețul din catalog | da |

- **Prețul de bază** este `manual_price_bani`, dacă există; altfel
  `list_price_bani`.
- **Fără reduceri în lanț:** schimbată la 20%, reducerea dă 80 (tot din 100),
  nu 56 (din 70).
- **Ordinea nu contează:** întâi 30%, apoi prețul nou 100 dă tot 70.
- **Fiecare parte se schimbă separat.** `manual_price_bani: null` întoarce linia
  la prețul din catalog, minus reducerea; `discount_bp: 0` scoate reducerea,
  dar păstrează prețul nou. *Preț din catalog* le scoate pe amândouă.
- **Catalogul nu se atinge:** produsul rămâne la 120 lei pentru bonul următor.
- **Casa primește doar prețul final** (70). Pe bon nu apare un rând separat de
  reducere.
- **Limite:** o reducere care ar duce prețul la 0 lei e refuzată; prețul nou e
  între 0,01 și 999.999,99 lei.

**Categorii.** Există exact două, fixe: **La bucată** și **La kilogram** —
câmpul `sale_type` (`unit` / `weight`) al produsului, copiat pe linia de bon.
Numele lor sunt în `routes/products.CATEGORY_NAMES`. Nu există raioane.

**Vânzarea la kilogram.** Tot ce se vinde la kg are **un singur preț pe kg**,
oricare ar fi marfa: un rând fix în `products`, codul `KG`, creat de `init_db`
cu prețul 0. Cât timp prețul e 0, vânzarea la kg e refuzată. Se modifică doar
prin `/api/products/kg` (*Produse → La kilogram*). Catalogul propriu-zis are
numai produse la bucată.

**TVA.** O singură cotă: **21%, grupa A** a casei — `fiscal.VAT_GROUP` și
`fiscal.VAT_PERCENT`, fixe în cod. Cota se copiază pe fiecare linie, deci o
schimbare viitoare nu atinge bonurile vechi. `check-till` verifică faptul că
grupa A de pe casă are exact această cotă.

**Bonul e un instantaneu.** Numele, prețul, tipul și TVA-ul se copiază pe linie
la adăugare; cumpărătorul se copiază pe comandă la plată. Schimbările ulterioare
din catalog nu modifică bonurile.

**Stocul.**
- Se mișcă doar prin `stock_movements`; un trigger ține la zi
  `products.stock_qty`.
- La plată scad numai produsele la bucată; marfa la kg nu scade stocul.
- Stocul poate deveni negativ, intenționat: casa nu se blochează dacă recepția
  nu a fost introdusă.

**Erorile pentru utilizator** sunt `ApiError` → `{"error": "mesaj"}`, cu mesaj
în română, scris pentru casier. Interfața îl afișează așa cum vine.

**Textul trimis la casă:**
- fără diacritice (casa e setată pe o codificare fără ș/ț cu virgulă);
- fără caracterele `;`, `` ` `` și `|`, pe care protocolul le folosește ca
  separatori;
- denumirea are cel mult 30 de caractere (`tremol.encode_text`).

## 7. Baza de date

SQLite, un singur fișier (`detoate.db`), în modul WAL, cu chei străine
verificate. Toată schema e în `database.init_db`.

| Tabel | Ce ține |
|---|---|
| `products` | Catalogul: cod (unic), cod de bare (opțional, unic), nume, `sale_type`, preț, stoc, stoc minim, activ. Plus rândul fix `KG`. |
| `stock_movements` | Registrul de stoc: recepție, vânzare, ajustare, retur, anulare (`reason`), în bucăți. Sursa de adevăr pentru stoc. |
| `orders` | Bonul: `pending` (coș deschis) → `paid` (bon emis pe casă) sau `cancelled`. Plata, numărul bonului fiscal, numărul raportului Z, `fiscal_simulated`, cumpărătorul copiat. |
| `order_items` | Liniile bonului (vezi [Prețul unei linii](#6-regulile-de-bază-ale-codului)). |
| `fiscal_reports` | Jurnalul rapoartelor X / Z / pe perioadă: totalurile aplicației și, în `response_json`, ce a raportat casa. |
| `customers` | Există în schemă, dar nu are ecran — CUI-ul se tastează pe bon (vezi Decizii). |

**Actualizarea schemei.** `init_db` rulează la fiecare pornire și aduce o bază
mai veche la zi. Regula pentru modificări:

- **doar adăugări** — tabele noi cu `CREATE TABLE IF NOT EXISTS`, coloane noi
  cu `ALTER TABLE ... ADD COLUMN`, după ce s-a verificat cu `pragma_table_info`
  că lipsesc (exemple: `order_items.discount_bp`, `order_items.manual_price_bani`
  — aceasta din urmă completată la adăugare pentru liniile vechi cu preț tastat,
  în aceeași tranzacție);
- **nicio ștergere sau redenumire** de coloane — SQLite nu le poate scoate pe
  cele cu chei străine, iar baza din magazin trebuie să meargă mai departe.
  O coloană care nu mai e folosită rămâne în tabel, nefolosită;
- o bază pe care aplicația nu o mai poate folosi e **refuzată la pornire**, cu
  mesaj clar. Exemplu: bazele de probă de dinainte de lansare, care aveau cote
  TVA pe produs (`products.vat_rate_id`).

**Unde stă baza:**

| Mediu | Locul bazei |
|---|---|
| dezvoltare | `DETOATE_DB_PATH`, implicit `backend/detoate.db` |
| magazin | `%LOCALAPPDATA%\detoate\detoate.db`, în afara dosarului exe-ului, deci o versiune nouă nu o atinge |

**Copii de siguranță** (`backup.py`):
- automat, la pornire și apoi la 4 ore, ultimele 60;
- opțional, încă o copie pe stick sau OneDrive (`DETOATE_BACKUP_COPY_DIR`);
- manual, cu `detoate.exe backup`;
- restaurare: trageți copia `.db` peste `detoate.exe`. Baza de dinainte se
  păstrează și ea ca o copie, deci restaurarea se poate desface.

## 8. API

Toate rutele sunt sub `/api`, cu JSON. O eroare întoarce `{"error": "mesaj"}`
cu un status: 400 (date greșite), 404, 409 (comanda nu mai e pending), 502 (casa
a refuzat), 503 (casa nu e disponibilă). Listele au paginarea `limit` / `offset`.

| Metodă și cale | Ce face |
|---|---|
| `GET /api/health` | `{"status": "ok"}` — folosit de exe ca să vadă dacă serverul rulează deja |
| **Produse** | |
| `GET /api/products` | catalogul la bucată; `q` (cod, cod de bare, nume fără diacritice), `active` (1 / 0 / all), `low_stock=1` |
| `GET /api/products/lookup?code=` | produsul activ cu exact acest cod sau cod de bare (`KG` = la kilogram) — scanare |
| `GET/POST /api/products`, `GET/PATCH/DELETE /api/products/<id>` | un produs. La creare: `sale_type` e mereu `unit`, iar stocul se dă în `initial_stock_qty`. Ștergerea e definitivă dacă produsul nu are istoric, altfel produsul doar se dezactivează (`{"deleted": "hard" / "soft"}`) |
| `GET/PATCH /api/products/kg` | denumirea de pe bon și prețul unic pe kg |
| `POST /api/products/<id>/stock` | mișcare manuală: `receipt` (recepție, +) sau `adjustment` (±), în bucăți |
| `GET /api/products/<id>/movements` | registrul de stoc al produsului |
| **Bonuri** | |
| `GET /api/orders` | lista; `status` (ex. `paid,cancelled`), `date_from` / `date_to`, `q` (nr. bon, nr. comandă sau CUI) |
| `POST /api/orders` | bon nou, gol (`pending`) |
| `GET/PATCH /api/orders/<id>` | bonul cu liniile; cumpărătorul (`buyer_type` pf/pj, `buyer_name`, `buyer_cui`) |
| `POST /api/orders/<id>/cancel` | anulează un bon neplătit |
| `POST /api/orders/<id>/items` | `{product_id, quantity_milli}` — același produs, la același preț și fără reducere, se adună pe linia existentă |
| `PATCH /api/orders/<id>/items/<item>` | `quantity_milli`, `manual_price_bani` (sau `null` = fără preț nou), `discount_bp` — oricare, și împreună; ce nu se trimite rămâne cum era |
| `DELETE /api/orders/<id>/items/<item>` | șterge linia |
| `POST /api/orders/<id>/pay` | `{payment_method: cash / card, cash_received_bani?}` — emite bonul fiscal; întoarce comanda și restul (`change_bani`) |
| **Casa de marcat** | |
| `GET /api/fiscal/status` | modul (`simulate` / `tremol` / `none` / `conflict`) și problema de afișat |
| `GET /api/fiscal/unreported` | ce ar cuprinde un Z acum (bonuri plătite, neincluse încă într-un Z) |
| `GET/POST /api/fiscal/reports` | jurnalul; un raport nou: `{type: X}`, `{type: Z}` sau `{type: period, date_from, date_to}` |
| **Rapoarte și Excel** | |
| `GET /api/reports/sales` | vânzările din perioadă: totaluri, TVA, pe categorii, pe zile, top produse |
| `POST /api/excel/products` | import catalog (.xlsx / .csv), totul sau nimic |
| `GET /api/excel/products` | exportul catalogului (gol = șablon) |
| `GET /api/excel/sales` | exportul vânzărilor: foaia „Bonuri” și foaia „Linii” |

## 9. Fluxul unei vânzări

1. **Primul produs** atins sau scanat creează bonul (`POST /api/orders`), apoi
   linia (`POST .../items`). Interfața ține bonul curent în `store.js`; după o
   repornire îl reia (bonul `pending` cel mai recent).
2. **Liniile** se schimbă din −/+ sau din editorul liniei (`PATCH .../items/<id>`).
3. **Plata** (`POST .../pay`), totul sub `orders_lock`:
   1. verificări: bonul are linii, suma primită acoperă totalul;
   2. se construiește `fiscal.Receipt` (liniile cu prețul final, plata,
      CUI-ul);
   3. `fiscal.send_receipt` → `tremol.TremolPrinter.send_receipt`, care
      trimite pe rând comenzile casei:

      | Comanda | Ce face |
      |---|---|
      | `72h` | e un bon rămas deschis pe casă? Dacă da și nu are plată, îl anulează (`39h`) |
      | `71h` | numărul ultimului bon, ca să se recunoască un bon emis, dacă legătura cade |
      | `30h` | deschide bonul (operator, parolă; cu CUI, varianta cu cumpărător) |
      | `31h` | câte una pentru fiecare linie |
      | `33h` | subtotalul calculat de casă — dacă diferă de cel din aplicație, bonul se anulează |
      | `35h` | plata: numerar, cu suma primită, sau card, cu suma exactă |
      | `38h` | închide bonul |
      | `71h` | numărul bonului emis |

      Înaintea fiecărei comenzi, aplicația așteaptă până casa nu mai e
      ocupată cu tipărirea (`09h` → `41h` = ocupată);
   4. dacă bonul s-a emis: comanda devine `paid`, cu numărul bonului, iar
      produsele la bucată scad din stoc.
4. **Când ceva nu merge:**

   | Situația | Ce se întâmplă |
   |---|---|
   | Casa refuză o comandă **înainte de plată** | Bonul se anulează pe casă și comanda rămâne `pending`. Casierul vede mesajul casei (status 502) și poate reîncerca. |
   | Casa refuză **închiderea, după plată** | Mesaj explicit: plata e înregistrată pe casă, iar situația se rezolvă pe casă. |
   | **Legătura cade** (cablu, USB, casa repornită) | `TransportError`, apoi status 503. Comanda rămâne „nesigură” în memoria procesului. La reîncercare, dacă bonul apucase să se emită, nu se mai tipărește a doua oară, iar un bon rămas deschis se anulează. |
   | Casa **nu e configurată** sau e configurată **dublu** | Plata e refuzată, cu mesaj (vezi [Setări](#13-setări)). |

## 10. Rapoarte

- **Vânzări** (`/api/reports/sales`, *Rapoarte*): pe bonurile plătite, după
  ziua plății. TVA-ul afișat e cel conținut în total, orientativ — TVA-ul
  oficial e cel de pe raportul Z.
- **X**: situația zilei, fără închidere.
- **Z**: închide ziua fiscală, ireversibil.
  - Totalurile casei se citesc înainte de Z (Z-ul le golește).
  - Bonurile plătite de la Z-ul precedent primesc numărul acestui Z.
  - Jurnalul pune totalul casei lângă cel al aplicației. Un ⚠ înseamnă că s-a
    vândut ceva direct de pe casă, ocolind aplicația.
  - Casa se blochează după 24 de ore fără Z.
- **Pe perioadă**: raport scurt din memoria fiscală, între două date.
- Bonurile din modul simulare au propriile rapoarte și numere de Z; nu se
  amestecă niciodată cu cele reale (`fiscal_simulated`).

## 11. Import și export Excel / CSV

*Produse → Excel*. Fișierul: `.xlsx` (prima foaie) sau `.csv`. Primul rând
conține capetele de tabel, în orice ordine. Diacriticele și literele mari nu
contează.

| Coloana | Nume acceptate | Note |
|---|---|---|
| Cod | „Cod produs”, „PLU” | Fără coloana Cod: produsele se potrivesc după denumire, iar cele noi primesc coduri 1, 2, 3…, după cel mai mare cod existent. |
| Cod de bare | „EAN”, „Barcode” | Celula goală = fără cod de bare. |
| **Denumire** (obligatoriu) | „Nume”, „Produs”, „Denumire produs”, „Nume produs” | |
| **Preț (lei)** (obligatoriu) | „Preț”, „Preț vânzare”, „Preț de vânzare”, „Preț cu TVA”… | „12,50”, „1.234,50” sau 12.5 |
| Stoc (buc) | „Stoc”, „Cantitate”, „Cantitate produs” | Contează doar la produsele noi. |
| Stoc minim, Activ | | Activ: da / nu |

- Lista magazinului (*Denumire Produs, Cantitate Produs, Pret Vanzare*) se
  importă direct.
- **Totul sau nimic:** la orice rând greșit nu se scrie nimic, iar răspunsul
  listează rândurile cu problema lor.
- Un rând marcat „kg” e eroare: la kilogram e un singur preț, setat în aplicație.
- O coloană TVA se ignoră, pentru că TVA-ul e fix.
- CSV-ul: separatorul (`;`, `,` sau tab) și codificarea (UTF-8 sau Windows-1250,
  cum salvează Excel în română) se recunosc singure.
- Exportul catalogului e chiar formatul de import; gol, servește ca șablon.

## 12. Casa de marcat Tremol

### 12.1 Moduri

`fiscal.mode()` alege din variabile; trebuie setat **exact unul** dintre
`DETOATE_FISCAL_SIMULATE` și `DETOATE_TREMOL_PORT`:

| Setat | Mod | Efect |
|---|---|---|
| `DETOATE_FISCAL_SIMULATE=1` | `simulate` | nimic nu se tipărește; banda galbenă *MOD SIMULARE* |
| `DETOATE_TREMOL_PORT=COM5` | `tremol` | casa reală |
| niciuna | `none` | plățile sunt refuzate; banda roșie *Casa de marcat nu este configurată* |
| amândouă | `conflict` | refuzat, ca o greșeală de configurare să nu decidă în tăcere între bonuri reale și simulate |

Implicit **nu** e simulare, intenționat: dacă setarea lipsește în magazin,
plata eșuează, în loc să marcheze bonuri care nu există pe casă.

### 12.2 Verificarea casei: `detoate.exe check-till`

(`python3 tremol_check.py` în dezvoltare.) Pașii 0–8 nu schimbă nimic pe casă:

| Pas | Verifică |
|---|---|
| 0 | fără `--port`: caută casa pe toate porturile COM, la toate vitezele |
| 1 | casa răspunde (`04h`) și e pregătită (`09h`) |
| 2 | starea (`20h`): memorie fiscală, hârtie, blocare de 24 h, bon deschis |
| 3 | modelul, interfețele, codificarea, câte caractere are numele unui articol |
| 4 | grupa A de pe casă are 21% (`62h`) |
| 5 | prețuri cu zecimale (`63h`) |
| 6 | tipurile de plată (`64h`) — care număr e cardul |
| 7 | ultimul bon și ultimul Z (`71h`, `73h`), bon deschis acum (`72h`) |
| 8 | operatorul (`6Ah`): numele și parola lui de pe casă, comparată cu `--password` |
| 9 | doar cu `--bon`, după ce se scrie `DA`: **un bon fiscal real** de 0,10 lei, numerar; cu `--cui`, și CUI-ul cumpărătorului |

Opțiuni: `--port`, `--baud`, `--operator`, `--password` (goală: `--password=`),
`--card-payment`, `--bon`, `--cui`. La final, check-till afișează rândurile de
trecut în `config.txt`.

### 12.3 Protocolul, pe scurt

Sursa este `protocol_description_RO_2601151250.pdf`, din SDK-ul Tremol
(`ZFP_SDK_RO_2601151250`, primit de la producător). SDK-ul **nu e în proiect** —
păstrați-l.

```
cerere   02h  LEN  NBL  CMD  DATA…  CS CS  0Ah
           LEN = octeții LEN+NBL+CMD+DATA, plus 20h
           NBL = numărul mesajului plus 20h; fiecare comandă nouă are alt NBL
                 (același NBL = retransmisie, casa nu o execută a doua oară)
           CS  = XOR pe LEN…DATA, cele două jumătăți plus 30h
răspuns  ACK   06h NBL STE1 STE2 CS CS 0Ah    "00" = executată
         date  02h LEN NBL CMD DATA… CS CS 0Ah
         NACK  15h (cadru stricat, se retrimite) · RETRY 0Eh (ocupată)
mesaje de un octet: 04h → 04h (pornită) · 09h → 40h pregătită, 41h ocupată, 42h fără hârtie…
```

**Codurile de eroare** sunt cele două caractere de stare din răspunsul casei:
- primul (STE1) e starea casei;
- al doilea (STE2) e problema comenzii.

Aplicația le traduce în mesaj și adaugă codul brut, de exemplu
`(comanda 30h, cod 92)`. Cele întâlnite pe casa din magazin:

| Cod | Înseamnă |
|---|---|
| `92` | 9 = parolă greșită, 2 = comandă nepermisă (operatorul sau parola) |
| `04` | 0 = casa e în regulă, 4 = eroare de sintaxă (formatul datelor) |
| `00` | executată |

Tabelul complet: `tremol.FPR_ERRORS` / `COMMAND_ERRORS` (PDF 1.2.1).

### 12.4 Ce s-a învățat pe casa reală (octombrie 2026)

Lucrurile de mai jos nu se văd clar în PDF și au costat câteva zile de probe.
Toate sunt acoperite de teste.

1. **Câmpurile cu lungime fixă se completează cu spații.** În PDF, `[4]`
   înseamnă exact 4 caractere, iar `[1..10]` înseamnă între 1 și 10.
   - **Parola operatorului** `<OperPass[4]>`: parola `0` se trimite ca
     `"0   "`. Trimisă ca `"0"`, casa răspunde **cod 92**, parolă greșită.
     (`TremolPrinter._open_data`, `password.ljust(4)`.)
   - **Numele articolului** `<NamePLU[36]>` are 30 de caractere pentru nume,
     separatorul `` ` ``, 3 caractere pentru unitate (buc / kg) și 2 spații.
     Un nume mai scurt dă **cod 04**, eroare de sintaxă (`_sell_data`).
   - Dacă linia cu unitate primește exact 04, aplicația o retrimite doar cu
     numele, completat la 36 de caractere. Dacă așa trece, liniile se trimit
     de atunci fără unitate (`printer.units = False`), iar check-till afișează
     un ATENȚIE.
2. **Parola corectă** a casei din magazin e `0`, pentru operatorul 1. Producătorul
   a spus întâi „0”, apoi „fără parolă”; numai `"0   "` a mers. Parola goală
   (patru spații) e refuzată.
3. **`6Ah`, citirea operatorului:** casa din magazin adaugă un `;` la sfârșitul
   răspunsului. Câmpurile se citesc după poziție (număr; nume; parolă). Alte
   case întorc parola goală, adică o ascund; atunci check-till doar avertizează.
4. **Așteptarea cât casa tipărește.** După o comandă care tipărește, casa
   răspunde `41h` (ocupată) la `09h`. Driverul Tremol așteaptă `40h` înainte de
   comanda următoare, iar aplicația face la fel (`_wait_ready`).
5. **Legătura USB poate cădea** în timp ce casa tipărește: portul COM dispare din
   *Manager dispozitive*. S-a întâmplat și cu driverul Tremol. Aplicația
   transformă căderea într-un mesaj clar, nu într-o eroare internă
   (`_session`). La reîncercare anulează bonul rămas deschis. Cauza ține de
   hardware: alimentarea casei, cablul, portul.
6. **Parola goală din linia de comandă:** `--password ""` nu ajunge la program
   din unele ferestre de comenzi (PowerShell). Se scrie `--password=`.
7. **Cum se află formatul corect al unei comenzi:** cu driverul Tremol, o
   singură dată (vezi 12.6). Jurnalul lui arată octeții exacți trimiși casei;
   se compară cu `tremol.build_frame(...)`. Atenție: în jurnal, textul
   „prepared cmd” **începe cu octetul comenzii** — `'01;0   ;0;0;0'` înseamnă
   comanda `0` (= 30h) cu datele `1;0   ;0;0;0`.

### 12.5 Casa din magazin

| | |
|---|---|
| Versiune (`21h`) | `Ver 2.02TRM20-AC` |
| Interfețe | USB, RS232, LAN — folosită: USB, port **COM5** (numărul se poate schimba dacă se mută cablul) |
| Operator / parolă | 1 / `0` → `DETOATE_TREMOL_PASSWORD=0` |
| Plăți | 0 Numerar, **1 Card**, 2 Avans, 3 Tichete, 4 Bonuri, 5 Voucher, 6 Credit, 7 Moderne, 8 Alte, 9 EUR |
| TVA | grupa A = 21% |
| Nume articol | 34 de caractere acceptate (aplicația trimite cel mult 30) |
| Codificare | 1250 (aplicația trimite text fără diacritice) |
| De rezolvat cu dealerul | *SIM neactivat* — transmiterea către ANAF |

### 12.6 ZFPLabServer, driverul Tremol

Un program Tremol care primește comenzi prin HTTP (`localhost:4444`) sau prin
fișiere XML (dosarele `FILE_IN` / `FILE_OUT`) și le trimite casei.
**detoate nu îl folosește.**
- Pornește odată cu Windows și ține portul COM ocupat. Cât rulează, detoate
  nu poate tipări.
- E util o singură dată, ca diagnostic, pentru a afla formatul exact al unei
  comenzi.

Pași pentru diagnostic:
1. instalați-l (`ZFPLabServerSetup.exe` din SDK) și închideți detoate;
2. în browser, `http://localhost:4444/Settings(tcp=0,com=COM5,baud=115200)`;
3. apoi comanda de încercat, de exemplu
   `http://localhost:4444/OpenReceipt(OperNum=1,OperPass=0,OptionFiscalReceiptPrintType=0)`.
   Dacă deschide bonul, anulați-l cu `/CancelReceipt()`;
4. `http://localhost:4444/log` arată octeții trimiși și răspunsul casei;
5. închideți și dezinstalați driverul, apoi porniți detoate.

Definițiile lui, cu octetul fiecărei comenzi și formatul câmpurilor, sunt în
SDK, în `ZFPLABServerLinux/XML/s_<Comanda>.xml`.

**Varianta prin driver, dacă va fi nevoie:**
- s-ar schimba doar adaptorul: `TremolPrinter` ar face apeluri HTTP către
  driver în loc să trimită octeți pe port;
- s-ar adăuga o setare, de exemplu `DETOATE_TREMOL_DRIVER`, în locul portului;
- comenzile driverului (`OpenReceipt`, `SellPLUwithSpecifiedVAT`, `Subtotal`,
  `Payment`, `PayExactSum`, `CloseReceipt`, `CancelReceipt`,
  `ReadCurrentReceiptInfo`, `ReadLastAndTotalReceiptNum`, `PrintDailyReport`…)
  există toate.

Costul: driverul trebuie să ruleze permanent pe calculatorul casei.

## 13. Setări

În dezvoltare, setările sunt variabile de mediu. În magazin stau în
`config.txt`, lângă `detoate.exe`. Exe-ul creează fișierul la prima pornire,
cu explicații, și el se modifică cu Notepad.

| Variabilă | Implicit | Ce face |
|---|---|---|
| `DETOATE_FISCAL_SIMULATE` | gol | `1` = mod simulare. Gol în magazin. |
| `DETOATE_TREMOL_PORT` | gol | portul casei, ex. `COM5` |
| `DETOATE_TREMOL_BAUD` | `115200` | viteza portului |
| `DETOATE_TREMOL_OPERATOR` | `1` | operatorul care deschide bonurile |
| `DETOATE_TREMOL_PASSWORD` | `0000` | parola lui; se trimite completată la 4 caractere. În magazin: `0` |
| `DETOATE_TREMOL_CARD_PAYMENT` | `1` | numărul plății „Card” de pe casă (check-till, pasul 6) |
| `DETOATE_PORT` | `5000` | portul serverului web |
| `DETOATE_DATA_DIR` | `%LOCALAPPDATA%\detoate` (exe) | dosarul datelor |
| `DETOATE_DB_PATH` | `<date>\detoate.db`; în dezvoltare `backend/detoate.db` | baza de date |
| `DETOATE_LOG_DIR` | `logs` lângă bază | jurnalul `detoate.log` (rotativ, 5 × 5 MB) |
| `DETOATE_BACKUP_DIR` | `backups` lângă bază | copiile de siguranță |
| `DETOATE_BACKUP_KEEP` | `60` | câte copii se păstrează |
| `DETOATE_BACKUP_EVERY_HOURS` | `4` | la câte ore se face o copie cât rulează serverul |
| `DETOATE_BACKUP_COPY_DIR` | gol | încă un loc pentru fiecare copie (stick, OneDrive) |
| `DETOATE_AUTOSTART` | `1` | pornirea odată cu Windows (un `.bat` în dosarul *Startup*) |
| `DETOATE_OPEN_BROWSER` | `1` (exe) | deschide casa în browser la pornire |
| `DETOATE_FRONTEND_DIST` | `frontend/dist` | interfața construită (exe-ul o are în interior) |

Cum citește exe-ul `config.txt` (`detoate_exe.load_config`):
- formatul e `CHEIE=valoare`; rândurile cu `#` sunt comentarii;
- un BOM de la Notepad e acceptat;
- o cheie necunoscută e semnalată la pornire, cu numărul rândului;
- o variabilă de mediu deja setată are întâietate;
- **dacă o cheie apare de două ori, contează primul rând** (vezi Limitări).

## 14. În magazin: detoate.exe

Pe calculatorul casei e nevoie de **un singur fișier**, `detoate.exe`, care
conține Python, serverul și interfața. Ghidul complet pentru magazin:
[deploy/windows/README.md](deploy/windows/README.md).

| Comandă | Ce face |
|---|---|
| `detoate.exe` (dublu-clic) | pornește serverul și deschide browserul; dacă rulează deja, doar deschide browserul. Fereastra „detoate - server” *este* aplicația. |
| `detoate.exe check-till [...]` | verificarea casei (12.2) |
| `detoate.exe backup [--list]` | o copie acum, sau lista copiilor |
| `detoate.exe restore FIȘIER` | sau trageți copia `.db` peste exe; cere `DA` |

**Construirea unei versiuni noi**, fără GitHub:
1. copiați proiectul pe un calculator cu Windows, care are Python 3.9+ și,
   opțional, Node.js 22+;
2. rulați `deploy\windows\build-exe.bat`. Rezultatul: `dist\detoate.exe`.
   Fără Node.js, scriptul folosește `frontend\dist` construit dinainte cu
   `npm run build`.

Din Mac, arhiva pentru Windows se face fără `node_modules`, fără bazele `.db`,
fără `dist/` și `build/`.

**Actualizarea în magazin:**
1. închideți fereastra „detoate - server”;
2. înlocuiți `C:\detoate\detoate.exe` cu cel nou;
3. porniți-l.

Datele și `config.txt` rămân. La pornire se face o copie a bazei, iar
`init_db` aduce schema la zi singur.

**Mutarea pe alt calculator:** copiați `%LOCALAPPDATA%\detoate\detoate.db` (sau
o copie din `backups`) în același loc pe calculatorul nou, împreună cu exe-ul și
`config.txt`, apoi rulați check-till, pentru că portul COM poate fi altul.

## 15. Decizii luate

| Decizie | De ce |
|---|---|
| Doar două categorii fixe (La bucată / La kilogram); raioanele au fost scoase | Cerința magazinului; mai simplu la casă. |
| TVA fix 21%, grupa A, fără alegere în aplicație | Cerința magazinului. **De confirmat cu contabilul**: alimentele au de obicei 11%. |
| Un singur preț pe kilogram, pentru orice marfă la kg | Cerința magazinului: la kg se plătește doar prețul pe kg. |
| Fără date demo; baza pornește goală | Pregătire pentru producție. |
| Fără ecran de clienți salvați; CUI-ul se tastează pe bon | Firmele sunt rare la casă. |
| Recepția mărfii — amânată | O va face proprietarul mai târziu; API-ul de stoc există. |
| Linia de bon: preț nou și reducere peste el (`manual_price_bani` + `discount_bp`) | Cerința magazinului (13 noiembrie 2026): 120 → preț nou 100 → −30% → 70 lei. Pe bon apare doar prețul final (varianta A); varianta B — casa tipărește separat rândul de reducere (`DiscAddP` la `31h`) — nu a fost încercată pe casa reală. |
| Un singur `.exe`, construit pe Windows, fără GitHub | Cât mai puține fișiere și pași în magazin. |
| Direct pe portul COM, fără ZFPLabServer | Un program în loc de două, nimic de instalat; bonurile ies identic, octet cu octet (verificat cu jurnalul driverului). |
| Fără simulare implicită | Un bon marcat plătit fără să existe pe casă e mai grav decât o plată refuzată. |

## 16. Limitări cunoscute și ce urmează

- **De încercat pe casa reală:** plata cu cardul, bonul cu CUI, X / Z / raportul
  pe perioadă, plata cu rest. Până acum s-a emis bonul de test, numerar.
  Nu se știe încă dacă unitatea (buc / kg) a fost acceptată pe bon:
  check-till avertizează dacă nu.
- **SIM neactivat** pe casă — de rezolvat cu dealerul (raportarea către ANAF).
- **„Bonul nesigur” e ținut doar în memoria procesului** (`_uncertain`). După o
  repornire a exe-ului imediat după o cădere a legăturii, aplicația nu mai știe
  dacă bonul a ieșit; trebuie văzut pe hârtie înainte de a plăti din nou.
- **`config.txt`:** dacă o cheie apare de două ori, contează **primul** rând.
  Ar fi mai firesc ultimul, cu un avertisment.
- **Recepția mărfii** nu are ecran; stocul intră doar la crearea produsului
  sau prin `POST /api/products/<id>/stock`.
- **Diacritice pe bon:** casa e pe codificarea 1250, care ar putea tipări ă, â,
  î și ș / ț (cu sedilă). Azi aplicația le scoate.
- Nu există un **număr de versiune** afișat în aplicație.
- O singură casă, un singur calculator, fără autentificare. Oricine are acces
  la calculatorul casei poate folosi aplicația.
