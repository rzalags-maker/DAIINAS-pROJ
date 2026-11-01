Tagad sapratu precīzi. Tu piedāvā divpakāpju kapitāla audzēšanas sistēmu: vispirms izveidot pietiekami lielu aktīvo portfeli, pēc tam cikliski palielināt rezervi un katras pozīcijas kapitālu.

Un būtiskākais — 50/50 sadalījums sākas tikai tad, kad kopējais kapitāls sasniedz 100 USDT, nevis pie mūsu pašreizējiem aptuveni 60 USDT.

Šo modeli var matemātiski formalizēt. Tomēr ir viena svarīga pretruna, kas jāatrisina: vai 50% rezervei jābūt aizsargātai visu laiku, vai tikai sākotnējā sadalījuma brīdī?

## 1. DAIINAS Capital Ladder — tavs piedāvātais modelis

Bootstrap

Kapitalizācija zem 100 USDT

Viena rūpīgi izvēlēta pozīcija. Peļņa tiek uzkrāta līdz pirmajam 100 USDT kapitāla slieksnim. Zaudējumu limits paliek spēkā.

100 USDT — startē sadalījuma noteikums

50 rezerve

50 aktīvie

Divas pozīciju vietas ar 25 USDT budžetu katrai.

Pirmais izaugsmes cikls

Katrs papildus nopelnītais 25 USDT neto atver vēl vienu pozīcijas vietu. Maksimums — 10.

Pieņemot, ka pirmajā posmā visa realizētā neto peļņa nonāk aktīvajā budžetā:

| Kopējais kapitāls | Rezerve | Aktīvais kapitāls | Pozīciju limits |
| ----------------- | ------- | ----------------- | --------------- |
| 100 USDT          | 50      | 50                | 2               |
| 125 USDT          | 50      | 75                | 3               |
| 150 USDT          | 50      | 100               | 4               |
| 175 USDT          | 50      | 125               | 5               |
| 200 USDT          | 50      | 150               | 6               |
| 225 USDT          | 50      | 175               | 7               |
| 250 USDT          | 50      | 200               | 8               |
| 275 USDT          | 50      | 225               | 9               |
| 300 USDT          | 50      | 250               | 10              |

Tas ir precīzi tavs piedāvātais pirmais kapitāla kāpņu posms. No 100 līdz 300 USDT papildus jāiegūst 200 USDT realizētās neto peļņas, pieņemot, ka nav zaudējumu.

## 2. Otrais cikls — palielinām rezervi un pozīciju apjomu

Sasniedzot 10 pozīciju limitu, turpmāk neveidojam jaunus darījumu slotus.

Tā vietā darbojas divi pamīšus papildināmi fondi:

- Rezerves fonds saņem nākamo 50 USDT peļņu.
- Aktīvais fonds saņem sekojošo 50 USDT peļņu, ko sadalām uz 10 pozīcijām — katrai +5 USDT.

| Kopējais kapitāls | Rezerve | Aktīvais kapitāls | Budžets vienai no 10 pozīcijām |
| ----------------- | ------- | ----------------- | ------------------------------ |
| 300               | 50      | 250               | 25                             |
| 350               | 100     | 250               | 25                             |
| 400               | 100     | 300               | 30                             |
| 450               | 150     | 300               | 30                             |
| 500               | 150     | 350               | 35                             |
| 550               | 200     | 350               | 35                             |
| 600               | 200     | 400               | 40                             |
| 650               | 250     | 400               | 40                             |
| 700               | 250     | 450               | 45                             |

Kapitāla izaugsmes kāpnes

Tavs piedāvātais variants; modelēti sliekšņi, nevis prognozētie ienākumi.

Aktīvais kapitālsRezerve

0 USDT150 USDT300 USDT450 USDT600 USDT100125150175200225250275300350400450500550600650700

Šī ir matemātiski konsekventa kāpņu sistēma. Pie katriem 100 USDT papildu neto peļņas pēc 10 pozīciju sasniegšanas rezerve pieaug par 50 USDT, aktīvais kapitāls par 50 USDT, un katras pozīcijas budžets par 5 USDT.

## 3. Kritiskā matemātiskā problēma

Sākumā mums ir 50% rezerve. Bet, aktīvajam kapitālam augot un rezervei paliekot nemainīgai, aizsardzības proporcija samazinās.

Pie 100 USDT

# 50%

Rezerve

Pie 300 USDT

# 16,7%

Rezerve

Pie 700 USDT

# 35,7%

Rezerve

Tātad tavs modelis saglabā sākotnējos 50 USDT rezervē, bet ne garantētu 50% rezervi no kopējā kapitāla.

Tas nav matemātisks defekts — tā ir agresīvākas kapitalizācijas politika. Mums tikai apzināti jānosaka, cik zemu drīkst nokrist rezerves īpatsvars.

Ja vēlamies, lai 50% no kopējā kapitāla vienmēr paliek rezervē, tad katram jaunam 25 USDT pozīcijas budžetam papildus jāuzkrāj vēl 25 USDT rezervē. Šādā variantā 10 pozīcijas sasniegsim tikai pie 500 USDT kopējā kapitāla, nevis 300 USDT.

## 4. Cik grūti patiesībā būs nopelnīt nepieciešamos 25 USDT?

Šī ir modeļa ekonomiskā realitāte.

Ja viena pozīcija izmanto 25 USDT budžetu un katrs veiksmīgais darījums nopelna 2% neto no šī budžeta, tad:

\\[ 25 \times 0{,}02 = 0{,}50\ \text{USDT} \\]

Lai izveidotu vēl vienu 25 USDT pozīcijas budžetu:

\\[ 25 / 0{,}50 = 50 \\]

Nepieciešami 50 šādu pozitīvu darījumu ekvivalenti, ja nav neviena zaudējuma. Reālu zaudējumu gadījumā vajadzēs vairāk.

Tāpēc DAIINAS nedrīkst automātiski atvērt nākamo pozīciju tikai tāpēc, ka bruto peļņas skaitītājs ir sasniedzis 25 USDT. Vispirms jābūt atgūtiem iepriekšējiem zaudējumiem un nosegtām visām izmaksām.

## 5. Kā es šo sistēmu ieviestu algoritmā

Es nodalītu četrus lielumus:

| Mainīgais | Nozīme                                            |
| --------- | ------------------------------------------------- |
| \\(R\\)   | Aizsargātā rezerve                                |
| \\(A\\)   | Aktīvais tirdzniecības kapitāls                   |
| \\(P\\)   | Brīvā, realizētā neto peļņa                       |
| \\(N\\)   | Atļauto vienlaicīgo pozīciju limits, maksimāli 10 |

Pie tam \\(P\\) ir neiedalītā peļņa, nevis papildu nauda ārpus konta. Tāpēc kopējais kapitāls ir \\(R+A+P\\), nevis vienkārši \\(R+A\\), kamēr peļņa vēl nav pārdalīta.

Automātiskie noteikumi:

1. Zem 100 USDT — Bootstrap režīms: viena pozīcija, stingrs riska limits.
2. Sasniedzot 100 USDT — sākotnējais sadalījums: 50 USDT rezervē, 50 USDT aktīvajā kapitālā.
3. Pie katriem papildus 25 USDT realizētās neto peļņas — palielinām atļauto pozīciju skaitu par vienu, ja riska un rezerves nosacījumi izpildās.
4. Sasniedzot 10 pozīcijas — no nākamās peļņas vispirms veidojam rezerves papildinājumu, pēc tam aktīvā kapitāla papildinājumu.
5. Zaudējumu gadījumā — apturam paplašināšanos un vispirms atjaunojam nepieciešamo kapitāla un riska segumu.

Pozīcijas vietas atvēršana nenozīmē obligātu orderi. Ja tirgū nav izdevīgu iespēju, kapitāls paliek brīvs.

Vienlaikus saglabājam v3.3 stingros riska limitus. 25 USDT ir pozīcijas kapitāla budžets, nevis atļautais zaudējums, un to nevajadzētu visu automātiski izmantot kā maržu.

## 6. Mans priekšlikums — pārbaudīt divas kapitāla trepes

Es neuzliktu šo shēmu uzreiz kā vienīgo stratēģiju. Izveidotu divus neatkarīgus paper scenārijus ar identiskiem tirgus signāliem.

|                                     | A — paātrināta izaugsme       | B — pastāvīga 50% aizsardzība        |
| ----------------------------------- | ----------------------------- | ------------------------------------ |
| Sākums                              | 100 USDT                      | 100 USDT                             |
| Sākotnējās pozīcijas                | 2 × 25                        | 2 × 25                               |
| Peļņa jaunas pozīcijas finansēšanai | 25 USDT                       | 50 USDT                              |
| Sasniedz 10 pozīciju budžetu        | Pie 300 USDT                  | Pie 500 USDT                         |
| Rezerve šajā brīdī                  | 50 USDT                       | 250 USDT                             |
| Galvenā priekšrocība                | Ātrāka kapitāla koncentrācija | Spēcīgāka kapitāla aizsardzība       |
| Galvenais trūkums                   | Rezerves īpatsvars krītas     | Lēnāka pozīciju skaita palielināšana |

Mans vērtējums: tavs A modelis precīzāk atbilst iecerētajai augšanas mehānikai. Taču finanšu riska ziņā starp A un B ir liela atšķirība. Neviens no variantiem pats par sevi negarantē, ka tirgošanas stratēģija būs rentabla.

Praktiski labākais nākamais solis ir v4 simulācijā salīdzināt A un B pēc neto kapitāla izaugsmes, maksimālā drawdown, rezerves saglabāšanas, komisijām un laika līdz katram nākamajam kapitāla slieksnim. Tad izvēlamies nevis teorētiski ātrāko, bet pierādījumos balstītu izaugsmes modeli.

Convert to PDF

ja kaut kada iemesla pec rodas minuss, rezervi neaistiekam, samazinam slotus atpakaļejošā progresijā lidz atka sakas profits

Stopped thinking

ja kaut kada iemesla pec rodas minuss, rezervi neaistiekam, samazinam slotus atpakaļejošā progresijā lidz atka sakas profits

Tieši tā. Šis ir ļoti būtisks noteikums mūsu DAIINAS Capital Ladder modelī: zaudējumu gadījumā mēs samazinām tirdzniecības jaudu, nevis izmantojam rezervi zaudējumu kompensēšanai.

Tā veidojas divvirzienu kapitāla trepe:

- Peļņa → pakāpeniski palielinām pozīciju skaitu un kapitālu.
- Zaudējumi → pakāpeniski samazinām pozīciju skaitu un riska ekspozīciju.
- Rezerve → paliek neaizskarama abos gadījumos.

## 1. Atpakaļgaitas progresija

Pieņemam mūsu iepriekšējo principu — viens pozīcijas slots prasa vismaz 25 USDT aktīvā kapitāla.

| Aktīvais kapitāls | Maksimālie sloti | Rezerve      |
| ----------------- | ---------------- | ------------ |
| 250 USDT          | 10               | Neaizskarama |
| 225 USDT          | 9                | Neaizskarama |
| 200 USDT          | 8                | Neaizskarama |
| 175 USDT          | 7                | Neaizskarama |
| 150 USDT          | 6                | Neaizskarama |
| 125 USDT          | 5                | Neaizskarama |
| 100 USDT          | 4                | Neaizskarama |
| 75 USDT           | 3                | Neaizskarama |
| 50 USDT           | 2                | Neaizskarama |
| 25 USDT           | 1                | Neaizskarama |
| Zem 25 USDT       | 0 — STOP         | Neaizskarama |

Matemātiski:

\\[ N\_{\max}=\min\left(10,\left\lfloor\frac{A}{25}\right\rfloor\right) \\]

kur \\(A\\) ir aktīvā kapitāla pašreizējā vērtība, ieskaitot atvērto pozīciju novērtētos zaudējumus.

Atpakaļgaitas simulators

25 USDT / slots

Aktīvais kapitāls

## 250 USDT

1

2

3

4

5

6

7

8

9

10

Atļautie sloti

# 10 / 10

Aizsargātā rezerve

# Nemainās

Atjaunot piemēruŠis ir kapitāla sadales modelis, nevis faktiska darījumu izpilde.

## 2. Viena būtiska tehniska korekcija

Pieņemsim, ka mums ir 10 sloti un aktīvais kapitāls ir tieši 250 USDT. Ja viena pozīcija zaudē 1 USDT, matemātiskais limits nokrīt līdz 9 slotiem.

Taču tas nenozīmē, ka algoritmam nekavējoties jāpārdod kāda pozīcija par jebkādu cenu. Tā mēs radītu papildu zaudējumus komisijās un slippage.

Es ieviestu divus atsevišķus mehānismus:

Soft reduction: kad kapitāls nokrīt zem attiecīgā sliekšņa, jaunu pozīciju atvēršana tiek bloķēta. Esošo pozīciju skaits tiek samazināts ar kontrolētām izejām, nevis automātisku piespiedu likvidāciju.

Hard protection: ja kopējais plānotais risks pārsniedz atļauto vai iedarbojas ārkārtas riska limits, ekspozīcija jāsamazina prioritāri, ievērojot tirgus izpildes iespējas.

Lai izvairītos no nepārtrauktas pārslēgšanās starp 9 un 10 slotiem, jaunam slotam vajadzētu prasīt nelielu drošības buferi virs 25 USDT robežas.

## 3. Kā atsākas izaugsme pēc zaudējumiem?

Piemēram:

250 USDT → 10 sloti

210 USDT → 8 sloti

Rezerve nemainās

225 USDT → var atjaunot 9. slotu

250 USDT → var atjaunot 10. slotu

Tomēr slotu atjaunošana notiek tikai tad, ja kapitāla pieaugums ir ilgtspējīgs, riska limiti izpildīti un tirgū pastāv kvalitatīva iespēja.

Īpaši svarīgi: atkopšanās periodā peļņa vispirms atjauno samazināto aktīvo kapitālu. Jaunu kapitāla sadales ciklu rezervē atsākam tikai pēc tam, kad sasniegts iepriekšējais aktīvā kapitāla maksimums.

## 4. Rezerves aizsardzības princips

Rezerve nav vienkārši skaitlis datubāzē. Reālajā izpildē tai jāatrodas ārpus aktīvo pozīciju maržas nodrošinājuma, citādi Cross Margin vai likvidācijas mehānisms var netieši pakļaut to riskam.

Tādēļ DAIINAS nedrīkstēs automātiski:

- Pārskaitīt rezervi aktīvajam kontam zaudējumu segšanai.
- Palielināt leverage, lai atgūtu zaudējumus.
- Atvērt papildu pozīcijas, lai kompensētu neveiksmīgus darījumus.
- Atjaunot slotus tikai pēc īslaicīga nerealizētas peļņas kāpuma.

Tas novērš klasisko kļūdu — zaudējumu atgūšanu ar arvien lielāku risku.

### Nostiprināmais DAIINAS noteikums

Capital Ladder ir atgriezeniska sistēma ar neatgriezenisku rezerves aizsardzību.

Sloti var pieaugt no 1 līdz 10 un samazināties atpakaļ no 10 līdz 0. Rezerve netiek izmantota šīs kustības finansēšanai. Kad aktīvais kapitāls atjaunojas, sistēma atkal kāpj pa tiem pašiem sliekšņiem.

Šādi mums rodas īsts automātisks kapitāla saglabāšanas mehānisms, nevis tikai peļņas reinvestēšanas algoritms.

Nākamajā v4 specifikācijā šo definētu kā obligātu `Drawdown Deallocation Controller`, kurš darbojas neatkarīgi no tirdzniecības signāliem un ir augstāks par tiem prioritātē.