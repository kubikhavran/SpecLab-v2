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

## AI asistent (e-INFRA CZ / CESNET)

Tlačítko **AI asistent** otevře chat. Napište jakýkoli požadavek běžnou řečí, například:

- *„Dej spektra do offsetu, aby byla porovnatelná, označ nejdůležitější píky u každého spektra a obarvi je podle vlnové délky laseru.“*
- *„Z celé série vyber spektra po 200 mV, seřaď je od −1000 mV, obarvi gradientem od modré k červené, odečti pozadí a popiš 5 hlavních pásů.“*
- *„Uprav moje spektra tak, aby vypadala jako na přiloženém obrázku.“*

AI pracuje jako agent: ovládá SpecLab stejnými nástroji jako vy (zpracování dat, barvy, šířky a viditelnost jednotlivých křivek, názvy, pořadí a offset, detekce píků zvlášť pro každé spektrum, vlastní popisky, osy, písmo, rámeček, rozměry exportu). Pracuje na kopii pracovního prostoru, takže se nic nezmění, dokud výsledek nepotvrdíte. Chybné nebo mimo rozsah zadané hodnoty dostane zpět jako vysvětlení a opraví je sama. Než skončí, vykreslí si publikační obrázek přesně tak, jak se bude exportovat, prohlédne si ho a dostane i automatickou kontrolu: popisky přes sousední křivku, skryté popisky, příliš malá nebo „plochá“ spektra, dlouhé názvy. Případné problémy opraví. Výsledek se zobrazí v náhledu; **Použít změny** ho zapíše jako jeden krok Zpět, **Zahodit** ho zahodí. V konverzaci lze pokračovat („ještě zvětši písmo“, „1590 popiš jako ν(C=C)“).

Z názvů souborů a metadat AI pozná podmínky měření: laser (u WDF i z hlavičky přístroje), mřížku, výkon, akumulace, potenciál nebo bod mapy. Barvy laserů jsou vhodné pro tisk: 532 nm zelená, 633 nm oranžovočervená, 785 nm tmavě červená, 1064 nm hnědočervená.

**Vzory:** tlačítkem **Přiložit vzor…**, přetažením nebo vložením ze schránky (⌘V) lze přidat obrázek grafu (PNG, JPG, …, PDF), projekt SpecLabu `.speclab.json` nebo preset `.json` (styl se převezme přesně, volitelně i zpracování a popsané pásy) či soubory spekter. AI pak napodobí rozložení, barvy, osy, písmo, popisky i poměr stran. Co SpecLab neumí (např. legendu uvnitř grafu), AI uvede ve shrnutí.

**Model:** výchozí je `kimi-k3`, nejschopnější model na e-INFRA: zvládá nástroje, vidí obrázky a má kontext 1M tokenů. Je důkladný, ale pomalý: v testech na datech z bakalářky trvala jedna zpráva 7–15 minut (dlouho přemýšlí). Průběh je vidět v chatu. `deepseek-v4.1-flash-thinking` dal v týchž testech srovnatelné výsledky 3–5× rychleji (1,5–7 min) a obrázky vzorů vnímal přesněji. Pro běžnou práci je tedy dobrou volbou. Modely bez obrazového vstupu (`glm-5.3`, `gpt-oss-120b`) dostanou kontrolu obrázku jen jako text. API dovoluje nejvýše 4 souběžné požadavky na klíč; při přetížení aplikace sama počká a zkusí to znovu.

**Co se odesílá:** zadání, souhrn spekter (rozsahy, nejvýraznější pásy, šum, zpracování, styl), názvy spekter a souborů (lze vypnout v **Připojení a soukromí**), vykreslené náhledy grafu a přiložené vzory. Nikdy se neodesílají cesty k souborům ani API klíč.

API klíč získáte na [chat.ai.e-infra.cz](https://chat.ai.e-infra.cz). Zadejte jej v **Připojení a soukromí**; klíč zůstává pouze v paměti po dobu běhu aplikace. Alternativně jej nastavte v proměnné `E_INFRA_API_TOKEN`. Výchozí endpoint je `https://llm.ai.e-infra.cz/v1`.

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
