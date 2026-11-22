# Istoricul modificărilor

Cele mai noi primele. Detaliile tehnice: [README.md](README.md); ghidul pentru
magazin: [deploy/windows/README.md](deploy/windows/README.md).

## 2026-11-13 — Reducere peste prețul nou

O linie de bon poate avea acum **și** preț nou, **și** reducere. Exemplu: 120 lei
→ preț nou 100 → reducere 30% → **70 lei** pe bonul fiscal.

- **Baza de date:** coloana nouă `order_items.manual_price_bani` (prețul tastat;
  `NULL` = prețul din catalog). La prima pornire, o bază mai veche primește
  coloana, iar liniile vechi cu preț tastat își păstrează prețul ca „preț nou”.
  Totul se face într-o singură tranzacție.
- **Calculul:** prețul încasat = (prețul nou sau cel din catalog) minus
  reducerea. Reducerile nu se aplică în lanț: 20% din 100 = 80, nu 20% din 70.
  Ordinea nu contează.
- **API:** `PATCH /api/orders/<id>/items/<item>` primește `manual_price_bani`
  (sau `null`) și `discount_bp`, oricare dintre ele sau amândouă. Ce nu se
  trimite rămâne cum era. `unit_price_bani` nu mai e acceptat la intrare.
- **Casa de marcat:** neschimbat — primește doar prețul final (varianta A).
- **Linii comasate:** un produs adăugat din nou nu se adună pe o linie cu preț
  nou sau cu reducere.
- **Excel, foaia „Linii”:** coloana nouă „Preț modificat (lei)”.
- **Editorul liniei:** aceleași file și butoane. S-au schimbat doar calculele
  din spate:
  - previzualizarea combină prețul nou cu reducerea;
  - *Salvează* trimite amândouă părțile;
  - *Preț din catalog* le scoate pe amândouă;
  - indiciul din câmpul prețului e prețul de bază.
- **Teste:** 265 de teste backend, plus scenariul de browser pentru linia de bon.
  Acoperă combinația, ordinea, limitele, migrarea bazelor vechi, plata și
  exportul.

## 2026-11-03 — Documentație

- `README.md` rescris pentru cine lucrează pe cod:
  - arhitectura și structura fișierelor;
  - regulile codului: bani, rotunjire, prețul liniei, TVA, stoc;
  - baza de date și cum se actualizează schema;
  - API-ul;
  - fluxul unei vânzări, comandă cu comandă;
  - casa Tremol, cu tot ce s-a învățat pe casa reală;
  - setările, deciziile luate și limitările cunoscute.
- `CHANGELOG.md` (acest fișier).
- `deploy/windows/README.md`:
  - setările casei din magazin (COM5, parola `0`);
  - ZFPLabServer nu trebuie instalat;
  - cablul USB;
  - editarea liniei de bon;
  - probleme noi în tabel: cod 92, legătura întreruptă, casa nu răspunde.
- `database.py`: comentariul tabelei `order_items` descrie și prețul nou.

## 2026-10-23 — Prima casă reală; Modificare preț

Casa Tremol din magazin (COM5) emite bonuri din aplicație. Corecturile din
`tremol.py` au fost găsite pe casa reală, comparând cu jurnalul driverului
Tremol:

- **Parola operatorului** se trimite completată cu spații până la 4 caractere
  (`"0"` → `"0   "`), cum cere `<OperPass[4]>`. Înainte, casa răspundea
  *parolă greșită*, cod 92.
- **Numele articolului** are lungimea fixă de 36 de caractere: 30 pentru nume,
  `` ` ``, 3 pentru unitate și 2 spații. Înainte, casa răspundea *eroare de
  sintaxă*, cod 04. Dacă o casă refuză unitatea, liniile se trimit fără ea.
- **Așteptarea cât casa tipărește:** `09h`, până când casa nu mai răspunde `41h`.
  Driverul Tremol face la fel.
- **Căderea legăturii USB** în timpul unui bon dă acum un mesaj clar, *legătura
  cu casa s-a întrerupt*, nu o eroare internă. La reîncercare, bonul rămas
  deschis se anulează.

Verificarea casei (`check-till`):

- pasul 8 citește câmpurile după poziție (casa adaugă un `;` la final); o parolă
  goală e doar avertisment (unele case o ascund);
- avertizare când casa refuză unitatea de măsură;
- parola goală se scrie `--password=`.

Linia de bon:

- editorul liniei are două file, **Reducere (%)** și **Modificare preț**;
- câmpul prețului nou e gol la deschidere și arată prețul de acum ca indiciu;
- `PATCH /api/orders/<id>/items/<item>` acceptă `unit_price_bani` (prețul nou);
  trimis împreună cu `discount_bp`, e refuzat;
- reducerea pornește mereu de la prețul din catalog;
- butonul „Fără reducere” devine „Preț din catalog”.

Teste:

- casa falsă cere câmpurile cu lungime fixă și simulează casa ocupată, căderea
  USB și refuzul unității;
- 256 de teste backend.

## 2026-10-22 — Reducere pe linie; import CSV; verificarea operatorului

- **Linia de bon:** în locul prețului tastat, o **Reducere (%)** liberă:
  - `order_items.discount_bp`, în sutimi de procent; bazele vechi primesc
    coloana singure;
  - eticheta `−X%` în bon și în *Bonuri*;
  - coloana „Reducere (%)” în exportul vânzărilor.
- **Import CSV:** lista magazinului (*Denumire Produs, Cantitate Produs, Pret
  Vanzare*) se importă direct:
  - separatorul și codificarea se recunosc singure;
  - fără coloana Cod, potrivirea se face după denumire și se dau coduri
    automate;
  - alte nume acceptate pentru coloane.
- **check-till, pasul 8:** citește operatorul și parola de pe casă (`6Ah`) și le
  compară cu `--password`, înainte de bonul de test. Setările de operator și
  parolă apar în rândurile de trecut în `config.txt`.
- Cadrele trimise de aplicație (`30h`, `31h`, `33h`, `35h`, `38h`, `39h`) au
  fost verificate cu PDF-ul protocolului.

## 2026-10-20 — Pregătirea pentru producție

- **Două categorii fixe**, *La bucată* și *La kilogram* (`sale_type`). Raioanele
  au fost șterse: tabelul, API-ul și ecranul.
- **TVA fix 21%, grupa A.** Cotele TVA au fost șterse: tabelul, API-ul și
  alegerea din interfață. O bază veche, cu cote pe produs, e refuzată la
  pornire, cu mesaj.
- **Un singur preț pe kilogram:**
  - rândul fix `KG` în baza de date;
  - *Produse → La kilogram* pentru preț și denumire;
  - butonul *La kilogram* la casă;
  - catalogul are doar produse la bucată.
- **Fără date demo:** baza pornește goală.
- **detoate.exe:**
  - un singur fișier (PyInstaller), cu `config.txt` lângă el;
  - datele în `%LOCALAPPDATA%\detoate`;
  - pornire automată cu Windows;
  - comenzile `check-till`, `backup` și `restore`, plus restaurarea prin tragerea
    copiei peste exe;
  - construit cu `deploy/windows/build-exe.bat`.

## Până la 2026-10-19 — Versiunea inițială

- Backend Flask + SQLite:
  - catalogul, cu stocul ținut prin mișcări;
  - bonurile, cu plata care emite bonul fiscal;
  - raportul de vânzări;
  - importul și exportul Excel.
- Adaptorul Tremol ZFP, direct pe portul serial; verificarea casei; modul
  simulare.
- Rapoartele fiscale X, Z și pe perioadă, cu jurnal.
- Interfața Vue, în culorile detoatemarket, pentru ecran tactil: Casa, Bonuri,
  Produse, Rapoarte.
- Producția: serverul waitress, jurnalul, copiile automate ale bazei.
- Decizie: fără ecran de clienți salvați; CUI-ul se tastează pe bon.
