"""Resolve every dumped weapon class (CDO with WeaponConfig) and its projectile; print missing parents.

Usage: collect.py <dump dir> <files.txt> <resolved.json out>
    dump dir   SquadExtract dumpall output (<pak path>.json per asset)
    files.txt  SquadExtract list output: every path in the paks
A missing parent class means the dump regex has to include it; dump it and run again.
"""
import json, glob, os, sys
from resolve import Dump, class_path

# Projectile CDO properties of the impact explosion (ASQProjectile) and of the optional second one.
EXPLOSION_FIELDS = ("ExplosiveBaseDamage", "ExplosiveDamageInnerRadius", "ExplosiveDamageOuterRadius",
                    "ExplosiveDamageFalloff", "ExplosiveDamageDistanceFromImpactNormal", "bUseSecondaryExplosion",
                    "SecondaryExplosionBaseDmg", "SecondaryExplosionInnerRadius", "SecondaryExplosionOuterRadius",
                    "SecondaryExplosionDamageFalloff", "SecondaryExplosionDistanceFromImpact")
ROOT, FILES, OUT = sys.argv[1:4]
d = Dump(ROOT, FILES)
weapons = []
for f in glob.glob(ROOT + "/**/*.uasset.json", recursive=True):
    if '"BlueprintGeneratedClass"' not in open(f).read():
        continue
    pak = os.path.relpath(f, ROOT)[:-len(".json")]
    if pak.startswith("SquadGame/Content/"):
        obj = "/Game/" + pak[len("SquadGame/Content/"):-len(".uasset")]
    else:
        continue
    weapons.append(obj)
out = {}
for w in sorted(weapons):
    cdo, comps, chain = d.resolved(w)
    wc = cdo.get("WeaponConfig") or {}
    if not wc:
        continue
    proj = class_path(wc.get("ProjectileClass"))
    entry = {"chain": chain, "config": wc}
    if proj:
        pcdo, pcomps, pchain = d.resolved(proj)
        entry["projectile"] = {"chain": pchain, "movement": pcomps.get("ProjectileComp"), "life": pcdo.get("InitialLifeSpan"),
                               "explosion": {k: pcdo[k] for k in EXPLOSION_FIELDS if k in pcdo}}
    out[w] = entry
json.dump(out, open(OUT, "w"), indent=1)
print(len(out), "weapons")
print("\n".join(sorted(m for m in d.missing)))
