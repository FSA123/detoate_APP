# detoate.exe — instalarea în magazin (Windows)

Pe calculatorul casei e nevoie de **un singur fișier: `detoate.exe`**. Nu
trebuie instalat Python, Node.js sau altceva.

| Pe calculatorul casei | Ce e |
|---|---|
| `C:\detoate\detoate.exe` | toată aplicația; la o actualizare se înlocuiește doar el |
| `C:\detoate\config.txt` | setările (portul casei de marcat…), create la prima pornire; se modifică cu Notepad |
| `%LOCALAPPDATA%\detoate\` | datele: baza `detoate.db`, copiile `backups\`, jurnalul `logs\` — o actualizare nu le atinge |

Comenzile, toate din același fișier:

| Ce | Cum |
|---|---|
| pornește casa | dublu-clic pe `detoate.exe` (pornește și singur, cu Windows) |
| verifică casa de marcat | `detoate.exe check-till` |
| o copie de siguranță acum | `detoate.exe backup` |
| restaurează o copie | trageți copia `.db` peste `detoate.exe`, cu aplicația închisă |

## 1. Construirea lui detoate.exe — o dată pentru fiecare versiune

Pe orice calculator cu Windows 10/11 (poate fi chiar cel al casei):

1. Instalați **Python 3.9+** de pe <https://www.python.org/downloads/> și
   bifați **„Add python.exe to PATH”**.
2. Interfața: fie instalați **Node.js 22+** de pe <https://nodejs.org>, fie
   copiați folderul `frontend\dist` construit pe Mac cu `npm run build`.
3. Copiați folderul proiectului și dați dublu-clic pe
   `deploy\windows\build-exe.bat`. Rezultatul: **`dist\detoate.exe`**.

După aceea Python și Node.js nu mai sunt necesare — `detoate.exe` le conține.

## 2. Instalarea pe calculatorul casei

1. Creați folderul `C:\detoate` și copiați `detoate.exe` în el (nu în
   *Program Files*: `config.txt` trebuie să se poată scrie lângă el).
2. Dublu-clic pe `detoate.exe`. La prima pornire:
   - creează `config.txt` lângă el și datele în `%LOCALAPPDATA%\detoate`;
   - se pune să pornească singur la deschiderea sesiunii Windows;
   - deschide casa în browser, la <http://127.0.0.1:5000>.

   Fereastra neagră **„detoate - server”** este aplicația: minimizați-o, nu o
   închideți. Pornirea durează câteva secunde (fișierul se despachetează).
3. Sus apare, cu roșu, *Casa de marcat nu este configurată* — normal până la
   pasul 4.
4. Opțional, o scurtătură pe Desktop: clic dreapta pe `detoate.exe` → *Trimitere
   către* → *Desktop (creare comandă rapidă)*.

**Windows SmartScreen** poate spune la prima pornire *„Windows a protejat
computerul”* (fișierul nu e semnat digital): *Mai multe informații* → *Rulați
oricum*. Dacă antivirusul îl blochează, adăugați o excepție pentru `C:\detoate`.

## 3. Conectarea casei de marcat

Casa trebuie să lucreze în modul **imprimantă fiscală** (comandată de
calculator) — protocolul Tremol e scris pentru acest mod. Dacă nu știți în ce
mod e, întrebați dealerul de la care ați cumpărat-o.

- **Cablu USB:** conectați cablul și porniți casa. În **Manager dispozitive →
  Porturi (COM și LPT)** apare un port nou, de exemplu „USB Serial Device
  (COM3)”. Windows 10/11 îl recunoaște de obicei fără driver; dacă nu apare
  niciun port nou, cereți driverul USB de la Tremol sau de la dealer.
- **Cablu serial (RS232):** portul e cel al calculatorului (de obicei COM1) sau
  al adaptorului USB–serial, dacă folosiți unul.
- **Rețea (LAN/WiFi):** aplicația nu folosește încă legătura prin rețea —
  conectați casa prin cablu.

Nu trebuie să știți numărul portului: verificarea de mai jos îl găsește.

**Nu instalați „driverul” Tremol (ZFPLabServer) pe calculatorul casei.**
detoate vorbește direct cu casa. ZFPLabServer pornește odată cu Windows și ține
portul COM ocupat, iar atunci detoate nu mai poate tipări. Dacă l-ați instalat
pentru o probă, dezinstalați-l (*Setări → Aplicații*).

**Cablul USB:** folosiți cablul original, direct într-un port USB din spatele
calculatorului (fără hub sau prelungitor), cu casa pe alimentatorul ei. O
legătură USB care cade în timp ce casa tipărește apare ca *legătura cu casa
s-a întrerupt*.

## 4. Verificarea casei — înainte de prima vânzare

Deschideți *Command Prompt* (Win+R → `cmd` → Enter) și scrieți:

```
cd C:\detoate
detoate.exe check-till
```

Verificarea **nu schimbă nimic pe casă**:

| Pas | Ce verifică |
|---|---|
| 0 | caută casa pe toate porturile COM, la toate vitezele din protocol |
| 1 | casa răspunde și e pregătită (hârtie, cap de imprimare) |
| 2 | memoria fiscală e fiscalizată, fără blocare de 24 h, fără bon rămas deschis |
| 3 | modelul, interfețele lui (RS232, USB, LAN…) și pe care e conectat acum, lungimea numelor de articol |
| 4 | **grupa TVA A de pe casă are 21%** — aplicația vinde totul cu 21%, pe grupa A |
| 5 | casa lucrează cu prețuri cu bani (zecimale) |
| 6 | tipurile de plată: 0 e numerarul; cel care se numește „CARD” e numărul pentru card |
| 7 | ultimul bon și ultimul raport Z |
| 8 | operatorul 1 (sau `--operator N`): numele și **parola lui de pe casă**, comparată cu `--password` |

Fiecare rând **EROARE** trebuie rezolvat înainte de a folosi casa:

- *casa nu a fost găsită* / *casa nu răspunde* — cablul, casa pornită (opriți-o și
  porniți-o din nou), driverul USB, modul imprimantă fiscală, ZFPLabServer oprit;
- *operatorul 1 are pe casă parola „…”* — rulați din nou cu `--password` și parola
  arătată (fără ea, bonul e refuzat cu „parolă greșită”, cod 92). Unele case nu
  arată parola (pasul 8 spune *casa arată parola goală*): atunci doar bonul de test
  lămurește care e;
- *grupa A: …% pe casă, dar aplicația vinde totul cu 21%* — un tehnician
  autorizat programează casa, nu se modifică din aplicație;
- *casa acceptă nume de articol de N caractere* — spuneți-mi, adaptorul trebuie ajustat.

**Bonul de test.** Când toate verificările sunt OK, emiteți **un singur bon
fiscal real** de 0,10 lei (numerar). Scriptul cere să scrieți `DA`; bonul intră
în memoria fiscală și în raportul Z al zilei.

```
detoate.exe check-till --port COM5 --password 0 --bon
detoate.exe check-till --port COM5 --password 0 --bon --cui RO14080700
```

Al doilea rând încearcă și bonul cu CIF-ul cumpărătorului. Pe hârtie
verificați: numele „TEST CASA”, prețul 0,10, TVA grupa A (21%), CIF-ul (dacă
l-ați cerut). Mesajul care confirmă bonul este `bon emis, nr. …` la pasul 9 —
un OK la pasul 8 singur nu înseamnă că bonul s-a emis.

Parola: casa din magazin are operatorul 1 cu parola **`0`** (detoate o trimite
completată cu spații până la 4 caractere, cum cere protocolul). O parolă goală se
scrie `--password=` (fără nimic după `=`): `--password ""` nu ajunge la program
din unele ferestre de comenzi.

**Setările.** La final, verificarea arată ce să treceți în `config.txt`.
Deschideți `C:\detoate\config.txt` cu Notepad și completați — pentru casa din
magazin:

```
DETOATE_TREMOL_PORT=COM5
DETOATE_TREMOL_CARD_PAYMENT=1
DETOATE_TREMOL_PASSWORD=0
```

Fiecare setare **o singură dată**: rândul `DETOATE_TREMOL_PORT=` există deja în
fișier — modificați-l, nu adăugați încă unul (dacă o setare apare de două ori,
contează primul rând). Rândul cu parola lipsește din fișier: adăugați-l, dacă
parola nu e cea implicită, `0000`. Salvați. `DETOATE_FISCAL_SIMULATE` rămâne
**gol** în magazin. Închideți fereastra „detoate - server” și dați din nou
dublu-clic pe `detoate.exe`. Sus nu trebuie să mai apară niciun avertisment:

- galben, *MOD SIMULARE* — bonurile nu se tipăresc: `DETOATE_FISCAL_SIMULATE` nu e gol;
- roșu, *Casa de marcat nu este configurată* — `DETOATE_TREMOL_PORT` e gol.

## 5. Primele setări în aplicație

Aplicația pornește **goală**: fără produse și fără preț pe kilogram.

1. **Prețul pe kilogram** — *Produse → La kilogram*: prețul (lei / kg) și
   denumirea care apare pe bon (implicit „Marfă la kilogram”) → *Salvează*.
   Până atunci, la casă butonul *La kilogram* arată „preț nesetat” și nu vinde.
   Prețul se poate schimba oricând; bonurile deja emise rămân cu prețul lor.
2. **Produsele la bucată** — *Produse → Produs nou* (cod, denumire, preț, cod de
   bare opțional) sau, pentru multe deodată, *Produse → Excel*: descărcați
   șablonul, completați-l, importați-l.
3. **Prima vânzare reală:** un produs la bucată și ceva la kilogram, plătit
   numerar; comparați bonul tipărit cu ecranul (denumiri, cantități, total,
   TVA 21%). Apoi *Bonuri* — bonul apare cu numărul de pe hârtie.

La casă: atingeți un produs (sau scanați codul de bare); pentru marfa la
kilogram, butonul **La kilogram** → greutatea pe tastatura de pe ecran →
*Adaugă*. De la tastatură merge și `1,25*KG` + Enter, iar `3*200` + Enter pune
3 bucăți din produsul cu codul 200.

**O linie de pe bon** se modifică atingând-o: cantitatea și, pe două file,
prețul liniei —

- **Modificare preț** — prețul nou, în lei pe bucată sau pe kg, mai mic sau mai
  mare decât cel din catalog; pe bon apare eticheta *preț modificat*;
- **Reducere (%)** — un procent (10, 12,5…) din prețul nou, dacă linia are unul,
  altfel din cel din catalog; pe bon apare eticheta `−10%`.

Cele două se combină: un produs de 120 lei, cu prețul nou 100 și reducerea
30%, costă 70 lei. Butonul *Preț din catalog* le anulează pe amândouă. Casa de
marcat primește doar prețul final al liniei (70), iar prețul din catalog al
produsului nu se schimbă.

## Zilnic

- **Dimineața:** porniți calculatorul — aplicația pornește singură.
- **La închidere:** *Rapoarte → Raport Z*, o dată pe zi. Jurnalul de sub
  butoane arată, pentru fiecare Z, totalul casei lângă cel al aplicației; un
  ⚠ înseamnă că s-a vândut ceva direct de pe casă, ocolind aplicația.

## Copii de siguranță

- **Automat:** aplicația face o copie a bazei de date la pornire și apoi la
  fiecare 4 ore, în `%LOCALAPPDATA%\detoate\backups`, și păstrează ultimele 60.
- **Recomandat:** în `config.txt`, `DETOATE_BACKUP_COPY_DIR` — un stick USB sau
  un folder OneDrive — ca fiecare copie să existe și în afara calculatorului.
  Dacă stickul lipsește, copia locală se face oricum.
- **Manual,** de exemplu înainte de o actualizare: `detoate.exe backup`.
- **Restaurare:** închideți fereastra „detoate - server”; deschideți copiile
  (Win+R → `%LOCALAPPDATA%\detoate\backups`), trageți copia dorită peste
  `detoate.exe` și scrieți `DA`. Baza de dinainte se păstrează și ea ca o copie,
  deci o restaurare greșită se poate desface. Porniți din nou `detoate.exe`.

## Actualizarea aplicației

1. Închideți fereastra „detoate - server” (la pornire se face oricum o copie a
   bazei de date).
2. Înlocuiți `C:\detoate\detoate.exe` cu cel nou. `config.txt` și datele rămân.
3. Dublu-clic pe `detoate.exe`.

## Probleme

| Ce se vede | Ce faceți |
|---|---|
| În browser: *Serverul nu răspunde* | dublu-clic pe `detoate.exe` |
| Fereastra serverului afișează erori | jurnalul complet: `%LOCALAPPDATA%\detoate\logs\detoate.log` |
| *Atenție: config.txt, rândul N … nu e o setare cunoscută* | o greșeală de scriere în `config.txt` — comparați cu numele din fișier |
| Casa nu mai răspunde după ce ați mutat cablul în alt port USB | `detoate.exe check-till` găsește noul COM → `config.txt` → reporniți |
| *Casa a refuzat bonul: casa: parolă greșită… (comanda 30h, cod 92)* | parola operatorului: `DETOATE_TREMOL_PASSWORD` în `config.txt` (la casa din magazin: `0`) |
| *Legătura cu casa s-a întrerupt* sau portul COM dispare din *Manager dispozitive* | casa pornită și pe alimentator, cablul USB direct în calculator; apoi plătiți din nou — un bon rămas deschis pe casă se anulează singur, iar un bon deja emis nu se tipărește a doua oară (dacă între timp nu ați repornit `detoate.exe`; după o repornire, uitați-vă întâi dacă bonul a ieșit pe hârtie) |
| *Casa nu răspunde* | opriți și porniți casa; ZFPLabServer să nu ruleze (*Task Manager*); `detoate.exe check-till` fără `--port` |
| Portul 5000 e ocupat de alt program | alt număr în `DETOATE_PORT`, în `config.txt` |
| Aplicația nu mai trebuie să pornească singură | `DETOATE_AUTOSTART=0` în `config.txt`, apoi porniți o dată `detoate.exe` |
| La casă: *Prețul pe kilogram nu e setat* | *Produse → La kilogram* → prețul → *Salvează* |
| Serverul nu pornește: *Baza de date … e dintr-o versiune mai veche* | o bază din probele de dinainte de lansare; mutați `detoate.db` deoparte și porniți din nou — se creează una nouă, goală |
| Antivirusul șterge sau blochează `detoate.exe` | excepție pentru `C:\detoate` în antivirus |

Aplicația ascultă doar pe calculatorul casei (`127.0.0.1`), fără parolă:
oricine are acces la acest calculator o poate folosi.
