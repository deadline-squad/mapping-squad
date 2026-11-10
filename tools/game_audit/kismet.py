"""Kismet bytecode of a dumped Blueprint as one line per statement, and the constant a function adds to a value.

``SquadExtract dumpbytecode`` writes every function of a Blueprint with its ``ScriptBytecode``, a tree of expressions.
A sight widget computes what the gunner reads in such a function (the mortar's elevation wheel turns by the tube
pitch + 45), so the formula is game data like any property. This module renders the tree as text a person can read
and answers the one question the audit asks of it: what is added to the pitch before it is shown.

Usage::

    python3 -I kismet.py <file.uasset.json> [regex over function names]
"""
import json
import re
import sys

CONSTANTS = ("EX_FloatConst", "EX_DoubleConst", "EX_IntConst", "EX_ByteConst", "EX_Int64Const", "EX_IntConstByte")
VARIABLES = ("EX_LocalVariable", "EX_InstanceVariable", "EX_LocalOutVariable", "EX_DefaultVariable", "EX_ClassSparseDataVariable")
CALLS = ("EX_FinalFunction", "EX_CallMath", "EX_LocalFinalFunction", "EX_VirtualFunction", "EX_LocalVirtualFunction")
ASSIGNMENTS = ("EX_Let", "EX_LetObj", "EX_LetBool", "EX_LetWeakObjPtr", "EX_LetDelegate", "EX_LetMulticastDelegate", "EX_LetValueOnPersistentFrame")
CONTEXTS = ("EX_Context", "EX_Context_FailSilent", "EX_ClassContext")
CASTS = ("EX_PrimitiveCast", "EX_Cast", "EX_DynamicCast", "EX_MetaCast", "EX_ObjToInterfaceCast")
FLOW = ("EX_PopExecutionFlow", "EX_EndOfScript", "EX_PushExecutionFlow", "EX_PopExecutionFlowIfNot", "EX_Tracepoint", "EX_WireTracepoint")
LITERALS = {"EX_True": "true", "EX_False": "false", "EX_Self": "self", "EX_NoObject": "none", "EX_Nothing": "none", "EX_NoInterface": "none"}

ASSIGNMENT = re.compile(r"^(?P<target>.+?) := (?P<value>.+)$")
CAST = re.compile(r"^cast<[^>]*>\((?P<inner>.+)\)$")
ADDITION = re.compile(r"^Add_DoubleDouble\((?P<operand>.+), (?P<constant>-?\d+(?:\.\d+)?)\)$")
SHOWN = re.compile(r"\bConv_DoubleToText\((?P<operand>[^,]+),")


def name(reference):
    """The short name of a property, function or object reference of the dump."""
    if not isinstance(reference, dict):
        return str(reference)
    if isinstance(reference.get("Property"), dict) and "Name" in reference["Property"]:
        return str(reference["Property"]["Name"])
    if isinstance(reference.get("Path"), list):
        return ".".join(map(str, reference["Path"]))
    if "ObjectName" in reference:
        return reference["ObjectName"].split(".")[-1].split(":")[-1].strip("'")
    if "Path" in reference:
        return str(reference["Path"]).split(".")[-1].split(":")[-1]
    return str(reference.get("Name", reference))


def expression(node):
    """One bytecode expression as text; an instruction this module does not know is shown with its raw fields."""
    if not isinstance(node, dict):
        return json.dumps(node)
    token = node.get("Token", "?")
    if token in CONSTANTS:
        return str(node.get("Value"))
    if token in LITERALS:
        return LITERALS[token]
    if token in ("EX_NameConst", "EX_StringConst", "EX_UnicodeStringConst"):
        return json.dumps(node.get("Value"))
    if token == "EX_ObjectConst":
        return "obj:" + name(node.get("Value"))
    if token in VARIABLES:
        return name(node.get("Variable"))
    if token in CALLS:
        return f"{name(node.get('Function'))}({', '.join(expression(p) for p in node.get('Parameters', []))})"
    if token in ASSIGNMENTS:
        target = node.get("Variable") or node.get("DestinationProperty")
        value = node.get("Expression") or node.get("AssignmentExpression")
        return f"{expression(target)} := {expression(value)}"
    if token in CONTEXTS:
        return f"{expression(node.get('ObjectExpression'))}.{expression(node.get('ContextExpression'))}"
    if token == "EX_StructMemberContext":
        return f"{expression(node.get('StructExpression'))}.{name(node.get('Property'))}"
    if token == "EX_JumpIfNot":
        return f"if !({expression(node.get('BooleanExpression'))}) goto {node.get('CodeOffset')}"
    if token == "EX_Jump":
        return f"goto {node.get('CodeOffset')}"
    if token == "EX_ComputedJump":
        return f"goto computed {expression(node.get('CodeOffsetExpression'))}"
    if token == "EX_Return":
        return f"return {expression(node.get('Expression'))}"
    if token in ("EX_VectorConst", "EX_RotationConst"):
        return json.dumps(node.get("Value"))
    if token == "EX_StructConst":
        return f"{name(node.get('Struct'))}{{{', '.join(expression(p) for p in node.get('Properties', []))}}}"
    if token in ("EX_SetArray", "EX_ArrayConst"):
        return f"[{', '.join(expression(p) for p in node.get('Elements', []))}]"
    if token in CASTS:
        kind = name(node.get("InterfaceClass") or node.get("ConversionType") or "")
        return f"cast<{kind}>({expression(node.get('Target'))})"
    if token == "EX_TextConst":
        return "text:" + json.dumps(node.get("Value"))[:120]
    if token == "EX_SwitchValue":
        cases = "; ".join(f"{expression(c.get('CaseIndexValueTerm'))}=>{expression(c.get('CaseTerm'))}" for c in node.get("Cases", []))
        return f"switch({expression(node.get('IndexTerm'))}){{{cases}; default=>{expression(node.get('DefaultTerm'))}}}"
    if token in FLOW:
        condition = expression(node["BooleanExpression"]) if "BooleanExpression" in node else ""
        return f"{token[3:]} {node.get('PushingAddress', '')} {condition}".strip()
    rest = {key: value for key, value in node.items() if key not in ("Token", "StatementIndex", "ObjectPath")}
    return f"{token}{json.dumps(rest)[:200]}"


def statements(function):
    """The statements of a ``Function`` export as text, in bytecode order."""
    return [expression(statement) for statement in function.get("ScriptBytecode") or []]


def function_named(exports, function_name):
    """The ``Function`` export called ``function_name``; KeyError when the Blueprint has none."""
    for export in exports:
        if export.get("Type") == "Function" and export.get("Name") == function_name:
            return export
    raise KeyError(f"no function {function_name}")


def added_constant(function, source):
    """What ``function`` adds to the value named ``source`` before it uses or shows it.

    Follows ``source`` through the implicit casts the compiler inserts and returns the constant of the first
    ``Add_DoubleDouble(value, constant)``; 0.0 when the value goes to ``Conv_DoubleToText`` as it is. A widget
    reads ``source`` either as a variable of its own or as a member of another object (``Turret.CachedTubePitch``).
    Raises ValueError when the function does neither, so a widget rewritten by a game patch is noticed instead of
    being read as "adds nothing".
    """
    aliases = {source}
    for text in statements(function):
        shown = SHOWN.search(text)
        if shown and shown.group("operand") in aliases:
            return 0.0
        assignment = ASSIGNMENT.match(text)
        if not assignment:
            continue
        value = assignment.group("value")
        cast = CAST.match(value)
        if cast and (cast.group("inner") in aliases or cast.group("inner").endswith("." + source)):
            aliases.add(assignment.group("target"))
            continue
        addition = ADDITION.match(value)
        if addition and addition.group("operand") in aliases:
            return float(addition.group("constant"))
    raise ValueError(f"{function.get('Name')}: {source} is neither shown nor added to a constant")


def main(argv):
    if not 2 <= len(argv) <= 3:
        sys.exit(__doc__)
    pattern = re.compile(argv[2]) if len(argv) == 3 else None
    with open(argv[1], encoding="utf-8") as dump:
        exports = json.load(dump)
    for export in exports:
        if export.get("Type") != "Function" or (pattern and not pattern.search(export["Name"])):
            continue
        print(f"--- {export['Name']}")
        for statement, text in zip(export.get("ScriptBytecode") or [], statements(export)):
            print(f"{statement.get('StatementIndex', '')}: {text}")


if __name__ == "__main__":
    main(sys.argv)
