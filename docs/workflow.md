# SpecLab: pracovní postup

Vizuální záměr: klidný světlý pracovní prostor, velký graf a jeden právě otevřený krok. Tyrkysová označuje použití změny, tlumená červená reset. Navigace je volná; kroky se nemusí provádět všechny.

| Krok | Dostupné nástroje |
| --- | --- |
| 1. Spektra | Import všech stávajících formátů, vícenásobný výběr, názvy, pořadí, hromadné názvy, zobrazení výběru bez odebrání ostatních, technika a jednotky |
| 2. Rozsah a převody | Ořez dat, absorbance / transmitance, převzorkování |
| 3. Spiky | Lokální cosmic ray removal, série podle sousedů, ruční interpolace |
| 4. Baseline | AsLS, lambda, asymetrie, iterace, překryv baseline |
| 5. Šum a derivace | Savitzky–Golay, 1. / 2. derivace |
| 6. Měřítko dat | Normalizace max / vector / area / minmax, násobení intenzit, posun X/Y |
| 7. Píky | Detekce maxim / minim / obojího, region, prominence, vzdálenost, počet, ruční přidání a odebrání, tabulka a integrace |
| 8. Čáry a barvy | Globální paleta a šířka, individuální barva / šířka / styl / viditelnost křivky |
| 9. Osy a písmo | Názvy, písmo, velikosti, tučné / kurzíva, značky, mřížka, rámeček, rozsahy |
| 10. Rozložení a popisky | Common / Full scale jako zobrazení bez změny dat, rozestup série, pořadí, vzhled popisků a vodicích čar, ruční pozice |
| 11. Export a preset | Publikační PNG / SVG / PDF, náhled, CSV / TSV, původní data, píky, dávka a ZIP, rozměry, preset a projekt |

Trvale dostupné: aktivní spektrum, rozsah aplikace (aktivní / vybraná / všechna), porovnání, původní data, undo / redo, historie a AI. Parametry filtrů mají posuvník i číselné pole; filtry mění data až použitím. Vzhled má vlastní použití a reset. Reset filtru přehraje zbývající recept z originálu; neúspěšný přepočet nic nezmění.

AI asistent je agent, který SpecLab ovládá stejnými validovanými nástroji jako ruční kroky (zpracování, barvy a viditelnost křivek, pořadí a offset, popisky píků po spektrech, osy, písmo, rozměry). Pracuje na odděleném stavu a kontroluje vykreslený publikační obrázek. Výsledek se zobrazí v hlavním grafu a použije se jednou vratnou transakcí. Klíč, cesty k souborům ani zápis souborů agent nemá k dispozici. Preset přenáší recept a kompletní globální vzhled; projekt zachovává i individuální data, názvy, píky a pozice popisků.
