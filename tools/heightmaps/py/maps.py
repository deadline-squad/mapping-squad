"""SquadCalc map folder -> SquadHeight export name and the game levels holding its landscape.

Level paths are relative to the SquadExtract output root (the umap path without extension).
Belaya is absent: it is not in the current game build and SquadHeight covers other bounds than SquadCalc.
"""

MAPS = {
    "albasrah": ("AlBasrah", ["SquadGame/Plugins/Al_Basrah/Content/Maps/Sublevels/070_Landscape/L_070_Landscape_AlBasrah_01"]),
    "anvil": ("Anvil", ["SquadGame/Content/Maps/Anvil/Anvil_GEO"]),
    "blackcoast": ("BlackCoast", ["SquadGame/Plugins/Expansions/BlackCoast/Content/Maps/Black_Coast_Geo"]),
    "chora": ("Chora", ["SquadGame/Content/Maps/Chora/Chora"]),
    "fallujah": ("Fallujah", [f"SquadGame/Content/Maps/Fallujah_City/Sublevels/070_Landscape/L_070_Landscape_Fallujah_0{i}" for i in (0, 1, 3, 4, 5)]),
    "foolsroad": ("FoolsRoad", ["SquadGame/Content/Maps/Fools_Road/Fools_Road_Landscape_and_Geo"]),
    "goosebay": ("GooseBay", ["SquadGame/Content/Maps/Goose_Bay/Goose_Bay"]),
    "gorodok": ("Gorodok", ["SquadGame/Content/Maps/Gorodok/Sublevels/070_Landscape/L_070_Landscape_Gorodok"]),
    "harju": ("Harju", ["SquadGame/Plugins/Expansions/Harju/Content/Maps/Harju_Landscape"]),
    "jensen": ("Jensen", ["SquadGame/Content/Maps/Jensens_Range/Jensens_Range_Geo"]),
    "kamdesh": ("Kamdesh", ["SquadGame/Content/Maps/Kamdesh_Highlands/Kamdesh_Highlands"]),
    "kohat": ("Kohat", ["SquadGame/Content/Maps/Kohat/Kohat_landscape"]),
    "kokan": ("Kokan", ["SquadGame/Content/Maps/Kokan_Valley/Kokan_Valley_Landscape"]),
    "lashkar": ("Lashkar", ["SquadGame/Content/Maps/Lashkar_Valley/Lashkar_GEO"]),
    "logar": ("Logar", ["SquadGame/Content/Maps/Logar_Valley/Logar_Valley_landscape"]),
    "manicouagan": ("Manicouagan", ["SquadGame/Content/Maps/Manicouagan/Manicouagan_geo"]),
    "mestia": ("Mestia", ["SquadGame/Content/Maps/Mestia_Green/Mestia_Geo"]),
    "mutaha": ("Mutaha", ["SquadGame/Content/Maps/Mutaha/Sublevels/070_Landscape/L_070_Mutaha_Landscape"]),
    "narva": ("Narva", ["SquadGame/Content/Maps/Narva/Sublevels/070_Landscape/L_070_Landscape_Narva"]),
    "pacific": ("Pacific", ["SquadGame/Content/Maps/PacificProvingGrounds/PacificProvingGrounds_Geo"]),
    "sanxian": ("Sanxian", ["SquadGame/Plugins/Expansions/SanxianIslands/Content/Maps/Sublevels/070_Landscape/L_070_Landscape_Sanxian_01"]),
    "skorpo": ("Skorpo", ["SquadGame/Content/Maps/Skorpo/Skorpo_Baselayer"]),
    "sumari": ("Sumari", ["SquadGame/Content/Maps/Sumari/Sumari_master"]),
    "tallil": ("Tallil", ["SquadGame/Content/Maps/Tallil_Outskirts/Tallil_Outskirts"]),
    "yehorivka": ("Yehorivka", ["SquadGame/Content/Maps/Yehorivka/Sublevels/070_Landscape/L_070_Landscape_Yehorivka"]),
}


# Heightmap cell size in metres of the maps whose landscape has vertices every 0.5 m (landscape scale 50:
# a 1 m grid drops every other vertex); every other map is built on SquadHeight's 1 m grid
DEFAULT_CELL_M = 1.0
CELL_M = {"chora": 0.5, "kokan": 0.5}


def cell_m(slug):
    """Cell size in metres of a map's heightmap grid."""
    return CELL_M.get(slug, DEFAULT_CELL_M)


def statics_root(slug):
    """Path filter of every level of a map, for ``SquadExtract statics``: its map folder, or its plugin."""
    level = MAPS[slug][1][0]
    if "/Plugins/" in level:
        return level[:level.index("/Content/") + 1]
    parts = level.split("/")
    return "/".join(parts[:4]) + "/"
