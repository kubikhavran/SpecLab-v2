# Architektura SpecLab Studio

Tento dokument popisuje aktuální desktopovou aplikaci Python/PySide6. Vstupním bodem je `src_python/main.py`; CLI vytvoří Qt aplikaci a hlavní okno, volitelně načte demo data nebo zadané soubory.

## Stav a transakce

- `src_python/app/state.py` obsahuje `AppState`: spektra, aktivní výběr, nastavení zobrazení a zpracování, píky, náhledy, receptury a historii původu změn.
- Importovaná data jsou uchována odděleně jako neměnné originály pro každé spektrum. `add_spectra` přidá dávku importovaných spekter.
- Zpracování probíhá jako náhled nad kopiemi dat. `preview_operations` ověří recepturu a připraví výsledek; `apply_preview` jej použije jako jedinou transakci.
- Undo/redo ukládá snapshoty. Snapshoty sdílejí nezměněné seznamy X/Y, proto se tyto seznamy nikdy nesmějí měnit na místě; vždy se musí nahradit novými seznamy.
- Posuny popisků píků se ukládají v metadatech spektra pod klíčem `peak_label_offsets`. Hodnoty jsou posuny vůči souřadnici příslušného píku, nikoli absolutní souřadnice grafu.
- Import, odebrání i vymazání spekter jsou transakce s undo; `_restore_transaction` při návratu bere přidaná/odebraná spektra z cílového snapshotu a u ostatních zachová pozdější netransakční změny (nastavení, výběr).
- UI sloty s delším během používají `ui/busy.py` (`with_busy_cursor`); zpracování běží ve vlákně UI.

## Zpracování a AI

- `src_python/core/processing.py` definuje whitelist operací v `DEFAULTS`, validaci parametrů a `run_operations`, které operace provádí v pořadí bez změny vstupů.
- `src_python/core/ai_client.py` poskytuje `EInfraClient`, `parse_plan` a `spectrum_context`. AI odpovídá pouze JSON plánem; plán prochází stejnou validací operací jako místní ovládací prvky. Žádný generovaný kód ani náhradní naměřená data se nevykonávají.
- Zpracovatelské panely v `src_python/ui/` sestaví operace a použijí cestu `AppState.preview_operations` → `AppState.apply_preview`. Ovládací panely vzhledu, píků a exportu upravují své příslušné nastavení nebo data jinými metodami stavu.

## Projekty a import

- `src_python/core/project_io.py` bezpečně ukládá a načítá verzovaný projekt JSON včetně původních a aktuálních dat, receptur, píků, nastavení a provenance. Runtime historie undo/redo ani API klíče se neukládají.
- `src_python/core/spectrum_parser.py` je vstupní dispatcher parserů. Textové tabulky zpracuje přímo; pro WDF, SPA, SPC a JCAMP-DX předává soubory modulům `wdf_parser.py`, `spa_parser.py`, `spc_parser.py` a `jcamp_parser.py` v `src_python/core/`.
- `src_python/app/main_window.py` propojuje `AppState`, graf, seznam spekter, tabulku píků, historii a panely UI. Jednotlivé panely jsou v `src_python/ui/`; graf zobrazuje aktuální data a náhledy.

## Testy

Testy jsou v kořenové složce `tests/`: `test_state.py`, `test_processing.py`, `test_ai.py`, `test_project.py`, `test_imports.py`, `test_exports.py` a `test_studio.py`. `pytest.ini` přidává `src_python` do importní cesty.

## Doplňky (2026-10-14)

- `core/sampling.py`: detekce mezer v ose X (krok > 3× typický); používají ji zpracování (filtry po úsecích), detekce píků (po úsecích) a graf (`connect="finite"`).
- `core/spa_parser.py`: píky z OMNIC – blok 104 (u32 počet; záznam u16 příznaky, f32 poloha píku, f32 poloha popisku, f32 intenzita, text NUL), záložně tabulka FIND PEAKS v bloku 130; NaN = vymazané oblasti.
- `ui/plot_widget.py`: `place_labels` (hladové umístění bez kolizí, priorita podle prominence), `label_anchor`, rezerva rozsahu osy pro popisky; přepočet při `sigRangeChanged`/`sigResized` (i při exportu).
- `core/presentation.py`: whitelist vzhledu pro AI (`graphics`, `peaks` vč. `relative_prominence`, `plot`, `detect_peaks`), aplikace přes `AppState.apply_presentation`.

