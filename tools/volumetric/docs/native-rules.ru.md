# Нативные правила выделенного сервера Squad (сборка 26005357)

Вопрос (пункт C7 плана в deadline-squad/deadline-squadcalc#22): три правила - нативный C++, а не cooked-ассеты:
(1) как игра превращает MaxHealth, модификаторы `AllowableDamageTypes`, множители прямого / косвенного / прямого радиального
попадания, `ImpactDamageToApply` и радиальный взрыв в урон по развёртываемому объекту; (2) динамический MOA оружия
(разброс очереди AGS-17, MK19, QLZ87); (3) какое расстояние меряется от взрыва до сооружения. English version: [`native-rules.md`](native-rules.md).

Метод: **только статический дизассемблинг** установленного у владельца `SquadGameServer` (ELF, non-PIE, BuildID
`b070e18070f98fc2c3b0cc27b0665dfc242b1d99`, 220 МБ, без символов функций, кроме 75 000 имён динамической таблицы, среди которых
все vtable C++). Ничего не запускалось, ничего не расшифровывалось и не обходилось, без сети, игровые хосты не тронуты.
Инструменты: `readelf`, `nm -D`, `objdump -d -M intel` по диапазонам адресов и короткий Python-помощник для карты строк, vtable и
таблиц рефлексии. Декомпилятора нет; каждое утверждение прочитано из инструкций.

Метки: **VERIFIED** = прочитано из машинного кода (байты инструкций закреплены `tests/test_native_rules.py`);
**INFERRED** = следует из прочитанного кода плюс довод по имени или раскладке; **NOT RECOVERED** = не найдено, с перечнем
попыток и минимальным замером в игре.

## 0. Как найден код (воспроизводимо)

* vtable классов: `nm -D -C SquadGameServer | grep "vtable for ASQDeployable"` даёт адрес; слот `i` - 8-байтовый указатель по
  `vtable + 0x10 + 8*i`. `ASQDeployable` = 0x2534380, `ASQVehicle` = 0x256e828, `ASQProjectile` = 0x23d1ee0, `ASQWeapon` =
  0x257f350, `AActor` = 0x19ad638. `TakeDamage` - слот 217 (смещение 0x6c8), `InternalTakeRadialDamage` - слот 218 (0x6d0),
  `InternalTakePointDamage` - слот 219 (0x6d8).
* Смещения свойств: таблицы рефлексии UE лежат в `.rodata`. Запись свойства: первое слово - указатель на имя, седьмое -
  `(смещение << 16) | размер_массива`. Строки имён (`AllowableDamageTypes`, `ExplosiveMinimumDamage`, ...) лежат в `.rodata`,
  поэтому поиск 8-байтовых указателей на них находит запись и смещение в C++-объекте. Пример: запись `AllowableDamageTypes` по
  0x22f8078 даёт смещение 0x438 в `ASQDeployable`.
* Якоря в коде: собственные строки лога игры (UTF-16), например `"ASQDeployable::TakeDamage[SQRadialDamage] %s for %f damage
  (type=%s) direct hit = %d"` по 0xdbb092, грузится `mov esi, imm32` по 0xa4978f2 внутри `ASQDeployable::TakeDamage`.

Структура `FSQDamageModifier` (элемент `AllowableDamageTypes`, размер 0x28, таблица свойств 0x22edb20): `DamageTypeClass`
+0x00, `Modifier` +0x08, `bForwardDamageToSoldier` +0x0c, `ForwardDamageToSoldierModifier` +0x10, `bForwardDeathToSoldier`
+0x14, `bIncapSoldierOnDeath` +0x15, `bOnlyPassDamageIfDirectHit` +0x16, `DirectHitDamageMultiplier` +0x18,
`IndirectHitDamageMultiplier` +0x1c, `DirectHitRadialDamageMultiplier` +0x20 (смещения float - из таблицы; смещения bool
следуют из порядка объявления и подтверждены кодом, читающим +0x16).

## 1. Урон по развёртываемому объекту

### 1.1 `ASQDeployable::TakeDamage` (0xa4970d0, слот vtable 217) - VERIFIED

Поля `ASQDeployable`: `MaxHealth` +0x424, `InitialHealth` +0x428, `Health` +0x42c, данные TArray `AllowableDamageTypes` +0x438,
число элементов +0x440. Аргументы: `xmm0` = DamageAmount, `rsi` = FDamageEvent, `rdx` = контроллер инициатора, `rcx` = причинитель.

1. `if (Health <= 0) return 0` (0xa4970ea). Без авторитета (`Role != 3`, байт +0x168) тело ниже пропускается, работает только
   `AActor::TakeDamage`, и Health на клиенте не меняется.
2. Таблица обходится с индекса 0 шагом 0x28 (0xa49748b-0xa4974c4); используется **первый элемент, у которого `DamageTypeClass`
   равен по указателю классу типа урона события** (0xa4974cf). Обхода `IsChildOf` нет: тип урона, не перечисленный дословно,
   не совпадает, даже если перечислен родительский класс.
3. **Тип урона не перечислен**: переход на 0xa4975f4, где вызывается `AActor::TakeDamage` (0x79fa950) с неизменённой величиной,
   но обновление Health ниже не выполняется. Итог: **здоровье не меняется** (раньше INFERRED по имени свойства, теперь VERIFIED).
4. Перечислен, событие **не** `FSQRadialDamageEvent` (точечный или общий урон; `event->IsOfType(1000)` ложно на 0xa4974e5):
   `D' = DamageAmount * Modifier` (0xa497a1d), затем `AActor::TakeDamage(D', ...)`. Ни один из трёх множителей попадания не используется.
5. Перечислен, событие **является** `FSQRadialDamageEvent` (id класса 1000; несёт `bDirectHit`, см. 1.3):
   * если `bOnlyPassDamageIfDirectHit` (+0x16, проверка 0xa497ac4): прямое попадание берёт смещение 0x18; промах даёт
     **нулевой урон, `AActor::TakeDamage` не вызывается**;
   * иначе смещение `0x18 + 4 * (не прямое)` (0xa497ae2): `DirectHitDamageMultiplier` при прямом попадании,
     `IndirectHitDamageMultiplier` в остальных случаях;
   * `D' = DamageAmount * Modifier * множитель` (0xa497af0-0xa497afd), затем `AActor::TakeDamage(D', ...)`.
   **`DirectHitRadialDamageMultiplier` (+0x20) код развёртываемых объектов не читает вообще.** Его читает код техники (1.5).
6. `AActor::TakeDamage` (0x79fa950) - функция движка. Для радиального события вызывает виртуальный `InternalTakeRadialDamage`,
   который у `ASQDeployable` собственный движковый (слот 218 совпадает с `AActor`, 0x79fb0a0, раздел 3); для точечного
   виртуальный слот 219 - пустая заглушка (`ret`, 0x48e20b0), то есть величина проходит как есть. Возвращает `ActualDamage`.
7. `if (байт +0x430 == 0) ActualDamage = 0` (0xa497b39). По порядку объявления байт после `Health` - `bCanUnbuild`
   (имя INFERRED); в ассетах он false только у вертолётной площадки и ноутбука Stugna, которых нет в таблицах урона,
   поэтому на таблицы не влияет.
8. `delta = ModifyHealthChange(-ActualDamage, инициатор, 1)` через виртуальный вызов (0xa22b9a0; реализация по умолчанию -
   пустая заглушка, то есть `delta = -ActualDamage`, если Blueprint не переопределяет - INFERRED, что у сооружений не
   переопределяет), затем `Health = clamp(Health + delta, 0, MaxHealth)` (0xa497b66-0xa497b86), затем хук после обновления (0xa22b780).

Итоговое правило для развёртываемого объекта (VERIFIED, кроме отмеченных шагов 7 и 8):

```
радиальный:  потеря = Lerp(Min, Base * Modifier * m, scale(d))   m = прямое ? DirectHit(+0x18) : Indirect(+0x1c); 0 если bOnly и промах
точечный  :  потеря = Amount * Modifier
Health = clamp(Health - потеря, 0, MaxHealth)
```

`Base`, `Min` - `ExplosiveBaseDamage` и `ExplosiveMinimumDamage` снаряда; `scale` и `d` - в 1.2 и разделе 3.
Реализовано в `semantics/native_rules.py` (`deployable_health_loss`), проверено в `tests/test_native_rules.py`.

### 1.2 Радиальный закон движка - VERIFIED

* `FRadialDamageParams::GetDamageScale` (0x7e7fc30): `inner = max(0, Inner)`, `outer = max(Outer, inner)`, `d = max(0, d)`;
  `d >= outer -> 0`; `d <= inner -> 1`; `Falloff == 0 -> 1`; иначе `(1 - (d - inner) / (outer - inner)) ^ Falloff` (`powf`,
  0xd362d90). Это в точности закон `squadDamage.js damageAtDistance`.
* `AActor::InternalTakeRadialDamage` (0x79fb0a0): `d = sqrt(min по ComponentHits от |ImpactPoint - Origin|^2)` (FLT_MAX без
  попаданий, scale 0), `scale = max(0, GetDamageScale(d))`, **`return Lerp(MinimumDamage, Damage, scale)`** =
  `Min + (Damage - Min) * scale` (0x79fb145-0x79fb158). Событие хранит `BaseDamage` +0x10, `MinimumDamage` +0x14, inner
  +0x18, outer +0x1c, falloff +0x20, origin +0x28, массив ComponentHits +0x40/+0x48, `bDirectHit` +0x50.

Следствие, которого не было в прежней документации и приложении: **`ExplosiveMinimumDamage` применяется после модификатора
сооружения и на него не умножается.** Пятнадцать Blueprint снарядов в дампе задают его, десять из них - в наборе снарядов приложения (раздел 5). Где `Min` больше модифицированного
урона, результат вдали от центра больше, чем в центре (125-мм HEAT, `Min` 35, по барьеру HESCO: `200 * 0.01 = 2` в центре,
`35 + (2 - 35) * 0.2304 = 27.4` на 10 м). Это прямо следует из инструкций; замера этого в игре нет (раздел 6).

### 1.3 Кто строит радиальное событие: `ASQProjectile::ApplyExplosiveDamage` (0xa745950) - VERIFIED

Нативное тело под именем `ApplyExplosiveDamage` (FName грузится по 0xa745c6c; название функции INFERRED по нему). Сразу
выходит, если не `bIsExplosiveProjectile` (+0x439). Точка взрыва - `ImpactPoint + ImpactNormal *
ExplosiveDamageDistanceFromImpactNormal` (+0x45c; умолчание C++ 20 см, конструктор 0xa731f5f, переопределяется в ассетах).
Затем вызывается радиальная функция Squad `0xa417230` с `(Base +0x43c, Minimum +0x440, KillZone +0x444, Inner +0x448, Outer
+0x44c, Falloff +0x450, DamageTypeToApply +0x2c8)` и `FHitResult` снаряда.

Умолчания C++ (конструктор 0xa731b80, VERIFIED): Base 115, Minimum 0, KillZone 0 (нулевая инициализация), Inner 500 см,
Outer 1500 см, Falloff 1.0, DistanceFromImpactNormal 20 см, `bIsExplosiveProjectile` false. «115 урона, 5-15 м, falloff 1»,
выведенные `gamecheck.py`, теперь VERIFIED, а Minimum по умолчанию равен 0.

`0xa417230` (вариант Squad для `ApplyRadialDamageWithFalloff`):

1. Сферическое пересечение в точке взрыва с радиусом = **Outer** (`FCollisionShape` типа 2, 0xa417312-0xa41731e), multi-hit.
2. Для каждого компонента - расстояние до его bounds как до выровненного по осям бокса (центр +0x108..0x118, полуразмер
   +0x120..0x130, 0xa417525-0xa417870). Если оно **меньше KillZone**, компонент берётся без проверки видимости, а его запись
   попадания - в мировой позиции компонента (+0x200, 0xa417898-0xa417969).
3. Иначе `0xa416c10` (`ComponentIsDamageableFrom`) делает **один трейс по каналу Visibility (3) от точки взрыва к центру
   bounds компонента** (0xa416c78-0xa416d9a); компонент засчитывается, только если первое блокирующее попадание принадлежит тому
   же актору, и возвращённый `FHitResult` (с `ImpactPoint` на поверхности, куда попал луч) добавляется в `ComponentHits` актора.
4. На актора строится одно `FSQRadialDamageEvent` (vtable 0x22f26b0, 0xa417ee1-0xa418164): тип урона, шесть чисел выше, точка
   взрыва, список попаданий, **`bDirectHit = (актор == актор попадания снаряда)`** (0xa4180f4-0xa418104), копия `FHitResult`
   снаряда; затем `actor->TakeDamage(Base, event, инициатор, причинитель)` (виртуальный 0x6c8). Передаётся `Base`; масштаб
   применяется в 1.1 и 1.2.

### 1.4 `ImpactDamageToApply` и вторичный взрыв - INFERRED / NOT RECOVERED

* Нативное свойство `ImpactDamageToApply` есть только у `ASQMortarProjectile` (+0x618, запись рефлексии 0x23a8d58); нативный
  код копирует его в структуру параметров порождаемого снаряда (0xa73bf0e). У ракет, танковых снарядов и остальных Blueprint
  снарядов поле `ImpactDamageToApply` в ассетах - **переменная Blueprint**, а граф Blueprint, который её использует, - cooked
  байткод Kismet, который экстрактор не декодирует. Так же `SecondaryExplosion*` и `SecondaryOnlyDamageMeshes` - не нативные
  имена свойств, а переменные Blueprint. **Как `ImpactDamageToApply` прямого попадания и вторичный взрыв доходят до
  `TakeDamage`, по ELF восстановить нельзя.**
* Что ELF подтверждает на принимающей стороне: событие точечного типа попадает в ветку 4 из 1.1 (`Amount * Modifier`, без
  множителя прямого попадания); обычный нативный путь отправки такого события - функция снаряда 0xa73eda0 (заполняет
  FSQPointDamageEvent, vtable 0x22f2678, значением `DamageTypeToApply` и вызывает виртуальный 0x6c8). Поэтому
  `ImpactDamageToApply * Modifier` для удара и радиальный от `ExplosiveBaseDamage` для взрыва согласуются с кодом, но какой
  тип урона и величину передаёт конкретный Blueprint - INFERRED.

### 1.5 Техника и огневые точки (`ASQVehicle::TakeDamage`, 0xa6edb10) - VERIFIED

У `ASQVehicle` (и `ASQDeployableVehicle`, `ASQDeployableTripodVehicle`, `ASQDeployableMortarVehicle`, `ASQHelicopter2`,
`ASQGroundVehicle`..., слот 217 общий) свой `AllowableDamageTypes` по +0x9c0 с теми же элементами `FSQDamageModifier` и тем же
точным совпадением класса. Для радиального события множитель выбирается на 0xa6ee14b-0xa6ee20f: при
`bOnlyPassDamageIfDirectHit` прямое попадание берёт смещение **0x20**, промах не даёт урона; иначе смещение `0x1c + 4 *
прямое`, то есть **`DirectHitRadialDamageMultiplier` при прямом попадании и `IndirectHitDamageMultiplier` иначе**. Значит,
таблица из трёх множителей означает: `DirectHitDamageMultiplier` у развёртываемых объектов,
`DirectHitRadialDamageMultiplier` у техники и огневых точек, `Indirect` у обоих. Какие классы `structure_damage.json` -
`ASQDeployable`, а какие `ASQDeployableVehicle`, данные не говорят: предметы-треноги и миномёты (`BP_AGS17_Tripod`, `BP_DShK`,
`BP_*mortar_Deployable`) имеют корень `BP_Deployable`, а само орудие - отдельная машина `/Game/Vehicles/Emplaced_*` со своей
таблицей (не извлечена). UNVERIFIED, по какому из двух попадает снаряд.

## 2. Динамический MOA (AGS-17, MK19, QLZ87) - ВОССТАНОВЛЕНО ЧАСТИЧНО

Подтверждено (ASQWeapon, vtable 0x257f350; таблица рефлексии статических данных оружия 0x2515f78):

* Поля статических данных: `MOA` +0x8c, `MOACurve` (UCurveFloat*) +0x90, `DynamicMOAGainMultiplier` +0x98,
  `DynamicMOADecayMultiplier` +0x9c.
* Экземпляр оружия: копия `MOA` по +0x74c (конструктор ставит 4.0 до переопределения ассетом, 0xa737cb0), указатель
  `MOACurve` +0x750 (в конструкторе null), float **динамического входа по +0x7ac**.
* `GetCurrentMOA` (0xa752640, exec-thunk 0xa38d940): `if (MOACurve валиден) return MOACurve->GetFloatValue(this[+0x7ac]); else
  return this[+0x74c]` (0xa752640-0xa75266f; `GetFloatValue` = 0x7d9b940).
* `GetMOAAdjustedAimDirection[FromRotator]` (0xa752310, 0xa752570) берут `GetCurrentMOA()` и передают в `ConvertMOAToRadians`
  (0xa4252c0) - полуугол конуса случайного направления пули.
* Композиция разброса (0xa662c00-0xa662e12, функция класса, чьи свойства `MOAInfantryMultiplier` +0x338 и
  `MOATurretMultiplier` +0x340 записаны по 0x22ce298): передаётся `K[+0x328] * (четыре слагаемых движения/прицеливания +
  GetCurrentMOA() * M)`, где на одной ветке (слабая ссылка на объект по +0x380 проходит проверку класса) `M =
  MOATurretMultiplier`, а каждое из четырёх слагаемых умножено на свой множитель [+0x344..+0x350], на другой `M =
  MOAInfantryMultiplier` и слагаемые без множителей. Сопоставление веток «турель» и «пехота» - INFERRED по именам свойств.
* Все три названных оружия используют одну кривую `/Game/Vehicles/FC_MOACurve_GenericGMG`: кубический Эрмит, ключи
  `(t = 0 с, 15 MOA)` и `(t = 0.75 с, 50 MOA)`, касательные 122.2 и 1.12 MOA/с. Интервалы между выстрелами 0.15 с (AGS-17),
  0.171 с (MK19), 0.125 с (QLZ87). Несколько оружий техники задают `DynamicMOAGainMultiplier = 1.2` и
  `DynamicMOADecayMultiplier = 1.1` (RHIB, LPPV, M1151, ...); у AGS-17, MK19 и QLZ87 не заданы ни тот, ни другой.

**NOT RECOVERED: как вход по +0x7ac растёт (gain) и убывает (decay).** Что пробовали: (а) все инструкции 145-МБ `.text` с
32-битным смещением 0x7ac (62 места; любой базовый регистр, включая SIB-формы с r12/rsp): записи только в
`ASQKillDeathRuleset`, постороннем классе, и в конструкторах; в `ASQWeapon` нет ничего, кроме 16-байтного обнуления в
конструкторе (0xa737e36); читатели - только три функции MOA выше. (б) читатели +0x98/+0x9c статических данных: смещения
совпадают с сотнями посторонних структур, ни одно не привязано к оружию. (в) вызывающие `GetCurrentMOA`: только композиция
разброса выше. Значит, в нативном бинарнике нет кода, меняющего вход; правило gain/decay, если оно есть, лежит в байткоде
Blueprint (не декодируется) или работает через рефлексию по имени свойства. Значение по умолчанию двух множителей, когда
ассет их не задаёт, тоже неизвестно.

Минимальный замер в игре (только Training, с разрешения владельца): из установки AGS-17 дать десять очередей по 10 выстрелов
в плоскую стену примерно в 100 м, сфотографировать картину попаданий и измерить радиус группы для 1-го, 5-го и 10-го выстрела.
Постоянный радиус, равный `15 MOA` на 100 м (около 0.44 м), означает, что вход остаётся 0 (кривая при t = 0, нативный
результат); радиус, растущий к `50 MOA` (около 1.45 м) примерно за 5 выстрелов (0.75 с / 0.15 с), означает, что вход ведёт
Blueprint; пауза 2 с между очередями и повтор отделяют decay. То же на MK19 (0.171 с) и QLZ87 (0.125 с) фиксирует временную шкалу.

## 3. Расстояние от взрыва до сооружения - VERIFIED

Расстояние, масштабирующее радиальный урон, в `InternalTakeRadialDamage` (1.2) - наименьшее расстояние от **точки взрыва** до
**`ImpactPoint` из `ComponentHits` актора**, а эти попадания приходят из 1.3:

* Точка взрыва = точка удара снаряда + 20 см (переопределяется ассетом) вдоль нормали удара. Это не конец траектории снаряда
  и не центр цели.
* Одно попадание на пересечённый компонент сооружения (у барьера HESCO их несколько): в обычном случае `ImpactPoint` - место,
  куда **луч от точки взрыва к центру bounds компонента первым попадает в геометрию сооружения по каналу Visibility**, то есть
  точка поверхности, обращённой к взрыву, а не ближайшая точка меша и не пивот. Компонент, чьё расстояние от bounding-box до
  взрыва меньше `ExplosiveKillZoneRadius` (значение ассета, по умолчанию 0), обходит луч и записывается в пивоте (мировая
  позиция). Компонент, чей луч перекрыт геометрией другого актора (стена между ними), вообще не записывается, поэтому
  полностью укрытое от взрыва сооружение радиального урона не получает.
* Сфера пересечения имеет радиус Outer, поэтому компонент за её пределами не рассматривается; закон затем использует
  расстояние луча, которое не меньше расстояния до бокса.
* Расстояния и радиусы - в единицах движка (см).

Что это значит для приложения: расстояние от точки падения снаряда до центра или маркера сооружения (как в `structureInfo.js`
с `DIRECT_HIT_RADIUS` = 1 м) завышает расстояние движка у больших сооружений (луч попадает в обращённую поверхность, на
полширины ближе) и не учитывает перекрытие. Пивот используется только внутри kill zone. Точное расстояние до грани требует
коллизии сооружения, а её даёт volumetric-инструментарий.

## 4. Где прежние документы и приложение совпадают или расходятся

| Утверждение в `structure-damage.md` разд. 4 / SquadCalc `structureDamage.js` | Результат |
|---|---|
| Точное совпадение класса в `AllowableDamageTypes`, не перечисленный тип урона - нет урона | **Совпадает**, теперь VERIFIED (1.1 шаги 2, 3) |
| Радиальный закон `damage * (1 - (d - inner) / (outer - inner)) ^ falloff`, полный внутри inner, ноль за outer | **Совпадает**, VERIFIED (1.2); движок добавляет `Lerp(Min, ...)`, см. ниже |
| Радиальный урон при прямом попадании использует `directRadial` (`DirectHitRadialDamageMultiplier`) | **Расходится для `ASQDeployable`**: используется `DirectHitDamageMultiplier`; `DirectHitRadialDamageMultiplier` читает только техника и огневые точки (1.1 шаг 5, 1.5). Ящики с боеприпасами (d 1 / r 0) при прямом попадании получают полный радиальный урон, а не ноль. |
| Прямое попадание ещё добавляет `impact * modifier * direct` | **Расходится**: точечный урон - `amount * Modifier` без множителя прямого попадания (1.1 шаг 4); множитель `direct` относится к радиальной части. Где `direct = 1` (почти все сооружения), числа не меняются. |
| Промах использует `indirect` | **Совпадает** (1.1 шаг 5); при `bOnlyPassDamageIfDirectHit` промах даёт 0, чего приложение не моделирует |
| `ExplosiveMinimumDamage` «расчётом не используется» | **Расходится**: это нижняя граница после модификатора (1.2). Ноль у большинства снарядов, ненулевой у десяти снарядов приложения (раздел 5) |
| Умолчания 115 / 5-15 м / falloff 1 (`gamecheck.py`) | **Совпадает**, VERIFIED (1.3), Minimum по умолчанию 0 |
| Расстояние до сооружения UNVERIFIED | **Решено** (раздел 3): от точки взрыва до точки луча на поверхности сооружения или до пивота внутри kill zone |
| Регенерация здоровья, влияние состояния постройки, `bForwardDamageToSoldier` | Этой работой не затронуто. В `TakeDamage` нет члена про состояние постройки; `bForwardDamageToSoldier` читается в радиальном/точечном путях (как именно - UNVERIFIED) |

Числа для приложений (исходники SquadCalc не правились): потеря игры за событие - `Lerp(Min, Base * Modifier * m, scale)`, где
`m = DirectHitDamageMultiplier` при прямом попадании и `IndirectHitDamageMultiplier` иначе для `ASQDeployable`; `Min`
ненулевой у снарядов раздела 5. Мина (`BP_Mortarround4`, `Min` 0, модификаторы 1) по барьеру HESCO не меняется относительно
разобранного примера (66.1 за выстрел, 4 выстрела).

## 5. Blueprint снарядов с ненулевым `ExplosiveMinimumDamage` (из cooked-ассетов)

Десять снарядов из `data/structure_damage.json` (слияние по цепочке Blueprint):

| снаряд | Minimum | Base | inner-outer (м) | falloff |
|---|---|---|---|---|
| BP_Projectile_76mm_HEAT, 115mm_HEAT, 125mm_HEAT | 35 | 200 | 3.5-16 | 2 |
| BP_Projectile_120mm_HEAT, BP_PF-98_HE_Proj | 50 | 200 | 7-20 | 2 |
| BP_Projectile_120mm_Smoke | 50 | 150 | 2-10 | 1 |
| BP_BM21_Rocket_Proj2 | 30 | 250 | 2-10 | 1 |
| BP_Projectile_100mm_Frag, 125mm_Frag | 10 | 300 | 4-35 | 5 |
| BP_Projectile_Hell_Cannon | 1 | 125 | 1-50 | 1 |

В сыром дампе есть ещё пять вне набора приложения (76-мм дымовой 50, 30-мм CAS 30, ракета S8 30, generic tank HE 50, бомба
500 фунтов 5, артиллерия 155 мм 1). Все остальные Blueprint снарядов, включая мины, оставляют нативный 0. Мина `BP_Mortarround4`
также несёт `ExplosiveDamageDistanceFromImpactNormal` 100 см, `ImpactDamageToApply` 10 (нативное поле `ASQMortarProjectile`) и
переменные `bUseSecondaryExplosion` / `SecondaryExplosion*`, которые являются переменными Blueprint (1.4).

## 6. Минимальные замеры в игре, которые закроют то, чего бинарник не даёт

Все на squad2 (DeadLine Training), ни одного на squad1, этой работой не выполнялись:

1. **Нижняя граница урона (1.2):** 125-мм HEAT (Min 35) по полностью целому барьеру HESCO (200 HP, BasicHeat 0.01): один снаряд
   примерно в 2 м и один примерно в 10 м от барьера, прочитать потерянное здоровье. Прогноз: около 2 и около 27.
2. **Множитель развёртываемого объекта и огневой точки (1.1, 1.5):** один BP_Ammocrate (d 1 / r 0): прямое попадание HEAT.
   Прогноз по коду: полный урон; по прежней формуле радиальная часть была бы нулевой.
3. **Путь ударного урона (1.4):** прямое попадание РПГ по HAB против промаха в 2 м тем же выстрелом; сравнить с
   `ImpactDamageToApply * Modifier` плюс радиальная часть.
4. **Динамический MOA (2):** тест размера группы AGS-17 выше.

## 7. Воспроизведение

| Результат | Команда / адрес |
|---|---|
| адрес vtable | `nm -D -C SquadGameServer \| grep "vtable for ASQDeployable$"` |
| байты функции | `objdump -d -M intel --start-address=0xa4970d0 --stop-address=0xa4983c0 SquadGameServer` |
| закреплённые байты инструкций | `python3 -m unittest tests.test_native_rules` (из `tools/volumetric`; `SQUAD_SERVER_ELF`, если бинарник в другом месте) |
| формулы | `semantics/native_rules.py` |

Вспомогательные скрипты поиска (поиск строк и vtable, разбор таблиц рефлексии, сканы смещений) были черновыми и в репозиторий
не входят; приведённые адреса воспроизводят каждое утверждение одним `objdump`.
