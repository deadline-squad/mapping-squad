# Точные карты высот из файлов игры: инвентарь карт (RU)

Основной текст: `README.md`. Здесь описано, какие карты выделенный сервер Squad действительно может играть.

## Инвентарь карт: что есть в пакете сервера

Доказательства: сборка выделенного сервера 26005357 (`steamapps/appmanifest_403240.acf`), `ServerConfig/LayerVoting.cfg` и
`LevelRotation.cfg`, `Manifest_UFSFiles_Linux.txt` (88727 записей `.uasset`/`.umap`, ровно столько же файлов в индексе паков
по `SquadExtract list`, то есть установка полная) и содержимое паков. Карта *играбельна*, если она есть в `LevelRotation.cfg` и
поставляются её игровые слои (`Content/Maps/<папка>/Gameplay_Layers/<Layer_Id>.umap`, либо `Content/Maps/Gameplay_Layers` плагина).

| Карта | Слоёв в LayerVoting.cfg | из них с `.umap` слоя в сборке | в LevelRotation.cfg | карта высот у нас |
|---|---|---|---|---|
| AlBasrah | 7 | 6 | yes | yes |
| Anvil | 4 | 4 | yes | yes |
| Belaya | 6 | 0 | yes | только рельеф, SquadHeight (не из пакета) |
| BlackCoast | 6 | 6 | yes | yes |
| Chora | 8 | 8 | yes | yes |
| Fallujah | 7 | 7 | yes | yes |
| FoolsRoad | 8 | 6 | yes | yes |
| GooseBay | 4 | 4 | yes | yes |
| Gorodok | 8 | 8 | yes | yes |
| Harju | 9 | 9 | yes | yes |
| Kamdesh | 5 | 5 | yes | yes |
| Kohat | 5 | 5 | yes | yes |
| Kokan | 7 | 6 | yes | yes |
| Lashkar | 7 | 7 | yes | yes |
| Logar | 4 | 4 | yes | yes |
| Manicouagan | 6 | 6 | yes | yes |
| Mestia | 5 | 5 | yes | yes |
| Mutaha | 6 | 6 | yes | yes |
| Narva | 8 | 8 | yes | yes |
| PacificProvingGrounds | 1 | 1 | yes | yes |
| Sanxian | 7 | 7 | yes | yes |
| Skorpo | 3 | 3 | yes | yes |
| Sumari | 7 | 7 | yes | yes |
| Tallil | 5 | 5 | yes | yes |
| Yehorivka | 9 | 9 | yes | yes |

* В `LevelRotation.cfg` 25 карт; `Jensen` (Jensen's Range) среди них нет (`ExcludedLevels.cfg` исключает `JensensRange`, его слои
  в `ExcludedLayers.cfg`). Наши 25 карт: 24 играбельные плюс полигон Jensen; 25 играбельных карт сервера: наши 24 плюс Belaya.
* Слои из `LayerVoting.cfg` без `.umap` в сборке: `AlBasrah_Insurgency_v1`, `FoolsRoad_RAAS_v2`, `FoolsRoad_RAAS_v3`,
  `Kokan_RAAS_v2` (список голосования длиннее поставляемых слоёв; сами карты полные). Строка `Anvil_TC_v1Belaya_AAS_v1` склеена
  без перевода строки и не совпадает ни с одним слоем: `Belaya_AAS_v1` тоже не голосуется (у Belaya 6 читаемых слоёв плюс этот).
  Закомментированные `//` слои `Skirmish`/`Seed` не учитывались.
* **Belaya прописана в конфигах, но не поставляется.** строк с `grep -i belaya`: по 9 в `LayerVoting.cfg`, `LayerVotingNight.cfg`,
  `LayerVotingLowPlayers.cfg` и 1 в `LevelRotation.cfg`; но в паках 49 файлов с «Belaya» в пути, и ни один не `.umap`: только
  арт (`Content/Maps/Belaya_Pass/`: материалы и нормали окружающего рельефа, материалы скал и снега, миникарта и экраны
  загрузки, частицы `Belaya_Snow`, материалы воды, музыка загрузки). Нет ни уровня, ни ландшафта, ни слоёв, поэтому
  коллизия ландшафта и статические меши, которые читает `heightmaps.sh extract`, для Belaya в этой сборке не существуют, и карта
  высот, экспорт статики и воксельный слой из неё не строятся (в SquadHeight 1.3.0 Belaya есть, экспорт июня 2026 из Mod SDK,
  границы x -1954..1950, y -2080..1825, но он не из пакета сервера, и сплавить или проверить его по пакету нельзя; он выложен
  как карта только с рельефом и пониженным происхождением данных, см. следующий раздел). Текстура миникарты `Belaya_Minimap`
  есть в пакете только как заголовок ассета (импортированный размер 4096 x 4096, `SizeX` 0, мипов нет: выделенный сервер
  вырезает пиксели текстур; `SquadExtract texture` для неё ничего не пишет), поэтому и картинку карты из пакета не достать.
* **Неиграбельны, только дескриптор плагина:** `Plugins/Expansions/{Aussie,EastAsia,Haiyan,MijinHighway,OperationDragonfly,
  OskilRiver,Saaremaa,Yehorivka_Remaster,PCG_Test}`: по одному файлу `.uplugin` (ни `.umap`, ни ассетов); так же дескрипторы
  `Expansions/{Gorodok,Mestia,Narva,Yehorivka}`, чьё содержимое лежит в `Content/Maps`. `Content/Maps/Forest`: 42 файла
  текстур и материалов без уровня. Ни одного из этих имён нет в `LayerVoting.cfg` и `LevelRotation.cfg`.
  Плагины с содержимым: `Al_Basrah` (347 файлов), `Expansions/BlackCoast` (353), `Expansions/Harju` (287),
  `Expansions/SanxianIslands` (309).
* **Yehorivka_Remaster не заменяет Yehorivka.** В плагине ремастера в этой сборке нет содержимого (один `.uplugin`), а девять
  играбельных слоёв Yehorivka подгружают `Maps/Yehorivka/Sublevels/070_Landscape/L_070_Landscape_Yehorivka`
  (`SquadExtract json <слой>.umap LevelStreamingAlwaysLoaded` для `Yehorivka_AAS_v1`, `_RAAS_v1`, `_Invasion_v2`; ни один
  потоковый уровень не называет ремастер). Это тот ландшафт, который извлекает `py/maps.py`, данные Yehorivka актуальны.
  Они устареют, только когда сборка поставит содержимое ремастера и его слои.

## Belaya Pass: только рельеф, данные сообщества

Belaya Pass - 26-я играбельная карта, но ничего из неё не получено из пакета сервера (см. инвентарь выше). Калькулятор показывает
её с картой высот SquadHeight 1.3.0 (выгрузка Squad Mod SDK за июнь 2026, верхний трейс коллизии SDK, сетка 1 м, 3905 x 3906
отсчётов, x -1954..1950, y -2080..1825, z -307,2..-150,5 м) и больше ни с чем. Это сказано в `meta.json`: `"provenance":
"SquadHeight 1.3.0 (Mod SDK export), terrain only, not validated against server data"`, в `sources` только `sdk_surface`,
`stats` пуст, записи `volume` нет (тогда страница использует карту высот, как для любой карты без воксельного слоя). Поверхность
SDK включает всё, во что попал трейс (скалы, здания, мосты: 424 861 ячейка построек по статистике самой выгрузки), но земля и
объекты не разделены, и ни одна проверка из этого файла к ней не применима: нет вершин ландшафта для сравнения, нет эталона
с сервера, нет полноты и точности объектов, нет цифры точности. Цифры других карт для неё не приводить. Относительно самого
SquadHeight выложенный PNG точен (0,0 м), WebP в пределах половины шага 1 см (5 мм).

```sh
tools/heightmaps/heightmaps.sh belaya    # $SQUADHEIGHT/Belaya -> $OUT/belaya/{heightmap.png,heightmap.webp,meta.json}
```

Это делает `py/build_squadheight_only.py` (тесты: `python -m unittest test_build_squadheight_only`). Собственная 8-битная
`heightmap.png` SquadCalc для Belaya (`squadcalc.app/api/img/maps/belaya/`, запасная, когда точную не скачать) на той же сетке:
её уровни, умноженные на 0,307176 м, воспроизводят SquadHeight со СКО 8,8 см (квантование 8 бит, шаг 0,31 м). Архив рельефа
строится `maptiles.sh relief belaya` на `maptiles/belaya/meta.json` с одной рамкой `bounds_m` (тайлов Detailed у карты нет);
топометрия - `topometrics_cli.py`, как для остальных.

Чтобы добавить Belaya (или любую карту), когда её файлы появятся в пакете: `SquadExtract list Belaya` должен показать `.umap`;
затем запись в `py/maps.py` с её ландшафтным уровнем, `extract`, `build belaya` (он заменит карту сообщества) и шаги остальных карт (тайлы рельефа,
топометрия, статика, воксели, `src/data/maps.js`, локали).
