# SpecLab Studio — redesign

Vizuální směr: klidný světlý laboratorní pracovní prostor, jemné šedé plochy, jeden petrolejový akcent a graf jako hlavní obsah.

Rozvržení: nahoře souborové akce a historie, vlevo knihovna spekter s jednotkami konkrétního měření, uprostřed graf a tabulky, vpravo inspektor zpracování / AI / vzhledu / exportu / předvoleb. Žádná marketingová úvodní obrazovka.

Interakce: plynulý zoom grafu, přetahování popisků píků a okamžité porovnání aktuálních dat s návrhem. Animace čísel a dekorací by zhoršovala přesnost odečítání; hlavní přechody jsou změna záložky a náhled křivky.

Numerické jádro zpracovává explicitní posloupnost operací. Importovaná data zůstávají dostupná; ruční kroky vždy pokračují z aktuálního výsledku. Hromadný krok je atomický, záznam obsahuje parametry a původ (manual / AI). AI nevrací Python kód ani nové naměřené hodnoty: vrací povolený JSON plán. Náhled ověřuje revizi vstupu před aplikací.

Implementace navazuje na již existující Python port SpecLab-v2. Zachovává původní analýzy a palety; hlavní okno, práce s náhledem, historie, importéry a AI workflow jsou nově navrženy. Podrobné zhodnocení rozdílů proti původnímu SpecLabu je v auditu.
