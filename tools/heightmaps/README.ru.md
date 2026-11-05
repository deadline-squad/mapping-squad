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
  в `ExcludedLayers.cfg`). Одна из 25 названных карт не имеет файлов уровня в пакете и в таблицу не вошла. Наши 25 карт: 24 играбельные карты таблицы плюс полигон Jensen.
* Слои из `LayerVoting.cfg` без `.umap` в сборке: `AlBasrah_Insurgency_v1`, `FoolsRoad_RAAS_v2`, `FoolsRoad_RAAS_v3`,
  `Kokan_RAAS_v2` (список голосования длиннее поставляемых слоёв; сами карты полные).
  Закомментированные `//` слои `Skirmish`/`Seed` не учитывались.
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
