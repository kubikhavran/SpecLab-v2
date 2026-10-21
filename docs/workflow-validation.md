# Ověření pracovního postupu SpecLab

Implementace je v lokální větvi `codex/speclab-ai-redesign`. Změny nejsou odeslané na GitHub.

## Změněné soubory

- `app/main_window.py`: navigace 11 kroky, společný výběr rozsahu, správce spekter s přetažením pořadí a filtrem, porovnání výběru, sbalitelné podrobnosti, AI panel.
- `ui/workflow.py`, `ui/controls.py` (nové), `ui/theme.py`: kontextové nástroje, oddělené datové a grafické kroky, propojené posuvníky a číselná pole včetně exponentů, použití a reset.
- `ui/peaks_panel.py`, `ui/plot_widget.py`: přesné ruční přidávání píků, rozsahy parametrů, odebrání kliknutím, živé vodicí čáry, fyzické posuny popisků zachované při Full/Common scale, individuální čáry a viditelnost.
- `app/models.py`, `app/state.py`: režim měřítka zobrazení, libovolné pořadí, obecný reset operace, vratné nastavení vzhledu, izolovaný a atomický plán dat / grafiky / seznamu, kontrola zastarání.
- `core/collection.py`, `core/view.py` (nové): validace názvů / pořadí / stylů a společné transformace zobrazení.
- `core/processing.py`: násobení intenzity se záznamem do receptu.
- `core/ai_client.py`, `core/presentation.py`, `ui/ai_panel.py`: celý vzhled, názvy a pořadí, kontext výběru více spekter, volitelné odeslání názvů, čitelný návrh a samostatný náhled; JSON a připojení jsou rozbalitelné.
- `core/figure.py`: publikace přebírá čáry, barvy, písmo, značky, mřížku, pozadí a ruční pozice popisků; zachovává zvolený rozestup křivek a nenechá názvy utéct mimo stránku.
- `core/presets.py`, `ui/presets_panel.py`, `core/project_io.py`: přenos receptů a stylů podle pozic série, validace nových polí, volba přehrání původních dat. Při odlišném počtu spekter se použije uložený recept aktivního spektra na dávku.
- `requirements.txt`: doplněna deklarace matplotlib, který už používal stávající publikační renderer. Není zavedena nová knihovna ani změněn AI transport.
- `tests/test_workflow.py` (nové), `tests/test_ai.py`: integrační a regresní kontroly. Test zakazující rozsahy os v AI plánu byl aktualizován, protože jsou nyní podporované a validované.
- `README.md`, `docs/redesign.md`, `docs/workflow.md`: návod a mapa zachovaných funkcí.

## Příkazy a výsledky

Spouštěno z kořene SpecLab-v2:

```sh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
python3 -m ruff check src_python tests --output-format concise
git diff --check
```

Výchozí stav: 126 testů a 42 dílčích kontrol. Výsledný stav: 138 testů a 42 dílčích kontrol prošlo. Ruff a kontrola diffu prošly.

Navíc byl spuštěn skutečný Qt MainWindow s demonstračními daty, proveden baseline + smooth + detekce píků, ověřena okna 1500 × 940 a 1100 × 760, vytvořeny screenshoty jednotlivých kroků i AI panelu a skutečné PNG, SVG a PDF přes publikační renderer. Nejzazší název křivky v kontrolním exportu končí na 1584 px z 1600 px šířky.

Automatické kontroly pokrývají izolaci a jediné undo celého AI plánu, selhání bez částečných změn, zastarání nastavení, výběr / přejmenování / pořadí, společné a individuální měřítko bez změny dat, různé recepty série v presetu, projektový roundtrip, styl v exportu, ruční tažení a vodicí čáru, převod posunů popisků mezi měřítky, samotné značky bez textu, pozadí, viditelnost číselných polí a ruční exponenty. Zvláštní regresní test ověřuje, že použití náhledu spiků podle série nepřepne na běžný despike a nepozmění nedotčená spektra.

## Opravené problémy a meze ověření

Během přestavby byly opraveny: chybějící popisek prázdného formulářového řádku, vytlačení číselných polí mimo panel, chybné použití běžného filtru místo připraveného náhledu série, zastaralé návrhy vzhledu, ztráta individuálního stylu při resetu dat, přepsání globálního vzhledu v exportu, ignorované ruční pozice a oříznuté názvy. Dočasná chyba životního cyklu Qt v novém testu byla odstraněna řádným úklidem testovacích widgetů. Ve výsledné sadě nezůstává selhávající test.

Živý požadavek e-INFRA nebyl odeslán; síťová komunikace je ověřena existujícími testovacími transporty a lokální plán byl ověřen v aplikaci. Jeden AI požadavek dovoluje nejvýše 30 vybraných spekter. Názvy se posílají jen při výslovném zapnutí volby, cesty ani klíče v kontextu nejsou. Importéry a jejich formátové limity zůstávají popsány v README; nejde o nový příslib podpory všech proprietárních variant WDF / SPA / SPC. Reálná soukromá laboratorní data nebyla pro tuto přestavbu k dispozici. Ruční anotace a jejich přesné pozice jsou součástí projektu; přenositelný preset uchovává nastavení detekce a vzhledu, recepty a styly série.
