"""Tests of kismet.py on bytecode built in the shape CUE4Parse dumps it (no game data needed).

Run: python3 -m unittest discover -s tools/game_audit
"""
import unittest

import kismet


def local(name):
    return {"Token": "EX_LocalVariable", "Variable": {"Owner": {"ObjectName": "Function'W_C:F'"}, "Property": {"Type": "DoubleProperty", "Name": name}}}


def member(name):
    return {"Token": "EX_InstanceVariable", "Variable": {"Path": [name], "ResolvedOwner": {"ObjectName": "Class'SQDeployableMortarVehicle'"}}}


def let(target, value, index=0):
    return {"Token": "EX_Let", "StatementIndex": index, "Variable": local(target), "Expression": value}


def cast(value):
    return {"Token": "EX_Cast", "ConversionType": "CST_FloatToDouble", "Target": value}


def call(function, *parameters):
    return {"Token": "EX_CallMath", "Function": {"ObjectName": f"Class'KismetMathLibrary:{function}'", "ObjectPath": "/Script/Engine"}, "Parameters": list(parameters)}


def number(value):
    return {"Token": "EX_DoubleConst", "Value": value}


def function(name, *statements):
    return {"Type": "Function", "Name": name, "ScriptBytecode": list(statements)}


# The three statements of UMG_MortarControl that turn the elevation wheel (Squad build 26005357)
MORTAR = function(
    "ExecuteUbergraph_UMG_MortarControl",
    let("Pitch_ImplicitCast", cast({"Token": "EX_Context", "ObjectExpression": local("AsMortarVehicle"), "ContextExpression": member("CachedTubePitch")})),
    let("Sum", call("Add_DoubleDouble", local("Pitch_ImplicitCast"), number(45.0))),
    let("WheelAngle", call("Divide_DoubleDouble", local("Sum"), number(0.125))),
)
# The angle display of the UB-32: the pitch of the mount goes to the text as it is
UB32 = function(
    "AngleRotationDisplay",
    call("BreakRotator", local("Rotation"), local("CallFunc_BreakRotator_Roll"), local("CallFunc_BreakRotator_Pitch"), local("CallFunc_BreakRotator_Yaw")),
    let("Value_ImplicitCast", cast(local("CallFunc_BreakRotator_Pitch"))),
    let("Text", call("Conv_DoubleToText", local("Value_ImplicitCast"), {"Token": "EX_ByteConst", "Value": 0}, {"Token": "EX_False"})),
)


class Rendering(unittest.TestCase):
    def test_a_statement_reads_as_an_assignment_of_a_call(self):
        self.assertEqual(kismet.statements(MORTAR), [
            "Pitch_ImplicitCast := cast<CST_FloatToDouble>(AsMortarVehicle.CachedTubePitch)",
            "Sum := Add_DoubleDouble(Pitch_ImplicitCast, 45.0)",
            "WheelAngle := Divide_DoubleDouble(Sum, 0.125)",
        ])

    def test_jumps_literals_and_strings(self):
        self.assertEqual(kismet.expression({"Token": "EX_JumpIfNot", "CodeOffset": 709, "BooleanExpression": local("Valid")}), "if !(Valid) goto 709")
        self.assertEqual(kismet.expression({"Token": "EX_Return", "Expression": {"Token": "EX_Nothing"}}), "return none")
        self.assertEqual(kismet.expression({"Token": "EX_NameConst", "Value": "Attach_Muzzle"}), '"Attach_Muzzle"')

    def test_an_unknown_instruction_is_shown_with_its_fields_not_dropped(self):
        text = kismet.expression({"Token": "EX_FutureThing", "Value": 7})
        self.assertTrue(text.startswith("EX_FutureThing"))
        self.assertIn("7", text)

    def test_a_function_is_found_by_name(self):
        self.assertIs(kismet.function_named([{"Type": "WidgetBlueprintGeneratedClass", "Name": "W_C"}, UB32], "AngleRotationDisplay"), UB32)
        with self.assertRaises(KeyError):
            kismet.function_named([UB32], "Tick")


class AddedConstant(unittest.TestCase):
    def test_the_mortar_sight_adds_45_to_the_tube_pitch_of_the_vehicle(self):
        self.assertEqual(kismet.added_constant(MORTAR, "CachedTubePitch"), 45.0)

    def test_a_display_that_shows_the_pitch_as_it_is_adds_nothing(self):
        self.assertEqual(kismet.added_constant(UB32, "CallFunc_BreakRotator_Pitch"), 0.0)

    def test_the_hell_cannon_display_adds_40_before_the_text(self):
        display = function(
            "AngleRotationDisplay",
            let("A_ImplicitCast", cast(local("CallFunc_BreakRotator_Pitch"))),
            let("Sum", call("Add_DoubleDouble", local("A_ImplicitCast"), number(40.0))),
            let("Text", call("Conv_DoubleToText", local("Sum"))),
        )
        self.assertEqual(kismet.added_constant(display, "CallFunc_BreakRotator_Pitch"), 40.0)

    def test_a_constant_added_to_another_value_is_not_the_sights_offset(self):
        other = function(
            "TurretRotationValues",
            let("Yaw_ImplicitCast", cast(local("CallFunc_BreakRotator_Yaw"))),
            let("Sum", call("Add_DoubleDouble", local("Yaw_ImplicitCast"), number(180.0))),
        )
        with self.assertRaises(ValueError):
            kismet.added_constant(other, "CallFunc_BreakRotator_Pitch")

    def test_a_function_that_never_uses_the_value_is_an_error_not_zero(self):
        with self.assertRaises(ValueError):
            kismet.added_constant(function("Tick"), "CallFunc_BreakRotator_Pitch")


if __name__ == "__main__":
    unittest.main()
