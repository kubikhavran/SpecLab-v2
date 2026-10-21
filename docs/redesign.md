# SpecLab Studio — redesign

Vizuální směr: klidný světlý laboratorní pracovní prostor, jemné šedé plochy, jeden petrolejový akcent a graf jako hlavní obsah.

Rozvržení: nahoře souborové akce a Zpět/Znovu; vlevo jedenáct kroků pracovního postupu, uprostřed graf s výběrem spekter a rozsahu aplikace, vpravo jen aktuální krok. Knihovna spekter je prvním krokem, grafika je oddělená od zpracování dat a preset uzavírá export. AI asistent dočasně nahradí panel kroku. Tabulky, historie a integrace se rozbalují na vyžádání. Podrobný rozpis: [workflow.md](workflow.md). Žádná marketingová úvodní obrazovka.

Interakce: plynulý zoom grafu, přetahování popisků píků a okamžité porovnání aktuálních dat s návrhem. Animace čísel a dekorací by zhoršovala přesnost odečítání; hlavní přechody jsou změna záložky a náhled křivky.

Numerické jádro zpracovává explicitní posloupnost operací. Importovaná data zůstávají dostupná; ruční kroky vždy pokračují z aktuálního výsledku. Hromadný krok je atomický, záznam obsahuje parametry a původ (manual / AI). AI nevrací Python kód ani nové naměřené hodnoty: vrací povolený JSON plán. Náhled ověřuje revizi vstupu před aplikací.

Implementace navazuje na již existující Python port SpecLab-v2. Zachovává původní analýzy a palety; hlavní okno, práce s náhledem, historie, importéry a AI workflow jsou nově navrženy. Podrobné zhodnocení rozdílů proti původnímu SpecLabu je v auditu.
