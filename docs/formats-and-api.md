# SpecLab: e-INFRA API a formáty spekter

Ověřeno 14. 10. 2026. Tento dokument shrnuje ověřené rozhraní služby, návrh integrace a omezení implementovaných čteček; neprokazuje funkčnost spojení s uživatelským účtem.

## e-INFRA CZ

Oficiální API používá základ `https://llm.ai.e-infra.cz/v1/`, autentizaci `Authorization: Bearer …`, `GET /models` a `POST /chat/completions`. Klíč se vytváří v účtu na `chat.ai.e-infra.cz`; API klíč a JWT nejsou zaměnitelné. Dostupné identifikátory modelů se mají načítat ze služby. Metadata modelů poskytuje `/model/info`, v dokumentovaném příkladu s hlavičkou `x-litellm-api-key: Bearer …`. Nejsou podporovány všechny OpenAI endpointy. Dokumentace doporučuje SSE `stream: true`, zejména pro MCP; ne-streamované požadavky mají limit infrastruktury 30 minut. Podpora striktního JSON schématu není v tomto návodu garantována. [Oficiální dokumentace API](https://docs.cerit.io/en/docs/ai-as-a-service/ai-api).

Dokumentace ochrany dat doporučuje přímé API pro citlivější výzkumné workflow, protože obchází úložiště WebUI. Standardní lokální inference běží v e-INFRA; zvlášť sjednané externí modely mají odlišné podmínky. SpecLab má ukázat cílovou službu a obsah odesílaných dat. [Ochrana dat](https://docs.cerit.io/en/docs/ai-as-a-service/ai-data-privacy).

### Doporučený kontrakt AI

AI vrací pouze plán operací. Oprávnění k úpravám se odvozuje od místního seznamu operací a validátorů; text modelu se nikdy nevykonává jako Python. AI nesmí nahrazovat měřená data vymyšlenými hodnotami.

```json
{
  "version": 1,
  "summary": "Vyhladit šum a normalizovat intenzitu",
  "operations": [
    {"name": "smooth", "parameters": {"window": 11, "polyorder": 3}},
    {"name": "normalize", "parameters": {"method": "max"}}
  ]
}
```

Konkrétní jména musí odpovídat skutečné místní implementaci. Validace má odmítnout neznámé klíče, operace, duplicitní JSON klíče, ne-konečná čísla, booleany vydávané za čísla a nepřiměřenou délku plánu. Parametry se ověřují vůči aktuálnímu spektru, jeho jednotkám a počtu bodů. Neplatná odpověď se zobrazí jako chyba bez změny dat.

Plán se lokálně spočítá nad kopií spektra a zobrazí vedle původního výsledku. Uživatel plán aplikuje jako jednu vrátitelnou transakci; může navázat stejnými ručními operacemi. Zachovat původní soubor, naměřená pole, historii parametrů a příznak autora operace. Převzatý návrh musí být svázán s identitou a revizí konkrétního spektra, aby se omylem nepoužil po změně výběru. Přenos běží mimo UI vlákno, s timeoutem a zrušením; přerušené streamy nesmí vytvořit částečně platný plán. Klíč patří do prostředí nebo bezpečného úložiště OS, nikoli projektu či logů.

Do promptu odesílat typ měření, jednotky, rozsah, počet bodů, informaci o vzorkování a souhrn dostupných lokálních analýz. Pokud se odesílá podvzorkovaný průběh, označit jej jako reprezentaci pro návrh, nikoli úplná data vhodná pro kvantitativní výpočty.

## Čtečky a důležité rozdíly

| Formát | Doporučená cesta | Co musí import zachovat / ověřit |
|---|---|---|
| TXT, CSV, TSV | stdlib `csv`, NumPy; náhled importu | Oddělovač, desetinná čárka, kódování, hlavičky, sloupce X/Y, více spekter, chybějící hodnoty a jednotky. |
| WDF | Volitelný vendor modul `wdf` z balíčku `renishaw-wdf` | Všechny skutečně nasbírané spektrální záznamy, jednotky os, stage souřadnice, čas, laser a mapovací metadata. |
| SPA, SPG, SRS | Volitelný `spectrochempy.read_spa/read_spg/read_srs` | Spektrum versus interferogram, jednotky, směr osy, datum a metadata měření; SPG/SRS mohou obsahovat skupiny a série. |
| JCAMP-DX, JDX, DX | Úplná čtečka nebo jasně omezená vlastní implementace | Škálovací faktory, typ dat, komprese, počet bodů, více bloků a stránky NTUPLES. |
| SPC | Volitelný `spectrochempy.read_spc` | Více podspektrálních záznamů a jejich samostatné osy X. |
| Bruker OPUS | Volitelný `spectrochempy.read_opus` | Nativní bloky a jednotky; neodvozovat formát jen z číselné přípony. |

### WDF

Vendor balíček `renishaw-wdf` 1.4.0 je publikován Renishaw Spectroscopy, má Apache-2.0 licenci a jeho jádro potřebuje pouze standardní knihovnu. API: `with Wdf(path) as data`, `data.xlist()` a iterace přes spektra. `xlist()` obsahuje `.units` a `.datatype`; `origins` poskytují doprovodné hodnoty podle spektra. Mapy a bílé světlo jsou samostatná metadata. [Vendor balíček a API](https://pypi.org/project/renishaw-wdf/).

Kontrola distribuovaného zdroje ukázala významnou hranici: `len(data)` vrací kapacitu `hdr.nspectra`, zatímco iterator používá počet skutečně nasbíraných spekter `hdr.ncollected`. Pro neukončená měření nepoužívat kapacitu jako počet dat. Multitrack soubory mají `xlist(track)` a `hdr.ntracks`; jejich data nelze připojit ke společné první ose bez ověření struktury. Mapu nelze obecně rekonstruovat pouhým `reshape`: může obsahovat neúplný nebo nepravidelný průběh měření.

Alternativní třetí strana `renishawWiRE.WDFReader` nabízí `xdata`, `spectra`, `xpos`, `ypos`, `zpos` a informace o obrázku; tvar spekter se mění mezi jednotlivým měřením, sérií a mapou. Je to čtečka odvozená reverzním inženýrstvím, nikoli vendor API. [Projekt a příklady](https://github.com/alchem0x2A/py-wdf-reader).

### SPA a širší import

SpectroChemPy dokumentuje import OMNIC SPA/SPG/SRS, WDF, SPC, JCAMP, OPUS a dalších formátů. Výsledek může být `NDDataset` nebo seznam datasetů; adaptér musí zpracovat oba případy. [Importní API](https://www.spectrochempy.fr/userguide/importexport/import.html).

SPA může obsahovat primární spektrální signál, samostatný interferogram nebo přidružené interferogramy vzorku a pozadí. `read_spa(..., return_ifg="sample"/"background")` vybírá přidružený interferogram; absence vrací `None`. Převzít souřadnice a metadata místo pevného odhadu jednotek z přípony. [SPA API](https://www.spectrochempy.fr/en/stable/reference/generated/spectrochempy.read_spa.html).

SPC může obsahovat více spekter se stejnými i různými osami X. V druhém případě se nemají automaticky spojit do jedné matice ani převzorkovat bez viditelné operace. [Příklady SPC](https://www.spectrochempy.fr/en/0.9.2/gettingstarted/examples/gallery/auto_examples_core/c_importer/plot_read_spc.html).

### JCAMP-DX

Čistě textový soubor neznamená běžnou dvojici číselných sloupců. Standard IR používá AFFN, PAC, SQZ, DIF a DUP včetně DIFDUP; je nutné respektovat XFACTOR/YFACTOR a kontrolní hodnoty. [Původní IR specifikace IUPAC](https://iupac.org/wp-content/uploads/2021/08/JCAMP-DX_IR_1988.pdf). Rodina formátů zahrnuje také další typy spektroskopie a NTUPLES; parser omezený na základní XYDATA musí jiné varianty odmítnout s konkrétní zprávou. [Protokoly IUPAC](https://stats.iupac.org/jcamp/protocols.html).

Projekt `nzhagen/jcamp` poskytuje nyní `readfile()` a `read()`, pole `x`/`y`, metadata a podbloky `children`. Starší návody používají jiné názvy funkcí; adapter se musí řídit připnutou verzí. [Zdroj API](https://github.com/nzhagen/jcamp/blob/master/jcamp.py).

## Vědecké podmínky operací

Druh spektroskopie a význam os mají být oddělená pole datového modelu. U importu neznámých TXT/CSV musí uživatel potvrdit, zda Y znamená absorbanci, transmitanci v podílu, transmitanci v procentech nebo relativní intenzitu. Převod pro dekadickou absorbanci: `A = -log10(T)` pro podíl, `A = -log10(%T / 100)` pro procenta; opačně `T = 10**(-A)`. Nulová či záporná transmitance nemá konečný logaritmus. Neopravovat takové body tichým ořezem. [Absorbance](https://goldbook.iupac.org/terms/view/A00028), [Transmitance](https://goldbook.iupac.org/terms/view/T06484/1000).

Savitzky–Golay validace musí kontrolovat délku okna, stupeň polynomu a rozestup vzorků pro derivaci. Nenutit nerovnoměrnou osu do algoritmu s jediným `delta`; nabídnout výslovné převzorkování nebo použít metodu odpovídající ose. [SciPy API](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html).

U transmitance odpovídají absorpční pásy minimům. Detekce píků musí respektovat tento význam. Zobrazení IR osy v sestupném směru je prezentační volba; při integraci a derivování rozhoduje skutečné pořadí a rozestup bodů. Normalizace a korekce základní linie mění kvantitativní význam spektra, proto se ukládá původní jednotka i historie změn.

## Lokální prostředí a ověření

`python3` v tomto prostředí má nainstalovány NumPy, SciPy, matplotlib, PySide6, openai, httpx a requests. Importní spec pro `renishawWiRE`, `wdf`, `spectrochempy`, `jcamp`, `spc` ani `spc_spectra` nebyl nalezen. Žádný balíček nebyl instalován. Binární adaptéry lze připravit bez instalace závislosti, ale uživatelské rozhraní pak musí správně hlásit chybějící čtečku.

Byly čteny oficiální dokumentace a distribuovaný WDF zdroj v paměti. První HTTPS pokus přes systémový `urllib` selhal na chybě lokálního certifikátu; následné čtení přes existující `requests` s ověřením TLS uspělo. API nebylo voláno s uživatelským klíčem; ověření autentizovaného spojení zůstává otevřené.


## Skutečně implementovaný rozsah

- TXT/CSV/TSV/DAT/ASC/XY/DPT: vícesloupcový import (první sloupec X, každý další Y), citované CSV, desetinná čárka při oddělovači středník/tabulátor/mezera, UTF-8/UTF-16 a fallback CP1250. Chybné číselné řádky jsou odmítnuty. Neimplementuje tabulky s prokládanými nezávislými dvojicemi X/Y nebo automatické odstranění chybějících hodnot.
- WDF1: vlastní čtečka základních float32 spekter s jednou sdílenou osou, sérií a mapovacích původních souřadnic. Multitrack, XYXY a filter images jsou odmítnuty; obrázky a fitované výsledky se neimportují. Ověřeno na nezměněném vendor fixture Si-map.wdf: 88 spekter × 575 bodů, intenzity souhlasí s nezávislými referenčními hodnotami upstream testů. Fixture s původem, hashem a Apache licencí je v tests/fixtures.
- SPA: čtečka primárního spektrálního payloadu; vyžaduje shodu hlavičky a délky dat. Původní fallback, který zkrácená data rozprostřel na celý rozsah X, byl odstraněn. Zachovává označené embedded textové píky (označené jako heuristické). Interferogramy odmítá. Úspěšně přechodně ověřeno na veřejných souborech 7_CZ0-100_Pd_3.SPA a _4.SPA z [testovacích dat SpectroChemPy](https://github.com/spectrochempy/spectrochempy_data/tree/master/testdata/irdata/subdir/1-20): 5549 bodů, absorbance, 649.921–5999.713 cm⁻¹; soubory nebyly začleněny do projektu, protože repository neuvádí datovou licenci. Veřejný interferogram interfero.SPA byl správně odmítnut.
- JCAMP-DX: AFFN/PAC XYDATA (X++(Y..Y)), XYPOINTS, scale factors a více samostatných bloků. SQZ/DIF/DUP, NTUPLES a peak tables mají jasnou chybovou zprávu.
- SPC: nová verze 0x4B/0x4C, jedno float32 spektrum s rovnoměrnou nebo explicitní osou X. Integer-scaled, multifile, XYXY a interferogramy jsou odmítnuty. Textový soubor s příponou SPC se nadále dá načíst jako text.
- SPG, SRS a OPUS: výše uvedené balíčky jsou doporučení k budoucímu rozšíření, nikoli aktuálně implementovaná podpora.

Veškerý import vrací konečná číselná pole se společným přeuspořádáním X/Y do vzestupného pořadí. Duplicitní X se odmítá. Jednospektrální legacy API odmítá soubor s více spektry, aby nedošlo k tiché ztrátě dalších měření. Metadata používají aplikační názvy `infrared`, `raman`, `uv_vis`, `custom` a `transmittance_fraction` / `transmittance_percent`. U nerozpoznaného významu Y se zachovává nativní popis a vyžaduje interpretace importními ovládacími prvky.

Validace: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src_python python3 -m unittest discover -s tests -p test_imports.py -v`, 17 testů úspěšně. První běh odhalil chybu při zkoušení nesprávného kandidátního oddělovače citovaného CSV; opraveno a zopakováno s úspěchem. Nové závislosti nebyly přidány ani nainstalovány.
