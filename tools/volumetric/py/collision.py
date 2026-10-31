"""Which kinds of query a placed static mesh blocks, from its Unreal collision settings.

A component's ``BodyInstance`` (as written by ``SquadExtract statics``) holds only the overrides of the mesh's
own default instance. A channel's response is, in order: the component override, the mesh default, Block.
``CollisionEnabled`` NoCollision/PhysicsOnly switches queries off, the NoCollision and Overlap* profiles
answer Ignore/Overlap on every channel.

The three query classes the consumers care about are the Unreal channels ``Visibility`` (line of sight, the
SquadHeight trace), ``Projectile`` (bullets and mortar shells) and ``Pawn`` (players walking).
"""

VISIBILITY = 1
PROJECTILE = 2
PAWN = 4
CHANNELS = {"Visibility": VISIBILITY, "Projectile": PROJECTILE, "Pawn": PAWN}
NO_QUERY = ("ECollisionEnabled::NoCollision", "ECollisionEnabled::PhysicsOnly")
NON_BLOCKING_PROFILES = ("NoCollision", "OverlapAll", "OverlapAllDynamic", "UI")


def _responses(instance):
    return {r["Channel"]: r["Response"] for r in (instance.get("CollisionResponses") or {}).get("ResponseArray", [])}


def block_mask(component, mesh_default):
    """Bit set of VISIBILITY | PROJECTILE | PAWN that a mesh placement blocks.

    ``component`` is the placement's BodyInstance overrides (or None), ``mesh_default`` the mesh
    BodySetup's DefaultInstance (or None). Bits are 0 where the response is Ignore or Overlap.
    """
    component = component or {}
    mesh_default = mesh_default or {}
    enabled = component.get("CollisionEnabled") or mesh_default.get("CollisionEnabled")
    profile = component.get("CollisionProfileName") or mesh_default.get("CollisionProfileName")
    if enabled in NO_QUERY or profile in NON_BLOCKING_PROFILES:
        return 0
    responses = {**_responses(mesh_default), **_responses(component)}
    mask = 0
    for channel, bit in CHANNELS.items():
        if responses.get(channel, "ECR_Block") == "ECR_Block":
            mask |= bit
    return mask
