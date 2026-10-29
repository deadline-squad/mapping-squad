using CUE4Parse.Compression;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.Component.Landscape;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.UE4.Versions;
using Newtonsoft.Json;

var paks = args[0];
var mode = args[1];
OodleHelper.Initialize(Path.Combine(AppContext.BaseDirectory, OodleHelper.OodleFileName));
var provider = new DefaultFileProvider(paks, SearchOption.TopDirectoryOnly, new VersionContainer(EGame.GAME_Squad));
provider.Initialize();
provider.Mount();
Console.Error.WriteLine($"files: {provider.Files.Count}");

if (mode == "list")
{
    foreach (var path in provider.Files.Keys.Where(k => k.Contains(args[2], StringComparison.OrdinalIgnoreCase)).Order())
        Console.WriteLine(path);
}
else if (mode == "probe")
{
    var package = provider.LoadPackage(args[2]);
    foreach (var export in package.GetExports())
        Console.WriteLine($"{export.ExportType}\t{export.Name}");
}
else if (mode == "json")
{
    var package = provider.LoadPackage(args[2]);
    foreach (var export in package.GetExports().Where(e => e.Name == args[3] || e.ExportType == args[3]).Take(int.Parse(args.ElementAtOrDefault(4) ?? "1")))
        Console.WriteLine(JsonConvert.SerializeObject(export, Formatting.Indented));
}
else if (mode == "mesh")
{
    var mesh = provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.StaticMesh.UStaticMesh>(args[2]);
    var lods = mesh.RenderData?.LODs;
    Console.WriteLine($"lods={lods?.Length ?? 0} verts0={lods?.FirstOrDefault()?.PositionVertexBuffer?.Verts.Length ?? 0} bounds={mesh.RenderData?.Bounds} body={mesh.BodySetup?.Name}");
    var body = mesh.BodySetup?.Load();
    if (body != null) Console.WriteLine(JsonConvert.SerializeObject(body, Formatting.Indented)[..Math.Min(3000, JsonConvert.SerializeObject(body).Length)]);
}
else if (mode == "dumpall")
{
    // dumpall <regex over paths> <outdir>: every matching .uasset/.umap as JSON (all exports) under
    // <outdir>/<path>.json; used by tools/game_ballistics to read weapon and projectile Blueprints
    var re = new System.Text.RegularExpressions.Regex(args[2], System.Text.RegularExpressions.RegexOptions.IgnoreCase);
    foreach (var path in provider.Files.Keys.Where(k => (k.EndsWith(".uasset") || k.EndsWith(".umap")) && re.IsMatch(k)).Order())
    {
        var target = Path.Combine(args[3], path + ".json");
        try
        {
            var package = provider.LoadPackage(path);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.WriteAllText(target, JsonConvert.SerializeObject(package.GetExports(), Formatting.Indented));
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"{path}: FAILED {e.GetType().Name}: {e.Message}");
        }
    }
}
else if (mode == "statics")
{
    // statics <path filter> <outdir>: every static mesh placement of the levels under the filter
    // (gameplay layers excluded, foliage excluded) into <outdir>/instances.ndjson, and each mesh's
    // bounds and collision into <outdir>/bodies/<n>.json (+ <n>.<format>.bin cooked collision).
    var outDir = args[3];
    Directory.CreateDirectory(Path.Combine(outDir, "bodies"));
    var levels = provider.Files.Keys.Where(k => k.EndsWith(".umap") && k.Contains(args[2], StringComparison.OrdinalIgnoreCase) && !k.Contains("/Gameplay_Layers/")).Order().ToList();
    var meshes = new Dictionary<string, int>();
    var splineCount = 0;
    using var instances = new StreamWriter(Path.Combine(outDir, "instances.ndjson"));
    foreach (var level in levels)
    {
        var placed = 0;
        try
        {
            var package = provider.LoadPackage(level);
            foreach (var component in package.GetExports().OfType<CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.UStaticMeshComponent>())
            {
                if (component is CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.UFoliageInstancedStaticMeshComponent) continue;
                var meshIndex = component.GetOrDefault<FPackageIndex>("StaticMesh");
                if (meshIndex == null || meshIndex.IsNull) continue;
                var meshPath = meshIndex.ResolvedObject?.GetPathName();
                if (meshPath == null) continue;
                string meshId;
                var splineBody = component.ExportType == "SplineMeshComponent" ? component.GetOrDefault<FPackageIndex>("BodySetup") : null;
                if (splineBody != null && !splineBody.IsNull)
                {
                    // A spline mesh collides with its own BodySetup, already bent along the spline
                    meshId = "s" + splineCount++;
                    DumpBody(provider, meshPath, Path.Combine(outDir, "bodies", meshId), splineBody.Load<CUE4Parse.UE4.Objects.PhysicsEngine.UBodySetup>(), component.GetOrDefault<FStructFallback>("SplineParams"));
                }
                else if (component.ExportType == "SplineMeshComponent")
                {
                    continue;
                }
                else if (!meshes.TryGetValue(meshPath, out var known))
                {
                    meshId = meshes.Count.ToString();
                    meshes[meshPath] = meshes.Count;
                    DumpBody(provider, meshPath, Path.Combine(outDir, "bodies", meshId));
                }
                else
                {
                    meshId = known.ToString();
                }
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
                object[]? perInstance = null;
                if (component is CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.UInstancedStaticMeshComponent ism)
                    perInstance = (ism.PerInstanceSMData ?? []).Select(i => (object)new { q = i.TransformData.Rotation, t = i.TransformData.Translation, s = i.TransformData.Scale3D }).ToArray();
                var collision = component.Properties.FirstOrDefault(p => p.Name.Text == "BodyInstance")?.Tag?.GenericValue;
                instances.WriteLine(JsonConvert.SerializeObject(new { level, type = component.ExportType, mesh = meshId, chain, collision, instances = perInstance }));
                placed++;
            }
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"{level}: FAILED {e.GetType().Name}: {e.Message}");
        }
        if (placed > 0) Console.Error.WriteLine($"{level}: {placed} components");
    }
    File.WriteAllText(Path.Combine(outDir, "meshes.json"), JsonConvert.SerializeObject(meshes, Formatting.Indented));
}
else if (mode == "landscape" || mode == "extractall")
{
    // landscape <package> <outdir>: one level. extractall <path filter> <outdir>: every level under the filter
    // except gameplay layers, each into <outdir>/<level path> when it holds landscape collision.
    var levels = mode == "landscape"
        ? new List<string> { args[2] }
        : provider.Files.Keys.Where(k => k.EndsWith(".umap") && k.Contains(args[2], StringComparison.OrdinalIgnoreCase) && !k.Contains("/Gameplay_Layers/")).Order().ToList();
    foreach (var level in levels)
    {
        var outDir = mode == "landscape" ? args[3] : Path.Combine(args[3], Path.ChangeExtension(level, null));
        try
        {
            var written = ExtractLandscape(provider, level, outDir);
            if (written > 0) Console.Error.WriteLine($"{level}: components {written}");
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"{level}: FAILED {e.GetType().Name}: {e.Message}");
        }
    }
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

static int ExtractLandscape(DefaultFileProvider provider, string level, string outDir)
{
    var package = provider.LoadPackage(level);
    var components = package.GetExports().OfType<ULandscapeHeightfieldCollisionComponent>().ToList();
    if (components.Count == 0) return 0;
    Directory.CreateDirectory(outDir);
    var roots = new HashSet<string>();
    foreach (var export in components)
    {
        var parent = export.GetOrDefault<FPackageIndex>("AttachParent");
        if (parent != null && !parent.IsNull && roots.Add(parent.ResolvedObject?.GetPathName() ?? parent.Name))
        {
            var root = parent.Load();
            if (root != null)
                File.WriteAllText(Path.Combine(outDir, "root_" + root.Outer?.Name + "." + root.Name + ".json"), JsonConvert.SerializeObject(root, Formatting.Indented));
        }
        File.WriteAllText(Path.Combine(outDir, export.Name + ".json"), JsonConvert.SerializeObject(export, Formatting.Indented));
        if (export.CookedCollisionData != null)
            File.WriteAllBytes(Path.Combine(outDir, export.Name + ".bin"), export.CookedCollisionData);
    }
    return components.Count;
}
