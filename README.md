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

## Pracovní postup

Vlevo je 11 kroků: **Spektra → Rozsah a převody → Spiky → Baseline → Šum a derivace → Měřítko dat → Píky → Čáry a barvy → Osy a písmo → Rozložení a popisky → Export a preset**. Graf zůstává uprostřed a pravý panel ukazuje právě vybraný krok. Kroky lze přeskočit a kdykoli se k nim vrátit.

Nahoře vyberte aktivní spektrum a rozsah aplikace: aktivní, vybraná nebo všechna. Více spekter vyberete v kroku 01 pomocí Ctrl/⌘ nebo Shift; pořadí změníte tažením nebo šipkami. Přejmenování otevře dvojklik; dostupné jsou také hromadné názvy a sekvence. **Zobrazit výběr** porovná vybrané křivky bez odebrání ostatních; **Zobrazit vše** je vrátí do grafu. Individuální viditelnost lze nastavit i v kroku Čáry a barvy. Jednotky a technika popisují aktivní spektrum, samy nepřevádějí jeho hodnoty.

Filtry mají posuvníky i přesná číselná pole a tlačítka **Náhled / Použít / Reset**. Reset odebere daný nástroj z receptu a přepočítá zbývající operace z originálu. V kroku 06 je také obnova celých původních dat. Nastavení grafiky se potvrzuje vlastním tlačítkem Použít; reset obnoví jen příslušnou skupinu vzhledu. Globální vzhled platí pro celý graf, individuální barva, šířka a styl čáry respektují výběr spekter.

**Common scale** zachovává společné Y. **Full scale** zobrazuje každou křivku v rozsahu 0–1 pro porovnání tvarů. Oba režimy i rozestup série mění pouze obrázek; hodnoty CSV/TSV se mění jen nástroji zpracování dat. **Tabulka · historie · integrace** pod horní lištou zobrazí podrobnosti bez trvalého zmenšení grafu.

V kroku 11 uložíte preset i celý projekt. Preset zachytí globální nastavení a recepty / individuální styly podle pozic série: při stejném počtu spekter je přehraje podle pořadí. Při jiném počtu použije recept tehdy aktivního spektra na celou dávku. Přehrání dat lze vypnout. **Projekt** navíc uchová skutečná data, názvy, ruční píky a pozice jejich popisků. Použití presetu je vratná transakce.

Podrobná mapa funkcí: [docs/workflow.md](docs/workflow.md).

## Podporované formáty

- **TXT, CSV, TSV, DAT, ASC, XY, DPT:** vícesloupcový import; první sloupec je X a každý další sloupec Y samostatného spektra. Podporuje citované CSV, desetinnou čárku u oddělovače středník/tabulátor/mezera a kódování UTF-8/UTF-16 s fallbackem CP1250. Chybné číselné řádky se odmítají (jen poškozený poslední řádek, typický pro přerušený export, se vynechá s upozorněním); nejsou podporovány prokládané dvojice X/Y ani automatické odstraňování chybějících hodnot. Dlouhý formát exportu WiRE (`#Time/#X #Y #Wave #Intensity`) se rozdělí na jednotlivá spektra série podle času či polohy.
- **WDF (Renishaw, WDF1):** základní float32 spektra se sdílenou osou, série a mapovací původní souřadnice. Multitrack, XYXY a filter images jsou odmítnuty; obrázky a fitované výsledky se neimportují.
- **SPA (Thermo OMNIC):** čte primární spektrum při shodě hlavičky a délky dat. Popisky píků přebírá přesně z OMNIC (popisky zobrazené na spektru, jinak tabulka FIND PEAKS); historii úprav ani jiné texty souboru za píky nepovažuje. Oblasti vymazané v OMNIC (NaN, např. pásy nosné fólie) se načtou jako mezery a jejich rozsahy se uloží do metadat. Interferogramy jsou odmítnuty.
- **SPG (Thermo OMNIC, skupina spekter):** načte všechna spektra skupiny s jejich názvy.
- **SPC:** jedno float32 spektrum s rovnoměrnou nebo explicitní osou X. Integer-scaled, multifile, XYXY a interferogramy jsou odmítnuty; textový soubor s příponou SPC lze načíst jako text.
- **JCAMP-DX:** AFFN/PAC XYDATA (`X++(Y..Y)`), XYPOINTS, škálovací faktory a více samostatných bloků. SQZ/DIF/DUP, NTUPLES a peak tables jsou odmítnuty s chybou.

Import kontroluje číselná data, odmítá duplicitní X a seřadí odpovídající dvojice X/Y vzestupně. Formát binárních souborů se pozná i podle obsahu, takže se načte i soubor se špatnou příponou. **SRS a OPUS nejsou podporovány.** Podrobnosti a limity: [docs/formats-and-api.md](docs/formats-and-api.md).

## Zpracování dat

Operace v místním zpracovatelském jádře:

- **Baseline:** korekce základní linie metodou AsLS.
- **Smooth:** vyhlazení filtrem Savitzky–Golay.
- **Despike:** odstranění kosmických spiků. Spike se pozná podle reziduí vůči mediánovému filtru a navíc podle strmých hran nebo zubatosti, která převyšuje šum, takže se odstraní i spiky široké několik bodů, aniž by se ořezaly úzké skutečné pásy (např. Si 520 cm⁻¹). U série spekter (např. potenciálové EC-SERS) tlačítko **Spiky podle sousedních spekter** porovná každé spektrum s mediánem sousedů a nahradí jen místa, kde se od série výrazně liší.
- **Normalize:** normalizace maxima, vektorem, plochou nebo rozsahem.
- **Derivative:** výpočet první nebo druhé derivace.
- **Convert Y:** převod mezi transmitancí a absorbancí.
- **Crop:** oříznutí spektra na zvolený rozsah X.
- **Resample:** převzorkování na rovnoměrný krok X.
- **Scale:** explicitní násobení intenzity; výstup je relativní.
- **Shift:** posun os X a/nebo Y.
- **Interpolate:** interpolace hodnot Y ve zvoleném rozsahu.

Každá úprava se nejprve zobrazí v náhledu, zaznamená do **Historie úprav** a lze ji vrátit či znovu provést tlačítky **Zpět/Znovu** – to platí i pro import, odebrání a vymazání spekter. Původní importovaná data zůstávají zachována. Vyhlazení, korekce baseline a despike pracují po bodech a přijímají i mírně nerovnoměrné osy X (typické například pro Ramanovo CCD); skutečné mezery v ose X (vymazané oblasti) dělí spektrum na úseky, které se zpracují samostatně a graf je nepřemostí čarou. Derivace vyžaduje rovnoměrnou osu X; jinak nejprve použijte **Převzorkování**.

## Píky

Popisky píků se rozmisťují automaticky: zůstávají u svého pásu (u transmitance pod ním) a zachovávají pořadí pásů. Popisky se nikdy nepřekrývají a vodicí čáry se nekříží, nevedou přes jiný popisek ani přes křivku: posunuté popisky jednoho shluku se lomí ve společném pásu nad ním. Pokud by se popisek musel posunout dál než o 2,5 své šířky, oblast je příliš hustá a nejslabší pás v ní zůstane bez popisku (počet skrytých popisků ukazuje graf; po přiblížení se objeví). Ručně přetažený popisek si drží polohu vůči píku. Tlačítko **Auto** u rozestupu křivek rozestoupí překryv spekter tak, aby se nepřekrývala.

Automatická detekce podporuje maxima, minima nebo obojí, minimální prominenci, minimální vzdálenost v jednotkách X a omezení na oblast X. Ruční výběr zapnete volbou **Ruční výběr**: Ctrl/⌘+kliknutí přidá pík, Shift+kliknutí poblíž píku jej odstraní. Popisky píků lze přetahovat i ručně zadat pozici X a text. Vodicí čára se při tažení pohybuje s popiskem. Pravý klik na popisek jej odebere. Ruční pozice i nastavení čar, barev a písma přebírá také publikační export. Tabulku píků lze tlačítkem **Kopírovat TSV** zkopírovat do schránky.

## Projekty

Soubor `*.speclab.json` ukládá původní i aktuální data, recepturu zpracování, píky, nastavení a původ změn. Historie Zpět/Znovu se neukládá. API klíče se do projektu nikdy neukládají.

## AI (e-INFRA CZ / CESNET)

API klíč získáte na [chat.ai.e-infra.cz](https://chat.ai.e-infra.cz). Zadejte jej přes **AI asistent → Nastavení připojení e-INFRA**; klíč zůstává pouze v paměti po dobu běhu aplikace. Alternativně jej nastavte před spuštěním aplikace v proměnné `E_INFRA_API_TOKEN`. Výchozí endpoint je `https://llm.ai.e-infra.cz/v1`.

V panelu AI asistenta zvolte **Načíst dostupné modely**, vyberte model a popište požadovanou úpravu. AI vrátí plán povolených operací (JSON lze rozbalit v pokročilém nastavení) a volitelně návrh vzhledu (popisky os, písmo, paleta, styl a detekce píků s relativní prominencí); pro jeho kontrolu a zobrazení výsledku zvolte **Spočítat náhled**, pro potvrzené použití pak **Použít návrh**. Vzhled je omezený na bezpečný seznam nastavení a validuje se stejně jako presety. AI dostává objektivní popis spektra (polohy, šířky FWHM a relativní výšky nejvýraznějších pásů měřené vůči jejich okolí, takže široké pozadí pásy nezakryje; typickou šířku pásu a odhad šumu), aby volila přiměřené vyhlazení, baseline a práh detekce. Velikosti písma se ověřují (čitelné minimum), detekce píků uvedená omylem mezi operacemi se přesune do vzhledu.

Odesílá se text zadání a kontext spektra: technika, typ Y, jednotka X, rozsahy X/Y a počet bodů. Je-li zaškrtnuta volba redukovaného náhledu, přidá se min/max obálka o nejvýše 258 bodech. Cesty souborů se neodesílají. Názvy se posílají jen po zaškrtnutí samostatné volby; AI pak může navrhnout přejmenování a změnu pořadí. Kontext obsahuje všechny vybrané křivky, nejvýše 30 na jeden návrh. Návrh může obsahovat i individuální barvy, šířky a styly čar. Zpracování dat, grafiku s detekcí a změny seznamu lze před použitím nezávisle vypnout. **Prohlédnout celý návrh grafu** otevře oddělený náhled. Potvrzení všech částí vytvoří jediný krok Zpět; změna vstupu nebo nastavení starý náhled zneplatní.

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

Grafy lze exportovat do PNG, SVG a PDF. Export se vysází samostatným publikačním rendererem (matplotlib, 300 dpi, písma vložená do PDF/SVG): názvy os vystředěné na délku os, jednotky sazbou (cm⁻¹), skutečné minus, vnější ticky, otevřený rám, názvy spekter vedle křivek a stejné rozmístění popisků bez překryvů. Velmi malé nebo velké hodnoty (např. 0,0008 po normalizaci plochou) dostanou krátká čísla a násobitel v názvu osy (×10⁻⁴). Rozestup překrytých spekter se při exportu zvětší tak, aby se křivky ani popisky sousedů nedotýkaly. Výsledek lze předem zobrazit tlačítkem **Náhled publikačního obrázku…**; graf se rozvrhne do zvoleného poměru stran (šířka × výška v části Vzhled). Data lze uložit jako CSV nebo TSV, z aktuálních nebo původních importovaných dat, volitelně s desetinnou čárkou. Hromadný export spekter nabízí ZIP; tabulky píků lze exportovat také.

## Testy

```bash
python3 -m pytest
ruff check src_python tests
```

`pytest.ini` nastavuje cestu k aplikaci pro testy.

## Známá omezení

- Historie Zpět/Znovu drží posledních 40 kroků a neukládá se do projektu.
- Zpracování probíhá ve vlákně uživatelského rozhraní; u stovek spekter okno na okamžik zamrzne (baseline pro 500 spekter × 1000 bodů ≈ 0,6 s).
- Formáty SRS a OPUS nejsou podporovány.
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
