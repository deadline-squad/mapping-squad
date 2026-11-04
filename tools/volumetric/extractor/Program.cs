using CUE4Parse.Compression;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Versions;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Objects.UObject;
using Newtonsoft.Json;

// Volumetric-data extractor: read-only inventory and dumps from the dedicated server paks.
//   inventory <path filter> <out.json>   per level: export type -> count (every non-gameplay umap under the filter)
//   dump <package> <out.json> [type ...] exports of a package (all, or only the given export types) as JSON
//   props <package> <type> <max>         first <max> exports of a type with their property names
//   foliage <path filter> <outdir>      foliage placements with collision on, in the layout of the repo's statics mode
//   meshsections <list.txt> <out.ndjson> per static mesh object path (one per line): LOD0 sections (material slot,
//                                        triangles, bEnableCollision), materials with the physical material they resolve to
var paks = args[0];
var mode = args[1];
OodleHelper.Initialize(Path.Combine(AppContext.BaseDirectory, OodleHelper.OodleFileName));
var provider = new DefaultFileProvider(paks, SearchOption.TopDirectoryOnly, new VersionContainer(EGame.GAME_Squad));
provider.Initialize();
provider.Mount();

if (mode == "inventory")
{
    var levels = provider.Files.Keys.Where(k => k.EndsWith(".umap") && k.Contains(args[2], StringComparison.OrdinalIgnoreCase)).Order().ToList();
    var result = new Dictionary<string, Dictionary<string, int>>();
    foreach (var level in levels)
    {
        try
        {
            var package = provider.LoadPackage(level);
            var counts = new Dictionary<string, int>();
            foreach (var export in package.GetExports())
                counts[export.ExportType] = counts.GetValueOrDefault(export.ExportType) + 1;
            result[level] = counts;
        }
        catch (Exception e)
        {
            result[level] = new Dictionary<string, int> { ["FAILED:" + e.GetType().Name] = 1 };
        }
    }
    File.WriteAllText(args[3], JsonConvert.SerializeObject(result, Formatting.Indented));
}
else if (mode == "dump")
{
    var package = provider.LoadPackage(args[2]);
    var types = args.Skip(4).ToHashSet();
    var exports = package.GetExports().Where(e => types.Count == 0 || types.Contains(e.ExportType));
    File.WriteAllText(args[3], JsonConvert.SerializeObject(exports, Formatting.Indented));
}
else if (mode == "foliage")
{
    // foliage <path filter> <outdir>: placements of foliage components whose collision is on (trees, rocks), in the
    // layout of the repo's `statics` mode (instances.ndjson, bodies/<n>.json + .Chaos.bin). The mesh path is
    // resolved without regard to case: the pak paths and the paths inside the levels differ in case.
    var outDir = args[3];
    Directory.CreateDirectory(Path.Combine(outDir, "bodies"));
    var lower = provider.Files.Keys.Where(k => k.EndsWith(".uasset")).ToDictionary(k => k[..^".uasset".Length].ToLowerInvariant(), k => k[..^".uasset".Length], StringComparer.Ordinal);
    var levels = provider.Files.Keys.Where(k => k.EndsWith(".umap") && k.Contains(args[2], StringComparison.OrdinalIgnoreCase) && !k.Contains("/Gameplay_Layers/")).Order().ToList();
    var meshes = new Dictionary<string, int>();
    using var instances = new StreamWriter(Path.Combine(outDir, "instances.ndjson"));
    foreach (var level in levels)
    {
        try
        {
            var package = provider.LoadPackage(level);
            foreach (var component in package.GetExports().OfType<CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.UFoliageInstancedStaticMeshComponent>())
            {
                var collision = component.Properties.FirstOrDefault(p => p.Name.Text == "BodyInstance")?.Tag?.GenericValue;
                var profile = JsonConvert.DeserializeObject<Dictionary<string, object>>(JsonConvert.SerializeObject(collision) ?? "{}")?.GetValueOrDefault("CollisionProfileName") as string;
                if (profile == null || profile == "NoCollision") continue;
                var meshPath = component.GetOrDefault<FPackageIndex>("StaticMesh")?.ResolvedObject?.GetPathName();
                if (meshPath == null) continue;
                var objectPath = meshPath[..meshPath.LastIndexOf('.')];
                if (!lower.TryGetValue(objectPath.TrimStart('/').Replace("Game/", "squadgame/content/").ToLowerInvariant(), out var real)) continue;
                if (!meshes.TryGetValue(real, out var id))
                {
                    id = meshes.Count;
                    meshes[real] = id;
                    DumpBody(provider, real, Path.Combine(outDir, "bodies", id.ToString()));
                }
                var perInstance = (component.PerInstanceSMData ?? []).Select(i => (object)new { q = i.TransformData.Rotation, t = i.TransformData.Translation, s = i.TransformData.Scale3D }).ToArray();
                instances.WriteLine(JsonConvert.SerializeObject(new { level, type = component.ExportType, mesh = id.ToString(), chain = AttachChain(component), collision, instances = perInstance }));
            }
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"{level}: FAILED {e.GetType().Name}: {e.Message}");
        }
    }
    File.WriteAllText(Path.Combine(outDir, "meshes.json"), JsonConvert.SerializeObject(meshes, Formatting.Indented));
}
else if (mode == "meshsections")
{
    using var output = new StreamWriter(args[3]);
    foreach (var meshPath in File.ReadLines(args[2]).Where(l => l.Length > 0))
    {
        try
        {
            var mesh = provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.StaticMesh.UStaticMesh>(meshPath);
            var sections = mesh.RenderData?.LODs?.FirstOrDefault()?.Sections ?? [];
            var materials = (mesh.StaticMaterials ?? []).Select(m => new
            {
                slot = m.MaterialSlotName.Text,
                material = m.MaterialInterface?.ResolvedObject?.GetPathName(),
                physMaterial = ResolvePhysMaterial(m.MaterialInterface),
            }).ToArray();
            var body = mesh.BodySetup?.Load<CUE4Parse.UE4.Objects.PhysicsEngine.UBodySetup>();
            output.WriteLine(JsonConvert.SerializeObject(new
            {
                path = meshPath,
                traceFlag = body?.GetOrDefault<string>("CollisionTraceFlag"),
                bodyPhysMaterial = body?.GetOrDefault<FPackageIndex>("PhysMaterial")?.ResolvedObject?.GetPathName(),
                sections = sections.Select(s => new { s.MaterialIndex, s.NumTriangles, s.bEnableCollision }),
                materials,
            }));
        }
        catch (Exception e)
        {
            output.WriteLine(JsonConvert.SerializeObject(new { path = meshPath, error = e.Message }));
        }
    }
}
else if (mode == "props")
{
    var package = provider.LoadPackage(args[2]);
    foreach (var export in package.GetExports().Where(e => e.ExportType == args[3]).Take(int.Parse(args[4])))
        Console.WriteLine(export.Name + ": " + string.Join(", ", export.Properties.Select(p => p.Name.Text)));
}

// Relative transforms of a component and its attach parents, component first, root last
static List<object> AttachChain(CUE4Parse.UE4.Assets.Exports.UObject component)
{
    var chain = new List<object>();
    CUE4Parse.UE4.Assets.Exports.UObject? node = component;
    for (var depth = 0; node != null && depth < 32; depth++)
    {
        chain.Add(new
        {
            l = node.GetOrDefault("RelativeLocation", new FVector(0, 0, 0)),
            r = node.GetOrDefault("RelativeRotation", new FRotator(0, 0, 0)),
            s = node.GetOrDefault("RelativeScale3D", new FVector(1, 1, 1)),
        });
        var parent = node.GetOrDefault<FPackageIndex>("AttachParent");
        node = parent == null || parent.IsNull ? null : parent.Load();
    }
    return chain;
}

static void DumpBody(DefaultFileProvider provider, string meshPath, string prefix, CUE4Parse.UE4.Objects.PhysicsEngine.UBodySetup? ownBody = null, FStructFallback? spline = null)
{
    try
    {
        var mesh = provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.StaticMesh.UStaticMesh>(meshPath);
        var body = ownBody ?? mesh.BodySetup?.Load<CUE4Parse.UE4.Objects.PhysicsEngine.UBodySetup>();
        var meshDefault = ownBody != null ? mesh.BodySetup?.Load<CUE4Parse.UE4.Objects.PhysicsEngine.UBodySetup>()?.GetOrDefault<FStructFallback>("DefaultInstance") : null;
        File.WriteAllText(prefix + ".json", JsonConvert.SerializeObject(new { path = meshPath, bounds = mesh.RenderData?.Bounds, body, spline, meshDefault }, Formatting.Indented));
        foreach (var (format, bulk) in body?.CookedFormatData?.Formats ?? [])
            if (bulk.Data != null) File.WriteAllBytes($"{prefix}.{format.Text}.bin", bulk.Data);
    }
    catch (Exception e)
    {
        File.WriteAllText(prefix + ".json", JsonConvert.SerializeObject(new { path = meshPath, error = e.Message }));
    }
}


// Physical material of a material interface: its own PhysMaterial, else the nearest parent's.
static string? ResolvePhysMaterial(FPackageIndex? materialInterface)
{
    var node = materialInterface?.Load();
    for (var depth = 0; node != null && depth < 16; depth++)
    {
        var physical = node.GetOrDefault<FPackageIndex>("PhysMaterial");
        if (physical != null && !physical.IsNull) return physical.ResolvedObject?.GetPathName();
        var parent = node.GetOrDefault<FPackageIndex>("Parent");
        node = parent == null || parent.IsNull ? null : parent.Load();
    }
    return null;
}
