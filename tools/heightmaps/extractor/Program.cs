using CUE4Parse.Compression;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.Component.Landscape;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.UE4.Versions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System.Text.RegularExpressions;

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
                var chain = AttachChain(component);
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
else if (mode == "texraw")
{
    var re = new System.Text.RegularExpressions.Regex(args[2], System.Text.RegularExpressions.RegexOptions.IgnoreCase);
    Directory.CreateDirectory(args[3]);
    foreach (var path in provider.Files.Keys.Where(k => k.EndsWith(".uasset") && re.IsMatch(k)).Order())
    {
        try
        {
            var texture = provider.LoadPackage(path).GetExports().OfType<CUE4Parse.UE4.Assets.Exports.Texture.UTexture2D>().FirstOrDefault();
            var mip = texture?.GetFirstMip();
            if (texture == null || mip?.BulkData?.Data == null) { Console.Error.WriteLine($"{path}: no pixel data"); continue; }
            var name = Path.GetFileNameWithoutExtension(path);
            File.WriteAllBytes(Path.Combine(args[3], $"{name}.{texture.Format}.{mip.SizeX}x{mip.SizeY}.bin"), mip.BulkData.Data);
            Console.WriteLine($"{name} {texture.Format} {mip.SizeX}x{mip.SizeY} {mip.BulkData.Data.Length}");
        }
        catch (Exception e) { Console.Error.WriteLine($"{path}: FAILED {e.GetType().Name}: {e.Message}"); }
    }
}
else if (mode == "layerminimaps")
{
    // layerminimaps <regex over paths>: one line per gameplay layer: path, MapTexture, then the two minimap corners (cm)
    var re = new System.Text.RegularExpressions.Regex(args[2], System.Text.RegularExpressions.RegexOptions.IgnoreCase);
    foreach (var path in provider.Files.Keys.Where(k => k.EndsWith(".umap") && k.Contains("/Gameplay_Layers/") && re.IsMatch(k)).Order())
    {
        try
        {
            var exports = provider.LoadPackage(path).GetExports().ToList();
            var settings = exports.FirstOrDefault(e => e.ExportType == "SQWorldSettings");
            if (settings == null) { Console.WriteLine($"{path}\tno world settings"); continue; }
            var texture = settings.GetOrDefault<FPackageIndex>("MapTexture")?.ResolvedObject?.GetPathName() ?? "";
            string Corner(string key)
            {
                var actorName = settings.GetOrDefault<FPackageIndex>(key)?.ResolvedObject?.Name.Text;
                var root = exports.FirstOrDefault(e => (e.ExportType == "SceneComponent" || e.ExportType == "StaticMeshComponent") && e.Outer?.Name.Text == actorName);
                var loc = root?.GetOrDefault<FVector>("RelativeLocation");
                return loc == null ? "?\t?" : $"{loc.Value.X}\t{loc.Value.Y}";
            }
            Console.WriteLine($"{path}\t{texture}\t{Corner("MapTextureCornerZero")}\t{Corner("MapTextureCornerOne")}");
        }
        catch (Exception e) { Console.WriteLine($"{path}\tFAILED {e.GetType().Name}: {e.Message}"); }
    }
}
else if (mode == "features")
{
    // features <path filter> <outdir>: map features for tools/maptiles from the levels under the filter, one
    // pass per level, as ndjson in <outdir>:
    //   foliage.ndjson  one line per FoliageInstancedStaticMeshComponent: level, mesh path, the mesh's render
    //                   bounds (cm, mesh space) and whether it has collision, the attach chain, the component's
    //                   BodyInstance, and the instances as [x, y, z, yaw, scale] rows in component space;
    //   splines.ndjson  one line per LandscapeSplineSegment: level, the splines component's attach chain, the
    //                   segment's interpolated points (Center, Left, Right; component space, cm) and the meshes
    //                   laid along it (roads, tracks, rivers, walls, hedges, fences);
    //   water.ndjson    one line per component of an ocean or water actor (class name containing Ocean or
    //                   Water): level, actor class, component name and type, static mesh and attach chain.
    var outDir = args[3];
    Directory.CreateDirectory(outDir);
    var levels = provider.Files.Keys.Where(k => k.EndsWith(".umap") && k.Contains(args[2], StringComparison.OrdinalIgnoreCase) && !k.Contains("/Gameplay_Layers/")).Order().ToList();
    var meshInfo = new Dictionary<string, object?>();
    using var foliage = new StreamWriter(Path.Combine(outDir, "foliage.ndjson"));
    using var splines = new StreamWriter(Path.Combine(outDir, "splines.ndjson"));
    using var water = new StreamWriter(Path.Combine(outDir, "water.ndjson"));
    var Vec = (FStructFallback p, string key) => { var v = p.GetOrDefault<FVector>(key); return new[] { Math.Round(v.X, 1), Math.Round(v.Y, 1), Math.Round(v.Z, 1) }; };
    foreach (var level in levels)
    {
        int trees = 0, segments = 0, waters = 0;
        try
        {
            var package = provider.LoadPackage(level);
            foreach (var export in package.GetExports())
            {
                if (export is CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.UFoliageInstancedStaticMeshComponent component)
                {
                    var meshPath = component.GetOrDefault<FPackageIndex>("StaticMesh")?.ResolvedObject?.GetPathName();
                    if (meshPath == null) continue;
                    if (!meshInfo.TryGetValue(meshPath, out var info))
                    {
                        try
                        {
                            var mesh = provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.StaticMesh.UStaticMesh>(meshPath);
                            var body = mesh.BodySetup?.Load<CUE4Parse.UE4.Objects.PhysicsEngine.UBodySetup>();
                            info = new { bounds = mesh.RenderData?.Bounds, collision = body?.CookedFormatData?.Formats.Count > 0 || body?.GetOrDefault<FStructFallback>("AggGeom") != null };
                        }
                        catch (Exception e)
                        {
                            info = new { error = e.Message };
                        }
                        meshInfo[meshPath] = info;
                    }
                    var rows = (component.PerInstanceSMData ?? []).Select(i =>
                    {
                        var t = i.TransformData;
                        return new[] { Math.Round(t.Translation.X, 1), Math.Round(t.Translation.Y, 1), Math.Round(t.Translation.Z, 1), Math.Round(t.Rotation.Rotator().Yaw, 1), Math.Round(t.Scale3D.X, 3) };
                    }).ToArray();
                    foliage.WriteLine(JsonConvert.SerializeObject(new { level, mesh = meshPath, info, chain = AttachChain(component), collision = component.Properties.FirstOrDefault(p => p.Name.Text == "BodyInstance")?.Tag?.GenericValue, instances = rows }));
                    trees += rows.Length;
                }
                else if (export.ExportType == "LandscapeSplineSegment")
                {
                    var owner = export.Outer?.Load();
                    var points = export.GetOrDefault<FStructFallback[]>("Points") ?? [];
                    var meshes = (export.GetOrDefault<FPackageIndex[]>("LocalMeshComponents") ?? [])
                        .Select(m => m.Load()?.GetOrDefault<FPackageIndex>("StaticMesh")?.ResolvedObject?.GetPathName())
                        .Where(p => p != null).Distinct().ToArray();
                    splines.WriteLine(JsonConvert.SerializeObject(new
                    {
                        level,
                        chain = owner == null ? null : AttachChain(owner),
                        center = points.Select(p => Vec(p, "Center")),
                        left = points.Select(p => Vec(p, "Left")),
                        right = points.Select(p => Vec(p, "Right")),
                        meshes,
                    }));
                    segments++;
                }
                else if (export is CUE4Parse.UE4.Assets.Exports.Component.USceneComponent scene)
                {
                    var actorClass = scene.Outer?.Load()?.ExportType ?? "";
                    if (!actorClass.Contains("Ocean", StringComparison.OrdinalIgnoreCase) && !actorClass.Contains("Water", StringComparison.OrdinalIgnoreCase)) continue;
                    water.WriteLine(JsonConvert.SerializeObject(new
                    {
                        level,
                        actor = actorClass,
                        component = scene.Name,
                        type = scene.ExportType,
                        mesh = scene.GetOrDefault<FPackageIndex>("StaticMesh")?.ResolvedObject?.GetPathName(),
                        chain = AttachChain(scene),
                    }));
                    waters++;
                }
            }
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"{level}: FAILED {e.GetType().Name}: {e.Message}");
        }
        if (trees + segments + waters > 0) Console.Error.WriteLine($"{level}: {trees} foliage instances, {segments} spline segments, {waters} water components");
    }
}
else if (mode == "typestats")
{
    // typestats <path filter>: export types per level that are not plain engine components, to find Blueprint placements
    var counts = new Dictionary<string, int>();
    foreach (var level in provider.Files.Keys.Where(k => k.EndsWith(".umap") && k.Contains(args[2], StringComparison.OrdinalIgnoreCase) && !k.Contains("/Gameplay_Layers/")).Order())
    {
        try
        {
            foreach (var export in provider.LoadPackage(level).GetExports())
                counts[export.ExportType] = counts.GetValueOrDefault(export.ExportType) + 1;
        }
        catch (Exception e) { Console.Error.WriteLine($"{level}: FAILED {e.Message}"); }
    }
    foreach (var (type, count) in counts.OrderByDescending(kv => kv.Value)) Console.WriteLine($"{count}\t{type}");
}
else if (mode == "scene")
{
    // scene <path filter> <outdir>: everything a top-down renderer needs from the client paks. instances.ndjson: every static mesh
    // placement (foliage and spline meshes too) with its override materials; meshes.json and meshes/<n>.bin: first usable LOD as
    // 32 byte vertices (position xyz, normal xyz, uv) followed by 32 bit indices, with sections and materials; materials.json: blend
    // mode and texture, colour and scalar parameters of each material; textures.json and textures/<n>.bin: mip of at most 512 px, decoded.
    var outDir = args[3];
    CUE4Parse_Conversion.Textures.TextureDecoder.UseAssetRipperTextureDecoder = true;
    Directory.CreateDirectory(Path.Combine(outDir, "meshes"));
    Directory.CreateDirectory(Path.Combine(outDir, "textures"));
    var levels = provider.Files.Keys.Where(k => k.EndsWith(".umap") && k.Contains(args[2], StringComparison.OrdinalIgnoreCase) && !k.Contains("/Gameplay_Layers/")).Order().ToList();
    var meshes = new Dictionary<string, JObject>();
    var materials = new Dictionary<string, JObject>();
    var textures = new Dictionary<string, JObject>();
    using var instances = new StreamWriter(Path.Combine(outDir, "instances.ndjson"));

    string? ObjectPath(FPackageIndex? index) => index == null || index.IsNull ? null : index.ResolvedObject?.GetPathName();

    void AddTexture(string name, CUE4Parse.UE4.Assets.Exports.Texture.UTexture2D texture)
    {
        var path = texture.GetPathName();
        if (textures.ContainsKey(path)) return;
        var decoded = CUE4Parse_Conversion.Textures.TextureDecoder.Decode(texture, 512);
        if (decoded == null) { textures[path] = new JObject { ["error"] = "no pixel data" }; return; }
        var file = textures.Count.ToString();
        File.WriteAllBytes(Path.Combine(outDir, "textures", file + ".bin"), decoded.Data);
        textures[path] = new JObject { ["file"] = file, ["format"] = decoded.PixelFormat.ToString(), ["width"] = decoded.Width, ["height"] = decoded.Height, ["srgb"] = texture.SRGB, ["bytes"] = decoded.Data.Length };
    }

    void AddMaterial(string? path, CUE4Parse.UE4.Assets.Exports.Material.UMaterialInterface? material)
    {
        if (path == null || material == null || materials.ContainsKey(path)) return;
        var parameters = new CUE4Parse.UE4.Assets.Exports.Material.CMaterialParams2();
        var entry = new JObject();
        materials[path] = entry;
        try
        {
            material.GetParams(parameters, CUE4Parse.UE4.Assets.Exports.Material.EMaterialDepth.AllLayersNoRef);
            var names = new JObject();
            foreach (var key in parameters.Textures.Keys)
            {
                var texture = parameters.GetTextures(new[] { key }).OfType<CUE4Parse.UE4.Assets.Exports.Texture.UTexture2D>().FirstOrDefault();
                if (texture == null) continue;
                names[key] = texture.GetPathName();
                if (!Regex.IsMatch(key, CUE4Parse.UE4.Assets.Exports.Material.CMaterialParams2.RegexNormals, RegexOptions.IgnoreCase)) AddTexture(key, texture);
            }
            entry["textures"] = names;
            entry["blend"] = parameters.BlendMode.ToString();
            entry["shading"] = parameters.ShadingModel.ToString();
            entry["colors"] = JObject.FromObject(parameters.Colors.ToDictionary(kv => kv.Key, kv => new[] { kv.Value.R, kv.Value.G, kv.Value.B, kv.Value.A }));
            entry["scalars"] = JObject.FromObject(parameters.Scalars);
        }
        catch (Exception e) { entry["error"] = e.Message; }
    }

    void AddMesh(string path, CUE4Parse.UE4.Assets.Exports.StaticMesh.UStaticMesh mesh)
    {
        if (meshes.ContainsKey(path)) return;
        var entry = new JObject { ["id"] = meshes.Count };
        meshes[path] = entry;
        var lods = mesh.RenderData?.LODs ?? [];
        var lodIndex = Array.FindIndex(lods, l => !l.SkipLod);
        var slots = mesh.StaticMaterials.Select(m => m.MaterialInterface?.ResolvedObject?.GetPathName()).ToList();
        if (slots.Count == 0) slots = mesh.Materials.Select(m => ObjectPath(m)).ToList();
        var loaded = mesh.StaticMaterials.Select(m => m.MaterialInterface?.Load<CUE4Parse.UE4.Assets.Exports.Material.UMaterialInterface>()).ToList();
        if (loaded.Count == 0) loaded = mesh.Materials.Select(m => m == null || m.IsNull ? null : m.Load<CUE4Parse.UE4.Assets.Exports.Material.UMaterialInterface>()).ToList();
        for (var i = 0; i < slots.Count && i < loaded.Count; i++) AddMaterial(slots[i], loaded[i]);
        entry["materials"] = JArray.FromObject(slots.Select(m => m ?? ""));
        if (lodIndex < 0) { entry["error"] = "no usable LOD"; return; }
        var lod = lods[lodIndex];
        var verts = lod.PositionVertexBuffer!.Verts;
        var uvs = lod.VertexBuffer!.UV;
        var indices = lod.IndexBuffer!.Buffer!;
        using (var writer = new BinaryWriter(File.Create(Path.Combine(outDir, "meshes", entry["id"] + ".bin"))))
        {
            for (var i = 0; i < verts.Length; i++)
            {
                var normal = uvs[i].Normal[2];
                writer.Write(verts[i].X); writer.Write(verts[i].Y); writer.Write(verts[i].Z);
                writer.Write(normal.X); writer.Write(normal.Y); writer.Write(normal.Z);
                writer.Write(uvs[i].UV[0].U); writer.Write(uvs[i].UV[0].V);
            }
            foreach (var index in indices) writer.Write(index);
        }
        entry["lod"] = lodIndex;
        entry["vertices"] = verts.Length;
        entry["indices"] = indices.Length;
        entry["sections"] = JArray.FromObject(lod.Sections.Select(x => new { material = x.MaterialIndex, first = x.FirstIndex, triangles = x.NumTriangles }));
    }

    // A cooked component stores only what differs from its template: a Blueprint's StaticMesh and transforms live in the class
    var templates = new Dictionary<CUE4Parse.UE4.Assets.Exports.UObject, CUE4Parse.UE4.Assets.Exports.UObject?>();
    var exportMaps = new Dictionary<CUE4Parse.UE4.Assets.Package, Dictionary<CUE4Parse.UE4.Assets.Exports.UObject, CUE4Parse.UE4.Objects.UObject.FPackageIndex>>();

    CUE4Parse.UE4.Assets.Exports.UObject? TemplateOf(CUE4Parse.UE4.Assets.Exports.UObject value)
    {
        if (templates.TryGetValue(value, out var known)) return known;
        CUE4Parse.UE4.Assets.Exports.UObject? template = value.Template?.Object?.Value;
        if (template == null && value.Owner is CUE4Parse.UE4.Assets.Package owner)
        {
            if (!exportMaps.TryGetValue(owner, out var map))
            {
                map = new();
                for (var i = 0; i < owner.ExportMap.Length; i++)
                {
                    var loaded = owner.ResolvePackageIndex(new FPackageIndex(owner, i + 1))?.Object?.Value;
                    if (loaded != null) map.TryAdd(loaded, owner.ExportMap[i].TemplateIndex);
                }
                exportMaps[owner] = map;
            }
            if (map.TryGetValue(value, out var index)) template = owner.ResolvePackageIndex(index)?.Object?.Value;
        }
        templates[value] = template;
        return template;
    }

    T Inherited<T>(CUE4Parse.UE4.Assets.Exports.UObject start, string name, T fallback)
    {
        CUE4Parse.UE4.Assets.Exports.UObject? node = start;
        for (var depth = 0; node != null && depth < 16; depth++, node = TemplateOf(node))
            if (node.Properties.Any(p => p.Name.Text == name))
                return node.GetOrDefault(name, fallback);
        return fallback;
    }

    List<object> InheritedChain(CUE4Parse.UE4.Assets.Exports.UObject start)
    {
        var chain = new List<object>();
        CUE4Parse.UE4.Assets.Exports.UObject? node = start;
        for (var depth = 0; node != null && depth < 32; depth++)
        {
            chain.Add(new
            {
                l = Inherited(node, "RelativeLocation", new FVector(0, 0, 0)),
                r = Inherited(node, "RelativeRotation", new FRotator(0, 0, 0)),
                s = Inherited(node, "RelativeScale3D", new FVector(1, 1, 1)),
            });
            var parent = node.GetOrDefault<FPackageIndex>("AttachParent");
            node = parent == null || parent.IsNull ? null : parent.Load();
        }
        return chain;
    }

    var placedComponents = 0;
    var landscapeMaterials = new JObject();

    void PlaceLevel(string level)
    {
        var placed = 0;
        var package = provider.LoadPackage(level);
        var exports = package.GetExports().ToList();
        if (exports.Any(e => e.ExportType == "LandscapeComponent"))
        {
            ExtractWeights(provider, level, Path.Combine(outDir, "landscape", Path.GetFileNameWithoutExtension(level)));
            foreach (var instance in exports.Where(e => e.ExportType == "LandscapeMaterialInstanceConstant").Take(1).OfType<CUE4Parse.UE4.Assets.Exports.Material.UMaterialInterface>())
            {
                var parameters = new CUE4Parse.UE4.Assets.Exports.Material.CMaterialParams2();
                instance.GetParams(parameters, CUE4Parse.UE4.Assets.Exports.Material.EMaterialDepth.AllLayers);
                var names = new JObject();
                foreach (var key in parameters.Textures.Keys)
                {
                    var texture = parameters.GetTextures(new[] { key }).OfType<CUE4Parse.UE4.Assets.Exports.Texture.UTexture2D>().FirstOrDefault();
                    if (texture == null || texture.GetPathName().Contains("PersistentLevel")) continue;
                    names[key] = texture.GetPathName();
                    AddTexture(key, texture);
                }
                landscapeMaterials[level] = new JObject
                {
                    ["textures"] = names,
                    ["colors"] = JObject.FromObject(parameters.Colors.ToDictionary(kv => kv.Key, kv => new[] { kv.Value.R, kv.Value.G, kv.Value.B, kv.Value.A })),
                    ["scalars"] = JObject.FromObject(parameters.Scalars),
                };
            }
        }
        foreach (var component in exports.OfType<CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.UStaticMeshComponent>())
        {
            if (component.ExportType == "LandscapeNaniteComponent") continue;
            var meshIndex = Inherited<FPackageIndex?>(component, "StaticMesh", null);
            if (meshIndex == null || meshIndex.IsNull) continue;
            var meshPath = meshIndex.ResolvedObject?.GetPathName();
            if (meshPath == null) continue;
            var mesh = meshIndex.Load<CUE4Parse.UE4.Assets.Exports.StaticMesh.UStaticMesh>();
            if (mesh == null) continue;
            AddMesh(meshPath, mesh);
            var overrides = new List<string?>();
            foreach (var material in Inherited<FPackageIndex?[]>(component, "OverrideMaterials", []))
            {
                var materialPath = ObjectPath(material);
                overrides.Add(materialPath);
                if (materialPath != null) AddMaterial(materialPath, material!.Load<CUE4Parse.UE4.Assets.Exports.Material.UMaterialInterface>());
            }
            object[]? perInstance = null;
            if (component is CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.UInstancedStaticMeshComponent ism)
            {
                var data = ism.PerInstanceSMData;
                if ((data == null || data.Length == 0) && TemplateOf(ism) is CUE4Parse.UE4.Assets.Exports.Component.StaticMesh.UInstancedStaticMeshComponent template) data = template.PerInstanceSMData;
                perInstance = (data ?? []).Select(i => (object)new { q = new[] { i.TransformData.Rotation.X, i.TransformData.Rotation.Y, i.TransformData.Rotation.Z, i.TransformData.Rotation.W }, t = new[] { i.TransformData.Translation.X, i.TransformData.Translation.Y, i.TransformData.Translation.Z }, s = new[] { i.TransformData.Scale3D.X, i.TransformData.Scale3D.Y, i.TransformData.Scale3D.Z } }).ToArray();
            }
            object? spline = component is CUE4Parse.UE4.Assets.Exports.Component.SplineMesh.USplineMeshComponent sm
                ? new { p = sm.SplineParams, axis = sm.ForwardAxis.ToString(), up = sm.SplineUpDir } : null;
            var hidden = Inherited(component, "bHiddenInGame", false) || !Inherited(component, "bVisible", true);
            instances.WriteLine(JsonConvert.SerializeObject(new { level, name = component.Name, type = component.ExportType, owner = component.Outer?.Class?.Name.Text, mesh = meshes[meshPath]["id"], hidden, cull = new[] { Inherited(component, "InstanceStartCullDistance", 0), Inherited(component, "InstanceEndCullDistance", 0), (int)Inherited(component, "LDMaxDrawDistance", 0f), (int)Inherited(component, "CachedMaxDrawDistance", 0f) }, overrides, chain = InheritedChain(component), instances = perInstance, spline }));
            placed++;
        }
        placedComponents += placed;
        if (placed > 0) Console.Error.WriteLine($"{level}: {placed} components");
    }

    var failedLevels = 0;
    foreach (var level in levels)
    {
        try { PlaceLevel(level); }
        catch (Exception e)
        {
            failedLevels++;
            Console.Error.WriteLine($"{level}: FAILED {e.GetType().Name}: {e.Message}");
        }
        // These two reference every object of the packages they saw, meshes included: a large map outgrows the machine otherwise
        templates.Clear();
        exportMaps.Clear();
    }
    Console.Error.WriteLine($"placed components: {placedComponents}, levels failed: {failedLevels}");
    // A scene without one of its levels would render as a map with a district missing
    if (failedLevels > 0) Environment.Exit(1);
    File.WriteAllText(Path.Combine(outDir, "meshes.json"), JsonConvert.SerializeObject(meshes, Formatting.Indented));
    File.WriteAllText(Path.Combine(outDir, "materials.json"), JsonConvert.SerializeObject(materials, Formatting.Indented));
    File.WriteAllText(Path.Combine(outDir, "landscape.json"), landscapeMaterials.ToString(Formatting.Indented));
    File.WriteAllText(Path.Combine(outDir, "textures.json"), JsonConvert.SerializeObject(textures, Formatting.Indented));
}
else if (mode == "lsweights" || mode == "lsweightsall")
{
    // lsweights <package> <outdir>: the render weight maps of one level's landscape components.
    // lsweightsall <path filter> <outdir>: every level under the filter except gameplay layers, each into <outdir>/<level path>.
    // Per level: components.json (placement, layer allocations) and wm/<texture>.bin (raw mip 0, BGRA, one byte per channel).
    var levels = mode == "lsweights"
        ? new List<string> { args[2] }
        : provider.Files.Keys.Where(k => k.EndsWith(".umap") && k.Contains(args[2], StringComparison.OrdinalIgnoreCase) && !k.Contains("/Gameplay_Layers/")).Order().ToList();
    foreach (var level in levels)
    {
        var outDir = mode == "lsweights" ? args[3] : Path.Combine(args[3], Path.ChangeExtension(level, null));
        try
        {
            var count = ExtractWeights(provider, level, outDir);
            if (count > 0) Console.Error.WriteLine($"{level}: components {count}");
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"{level}: FAILED {e.GetType().Name}: {e.Message}");
        }
    }
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

static string ObjectLeaf(JToken? reference)
{
    var name = reference?["ObjectName"]?.ToString() ?? "";
    var match = Regex.Match(name, @"'(?:[^']*\.)?([^'.]+)'$");
    return match.Success ? match.Groups[1].Value : name;
}

static int ExtractWeights(DefaultFileProvider provider, string level, string outDir)
{
    var package = provider.LoadPackage(level);
    var exports = package.GetExports().ToList();
    var components = exports.Where(e => e.ExportType == "LandscapeComponent").ToList();
    if (components.Count == 0) return 0;
    Directory.CreateDirectory(Path.Combine(outDir, "wm"));
    var textures = new Dictionary<string, CUE4Parse.UE4.Assets.Exports.Texture.UTexture2D>();
    foreach (var texture in exports.OfType<CUE4Parse.UE4.Assets.Exports.Texture.UTexture2D>())
        textures.TryAdd(texture.Name, texture);
    var written = new HashSet<string>();
    var list = new JArray();
    foreach (var component in components)
    {
        var json = JObject.Parse(JsonConvert.SerializeObject(component));
        var properties = json["Properties"] as JObject;
        if (properties == null) continue;
        var weightmaps = (properties["WeightmapTextures"] as JArray ?? new JArray()).Select(ObjectLeaf).ToList();
        foreach (var name in weightmaps)
        {
            if (!written.Add(name)) continue;
            var data = textures.TryGetValue(name, out var texture) ? texture.GetFirstMip()?.BulkData?.Data : null;
            if (data == null) { Console.Error.WriteLine($"{level}: no pixel data in {name}"); continue; }
            File.WriteAllBytes(Path.Combine(outDir, "wm", name + ".bin"), data);
        }
        var layers = new JArray();
        foreach (var allocation in properties["WeightmapLayerAllocations"] as JArray ?? new JArray())
            layers.Add(new JObject
            {
                ["layer"] = ObjectLeaf(allocation["LayerInfo"]),
                ["texture"] = (int?)allocation["WeightmapTextureIndex"] ?? 0,
                ["channel"] = (int?)allocation["WeightmapTextureChannel"] ?? 0,
            });
        var bias = properties["WeightmapScaleBias"];
        var root = component.GetOrDefault<FPackageIndex>("AttachParent");
        var rootObject = root == null || root.IsNull ? null : root.Load();
        var location = rootObject?.GetOrDefault("RelativeLocation", new FVector(0, 0, 0)) ?? new FVector(0, 0, 0);
        var scale = rootObject?.GetOrDefault("RelativeScale3D", new FVector(1, 1, 1)) ?? new FVector(1, 1, 1);
        list.Add(new JObject
        {
            ["name"] = component.Name,
            ["location"] = new JArray(location.X, location.Y, location.Z),
            ["scale"] = new JArray(scale.X, scale.Y, scale.Z),
            ["yaw"] = rootObject?.GetOrDefault("RelativeRotation", new FRotator(0, 0, 0)).Yaw ?? 0,
            ["relative"] = new JArray(component.GetOrDefault("RelativeLocation", new FVector(0, 0, 0)).X, component.GetOrDefault("RelativeLocation", new FVector(0, 0, 0)).Y),
            ["actor"] = ObjectLeaf(json["Outer"]),
            ["sectionBaseX"] = (int?)properties["SectionBaseX"] ?? 0,
            ["sectionBaseY"] = (int?)properties["SectionBaseY"] ?? 0,
            ["componentSizeQuads"] = (int?)properties["ComponentSizeQuads"] ?? 0,
            ["subsectionSizeQuads"] = (int?)properties["SubsectionSizeQuads"] ?? 0,
            ["numSubsections"] = (int?)properties["NumSubsections"] ?? 1,
            ["weightmapScaleBias"] = bias == null ? null : new JArray((double)bias["X"]!, (double)bias["Y"]!, (double)bias["Z"]!, (double)bias["W"]!),
            ["weightmapSubsectionOffset"] = (double?)properties["WeightmapSubsectionOffset"] ?? 0,
            ["weightmapTextures"] = new JArray(weightmaps),
            ["layers"] = layers,
        });
    }
    File.WriteAllText(Path.Combine(outDir, "components.json"), list.ToString(Formatting.Indented));
    return list.Count;
}
