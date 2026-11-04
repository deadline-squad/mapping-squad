"""Rules of the Squad dedicated server (build 26005357) that are native C++ and not in the paks.

Each function re-states, in Python, one routine of ``SquadGameServer`` that was read from its machine code (static
disassembly only; nothing was executed). The addresses are the ones of docs/native-rules.md; ``tests/test_native_rules.py``
checks the instruction bytes at those addresses when the owner's binary is installed, so a game update that moves the code
fails the test instead of silently leaving the formulas out of date.

Lengths are in the units of the caller (the game uses centimetres, the ratios here do not depend on the unit).
"""

import math

FLT_MAX = 3.4028234663852886e38


def radial_damage_scale(distance, inner_radius, outer_radius, falloff):
    """Fraction of the radial damage at ``distance`` from the explosion: ``FRadialDamageParams::GetDamageScale`` (0x7e7fc30).

    The distance is clamped to >= 0, the inner radius to >= 0 and the outer radius to >= the inner radius. At or beyond the
    outer radius the scale is 0; up to the inner radius it is 1; a falloff of exactly 0 gives 1 inside the outer radius;
    otherwise ``(1 - (d - inner) / (outer - inner)) ** falloff``.
    """
    inner = max(0.0, inner_radius)
    outer = max(outer_radius, inner)
    distance = max(0.0, distance)
    if distance >= outer:
        return 0.0
    if inner >= distance:
        return 1.0
    if falloff == 0.0:
        return 1.0
    return (1.0 - (distance - inner) / (outer - inner)) ** falloff


def radial_damage_applied(damage, minimum_damage, scale):
    """``AActor::InternalTakeRadialDamage`` (0x79fb0a0): ``Lerp(MinimumDamage, damage, max(0, scale))``.

    ``damage`` is the damage after the structure's modifiers; ``minimum_damage`` is the projectile's ExplosiveMinimumDamage
    and is NOT scaled by any modifier, so it is a floor inside the outer radius (and a ceiling-inverting one when it exceeds
    the modified damage).
    """
    return minimum_damage + (damage - minimum_damage) * max(0.0, scale)


def closest_hit_distance(origin, impact_points):
    """Distance used by ``InternalTakeRadialDamage``: the smallest distance from the explosion origin to a recorded impact point.

    ``impact_points`` are the ``ComponentHits`` of the radial event (one point per component of the damaged actor). With no
    points the engine starts from FLT_MAX in squared units, which gives scale 0.
    """
    if not impact_points:
        return math.sqrt(FLT_MAX)
    return min(math.dist(origin, point) for point in impact_points)


def find_damage_entry(allowable_damage_types, damage_type_class):
    """First ``AllowableDamageTypes`` element whose class is exactly ``damage_type_class`` (no inheritance), else None."""
    for entry in allowable_damage_types:
        if entry["DamageTypeClass"] == damage_type_class:
            return entry
    return None


def deployable_hit_multiplier(entry, direct_hit):
    """Multiplier ``ASQDeployable::TakeDamage`` (0xa4970d0) applies to a radial hit.

    A direct hit uses DirectHitDamageMultiplier (+0x18); otherwise the entry's IndirectHitDamageMultiplier (+0x1c), or no
    damage at all when ``bOnlyPassDamageIfDirectHit`` (+0x16) is set. DirectHitRadialDamageMultiplier (+0x20) is not read.
    """
    if direct_hit:
        return entry["DirectHitDamageMultiplier"]
    if entry["bOnlyPassDamageIfDirectHit"]:
        return None
    return entry["IndirectHitDamageMultiplier"]


def vehicle_hit_multiplier(entry, direct_hit):
    """Same selection in ``ASQVehicle::TakeDamage`` (0xa6edb10): a direct hit uses DirectHitRadialDamageMultiplier (+0x20)."""
    if direct_hit:
        return entry["DirectHitRadialDamageMultiplier"]
    if entry["bOnlyPassDamageIfDirectHit"]:
        return None
    return entry["IndirectHitDamageMultiplier"]


def deployable_health_loss(allowable_damage_types, damage_type_class, damage, *, radial=None):
    """Health a deployable loses from one damage event (``ASQDeployable::TakeDamage``, 0xa4970d0).

    ``damage`` is the amount the event carries (the projectile's ExplosiveBaseDamage for a radial event, the point damage
    otherwise). ``radial`` is None for a point or generic event, or a dict with ``minimum_damage``, ``inner_radius``,
    ``outer_radius``, ``falloff``, ``distance`` and ``direct_hit`` for an FSQRadialDamageEvent. A damage type that is not in
    the table changes nothing.
    """
    entry = find_damage_entry(allowable_damage_types, damage_type_class)
    if entry is None:
        return 0.0
    modified = damage * entry["Modifier"]
    if radial is None:
        return modified
    multiplier = deployable_hit_multiplier(entry, radial["direct_hit"])
    if multiplier is None:
        return 0.0
    scale = radial_damage_scale(radial["distance"], radial["inner_radius"], radial["outer_radius"], radial["falloff"])
    return radial_damage_applied(modified * multiplier, radial["minimum_damage"], scale)
