# SpecLab Studio

## Co je SpecLab Studio

SpecLab Studio je lokální nástroj pro načítání, porovnávání, zpracování, anotování a export 1D spekter Raman, IR a UV–Vis. AI může navrhnout plán zpracování, nikdy však nenahrazuje ani nevytváří naměřená data.

## Požadavky a instalace

Vyžaduje Python 3.11 nebo novější. V kořeni projektu nainstalujte závislosti:

```bash
python3 -m pip install -r requirements.txt
```

## Spuštění

```bash
python3 src_python/main.py
python3 src_python/main.py --demo
python3 src_python/main.py soubor1.txt soubor2.wdf
```

`--demo` načte syntetická demonstrační spektra.

## Podporované formáty

- **TXT, CSV, TSV, DAT, ASC, XY, DPT:** vícesloupcový import; první sloupec je X a každý další sloupec Y samostatného spektra. Podporuje citované CSV, desetinnou čárku u oddělovače středník/tabulátor/mezera a kódování UTF-8/UTF-16 s fallbackem CP1250. Chybné číselné řádky se odmítají; nejsou podporovány prokládané dvojice X/Y ani automatické odstraňování chybějících hodnot.
- **WDF (Renishaw, WDF1):** základní float32 spektra se sdílenou osou, série a mapovací původní souřadnice. Multitrack, XYXY a filter images jsou odmítnuty; obrázky a fitované výsledky se neimportují.
- **SPA (Thermo OMNIC):** čte primární spektrální payload při shodě hlavičky a délky dat, zachovává označené vložené textové píky jako heuristické. Interferogramy jsou odmítnuty.
- **SPC:** jedno float32 spektrum s rovnoměrnou nebo explicitní osou X. Integer-scaled, multifile, XYXY a interferogramy jsou odmítnuty; textový soubor s příponou SPC lze načíst jako text.
- **JCAMP-DX:** AFFN/PAC XYDATA (`X++(Y..Y)`), XYPOINTS, škálovací faktory a více samostatných bloků. SQZ/DIF/DUP, NTUPLES a peak tables jsou odmítnuty s chybou.

Import kontroluje číselná data, odmítá duplicitní X a seřadí odpovídající dvojice X/Y vzestupně. **SPG, SRS a OPUS nejsou podporovány.** Podrobnosti a limity: [docs/formats-and-api.md](docs/formats-and-api.md).

## Zpracování dat

Operace v místním zpracovatelském jádře:

- **Baseline:** korekce základní linie metodou AsLS.
- **Smooth:** vyhlazení filtrem Savitzky–Golay.
- **Despike:** odstranění kosmických spiků.
- **Normalize:** normalizace maxima, vektorem, plochou nebo rozsahem.
- **Derivative:** výpočet první nebo druhé derivace.
- **Convert Y:** převod mezi transmitancí a absorbancí.
- **Crop:** oříznutí spektra na zvolený rozsah X.
- **Resample:** převzorkování na rovnoměrný krok X.
- **Shift:** posun os X a/nebo Y.
- **Interpolate:** interpolace hodnot Y ve zvoleném rozsahu.

Každá úprava se nejprve zobrazí v náhledu, zaznamená do **Historie úprav** a lze ji vrátit či znovu provést tlačítky **Zpět/Znovu** – to platí i pro import, odebrání a vymazání spekter. Původní importovaná data zůstávají zachována. Vyhlazení, korekce baseline a despike pracují po bodech a přijímají i mírně nerovnoměrné osy X (typické například pro Ramanovo CCD). Derivace vyžaduje rovnoměrnou osu X; jinak nejprve použijte **Převzorkování**.

## Píky

Automatická detekce podporuje maxima, minima nebo obojí, minimální prominenci, minimální vzdálenost v jednotkách X a omezení na oblast X. Ruční výběr zapnete volbou **Ruční výběr**: Ctrl/⌘+kliknutí přidá pík, Shift+kliknutí poblíž píku jej odstraní. Popisky píků lze přetahovat. Tabulku píků lze tlačítkem **Kopírovat TSV** zkopírovat do schránky.

## Projekty

Soubor `*.speclab.json` ukládá původní i aktuální data, recepturu zpracování, píky, nastavení a původ změn. Historie Zpět/Znovu se neukládá. API klíče se do projektu nikdy neukládají.

## AI (e-INFRA CZ / CESNET)

API klíč získáte na [chat.ai.e-infra.cz](https://chat.ai.e-infra.cz). Zadejte jej na kartě **AI**; klíč zůstává pouze v paměti po dobu běhu aplikace. Alternativně jej nastavte před spuštěním aplikace v proměnné `E_INFRA_API_TOKEN`. Výchozí endpoint je `https://llm.ai.e-infra.cz/v1`.

Na kartě AI zvolte **Načíst dostupné modely**, vyberte model a popište požadovanou úpravu. AI vrátí JSON plán povolených operací; pro jeho kontrolu a zobrazení výsledku zvolte **Spočítat náhled**, pro potvrzené použití pak **Použít návrh**.

Odesílá se text zadání a kontext spektra: technika, typ Y, jednotka X, rozsahy X/Y a počet bodů. Je-li zaškrtnuta volba redukovaného náhledu, přidá se min/max obálka o nejvýše 258 bodech. Náhled neobsahuje názvy ani cesty souborů.

Na macOS je nejpohodlnější uložit klíč jednou do Klíčenky (příkaz se na klíč zeptá, nezobrazí ho). Aplikace i testovací skript si ho pak načtou samy, pole „Klíč“ může zůstat prázdné:

```bash
security add-generic-password -a "$USER" -s e-infra-api -w
```

Alternativně proměnná prostředí v macOS/Linux:

```bash
export E_INFRA_API_TOKEN="VÁŠ_API_KLÍČ"
```

Windows PowerShell:

```powershell
$env:E_INFRA_API_TOKEN="VÁŠ_API_KLÍČ"
```

Spojení a odpověď zvoleného modelu lze ověřit bez GUI (klíč se čte z `E_INFRA_API_TOKEN`, případně se na něj skript zeptá bez zobrazení; nikdy se nevypisuje ani neukládá):

```bash
python3 scripts/ai_smoke_test.py            # vypíše modely a použije první
python3 scripts/ai_smoke_test.py MODEL_ID   # konkrétní model
```

## Export

Grafy lze exportovat do PNG, SVG a PDF; graf se při exportu rozvrhne do zvoleného poměru stran (šířka × výška v části Vzhled). Data lze uložit jako CSV nebo TSV, z aktuálních nebo původních importovaných dat, volitelně s desetinnou čárkou. Hromadný export spekter nabízí ZIP; tabulky píků lze exportovat také.

## Testy

```bash
python3 -m pytest
ruff check src_python tests
```

`pytest.ini` nastavuje cestu k aplikaci pro testy.

## Známá omezení

- Historie Zpět/Znovu drží posledních 40 kroků a neukládá se do projektu.
- Zpracování probíhá ve vlákně uživatelského rozhraní; u stovek spekter okno na okamžik zamrzne (baseline pro 500 spekter × 1000 bodů ≈ 0,6 s).
- Formáty SPG, SRS a OPUS nejsou podporovány.
- WDF multitrack a komprimované JCAMP (SQZ/DIF/DUP) se odmítají se zprávou.

## Autor / kontakt

Created by:
Jakub Havránek

Contact:
Personal email:
jakubhavranek120@gmail.com

Academic / institutional email:
havranek@vscht.cz

If you encounter bugs or issues, please report them through the project repository or contact the author.
