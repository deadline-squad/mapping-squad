# Native rules of the Squad dedicated server (build 26005357)

Question (plan item C7 of deadline-squad/deadline-squadcalc#22): three rules are native C++ and not in the cooked assets:
(1) how the game turns MaxHealth, the `AllowableDamageTypes` modifiers, the direct / indirect / direct-radial multipliers,
`ImpactDamageToApply` and the radial explosion into damage to a deployable; (2) the dynamic MOA of weapons (AGS-17, MK19,
QLZ87 burst spread); (3) which distance is measured from an explosion to a structure. Russian version: [`native-rules.ru.md`](native-rules.ru.md).

Method: **static disassembly only** of the owner's installed `SquadGameServer` (ELF, non-PIE, BuildID
`b070e18070f98fc2c3b0cc27b0665dfc242b1d99`, 220 MB, no function symbols except the 75 000 dynamic-table names, which include
every C++ vtable). Nothing was run, nothing decrypted or circumvented, no network, no game host touched. Tools: `readelf`,
`nm -D`, `objdump -d -M intel` on address ranges, and a 60-line Python helper that maps strings, vtables and reflection tables
(below). No decompiler was installed; every statement was read from the instructions.

Labels: **VERIFIED** = read from the machine code (the instruction bytes are pinned by `tests/test_native_rules.py`);
**INFERRED** = follows from verified code plus a naming or layout argument; **NOT RECOVERED** = could not be found, with what
was tried and the smallest in-game measurement.

## 0. How the code was located (reproducible)

* Class vtables: `nm -D -C SquadGameServer | grep "vtable for ASQDeployable"` gives the address; slot `i` is the 8-byte pointer
  at `vtable + 0x10 + 8*i`. `ASQDeployable` = 0x2534380, `ASQVehicle` = 0x256e828, `ASQProjectile` = 0x23d1ee0,
  `ASQWeapon` = 0x257f350, `AActor` = 0x19ad638. `TakeDamage` is slot 217 (offset 0x6c8), `InternalTakeRadialDamage` slot
  218 (0x6d0), `InternalTakePointDamage` slot 219 (0x6d8).
* Property offsets: UE reflection tables sit in `.rodata`. Each float/bool/struct property is a record whose first word is a
  pointer to its name and whose seventh word is `(offset << 16) | array_dim`. The name strings (`AllowableDamageTypes`,
  `ExplosiveMinimumDamage`, ...) are in `.rodata`, so searching 8-byte pointers to them finds the record and the byte offset in
  the C++ object. Example: `AllowableDamageTypes` record at 0x22f8078 says offset 0x438 in `ASQDeployable`.
* Anchors in code: the game's own log strings (UTF-16), e.g. `"ASQDeployable::TakeDamage[SQRadialDamage] %s for %f damage
  (type=%s) direct hit = %d"` at 0xdbb092, loaded by `mov esi, imm32` at 0xa4978f2 inside `ASQDeployable::TakeDamage`.

Struct `FSQDamageModifier` (one `AllowableDamageTypes` element, size 0x28, property table at 0x22edb20): `DamageTypeClass`
+0x00, `Modifier` +0x08, `bForwardDamageToSoldier` +0x0c, `ForwardDamageToSoldierModifier` +0x10, `bForwardDeathToSoldier`
+0x14, `bIncapSoldierOnDeath` +0x15, `bOnlyPassDamageIfDirectHit` +0x16, `DirectHitDamageMultiplier` +0x18,
`IndirectHitDamageMultiplier` +0x1c, `DirectHitRadialDamageMultiplier` +0x20 (float offsets from the table; the bool offsets
follow from the declaration order and are confirmed by the code reading +0x16).

## 1. Damage to a deployable

### 1.1 `ASQDeployable::TakeDamage` (0xa4970d0, vtable slot 217) - VERIFIED

Fields of `ASQDeployable`: `MaxHealth` +0x424, `InitialHealth` +0x428, `Health` +0x42c, `AllowableDamageTypes` TArray data +0x438
and count +0x440. Arguments: `xmm0` = DamageAmount, `rsi` = FDamageEvent, `rdx` = instigator controller, `rcx` = causer.

1. `if (Health <= 0) return 0` (0xa4970ea). If the actor does not have authority (`Role != 3`, byte +0x168) the body below is
   skipped and only `AActor::TakeDamage` runs, so Health never changes on a client.
2. The table is scanned from index 0 in 0x28-byte steps (0xa49748b-0xa4974c4); the **first element whose `DamageTypeClass` is
   pointer-equal to the event's damage type class** is used (0xa4974cf). There is no `IsChildOf` walk: a damage type that is
   not listed verbatim is not matched, even if a parent class is listed.
3. **Damage type not listed**: the code jumps to 0xa4975f4, which calls `AActor::TakeDamage` (0x79fa950) with the unmodified
   amount, but the Health update below is not reached. Result: **no health change** (previously INFERRED from the property
   name; now VERIFIED).
4. Listed, event is **not** an `FSQRadialDamageEvent` (point or generic damage; `event->IsOfType(1000)` is false at 0xa4974e5):
   `D' = DamageAmount * Modifier` (0xa497a1d), then `AActor::TakeDamage(D', ...)`. None of the three hit multipliers is used.
5. Listed, event **is** an `FSQRadialDamageEvent` (class id 1000; it carries `bDirectHit`, set in 1.3):
   * if `bOnlyPassDamageIfDirectHit` (+0x16, tested at 0xa497ac4): a direct hit uses offset 0x18; a near miss gives
     **zero damage and `AActor::TakeDamage` is not called**;
   * otherwise the offset is `0x18 + 4 * (not direct)` (0xa497ae2): `DirectHitDamageMultiplier` on a direct hit,
     `IndirectHitDamageMultiplier` otherwise;
   * `D' = DamageAmount * Modifier * multiplier` (0xa497af0-0xa497afd), then `AActor::TakeDamage(D', ...)`.
   **`DirectHitRadialDamageMultiplier` (+0x20) is not read by the deployable code at all.** It is read by the vehicle code
   (1.5).
6. `AActor::TakeDamage` (0x79fa950) is the engine function. For a radial event it calls the virtual `InternalTakeRadialDamage`,
   which for `ASQDeployable` is the engine's own (slot 218 equals `AActor`'s, 0x79fb0a0, section 3); for point damage the
   virtual at slot 219 is an empty stub (`ret`, 0x48e20b0), i.e. the amount passes through. It returns `ActualDamage`.
7. `if (byte +0x430 == 0) ActualDamage = 0` (0xa497b39). By declaration order the byte after `Health` is `bCanUnbuild`
   (INFERRED name); in the assets it is false only for the helicopter repair pad and a Stugna laptop, neither of which is in
   the damage tables, so it does not change the tables.
8. `delta = ModifyHealthChange(-ActualDamage, instigator, 1)` through a virtual (0xa22b9a0; the default implementation is an
   empty stub, so `delta = -ActualDamage` unless a Blueprint overrides it - INFERRED that none does for structures), then
   `Health = clamp(Health + delta, 0, MaxHealth)` (0xa497b66-0xa497b86), then the post-update hook (0xa22b780).

Net rule for a deployable (VERIFIED, step 7 and 8 excepted as marked):

```
radial:  loss = Lerp(Min, Base * Modifier * m, scale(d))     m = direct ? DirectHit(+0x18) : Indirect(+0x1c); 0 if bOnly & near miss
point :  loss = Amount * Modifier
Health = clamp(Health - loss, 0, MaxHealth)
```

`Base`, `Min` are the projectile's `ExplosiveBaseDamage` and `ExplosiveMinimumDamage`; `scale` and `d` are in 1.2 and 3.
Implemented in `semantics/native_rules.py` (`deployable_health_loss`), tested in `tests/test_native_rules.py`.

### 1.2 The engine radial law - VERIFIED

* `FRadialDamageParams::GetDamageScale` (0x7e7fc30): `inner = max(0, Inner)`, `outer = max(Outer, inner)`, `d = max(0, d)`;
  `d >= outer -> 0`; `d <= inner -> 1`; `Falloff == 0 -> 1`; else `(1 - (d - inner) / (outer - inner)) ^ Falloff` (`powf`,
  0xd362d90). This is exactly the law in `squadDamage.js damageAtDistance`.
* `AActor::InternalTakeRadialDamage` (0x79fb0a0): `d = sqrt(min over ComponentHits of |ImpactPoint - Origin|^2)` (FLT_MAX with
  no hits, giving scale 0), `scale = max(0, GetDamageScale(d))`, **`return Lerp(MinimumDamage, Damage, scale)`** =
  `Min + (Damage - Min) * scale` (0x79fb145-0x79fb158). The event stores `BaseDamage` at +0x10, `MinimumDamage` +0x14, inner
  +0x18, outer +0x1c, falloff +0x20, origin +0x28, ComponentHits array +0x40/+0x48, `bDirectHit` +0x50.

Consequence the existing docs and the app did not have: **`ExplosiveMinimumDamage` is applied after the structure modifier
and is not multiplied by it.** Fifteen projectile Blueprints in the dump set it, ten of them in the app's projectile set (section 5). Where `Min` is larger than the modified
damage the result is larger far from the centre than at the centre (a 125 mm HEAT round, `Min` 35, against a HESCO barrier:
`200 * 0.01 = 2` at the centre, `35 + (2 - 35) * 0.2304 = 27.4` at 10 m). This follows directly from the instructions; no
in-game measurement of it exists (section 6).

### 1.3 Who builds the radial event: `ASQProjectile::ApplyExplosiveDamage` (0xa745950) - VERIFIED

The native body behind the `ApplyExplosiveDamage` name (the FName is loaded at 0xa745c6c; the function name is INFERRED from it). Returns at once unless `bIsExplosiveProjectile` (+0x439). The origin is
`ImpactPoint + ImpactNormal * ExplosiveDamageDistanceFromImpactNormal` (+0x45c; C++ default 20 cm, constructor 0xa731f5f,
overridden in assets). It then calls the Squad radial-damage routine `0xa417230` with `(Base +0x43c, Minimum +0x440,
KillZone +0x444, Inner +0x448, Outer +0x44c, Falloff +0x450, DamageTypeToApply +0x2c8)` and the projectile's `FHitResult`.

C++ defaults (constructor 0xa731b80, VERIFIED): Base 115, Minimum 0, KillZone 0 (zero-initialised), Inner 500 cm, Outer
1500 cm, Falloff 1.0, DistanceFromImpactNormal 20 cm, `bIsExplosiveProjectile` false. The "115 damage, 5-15 m, falloff 1"
that `gamecheck.py` inferred is now VERIFIED, and the default Minimum is 0.

`0xa417230` (the Squad variant of `ApplyRadialDamageWithFalloff`):

1. Sphere overlap at the origin with radius = **Outer** (a `FCollisionShape` of type 2 built at 0xa417312-0xa41731e), multi-hit.
2. Per overlapped component, an axis-aligned box distance from the origin to the component's bounds (centre +0x108..0x118,
   half-extent +0x120..0x130, 0xa417525-0xa417870). If that distance is **less than KillZone** the component is taken without
   any visibility test and its recorded hit is at the component's world location (+0x200, 0xa417898-0xa417969).
3. Otherwise `0xa416c10` (`ComponentIsDamageableFrom`) casts **one line trace on the Visibility channel (3) from the origin to
   the component's bounds origin** (0xa416c78-0xa416d9a); the component counts only if that trace's first blocking hit belongs
   to the same actor, and the returned `FHitResult` (with its `ImpactPoint` on the surface the ray strikes) is appended to the
   actor's `ComponentHits`.
4. Per actor, one `FSQRadialDamageEvent` (vtable 0x22f26b0) is built (0xa417ee1-0xa418164): DamageType, the six numbers above,
   origin, the hit list, **`bDirectHit = (actor == the actor of the projectile's impact hit result)`** (0xa4180f4-0xa418104), a
   copy of the projectile's `FHitResult`; then `actor->TakeDamage(Base, event, instigator, causer)` (virtual 0x6c8). The damage
   passed is `Base`; the scaling happens in 1.1 and 1.2.

### 1.4 `ImpactDamageToApply` and the secondary explosion - INFERRED / NOT RECOVERED

* The native property `ImpactDamageToApply` exists only on `ASQMortarProjectile` (+0x618, reflection record 0x23a8d58);
  the native code copies it into a spawn-parameter struct for the shell it creates (0xa73bf0e). For rockets, tank shells and the
  other projectile Blueprints the field named `ImpactDamageToApply` in the assets is a **Blueprint variable**, and the
  Blueprint graph that uses it is cooked Kismet bytecode, which the extractor does not decode. Likewise `SecondaryExplosion*`
  and `SecondaryOnlyDamageMeshes` are not native property names: they are Blueprint variables. **How a direct hit's
  `ImpactDamageToApply` and the secondary explosion reach `TakeDamage` is therefore not recoverable from the ELF.**
* What the ELF does verify about the receiving end: a point-type event reaches branch 4 of 1.1 (`Amount * Modifier`, no
  direct-hit multiplier); the generic native hit path that sends such an event is the projectile function at 0xa73eda0 (it
  fills an FSQPointDamageEvent, vtable 0x22f2678, with `DamageTypeToApply` and calls virtual 0x6c8).
  So `ImpactDamageToApply * Modifier` for the impact and `ExplosiveBaseDamage`-based radial for the explosion is consistent
  with the code, but which damage type and amount a given Blueprint passes is INFERRED.

### 1.5 Vehicles and emplacements (`ASQVehicle::TakeDamage`, 0xa6edb10) - VERIFIED

`ASQVehicle` (and `ASQDeployableVehicle`, `ASQDeployableTripodVehicle`, `ASQDeployableMortarVehicle`, `ASQHelicopter2`,
`ASQGroundVehicle`... they share slot 217) has its own `AllowableDamageTypes` at +0x9c0 with the same `FSQDamageModifier`
elements and the same exact-class match. For a radial event the multiplier is selected at 0xa6ee14b-0xa6ee20f: with
`bOnlyPassDamageIfDirectHit` a direct hit uses offset **0x20** and a near miss gives no damage; otherwise offset `0x1c + 4 *
direct`, i.e. **`DirectHitRadialDamageMultiplier` on a direct hit and `IndirectHitDamageMultiplier` otherwise**. So the
three-multiplier table means: `DirectHitDamageMultiplier` for deployables, `DirectHitRadialDamageMultiplier` for vehicles and
emplaced weapons, `Indirect` for both. Which of the `structure_damage.json` classes are `ASQDeployable` and which are
`ASQDeployableVehicle` is not stated by the data: the tripod/mortar items (`BP_AGS17_Tripod`, `BP_DShK`, `BP_*mortar_Deployable`)
have `BP_Deployable` roots in the item data, while the gun actor is a separate `/Game/Vehicles/Emplaced_*` vehicle with its own
table (not extracted). UNVERIFIED which of the two a shell hits.

## 2. Dynamic MOA (AGS-17, MK19, QLZ87) - PARTLY RECOVERED

Verified (ASQWeapon, vtable 0x257f350; reflection table of the weapon static data at 0x2515f78):

* Static data fields: `MOA` +0x8c, `MOACurve` (UCurveFloat*) +0x90, `DynamicMOAGainMultiplier` +0x98,
  `DynamicMOADecayMultiplier` +0x9c.
* Weapon instance: `MOA` copy at +0x74c (constructor sets 4.0 before the asset overrides it, 0xa737cb0), `MOACurve` pointer
  +0x750 (null in the constructor), a float **dynamic input at +0x7ac**.
* `GetCurrentMOA` (0xa752640, exec thunk 0xa38d940): `if (MOACurve valid) return MOACurve->GetFloatValue(this[+0x7ac]); else
  return this[+0x74c]` (0xa752640-0xa75266f; `GetFloatValue` = 0x7d9b940).
* `GetMOAAdjustedAimDirection[FromRotator]` (0xa752310, 0xa752570) take `GetCurrentMOA()` and pass it to `ConvertMOAToRadians`
  (0xa4252c0), which is the cone half-angle for the random bullet direction.
* Spread composition (0xa662c00-0xa662e12, a function of the class whose properties `MOAInfantryMultiplier` +0x338 and
  `MOATurretMultiplier` +0x340 are at the reflection record 0x22ce298): the number sent on is `K[+0x328] * (four movement/aim
  terms + GetCurrentMOA() * M)`, with `M = MOATurretMultiplier` and the four terms each times its own multiplier
  [+0x344..+0x350] on one branch (a weak object at +0x380 that passes a class check), and `M = MOAInfantryMultiplier` with
  unscaled terms on the other. Mapping the branches to "turret" and "infantry" is INFERRED from the property names.
* The three weapons named in the question all use the same curve, `/Game/Vehicles/FC_MOACurve_GenericGMG`: cubic
  Hermite keys `(t = 0 s, 15 MOA)` and `(t = 0.75 s, 50 MOA)`, tangents 122.2 and 1.12 MOA/s. Cycle times between shots are
  0.15 s (AGS-17), 0.171 s (MK19), 0.125 s (QLZ87). Several vehicle weapons set `DynamicMOAGainMultiplier = 1.2` and
  `DynamicMOADecayMultiplier = 1.1` (RHIB, LPPV, M1151, ...); the AGS-17, MK19 and QLZ87 assets set neither.

**NOT RECOVERED: how the input at +0x7ac grows (gain) and shrinks (decay).** Tried: (a) every instruction in the 145 MB
`.text` with a 32-bit displacement 0x7ac (62 sites; any base register including SIB forms with r12/rsp): the writes are in
`ASQKillDeathRuleset`, an unrelated class, and constructors; none in `ASQWeapon` besides the 16-byte zeroing in the
constructor (0xa737e36); the only readers are the three MOA functions above. (b) readers of static-data +0x98/+0x9c: the offsets
collide with hundreds of unrelated structs and none could be tied to the weapon. (c) callers of `GetCurrentMOA`: only the
spread composition above. So the native binary has no code that changes the input; the gain/decay rule, if it exists, is in
Blueprint bytecode (not decoded) or acts through reflection by property name. The cached default of the two multipliers when
an asset omits them is also unknown.

Smallest in-game measurement (Training only, with the owner's go-ahead): from an AGS-17 emplacement fire ten bursts of 10 rounds
at a flat wall about 100 m away, photograph the impact pattern, and measure the radius of the group for shot 1, shot 5 and
shot 10. A constant radius equal to `15 MOA` at 100 m (about 0.44 m) means the input stays 0 (curve at t = 0, the native result);
a radius growing towards `50 MOA` (about 1.45 m) over about 5 shots (0.75 s / 0.15 s) means a Blueprint drives the input; waiting
2 s between bursts and repeating separates decay. The same on the MK19 (0.171 s) and QLZ87 (0.125 s) fixes the time scale.

## 3. Distance from an explosion to a structure - VERIFIED

The distance that scales radial damage is, in `InternalTakeRadialDamage` (1.2), the smallest distance from the **explosion
origin** to an **`ImpactPoint` of the actor's `ComponentHits`**, and those hits come from 1.3:

* Origin = projectile impact point + 20 cm (asset-overridable) along the impact normal. It is not the shell's flight path end or
  the target's centre.
* One hit per overlapped component of the structure (a HESCO barrier has several): in the usual case the `ImpactPoint` is
  where a **ray from the origin to the component's bounding-box centre first hits the structure's geometry on the Visibility
  channel**, i.e. a surface point facing the explosion, not the nearest point of the mesh and not the pivot. A component whose
  bounding-box distance to the origin is below `ExplosiveKillZoneRadius` (the asset value, default 0) skips the ray and is
  recorded at its pivot (world location). A component whose ray is blocked by another actor's geometry (a wall in between)
  is not recorded at all, so a structure fully shielded from the origin takes no radial damage.
* The overlap sphere has the Outer radius, so a component outside it is never considered; the law then uses the ray distance,
  which is at least the box distance.
* Distances and radii are engine units (cm).

What this means for the app: using the distance from the shell's landing point to the structure's centre or marker (as
`structureInfo.js` does with `DIRECT_HIT_RADIUS` = 1 m) over-estimates the engine distance for big structures (the ray hits the
facing surface, up to half a structure width nearer) and ignores occlusion. The pivot is used only inside the kill zone. The
exact face distance needs the structure's collision, which is what the volumetric tooling provides.

## 4. Where the existing documents and the app agree or disagree

| Statement in `structure-damage.md` section 4 / SquadCalc `structureDamage.js` | Result |
|---|---|
| Exact class match on `AllowableDamageTypes`, damage type not listed -> no damage | **Agrees**, now VERIFIED (1.1 steps 2, 3) |
| Radial law `damage * (1 - (d - inner) / (outer - inner)) ^ falloff`, full inside the inner radius, zero beyond the outer | **Agrees**, VERIFIED (1.2); the engine adds `Lerp(Min, ...)`, see next rows |
| Radial damage on a direct hit uses `directRadial` (`DirectHitRadialDamageMultiplier`) | **Disagrees for `ASQDeployable`**: it uses `DirectHitDamageMultiplier`; `DirectHitRadialDamageMultiplier` is read only by vehicles and emplacements (1.1 step 5, 1.5). Ammunition crates (d 1 / r 0) therefore take the full radial on a direct hit, not zero. |
| Direct hit also adds `impact * modifier * direct` | **Disagrees**: point damage is `amount * Modifier` with no direct multiplier (1.1 step 4); the `direct` multiplier belongs to the radial part. Where `direct = 1` (nearly every structure) the numbers are unchanged. |
| Near miss uses `indirect` | **Agrees** (1.1 step 5); with `bOnlyPassDamageIfDirectHit` a near miss gives 0, which the app does not model |
| `ExplosiveMinimumDamage` "not used by the calculation" | **Disagrees**: it is a floor applied after the modifier (1.2). Zero for most projectiles, non-zero for ten of the app's projectiles (section 5) |
| Defaults 115 / 5-15 m / falloff 1 (`gamecheck.py`) | **Agrees**, VERIFIED (1.3), Minimum default 0 |
| Distance to a structure UNVERIFIED | **Resolved** (section 3): origin to the ray hit point on the structure's surface, or the pivot inside the kill zone |
| Health regeneration, build-state effect, `bForwardDamageToSoldier` | Not touched by this work. `TakeDamage` has no build-state term; `bForwardDamageToSoldier` is read in the radial/point paths (UNVERIFIED how) |

Numbers for the apps (the SquadCalc source was not edited): the game's per-event loss is
`Lerp(Min, Base * Modifier * m, scale)` with `m = DirectHitDamageMultiplier` on a direct hit and `IndirectHitDamageMultiplier`
otherwise for `ASQDeployable`; `Min` is non-zero for the projectiles in section 5. A mortar round (`BP_Mortarround4`, `Min` 0,
modifiers 1) on a HESCO barrier is unchanged from the worked example (66.1 per round, 4 rounds).

## 5. Projectile Blueprints with a non-zero `ExplosiveMinimumDamage` (from the cooked assets)

Ten of the projectiles in `data/structure_damage.json` (merged along the Blueprint chain):

| projectile | Minimum | Base | inner-outer (m) | falloff |
|---|---|---|---|---|
| BP_Projectile_76mm_HEAT, 115mm_HEAT, 125mm_HEAT | 35 | 200 | 3.5-16 | 2 |
| BP_Projectile_120mm_HEAT, BP_PF-98_HE_Proj | 50 | 200 | 7-20 | 2 |
| BP_Projectile_120mm_Smoke | 50 | 150 | 2-10 | 1 |
| BP_BM21_Rocket_Proj2 | 30 | 250 | 2-10 | 1 |
| BP_Projectile_100mm_Frag, 125mm_Frag | 10 | 300 | 4-35 | 5 |
| BP_Projectile_Hell_Cannon | 1 | 125 | 1-50 | 1 |

The raw dump has five more outside the app's set (76 mm smoke 50, 30 mm CAS 30, S8 rocket 30, generic tank HE 50, 500 lb bomb 5,
155 mm artillery 1). All other projectile Blueprints, including the mortar rounds, leave it at the native 0. The mortar round
`BP_Mortarround4` also carries `ExplosiveDamageDistanceFromImpactNormal` 100 cm, `ImpactDamageToApply` 10 (the native field of
`ASQMortarProjectile`) and `bUseSecondaryExplosion` / `SecondaryExplosion*` variables, which are Blueprint variables (1.4).

## 6. Smallest in-game measurements that would settle what the binary cannot

All on squad2 (DeadLine Training), none on squad1, none done by this work:

1. **Minimum-damage floor (1.2):** a 125 mm HEAT round (Min 35) at a full-health HESCO barrier (200 HP, BasicHeat 0.01): one shell
   at about 2 m and one at about 10 m from the barrier, read the health lost. Prediction: about 2 and about 27.
2. **Deployable vs emplacement multiplier (1.1, 1.5):** one BP_Ammocrate (d 1 / r 0): a direct HEAT hit. Prediction from the code:
   full damage; the old formula predicted the radial part to be zero.
3. **Impact damage path (1.4):** a direct RPG hit on a HAB vs a 2 m near miss with the same round; compare with
   `ImpactDamageToApply * Modifier` plus the radial part.
4. **Dynamic MOA (2):** the AGS-17 group-size test above.

## 7. Reproduction

| Result | Command / address |
|---|---|
| vtable address | `nm -D -C SquadGameServer \| grep "vtable for ASQDeployable$"` |
| function bytes | `objdump -d -M intel --start-address=0xa4970d0 --stop-address=0xa4983c0 SquadGameServer` |
| instruction bytes pinned | `python3 -m unittest tests.test_native_rules` (from `tools/volumetric`; set `SQUAD_SERVER_ELF` if the binary is elsewhere) |
| formulas | `semantics/native_rules.py` |

The helper scripts used for the search (string and vtable lookup, reflection-table decoding, displacement scans) were scratch
tools and are not part of the repository; the addresses above reproduce every claim with `objdump` alone.
