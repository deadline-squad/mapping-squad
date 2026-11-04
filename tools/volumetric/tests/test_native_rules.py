"""Tests of semantics/native_rules.py: the formulas read from the dedicated-server binary (docs/native-rules.md).

The formula tests are pure. ``ServerBinaryTest`` compares the instruction bytes at the documented addresses with the owner's
installed SquadGameServer (path in SQUAD_SERVER_ELF, default ~/data/squad-server/...); it is skipped when the binary is missing
and fails when a game update moved or changed the code, which means native-rules.md must be re-checked.
Run: python -m unittest discover tests (from tools/volumetric).
"""

import math
import os
import sys
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "semantics"))

import native_rules  # noqa: E402
from native_rules import (  # noqa: E402
    closest_hit_distance,
    deployable_health_loss,
    deployable_hit_multiplier,
    find_damage_entry,
    radial_damage_applied,
    radial_damage_scale,
    vehicle_hit_multiplier,
)

ELF_PATH = os.environ.get(
    "SQUAD_SERVER_ELF", os.path.expanduser("~/data/squad-server/SquadGame/Binaries/Linux/SquadGameServer")
)
BUILD_ID = "b070e18070f98fc2c3b0cc27b0665dfc242b1d99"

HESCO = {
    "DamageTypeClass": "Frag", "Modifier": 0.01, "DirectHitDamageMultiplier": 1.0, "IndirectHitDamageMultiplier": 1.0,
    "DirectHitRadialDamageMultiplier": 1.0, "bOnlyPassDamageIfDirectHit": False,
}
AMMO_CRATE = {
    "DamageTypeClass": "HEAT", "Modifier": 1.0, "DirectHitDamageMultiplier": 1.0, "IndirectHitDamageMultiplier": 0.5,
    "DirectHitRadialDamageMultiplier": 0.0, "bOnlyPassDamageIfDirectHit": False,
}
DIRECT_ONLY = {
    "DamageTypeClass": "Frag", "Modifier": 1.0, "DirectHitDamageMultiplier": 2.0, "IndirectHitDamageMultiplier": 0.5,
    "DirectHitRadialDamageMultiplier": 3.0, "bOnlyPassDamageIfDirectHit": True,
}


def radial(distance, direct_hit, minimum=0.0, inner=100.0, outer=1100.0, falloff=1.0):
    return {"minimum_damage": minimum, "inner_radius": inner, "outer_radius": outer, "falloff": falloff,
            "distance": distance, "direct_hit": direct_hit}


class RadialScaleTest(unittest.TestCase):
    def test_full_inside_inner_radius_and_zero_at_outer_radius(self):
        self.assertEqual(radial_damage_scale(0, 100, 1100, 1), 1.0)
        self.assertEqual(radial_damage_scale(100, 100, 1100, 1), 1.0)
        self.assertEqual(radial_damage_scale(1100, 100, 1100, 1), 0.0)
        self.assertEqual(radial_damage_scale(5000, 100, 1100, 1), 0.0)

    def test_power_law_between_the_radii(self):
        self.assertAlmostEqual(radial_damage_scale(600, 100, 1100, 1), 0.5)
        self.assertAlmostEqual(radial_damage_scale(600, 100, 1100, 2), 0.25)
        self.assertAlmostEqual(radial_damage_scale(600, 100, 1100, 3.5), 0.5 ** 3.5)

    def test_zero_falloff_is_flat_inside_the_outer_radius(self):
        self.assertEqual(radial_damage_scale(1099, 100, 1100, 0), 1.0)
        self.assertEqual(radial_damage_scale(1100, 100, 1100, 0), 0.0)

    def test_clamping_of_negative_and_inverted_radii(self):
        self.assertEqual(radial_damage_scale(-50, 100, 1100, 1), 1.0)
        self.assertEqual(radial_damage_scale(10, -5, 100, 1), (1 - 10 / 100) ** 1)
        self.assertEqual(radial_damage_scale(50, 100, 20, 1), 1.0)
        self.assertEqual(radial_damage_scale(150, 100, 20, 1), 0.0)


class RadialApplyTest(unittest.TestCase):
    def test_lerp_to_minimum_damage(self):
        self.assertEqual(radial_damage_applied(100.0, 10.0, 1.0), 100.0)
        self.assertEqual(radial_damage_applied(100.0, 10.0, 0.0), 10.0)
        self.assertAlmostEqual(radial_damage_applied(100.0, 10.0, 0.25), 32.5)

    def test_negative_scale_is_clamped(self):
        self.assertEqual(radial_damage_applied(100.0, 10.0, -3.0), 10.0)

    def test_minimum_damage_is_not_scaled_by_a_modifier(self):
        # 200 base, HESCO modifier 0.01: 2 at the centre, but the floor of 35 wins at range (the code order, see native-rules.md)
        centre = deployable_health_loss([HESCO], "Frag", 200.0, radial=radial(0, True, minimum=35.0))
        far = deployable_health_loss([HESCO], "Frag", 200.0, radial=radial(600, True, minimum=35.0))
        self.assertAlmostEqual(centre, 2.0)
        self.assertAlmostEqual(far, 35.0 + (2.0 - 35.0) * 0.5)
        self.assertGreater(far, centre)


class ClosestDistanceTest(unittest.TestCase):
    def test_nearest_impact_point(self):
        self.assertAlmostEqual(closest_hit_distance((0, 0, 0), [(3, 4, 0), (0, 0, 20)]), 5.0)

    def test_no_hits_gives_no_damage_scale(self):
        distance = closest_hit_distance((0, 0, 0), [])
        self.assertEqual(radial_damage_scale(distance, 100, 1100, 1), 0.0)
        self.assertGreater(distance, 1e18)


class MultiplierSelectionTest(unittest.TestCase):
    def test_deployable_uses_direct_hit_multiplier_not_the_radial_one(self):
        self.assertEqual(deployable_hit_multiplier(AMMO_CRATE, True), 1.0)
        self.assertEqual(deployable_hit_multiplier(AMMO_CRATE, False), 0.5)
        self.assertEqual(vehicle_hit_multiplier(AMMO_CRATE, True), 0.0)

    def test_direct_only_entries_pass_nothing_on_a_near_miss(self):
        self.assertEqual(deployable_hit_multiplier(DIRECT_ONLY, True), 2.0)
        self.assertIsNone(deployable_hit_multiplier(DIRECT_ONLY, False))
        self.assertEqual(vehicle_hit_multiplier(DIRECT_ONLY, True), 3.0)
        self.assertIsNone(vehicle_hit_multiplier(DIRECT_ONLY, False))

    def test_direct_only_near_miss_is_not_lifted_by_the_minimum_damage(self):
        loss = deployable_health_loss([DIRECT_ONLY], "Frag", 100.0, radial=radial(300, False, minimum=20.0))
        self.assertEqual(loss, 0.0)


class DeployableHealthLossTest(unittest.TestCase):
    def test_first_exact_class_match_wins(self):
        first = dict(HESCO, Modifier=0.5)
        second = dict(HESCO, Modifier=0.9)
        self.assertIs(find_damage_entry([first, second], "Frag"), first)
        self.assertIsNone(find_damage_entry([first], "Explosives"))

    def test_unlisted_damage_type_does_nothing(self):
        self.assertEqual(deployable_health_loss([HESCO], "Explosives", 250.0, radial=radial(0, True)), 0.0)

    def test_point_damage_is_damage_times_modifier_only(self):
        entry = dict(AMMO_CRATE, DirectHitDamageMultiplier=7.0, Modifier=1.75)
        self.assertAlmostEqual(deployable_health_loss([entry], "HEAT", 100.0), 175.0)

    def test_radial_direct_and_indirect(self):
        direct = deployable_health_loss([AMMO_CRATE], "HEAT", 115.0, radial=radial(0, True))
        indirect = deployable_health_loss([AMMO_CRATE], "HEAT", 115.0, radial=radial(0, False))
        self.assertAlmostEqual(direct, 115.0)
        self.assertAlmostEqual(indirect, 57.5)

    def test_mortar_secondary_explosion_on_a_hesco_barrier(self):
        explosives = dict(HESCO, DamageTypeClass="Explosives", Modifier=0.25)
        loss = deployable_health_loss([HESCO, explosives], "Explosives", 250.0, radial=radial(50, True, inner=100, outer=600, falloff=3.5))
        self.assertAlmostEqual(loss, 62.5)


@unittest.skipUnless(os.path.exists(ELF_PATH), "dedicated-server binary not installed")
class ServerBinaryTest(unittest.TestCase):
    """Instruction bytes behind each statement of native-rules.md (VERIFIED labels)."""

    @classmethod
    def setUpClass(cls):
        import elf_profiles

        cls.elf = elf_profiles.Elf(ELF_PATH)

    def code(self, va, length):
        offset = self.elf.text_off + va - self.elf.text_va
        return self.elf.map[offset:offset + length].hex()

    def test_build_id(self):
        import subprocess

        notes = subprocess.run(["readelf", "-n", ELF_PATH], capture_output=True, text=True, check=True).stdout
        self.assertIn(BUILD_ID, notes)

    def test_deployable_take_damage(self):
        self.assertEqual(self.code(0xA4970EA, 7), "0f2e872c040000")  # ucomiss xmm0,[rdi+0x42c]: Health <= 0 returns 0
        self.assertEqual(self.code(0xA49746A, 8), "4963842440040000")  # movsxd rax,[r12+0x440]: array count
        self.assertEqual(self.code(0xA49747B, 8), "4d8bac2438040000")  # mov r13,[r12+0x438]: AllowableDamageTypes
        self.assertEqual(self.code(0xA4974BC, 4), "4983c528")  # add r13,0x28: element stride
        self.assertEqual(self.code(0xA4974CF, 3), "4939c7")  # cmp r15,rax: class pointer equality
        self.assertEqual(self.code(0xA4974E0, 5), "bee8030000")  # mov esi,1000: FSQRadialDamageEvent id
        self.assertEqual(self.code(0xA497A1D, 6), "f3410f594508")  # point damage: * Modifier (+0x08)

    def test_deployable_radial_multiplier_selection(self):
        self.assertEqual(self.code(0xA497AC4, 5), "41807d1600")  # cmp byte [r13+0x16],0: bOnlyPassDamageIfDirectHit
        self.assertEqual(self.code(0xA497ACE, 5), "b818000000")  # mov eax,0x18: DirectHitDamageMultiplier
        self.assertEqual(self.code(0xA497AE2, 8), "488d048518000000")  # lea rax,[rax*4+0x18]: 0x18 direct, 0x1c indirect
        self.assertEqual(self.code(0xA497AF0, 6), "f3410f594508")  # * Modifier
        self.assertEqual(self.code(0xA497AF6, 7), "f3410f59440500")  # * [elem + selected offset]
        self.assertEqual(self.code(0xA497B74, 10), "f3410f5d8c2424040000")  # minss xmm1,[r12+0x424]: clamp to MaxHealth

    def test_vehicle_uses_the_radial_multiplier(self):
        self.assertEqual(self.code(0xA6EE14B, 4), "80781600")  # cmp byte [rax+0x16],0
        self.assertEqual(self.code(0xA6EE155, 5), "b820000000")  # mov eax,0x20: DirectHitRadialDamageMultiplier
        self.assertEqual(self.code(0xA6EE204, 11), "0fb6c1488d04851c000000")  # movzx eax,cl; lea rax,[rax*4+0x1c]

    def test_engine_radial_damage(self):
        self.assertEqual(self.code(0x79FB150, 12), "f30f5cc2f30f59c1f30f58c2")  # subss, mulss, addss: Lerp(Min, Damage, scale)
        self.assertEqual(self.code(0x7E7FC30, 8), "0f57c9f30f5f4f08")  # GetDamageScale: xorps; maxss xmm1,[rdi+8]: max(0, inner)

    def test_native_projectile_defaults(self):
        self.assertEqual(self.code(0xA731F4D, 8), "f20f118348040000")  # movsd [rbx+0x448],xmm0: inner 500 and outer 1500 cm
        self.assertEqual(self.code(0xA731F55, 10), "c783500400000000803f")  # falloff = 1.0f
        self.assertEqual(self.code(0xA731F5F, 10), "c7835c0400000000a041")  # DistanceFromImpactNormal = 20.0f

    def test_explosion_reads_projectile_fields(self):
        self.assertEqual(
            self.code(0xA745CE4, 0x30),
            "f30f10803c040000f30f108840040000f30f109044040000f30f109848040000f30f10a04c040000f30f10a850040000",
        )  # Base, Minimum, KillZone, Inner, Outer, Falloff

    def test_weapon_moa_evaluation(self):
        self.assertEqual(
            self.code(0xA752640, 0x30),
            "488b87500700004885c0741b8b4808f7c1000000407510f30f1087ac0700004889c7e9d99264fdf30f10874c070000c3",
        )  # curve at +0x750 and input +0x7ac, else static MOA +0x74c
        self.assertEqual(self.code(0xA737CB0, 10), "c7834c0700000000804048"[:20])  # ASQWeapon ctor: MOA +0x74c = 4.0f


if __name__ == "__main__":
    unittest.main()
