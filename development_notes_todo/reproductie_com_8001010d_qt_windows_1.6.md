# Reproductie 0x8001010D bij Qt/Windows — 25 oktober 2026

## Uitkomst

Dezelfde consolemelding als bij Portefeuille Viewer is op deze computer
reproduceerbaar met uitsluitend een leeg zichtbaar QWidget en QApplication.
Er zijn geen Access-, WebEngine- of portefeuille-imports nodig. Het testproces
blijft na de melding doorlopen en sluit normaal af met exitcode 0.

Dit bewijst dat die apponderdelen niet nodig zijn om deze melding uit te lokken.
Het is geen bewijs dat een specifieke Qt-DLL de fout bevat, dat iedere COM-fout
onschadelijk is, of dat de muisstotters dezelfde oorzaak hebben. Ook de invloed
van externe UI-Automation-clients op deze computer is nog niet geïsoleerd.

## Omgeving

- Windows, dezelfde desktop als de app, zonder gekoppelde debugger.
- Python 3.11.7, 64 bit; PySide6 en Qt 6.9.3; pyodbc 5.0.1 voor de Access-cases.
- `faulthandler.enable()` actief, gelijk aan de app.
- Proefvariabelen voor accessibility, Chromium, QPA en sandbox worden voor de
  matrixkindprocessen verwijderd; niet uit de gebruikersomgeving of appsettings.
- Geen nieuwe pakketten of wijzigingen aan geïnstalleerde Qt/Python-versies.

## Kleinste zelfstandige reproductie

`devtools/reproduce_qt_window_only.py` toont vier seconden een leeg, niet
activerend venster en sluit vanzelf. Geen database, appconfiguratie, netwerk,
worker of WebEngine. Tweemaal uitgevoerd: beide keren één `0x8001010D`, gevolgd
door `Qt eventloop klaar; exitcode 0`.

```powershell
cd C:\python_coding\portefeuille_viewer\portefeuille_viewer_1.6
C:\Python311\python.exe -m devtools.reproduce_qt_window_only
```

De reproductie hoort platform- en omgevingsafhankelijk te blijven: niet gebruiken
als algemene regressietest die eist dat een foutmelding altijd moet optreden.

## Matrix

`devtools/reproduce_qt_com.py` voert elke case uit in een apart proces met eigen
log. Testcases: Python, alleen Access, Qt, Qt+WebEngine, Qt+Access op de UI-thread,
Qt+Access op een vaste Python-thread, WebEngine+Access op beide routes en
WebEngine met de nieuwe STOCKDATA-worker. Ook een leeg QWidget kan apart getest.

Alle Access-cases gebruiken alleen een door het script nieuw gemaakte
`synthetic_qt_com.accdb`, met een markerrecord. Er wordt geen productiedatabase
geopend. De test biedt geen parameter voor een andere database. De bestaande
databaseworker is alleen in één expliciete case geïmporteerd.

| Opname | Processen | Processen met 0x8001010D | Niet-nul exitcode |
|---|---:|---:|---:|
| Zonder zichtbaar venster: 9 componentcases | 9 | 0 | 0 |
| Zichtbaar venster: 7 Qt-cases, ieder tweemaal | 14 | 14 | 0 |
| Leeg zichtbaar QWidget met native berichtregistratie, tweemaal | 2 | 2 | 0 |
| Kleinste zelfstandige script, tweemaal | 2 | 2 | 0 |

Webpagina's werden succesvol geladen vanuit lokale synthetische HTML; er was
geen website of marktdatabron betrokken. Leesacties op de synthetische database
werden op de bijbehorende cases zonder callbackfout voltooid.

De matrix ondersteunt ook `--surface offscreen`; die modus is voorbereid maar
is niet als aparte matrix uitgevoerd. `hidden` gebruikt juist het Windows-QPA-
platform met een aangemaakt maar niet getoond venster.

## Windows-bericht vlak voor de melding

De optionele passieve native eventfilter consumeert geen berichten en verandert
geen resultaten. In beide leeg-vensterproeven is de volgorde op dezelfde thread:

1. `WM_SHOWWINDOW`.
2. Qt-eventloop start.
3. `WM_GETOBJECT`, `lParam=-25`.
4. `Windows fatal exception: code 0x8001010d`.
5. Meer WM_GETOBJECT-berichten en uiteindelijk normale afsluiting.

WM_GETOBJECT wordt door Windows-toegankelijkheid/UI Automation gebruikt om een
provider voor een venster op te vragen. De waarneming wijst daarmee naar de
Qt/Windows UI-Automation-route, niet specifiek naar Chromium-renderer-accessibility.
Dat verklaart waarom de eerdere Chromium-flag geen verschil hoefde te maken.
Het betreft een aanwijzing uit berichtvolgorde, geen native dump met bewezen
DLL/functie of identificatie van de externe aanvrager.

Bronnen:
- [Microsoft WM_GETOBJECT](https://learn.microsoft.com/en-us/windows/win32/winauto/wm-getobject)
- [Qt 6.9 Windows UIA-afhandeling](https://github.com/qt/qtbase/blob/6.9/src/plugins/platforms/windows/uiautomation/qwindowsuiaaccessibility.cpp)
- [CPython 3.11 faulthandler](https://github.com/python/cpython/blob/3.11/Modules/faulthandler.c)

## Opnames en herhalen

Alle meetbestanden staan lokaal in `C:\python_coding\diagnostics`:

- `qt_com_repro_hidden_summary.json` en sessiemap `qt_com_repro_20261025_161032_968357`.
- `qt_com_repro_visible_summary.json` en sessiemap `qt_com_repro_20261025_161130_337940`.
- `qt_com_repro_empty_summary.json` en sessiemap `qt_com_repro_20261025_161327_088650`.
- `qt_window_only_1.log` en `qt_window_only_2.log`.

```powershell
python -m devtools.reproduce_qt_com --surface hidden --seconds 4
python -m devtools.reproduce_qt_com --surface visible --seconds 6 --repeat 2 --cases qt qt-web qt-access-ui qt-access-thread qt-web-access-ui qt-web-access-thread qt-web-appworker
python -m devtools.reproduce_qt_com --surface visible --seconds 5 --repeat 2 --cases qt-empty --native-messages
```

De zichtbare modus toont kort testvensters zonder toetsenbordfocus. Bij een
vastgelopen testcase begrenst de runner de wachttijd en beëindigt alleen het
eigen testproces en zijn eigen kinderen. Geen andere appprocessen worden gestopt.

## Vervolgadvies

Geen verdere database- of WebEngine-ombouw op basis van deze melding alleen.
De eerdere referentielijstcorrectie voorkomt wel onnodig databasewerk vanuit een
snapshotcallback, maar blijkt geen volledige oplossing voor deze COM-melding.

Een debugvlag voor faulthandler of een apart diagnostiekbestand kan de misleidende
console-uitvoer beperken; dat zou diagnostiekbeheer zijn, geen reparatie van COM.
Dit is in deze stap niet in de app toegepast. De performancetest van de nieuwe
databaseworkers blijft een afzonderlijk onderzoek.

In deze stap zijn uitsluitend twee reproductiescripts en dit verslag toegevoegd.
Geen productiecode, instellingen of productiedatabases aangepast.
