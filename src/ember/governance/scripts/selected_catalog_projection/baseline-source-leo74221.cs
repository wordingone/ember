using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace NikoSelectedProjection
{
    public static class Runner
    {
        public sealed class ExceptionLevel {
            public string type { get; set; }
            public string message { get; set; }
            public int hresult { get; set; }
            public string stack_trace { get; set; }
        }
        public sealed class FailureDiagnostics {
            public string error_type { get; set; }
            public string reason_code { get; set; }
            public string stack_trace { get; set; }
            public long a_input_bytes_read { get; set; }
            public ExceptionLevel[] exception_chain { get; set; }
        }
        public sealed class Binding {
            public string prediction_path, prediction_sha256, export_path, output_root, marker_path, tenant_declaration_path, tenant_declaration_key, tenant_command_sha_key, command_path, source_path, source_sha256, runner_path, runner_sha256;
            public long prediction_bytes, owner_reported_export_bytes, max_export_bytes, max_total_bytes_read, max_wall_seconds, max_private_bytes, max_output_bytes, min_C_free_bytes, max_tenant_declaration_bytes;
            public int max_metadata_passes;
            public Binding() {}
        }
        sealed class Prediction { public string ExportPath, ExportSha, Tokenizer; public List<string> Ids = new List<string>(); }
        sealed class Row {
            public readonly Dictionary<string,string> V = new Dictionary<string,string>(StringComparer.Ordinal); public readonly HashSet<string> SeenKeys = new HashSet<string>(StringComparer.Ordinal);
            public readonly Dictionary<string,long> CandidateTypes = new Dictionary<string,long>(StringComparer.Ordinal);
            public string KindType="missing";
            public string Kind { get { string x; return V.TryGetValue("kind",out x) ? x : ""; } }
            public string KindCountKey { get { string x; if(KindType=="missing")return "missing"; if(KindType=="string"&&V.TryGetValue("kind",out x))return "string:"+x; return "non_string:"+KindType; } }
        }
        sealed class Member { public string Id,Sha,Split,Admission,Tokenizer,Start,End; }
        sealed class ScanState {
            public long BytesRead,Rows,RecordRows,EdgeRows;
            public readonly Dictionary<string,long> RecordKindCounts=new Dictionary<string,long>(StringComparer.Ordinal);
            public readonly Dictionary<string,long> EdgeKindCounts=new Dictionary<string,long>(StringComparer.Ordinal);
            public readonly HashSet<string> RootKeys=new HashSet<string>(StringComparer.Ordinal); public readonly List<string> RootOrder=new List<string>(); public readonly List<string> RootArrayOrder=new List<string>(); public readonly List<string> TopLevelArrayOrder=new List<string>();
            public bool RecordsArray,EdgesArray,RecordsSeen,EdgesSeen;
            public string Mode="",PendingRoot="";
        }
        sealed class MarkerObservation { public string checkpoint,declaration_sha256; public bool marker_present,declared_tenant; }
        static readonly UTF8Encoding Utf8=new UTF8Encoding(false,true);
        static readonly long MiB=1024L*1024L;
        static readonly long MaxBuffer=512L*MiB;
        public static long LastAInputBytesRead=0;
        static long PeakPrivate,PrivateSampleCount;
        static int PrivateRowsSinceSample;
        const int PrivateSampleEveryRows=64;
        static string ActiveBindingSha="",ActiveCommandSha="";
        static readonly List<MarkerObservation> MarkerObservations=new List<MarkerObservation>();
        static string LastTenantDeclarationSha="";
        [StructLayout(LayoutKind.Sequential)]
        struct ProcessMemoryCountersEx {
            public uint cb;
            public uint PageFaultCount;
            public UIntPtr PeakWorkingSetSize,WorkingSetSize,QuotaPeakPagedPoolUsage,QuotaPagedPoolUsage;
            public UIntPtr QuotaPeakNonPagedPoolUsage,QuotaNonPagedPoolUsage,PagefileUsage,PeakPagefileUsage,PrivateUsage;
        }
        [DllImport("kernel32.dll",ExactSpelling=true)]
        static extern IntPtr GetCurrentProcess();
        [DllImport("psapi.dll",SetLastError=true)]
        static extern bool GetProcessMemoryInfo(IntPtr processHandle,out ProcessMemoryCountersEx counters,uint size);
        public sealed class ObserverFailedException : Exception {
            public ObserverFailedException(Exception inner) : base("OBSERVER_FAILED("+(inner==null?"unknown":inner.GetType().FullName)+")",inner) {}
        }
        public static FailureDiagnostics CaptureFailure(Exception error,long bytesRead) {
            var chain=new List<ExceptionLevel>();
            for(Exception e=error;e!=null;e=e.InnerException) {
                chain.Add(new ExceptionLevel{type=e.GetType().FullName,message=e.Message,hresult=e.HResult,stack_trace=e.StackTrace??""});
            }
            if(chain.Count==0) throw new InvalidOperationException("EXCEPTION_CHAIN_EMPTY");
            string reason=chain[chain.Count-1].type;
            for(Exception cursor=error;cursor!=null;cursor=cursor.InnerException) {
                var observerFailure=cursor as ObserverFailedException;
                if(observerFailure!=null) {
                    reason="OBSERVER_FAILED("+(observerFailure.InnerException==null?"unknown":observerFailure.InnerException.GetType().FullName)+")";
                    break;
                }
            }
            return new FailureDiagnostics{error_type=error.GetType().FullName,reason_code=reason,stack_trace=error.ToString(),a_input_bytes_read=bytesRead,exception_chain=chain.ToArray()};
        }
        static readonly HashSet<string> Capture=new HashSet<string>(new[]{"kind","id","state","sha256","exact_sha256","split","admission_state","tokenizer_sha256","window_start","window_end","from_id","to_id"},StringComparer.Ordinal);

        static string Hash(byte[] x) { using(var h=SHA256.Create()) return BitConverter.ToString(h.ComputeHash(x)).Replace("-","").ToLowerInvariant(); }
        static string Norm(string x) { return (x??"").Replace('/','\\').TrimEnd('\\'); }
        static bool IsSha(string x) { return x!=null&&x.Length==64&&x.All(Uri.IsHexDigit); }
        static void Add(Dictionary<string,long> d,string k,long n=1) { long x; d.TryGetValue(k,out x); d[k]=x+n; }
        static string UniqueField(string[] lines,string key) { string found=null; string prefix=key+":"; foreach(string raw in lines){string line=raw.Trim();if(line.StartsWith(prefix,StringComparison.Ordinal)){if(found!=null)throw new InvalidOperationException("GPU_TENANT_DECLARATION_DUPLICATE:"+key);found=line.Substring(prefix.Length).Trim();}}if(found==null)throw new InvalidOperationException("GPU_TENANT_DECLARATION_MISSING:"+key);return found; }
        static bool ObserveMarker(Binding b,string where) {
            bool present=File.Exists(b.marker_path); var o=new MarkerObservation{checkpoint=where,marker_present=present,declared_tenant=false,declaration_sha256=""};
            if(present) {
                var f=new FileInfo(b.tenant_declaration_path); if(!f.Exists||f.Length<1||f.Length>b.max_tenant_declaration_bytes)throw new InvalidOperationException("GPU_TENANT_DECLARATION_SIZE");
                byte[] raw=File.ReadAllBytes(b.tenant_declaration_path); string sha=Hash(raw); o.declaration_sha256=sha; LastTenantDeclarationSha=sha;
                string text=Utf8.GetString(raw); string[] lines=text.Split(new[]{"\r\n","\n"},StringSplitOptions.None);
                MarkerObservations.Add(o);
                string tenant=UniqueField(lines,b.tenant_declaration_key), command=UniqueField(lines,b.tenant_command_sha_key);
                string runnerToken="runner "+Path.GetFileName(b.runner_path)+" sha256 "+b.runner_sha256;
                string bindingToken="binding "+ActiveBindingSha;
                if(tenant.IndexOf(runnerToken,StringComparison.OrdinalIgnoreCase)<0||tenant.IndexOf(bindingToken,StringComparison.OrdinalIgnoreCase)<0)throw new InvalidOperationException("GPU_TENANT_PINS_MISMATCH");
                if(!IsSha(command)||!String.Equals(command,ActiveCommandSha,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("GPU_TENANT_COMMAND_SHA_MISMATCH");
                o.declared_tenant=true;
            }
            if(!present)MarkerObservations.Add(o); return present;
        }
        static bool MarkerPresentAt(string where) { return MarkerObservations.Any(x=>x.checkpoint==where&&x.marker_present); }
        static bool TenantDeclaredAt(string where) { return MarkerObservations.Any(x=>x.checkpoint==where&&x.marker_present&&x.declared_tenant); }
        static long ObservePrivateUsage() {
            try { return ObservePrivateUsage(GetCurrentProcess()); }
            catch(ObserverFailedException) { throw; }
            catch(Exception ex) { throw new ObserverFailedException(ex); }
        }
        static long ObservePrivateUsage(IntPtr processHandle) {
            try {
                var counters=new ProcessMemoryCountersEx();
                counters.cb=(uint)Marshal.SizeOf(typeof(ProcessMemoryCountersEx));
                if(!GetProcessMemoryInfo(processHandle,out counters,counters.cb)) throw new Win32Exception(Marshal.GetLastWin32Error());
                ulong raw=counters.PrivateUsage.ToUInt64();
                if(raw>(ulong)Int64.MaxValue) throw new OverflowException("PRIVATE_USAGE_OVERFLOW");
                long value=(long)raw;
                PrivateSampleCount++;
                if(value>PeakPrivate) PeakPrivate=value;
                return value;
            } catch(ObserverFailedException) { throw; }
              catch(Exception ex) { throw new ObserverFailedException(ex); }
        }
        static bool IsPrivateSampleBoundary(string where) {
            switch(where) {
                case "preflight": case "before_prediction": case "after_prediction_hash":
                case "before_export_pass": case "after_hash": case "after_root_order_check":
                case "after_pass1": case "after_pass2": case "before_output": case "before_receipt":
                    return true;
                default: return false;
            }
        }
        static void Check(Binding b,Stopwatch sw,long bytes,string where,bool markerCheckpoint=false) {
            if(sw.Elapsed.TotalSeconds>b.max_wall_seconds) throw new InvalidOperationException("CAP_WALL:"+where);
            if(bytes>b.max_total_bytes_read) throw new InvalidOperationException("CAP_TOTAL_READ:"+where);
            bool samplePrivate=false;
            if(where=="metadata_row") {
                PrivateRowsSinceSample++;
                if(PrivateRowsSinceSample>=PrivateSampleEveryRows) { PrivateRowsSinceSample=0; samplePrivate=true; }
            } else if(IsPrivateSampleBoundary(where)||where=="buffer_growth") {
                PrivateRowsSinceSample=0;
                samplePrivate=true;
            }
            if(samplePrivate) {
                long p=ObservePrivateUsage();
                if(p>b.max_private_bytes) throw new InvalidOperationException("CAP_PRIVATE:"+where);
            }
            if(markerCheckpoint)ObserveMarker(b,where);
        }
        static JsonElement RequirePredictionProperty(JsonElement owner,string property,string fullPath) {
            JsonElement value;
            if(owner.ValueKind!=JsonValueKind.Object||!owner.TryGetProperty(property,out value)) throw new KeyNotFoundException("PREDICTION_KEY_MISSING:"+fullPath);
            return value;
        }
        static string RequirePredictionString(JsonElement owner,string property,string fullPath) {
            JsonElement value=RequirePredictionProperty(owner,property,fullPath);
            if(value.ValueKind!=JsonValueKind.String) throw new InvalidOperationException("PREDICTION_KEY_TYPE:"+fullPath);
            return value.GetString();
        }
        static Prediction ReadPrediction(Binding b,Stopwatch sw,ref long total) {
            Check(b,sw,total,"before_prediction",true);
            var f=new FileInfo(b.prediction_path);
            if(!f.Exists||f.Length!=b.prediction_bytes) throw new InvalidOperationException("PREDICTION_SIZE");
            byte[] raw;
            using(var predictionCopy=new MemoryStream())
            using(var predictionStream=new FileStream(b.prediction_path,FileMode.Open,FileAccess.Read,FileShare.Read,4096,FileOptions.SequentialScan)) {
                byte[] chunk=new byte[4096]; int got;
                while((got=predictionStream.Read(chunk,0,chunk.Length))>0) {
                    total+=got; LastAInputBytesRead=total; predictionCopy.Write(chunk,0,got);
                }
                raw=predictionCopy.ToArray();
            }
            if(raw.LongLength!=b.prediction_bytes||Hash(raw)!=b.prediction_sha256.ToLowerInvariant()) throw new InvalidOperationException("PREDICTION_HASH");
            Check(b,sw,total,"after_prediction_hash",true);
            using(var d=JsonDocument.Parse(raw)) {
                var root=d.RootElement;
                var identity=RequirePredictionProperty(root,"identity","identity");
                var mixture=RequirePredictionProperty(identity,"production_mixture","identity.production_mixture");
                string exportPath=RequirePredictionString(mixture,"catalog_export_path","identity.production_mixture.catalog_export_path");
                string exportSha=RequirePredictionString(mixture,"catalog_export_sha256","identity.production_mixture.catalog_export_sha256");
                var inputBinding=RequirePredictionProperty(identity,"input_binding","identity.input_binding");
                string inputTokenizer=RequirePredictionString(inputBinding,"tokenizer_sha256","identity.input_binding.tokenizer_sha256");
                var data=RequirePredictionProperty(identity,"data","identity.data");
                string dataTokenizer=RequirePredictionString(data,"tokenizer_sha256","identity.data.tokenizer_sha256");
                if(!String.Equals(inputTokenizer,dataTokenizer,StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("PREDICTION_TOKENIZER_MISMATCH:identity.input_binding.tokenizer_sha256!=identity.data.tokenizer_sha256");
                var p=new Prediction { ExportPath=exportPath, ExportSha=exportSha, Tokenizer=inputTokenizer };
                var a=RequirePredictionProperty(mixture,"dataset_ids","identity.production_mixture.dataset_ids");
                if(a.ValueKind!=JsonValueKind.Array||a.GetArrayLength()!=8) throw new InvalidOperationException("DATASET_SELECTOR");
                foreach(var e in a.EnumerateArray()) {
                    if(e.ValueKind!=JsonValueKind.String) throw new InvalidOperationException("DATASET_SELECTOR");
                    string id=e.GetString();
                    if(String.IsNullOrWhiteSpace(id)||!id.StartsWith("dataset:issue1581-bulk-train:",StringComparison.Ordinal)) throw new InvalidOperationException("DATASET_SELECTOR");
                    p.Ids.Add(id);
                }
                if(p.Ids.Distinct(StringComparer.Ordinal).Count()!=8||!IsSha(p.ExportSha)||!IsSha(p.Tokenizer)) throw new InvalidOperationException("PREDICTION_BINDING");
                return p;
            }
        }
        static bool Candidate(string k) {
            string n=new string((k??"").Where(Char.IsLetterOrDigit).ToArray()).ToLowerInvariant();
            return n=="item"||n=="itemid"||n=="field"||n=="fieldname"||n=="ordinal"||n=="prepackingordinal"||n=="current208"||n=="current208membership";
        }
        static string TypeName(System.Text.Json.JsonTokenType t) {
            if(t==System.Text.Json.JsonTokenType.String)return "string";
            if(t==System.Text.Json.JsonTokenType.Number)return "number";
            if(t==System.Text.Json.JsonTokenType.True||t==System.Text.Json.JsonTokenType.False)return "boolean";
            if(t==System.Text.Json.JsonTokenType.Null)return "null";
            if(t==System.Text.Json.JsonTokenType.StartObject)return "object";
            if(t==System.Text.Json.JsonTokenType.StartArray)return "array";
            return "other";
        }
        static string ReadSmallString(ref Utf8JsonReader r,string key) {
            if(r.ValueSpan.Length>4096) throw new InvalidOperationException("CAP_METADATA_SCALAR:"+key);
            return r.GetString();
        }
        static void Grow(ref byte[] buf,int keep,Binding b,Stopwatch sw,long total) {
            long cur=ObservePrivateUsage();
            if(cur>b.max_private_bytes) throw new InvalidOperationException("CAP_PRIVATE:buffer_growth");
            long next=Math.Min(MaxBuffer,Math.Max((long)buf.Length*2,(long)keep+1));
            if(next<=buf.Length||cur+next+4*MiB>b.max_private_bytes) throw new InvalidOperationException("CAP_JSON_TOKEN_BUFFER");
            byte[] n=new byte[(int)next]; if(keep>0)Buffer.BlockCopy(buf,0,n,0,keep); buf=n; Check(b,sw,total,"buffer_growth");
        }
        // Hash pass extracts root keys only. Metadata passes capture the direct whitelist; other string values stay unmaterialized.
        static string Scan(FileStream fs,Binding b,Stopwatch sw,ref long total,bool hashPass,bool rootOrderGate,Action<Row> onRow,ScanState s) {
            Check(b,sw,total,"before_export_pass",true);
            if(fs.Length!=b.owner_reported_export_bytes||fs.Length>b.max_export_bytes)throw new InvalidOperationException("EXPORT_SIZE"); fs.Position=0;
            
            
            using(var sha=IncrementalHash.CreateHash(HashAlgorithmName.SHA256)) {
                byte[] buf=new byte[1024*1024]; int len=0; Row row=null; string pending=null;
                var js=new JsonReaderState(new JsonReaderOptions{AllowTrailingCommas=false,CommentHandling=JsonCommentHandling.Disallow,MaxDepth=64});
                while(true) {
                    Check(b,sw,total,"export_stream");
                    if(len==buf.Length)Grow(ref buf,len,b,sw,total);
                    int got=fs.Read(buf,len,buf.Length-len); bool final=got==0;
                    if(got>0){ total+=got;s.BytesRead+=got;LastAInputBytesRead=total;sha.AppendData(buf,len,got);len+=got;Check(b,sw,total,"export_read",true); }
                    var r=new Utf8JsonReader(new ReadOnlySpan<byte>(buf,0,len),final,js);
                    while(r.Read()) {
                        if(r.TokenType==System.Text.Json.JsonTokenType.PropertyName&&r.CurrentDepth==1) {
                            if(r.ValueSpan.Length>128)throw new InvalidOperationException("ROOT_KEY");
                            string k=r.GetString(); if(!s.RootKeys.Add(k))throw new InvalidOperationException("ROOT_KEY_DUPLICATE"); s.RootOrder.Add(k); s.PendingRoot=k;
                            if(k=="records"){if(s.RecordsSeen)throw new InvalidOperationException("ROOT_ARRAY_DUPLICATE");s.RecordsSeen=true;}
                            else if(k=="edges"){if(s.EdgesSeen)throw new InvalidOperationException("ROOT_ARRAY_DUPLICATE");s.EdgesSeen=true;}
                        }
                        if(r.TokenType==System.Text.Json.JsonTokenType.StartArray&&r.CurrentDepth==1) {
                            string arrayKey=s.PendingRoot;if(String.IsNullOrEmpty(arrayKey))throw new InvalidOperationException("ROOT_ARRAY_KEY_MISSING");s.TopLevelArrayOrder.Add(arrayKey);
                            if(arrayKey=="records"){s.RecordsArray=true;s.RootArrayOrder.Add(arrayKey);}if(arrayKey=="edges"){s.EdgesArray=true;s.RootArrayOrder.Add(arrayKey);}
                            s.Mode=(arrayKey=="records"||arrayKey=="edges")?arrayKey:"";s.PendingRoot="";
                        }
                        if(r.TokenType==System.Text.Json.JsonTokenType.EndArray&&r.CurrentDepth==1)s.Mode="";
                        if(!hashPass&&onRow!=null&&(s.Mode=="records"||s.Mode=="edges")&&r.TokenType==System.Text.Json.JsonTokenType.StartObject&&r.CurrentDepth==2) {
                            if(row!=null)throw new InvalidOperationException("ROW_NESTING");row=new Row();pending=null;
                        }
                        else if(!hashPass&&row!=null&&r.TokenType==System.Text.Json.JsonTokenType.PropertyName&&r.CurrentDepth==3)
                            if(r.ValueSpan.Length<=256){pending=r.GetString();if(!row.SeenKeys.Add(pending))throw new InvalidOperationException("DUPLICATE_ROW_PROPERTY");}else pending=null;
                        else if(!hashPass&&row!=null&&r.CurrentDepth==3&&r.TokenType!=System.Text.Json.JsonTokenType.PropertyName&&r.TokenType!=System.Text.Json.JsonTokenType.EndObject&&r.TokenType!=System.Text.Json.JsonTokenType.EndArray) {
                            string k=pending;pending=null;
                            if(!String.IsNullOrEmpty(k)) {
                                if(k=="kind")row.KindType=TypeName(r.TokenType);
                                if(Candidate(k))Add(row.CandidateTypes,k+"|"+TypeName(r.TokenType));
                                else if(Capture.Contains(k)) {
                                    string v=null;
                                    if(r.TokenType==System.Text.Json.JsonTokenType.String)v=ReadSmallString(ref r,k);
                                    else if(r.TokenType==System.Text.Json.JsonTokenType.Number){long n;if(r.TryGetInt64(out n))v=n.ToString(CultureInfo.InvariantCulture);}
                                    else if(r.TokenType==System.Text.Json.JsonTokenType.True)v="true";
                                    else if(r.TokenType==System.Text.Json.JsonTokenType.False)v="false";
                                    if(v!=null)row.V[k]=v;
                                }
                            }
                        }
                        else if(!hashPass&&row!=null&&(r.TokenType==System.Text.Json.JsonTokenType.StartObject||r.TokenType==System.Text.Json.JsonTokenType.StartArray)&&r.CurrentDepth==3) {
                            if(pending=="kind")row.KindType=TypeName(r.TokenType);
                            if(!String.IsNullOrEmpty(pending)&&Candidate(pending))Add(row.CandidateTypes,pending+"|"+TypeName(r.TokenType));pending=null;
                        }
                        else if(!hashPass&&row!=null&&r.TokenType==System.Text.Json.JsonTokenType.EndObject&&r.CurrentDepth==2) {
                            s.Rows++;if(s.Mode=="records"){s.RecordRows++;Add(s.RecordKindCounts,row.KindCountKey);}else{s.EdgeRows++;Add(s.EdgeKindCounts,row.KindCountKey);}onRow(row);row=null;pending=null;Check(b,sw,total,"metadata_row");
                        }
                    }
                    int used=checked((int)r.BytesConsumed);js=r.CurrentState;int rem=len-used;
                    if(rem>0)Buffer.BlockCopy(buf,used,buf,0,rem);len=rem;
                    if(final){if(len!=0)throw new InvalidOperationException("JSON_FINAL");break;}
                    if(got==0&&used==0)Grow(ref buf,len,b,sw,total);
                }
                if(row!=null)throw new InvalidOperationException("ROW_INCOMPLETE");
                if(!s.RootKeys.Contains("records")||!s.RootKeys.Contains("edges")||!s.RecordsArray||!s.EdgesArray)throw new InvalidOperationException("ROOT_ARRAYS");
                if(rootOrderGate&&(!s.RecordsSeen||!s.EdgesSeen))throw new InvalidOperationException("ROOT_ORDER");
                return BitConverter.ToString(sha.GetHashAndReset()).Replace("-","").ToLowerInvariant();
            }
        }
        static string Need(Dictionary<string,string> v,string k,string code){string x;if(!v.TryGetValue(k,out x)||String.IsNullOrWhiteSpace(x))throw new InvalidOperationException(code);return x;}
        static long GetCount(Dictionary<string,long> d,string k){long n;return d.TryGetValue(k,out n)?n:0;}
        static bool SameCounts(Dictionary<string,long> a,Dictionary<string,long> b){if(a.Count!=b.Count)return false;foreach(var x in a){long n;if(!b.TryGetValue(x.Key,out n)||n!=x.Value)return false;}return true;}
        static void VerifyPassCounts(ScanState a,ScanState b){if(a.RecordRows!=b.RecordRows||a.EdgeRows!=b.EdgeRows||!SameCounts(a.RecordKindCounts,b.RecordKindCounts)||!SameCounts(a.EdgeKindCounts,b.EdgeKindCounts))throw new InvalidOperationException("PASS_KIND_COUNTS_MISMATCH");}
        static object[] BuildKindCounts(string unit,Dictionary<string,long> logical,Dictionary<string,long> p1,Dictionary<string,long> p2,Dictionary<string,long> selected){return logical.Keys.Union(selected.Keys).OrderBy(x=>x,StringComparer.Ordinal).Select(k=>{long total=GetCount(logical,k),sel=GetCount(selected,k);if(sel>total)throw new InvalidOperationException("COUNT_SELECTED_EXCEEDS_TOTAL");long excluded=total-sel;return (object)new{kind=k,unit=unit,logical_rows=total,pass1_observations=GetCount(p1,k),pass2_observations=GetCount(p2,k),selected_rows=sel,excluded_rows=excluded,nonselected_rows=excluded};}).ToArray();}
        static string ValidateTwoPassOrder(ScanState s){if(s.TopLevelArrayOrder.Count!=2||s.TopLevelArrayOrder.Count(x=>x=="records")!=1||s.TopLevelArrayOrder.Count(x=>x=="edges")!=1)throw new InvalidOperationException("ROOT_ARRAY_UNKNOWN");if(!s.RecordsArray||!s.EdgesArray||!s.RecordsSeen||!s.EdgesSeen||s.RootArrayOrder.Count!=2)throw new InvalidOperationException("ROOT_ORDER_UNSUPPORTED");string a=s.RootArrayOrder[0],z=s.RootArrayOrder[1];if(a=="records"&&z=="edges")return "records_before_edges";if(a=="edges"&&z=="records")return "edges_before_records";throw new InvalidOperationException("ROOT_ORDER_UNSUPPORTED");}
        static string EdgeHash(string v,string prefix){if(v==null||!v.StartsWith(prefix+":",StringComparison.Ordinal))return null;string h=v.Substring(prefix.Length+1);return IsSha(h)?h.ToLowerInvariant():null;}

        public static void Run(string bindingPath,string expectedBindingSha,string commandPath,string expectedCommandSha) {
            LastAInputBytesRead=0;PeakPrivate=0;PrivateSampleCount=0;PrivateRowsSinceSample=0;MarkerObservations.Clear();LastTenantDeclarationSha="";byte[] bindingRaw=File.ReadAllBytes(bindingPath);if(Hash(bindingRaw)!=expectedBindingSha.ToLowerInvariant())throw new InvalidOperationException("BINDING_HASH");
            Binding b;using(var d=JsonDocument.Parse(bindingRaw))b=JsonSerializer.Deserialize<Binding>(d.RootElement.GetRawText(),new JsonSerializerOptions{IncludeFields=true});
            if(b==null||b.max_metadata_passes!=2)throw new InvalidOperationException("BINDING_SCHEMA");
            if(!IsSha(expectedCommandSha)||Norm(b.command_path)!=Norm(commandPath)||Hash(File.ReadAllBytes(b.command_path))!=expectedCommandSha.ToLowerInvariant())throw new InvalidOperationException("COMMAND_HASH");
            if(Hash(File.ReadAllBytes(b.source_path))!=b.source_sha256.ToLowerInvariant()||Hash(File.ReadAllBytes(b.runner_path))!=b.runner_sha256.ToLowerInvariant())throw new InvalidOperationException("SOURCE_RUNNER_HASH");
            if(Norm(b.output_root)!=Norm(Path.GetDirectoryName(bindingPath)))throw new InvalidOperationException("OUTPUT_ROOT");
            ActiveBindingSha=expectedBindingSha.ToLowerInvariant();ActiveCommandSha=expectedCommandSha.ToLowerInvariant();
            var sw=Stopwatch.StartNew();var proc=Process.GetCurrentProcess();if(proc.PriorityClass!=ProcessPriorityClass.BelowNormal)throw new InvalidOperationException("LAUNCH_PRIORITY");
            if(ObservePrivateUsage()>b.max_private_bytes)throw new InvalidOperationException("CAP_PRIVATE:launch");long total=0;
            string runDir=Path.Combine(b.output_root,"run");if(Directory.Exists(runDir))throw new InvalidOperationException("OUTPUT_EXISTS");
            if(new DriveInfo(Path.GetPathRoot(b.output_root)).AvailableFreeSpace<b.min_C_free_bytes)throw new InvalidOperationException("C_SPACE");
            Check(b,sw,total,"preflight",true);Prediction p=ReadPrediction(b,sw,ref total);
            if(Norm(p.ExportPath)!=Norm(b.export_path)||!IsSha(p.ExportSha)||!IsSha(p.Tokenizer))throw new InvalidOperationException("PREDICTION_BINDING");
            if(b.owner_reported_export_bytes>b.max_export_bytes)throw new InvalidOperationException("EXPORT_CAP");
            var exportFile=new FileStream(b.export_path,FileMode.Open,FileAccess.Read,FileShare.Read,1024*1024,FileOptions.SequentialScan); var hs=new ScanState();string exportSha=Scan(exportFile,b,sw,ref total,true,false,null,hs);
            if(!String.Equals(exportSha,p.ExportSha,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("EXPORT_HASH");
            Check(b,sw,total,"after_hash",true);string orderPlan=ValidateTwoPassOrder(hs);Check(b,sw,total,"after_root_order_check",true);

            var datasets=new Dictionary<string,string>(StringComparer.Ordinal);var members=new Dictionary<string,Member>(StringComparer.Ordinal);
            var byDataset=new Dictionary<string,List<string>>(StringComparer.Ordinal);foreach(string id in p.Ids)byDataset[id]=new List<string>();
            var heldout=new HashSet<string>(StringComparer.Ordinal);var quarantine=new HashSet<string>(StringComparer.Ordinal);var adjudicated=new HashSet<string>(StringComparer.Ordinal);var protectedEval=new HashSet<string>(StringComparer.Ordinal);
            var candidateTypes=new Dictionary<string,long>(StringComparer.Ordinal);var seenVersionEdges=new HashSet<string>(StringComparer.Ordinal);long duplicateVersionEdges=0,selectedVersionMembershipEdges=0;var p1=new ScanState();
            string pass1Sha=Scan(exportFile,b,sw,ref total,false,false,row=>{
                foreach(var x in row.CandidateTypes)Add(candidateTypes,row.Kind+"|"+x.Key,x.Value);
                if(row.Kind=="dataset_version"){string id;if(row.V.TryGetValue("id",out id)&&byDataset.ContainsKey(id)){if(datasets.ContainsKey(id))throw new InvalidOperationException("DATASET_DUPLICATE");datasets[id]=row.V.ContainsKey("state")?row.V["state"]:"";}}
                else if(row.Kind=="membership"){
                    string id=Need(row.V,"id","MEMBERSHIP_ID"),sha=Need(row.V,"exact_sha256","MEMBERSHIP_SHA").ToLowerInvariant();if(!IsSha(sha))throw new InvalidOperationException("MEMBERSHIP_SHA");
                    string split=row.V.ContainsKey("split")?row.V["split"]:"",adm=row.V.ContainsKey("admission_state")?row.V["admission_state"]:"";
                    if(members.ContainsKey(id))throw new InvalidOperationException("MEMBERSHIP_DUPLICATE");
                    members[id]=new Member{Id=id,Sha=sha,Split=split,Admission=adm,Tokenizer=row.V.ContainsKey("tokenizer_sha256")?row.V["tokenizer_sha256"]:"",Start=row.V.ContainsKey("window_start")?row.V["window_start"]:"",End=row.V.ContainsKey("window_end")?row.V["window_end"]:""};
                    if(split!="train"&&adm=="admitted")heldout.Add(sha);if(split=="train"&&adm!="admitted")quarantine.Add(sha);if(split!="train"&&adm!="admitted")adjudicated.Add(sha);
                }
                else if(row.Kind=="version_membership"){string f,t;if(row.V.TryGetValue("from_id",out f)&&row.V.TryGetValue("to_id",out t)&&byDataset.ContainsKey(f)){selectedVersionMembershipEdges++;if(!seenVersionEdges.Add(f+"|"+t))duplicateVersionEdges++;byDataset[f].Add(t);}}
                else if(row.Kind=="evaluation_object"){string t;if(row.V.TryGetValue("to_id",out t)){string h=EdgeHash(t,"object");if(h!=null)protectedEval.Add(h);}}
            },p1);if(!String.Equals(pass1Sha,p.ExportSha,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("EXPORT_CHANGED_PASS1");Check(b,sw,total,"after_pass1",true);

            var selected=new List<object>();var selectedMemberIds=new HashSet<string>(StringComparer.Ordinal);var selectedSha=new HashSet<string>(StringComparer.Ordinal);
            var shaDatasets=new Dictionary<string,HashSet<string>>(StringComparer.Ordinal);var perDataset=new Dictionary<string,long>(StringComparer.Ordinal);
            long stateMismatch=0,tokenizerMismatch=0,windowInvalid=0,repeatSha=0;
            foreach(string dsid in p.Ids.OrderBy(x=>x,StringComparer.Ordinal)){
                string state;if(!datasets.TryGetValue(dsid,out state))throw new InvalidOperationException("DATASET_MISSING");if(state!="admitted")stateMismatch++;
                var ids=byDataset[dsid].OrderBy(x=>x,StringComparer.Ordinal).ToList();if(ids.Count==0)throw new InvalidOperationException("MEMBERSHIP_EMPTY");perDataset[dsid]=ids.Count;
                foreach(string id in ids){Member m;if(!members.TryGetValue(id,out m))throw new InvalidOperationException("MEMBERSHIP_MISSING");selectedMemberIds.Add(id);
                    if(m.Split!="train"||m.Admission!="admitted")stateMismatch++;if(!String.Equals(m.Tokenizer,p.Tokenizer,StringComparison.OrdinalIgnoreCase))tokenizerMismatch++;
                    long a,z;if(!Int64.TryParse(m.Start,NumberStyles.Integer,CultureInfo.InvariantCulture,out a)||!Int64.TryParse(m.End,NumberStyles.Integer,CultureInfo.InvariantCulture,out z)||a<0||z<=a)windowInvalid++;
                    if(!selectedSha.Add(m.Sha))repeatSha++;HashSet<string> ds; if(!shaDatasets.TryGetValue(m.Sha,out ds)){ds=new HashSet<string>(StringComparer.Ordinal);shaDatasets[m.Sha]=ds;}ds.Add(dsid);
                    selected.Add(new{dataset_id=dsid,membership_id=id,exact_sha256=m.Sha,split=m.Split,admission_state=m.Admission,tokenizer_sha256=m.Tokenizer,window_start=m.Start,window_end=m.End});
                }
            }
            long heldoutHit=selectedSha.Count(x=>heldout.Contains(x)),quarantineHit=selectedSha.Count(x=>quarantine.Contains(x)),protectedHit=selectedSha.Count(x=>protectedEval.Contains(x)),adjudicatedHit=selectedSha.Count(x=>adjudicated.Contains(x));

            var objects=new Dictionary<string,List<string>>(StringComparer.Ordinal);var receiptLinks=new Dictionary<string,List<string>>(StringComparer.Ordinal);long selectedObjectReceiptEdges=0;var receiptShas=new HashSet<string>(StringComparer.Ordinal);var receiptRowsBySha=new Dictionary<string,long>(StringComparer.Ordinal);var p2=new ScanState();
            string pass2Sha=Scan(exportFile,b,sw,ref total,false,false,row=>{
                if(row.Kind=="immutable_object"){string h;if(row.V.TryGetValue("sha256",out h)&&selectedSha.Contains(h.ToLowerInvariant())){List<string> ids;if(!objects.TryGetValue(h.ToLowerInvariant(),out ids)){ids=new List<string>();objects[h.ToLowerInvariant()]=ids;}ids.Add(row.V.ContainsKey("id")?row.V["id"]:"");}}
                else if(row.Kind=="object_receipt"){string f,t;if(row.V.TryGetValue("from_id",out f)&&row.V.TryGetValue("to_id",out t)){string h=EdgeHash(f,"object"),r=EdgeHash(t,"receipt");if(h!=null&&r!=null&&selectedSha.Contains(h)){List<string>s;if(!receiptLinks.TryGetValue(h,out s)){s=new List<string>();receiptLinks[h]=s;}s.Add(r);selectedObjectReceiptEdges++;}}}
                else if(row.Kind=="receipt"){string h;if(row.V.TryGetValue("sha256",out h)&&IsSha(h)){h=h.ToLowerInvariant();receiptShas.Add(h);Add(receiptRowsBySha,h);}}
            },p2);if(!String.Equals(pass2Sha,p.ExportSha,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("EXPORT_CHANGED_PASS2");Check(b,sw,total,"after_pass2",true);VerifyPassCounts(p1,p2);
            long missingObject=selectedSha.LongCount(x=>!objects.ContainsKey(x)),duplicateObject=objects.Values.LongCount(x=>x.Count!=1);if(missingObject!=0||duplicateObject!=0)throw new InvalidOperationException("OBJECT_TOTALITY");
            long unresolvedReceipt=receiptLinks.Sum(x=>x.Value.LongCount(y=>!receiptShas.Contains(y)));
            var objectRows=new List<object>();foreach(string h in selectedSha.OrderBy(x=>x,StringComparer.Ordinal)){var rs=receiptLinks.ContainsKey(h)?receiptLinks[h].OrderBy(x=>x,StringComparer.Ordinal).ToArray():new string[0];objectRows.Add(new{sha256=h,catalog_object_ids=objects[h].OrderBy(x=>x,StringComparer.Ordinal).ToArray(),selected_dataset_ids=shaDatasets[h].OrderBy(x=>x,StringComparer.Ordinal).ToArray(),receipt_sha256s=rs});}
            var selectedRecordKinds=new Dictionary<string,long>(StringComparer.Ordinal);Add(selectedRecordKinds,"string:dataset_version",p.Ids.Count);Add(selectedRecordKinds,"string:membership",selectedMemberIds.Count);Add(selectedRecordKinds,"string:immutable_object",objects.Values.Sum(x=>(long)x.Count));
            var referencedReceiptHashes=new HashSet<string>(receiptLinks.Values.SelectMany(x=>x),StringComparer.Ordinal);long selectedReceiptRows=receiptRowsBySha.Where(x=>referencedReceiptHashes.Contains(x.Key)).Sum(x=>x.Value);Add(selectedRecordKinds,"string:receipt",selectedReceiptRows);
            var selectedEdgeKinds=new Dictionary<string,long>(StringComparer.Ordinal);Add(selectedEdgeKinds,"string:version_membership",selectedVersionMembershipEdges);Add(selectedEdgeKinds,"string:object_receipt",selectedObjectReceiptEdges);
            long selectedRecordRows=selectedRecordKinds.Values.Sum(),selectedEdgeRows=selectedEdgeKinds.Values.Sum();long excludedRecordRows=p1.RecordRows-selectedRecordRows,excludedEdgeRows=p1.EdgeRows-selectedEdgeRows;
            if(excludedRecordRows<0||excludedEdgeRows<0)throw new InvalidOperationException("COUNT_SELECTED_EXCEEDS_TOTAL");
            object[] recordKindCounts=BuildKindCounts("record",p1.RecordKindCounts,p1.RecordKindCounts,p2.RecordKindCounts,selectedRecordKinds),edgeKindCounts=BuildKindCounts("edge",p1.EdgeKindCounts,p1.EdgeKindCounts,p2.EdgeKindCounts,selectedEdgeKinds);
            var logicalCounts=new{records=new{unit="record",logical_rows=p1.RecordRows,pass1_observations=p1.RecordRows,pass2_observations=p2.RecordRows,selected_rows=selectedRecordRows,excluded_rows=excludedRecordRows,nonselected_rows=excludedRecordRows},edges=new{unit="edge",logical_rows=p1.EdgeRows,pass1_observations=p1.EdgeRows,pass2_observations=p2.EdgeRows,selected_rows=selectedEdgeRows,excluded_rows=excludedEdgeRows,nonselected_rows=excludedEdgeRows}};
            long globalContextEdges=GetCount(p1.EdgeKindCounts,"string:evaluation_object");
            var summary=new{schema="niko.selected_catalog_projection.summary.v1",status="COMPLETE_SELECTED_CATALOG_PROJECTION",scope="eight frozen dataset IDs only; not a global admitted total or current_208 selector",dataset_ids=p.Ids.OrderBy(x=>x,StringComparer.Ordinal).ToArray(),selected_dataset_version_states=p.Ids.OrderBy(x=>x,StringComparer.Ordinal).Select(x=>new{dataset_id=x,state=datasets[x]}).ToArray(),selected_membership_edge_rows=selected.Count,selected_membership_row_occurrences=selected.Count,unique_selected_membership_ids=selectedMemberIds.Count,duplicate_selected_membership_occurrences=selected.Count-selectedMemberIds.Count,unique_selected_sha256s=selectedSha.Count,unique_selected_object_digests=selectedSha.Count,selected_source_record_rows=selectedRecordRows,excluded_source_record_rows=excludedRecordRows,nonselected_source_record_rows=excludedRecordRows,selected_source_edge_rows=selectedEdgeRows,excluded_source_edge_rows=excludedEdgeRows,nonselected_source_edge_rows=excludedEdgeRows,global_analysis_context_edge_rows=globalContextEdges,logical_export_row_counts=logicalCounts,per_kind_export_row_counts=new{records=recordKindCounts,edges=edgeKindCounts},count_class_semantics="selected rows match the frozen selector or selected digest joins; excluded and nonselected are the same unmatched subset and overlap exactly, so do not add all three. Logical source rows count once; pass1_observations and pass2_observations are visits. evaluation_object edges remain global leakage context even though they are nonselected from the selected projection.",repeated_digest_membership_edges=repeatSha,per_dataset_membership_edges=perDataset,dataset_or_membership_state_mismatch_rows=stateMismatch,tokenizer_mismatch_rows=tokenizerMismatch,invalid_or_missing_declared_window_rows=windowInvalid,missing_selected_objects=missingObject,duplicate_object_rows=duplicateObject,duplicate_selected_version_membership_edges=duplicateVersionEdges,selected_object_receipt_edge_rows=selectedObjectReceiptEdges,unresolved_receipt_edges=unresolvedReceipt,selected_sha_intersections=new{admitted_non_train=heldoutHit,quarantined_train=quarantineHit,protected_evaluation=protectedHit,adjudicated_non_train=adjudicatedHit},export_top_level_key_order=hs.RootOrder.ToArray(),export_root_array_order=hs.RootArrayOrder.ToArray(),metadata_order_plan=orderPlan,candidate_key_type_counts=candidateTypes,candidate_boundary="direct property names/types only; values unread",content_boundary="paths/captions/payloads/source text/token arrays/image bytes not materialized",current_208="UNKNOWN"};
            byte[] mb=Utf8.GetBytes(String.Join("\n",selected.Select(x=>JsonSerializer.Serialize(x)))+"\n"),ob=Utf8.GetBytes(String.Join("\n",objectRows.Select(x=>JsonSerializer.Serialize(x)))+"\n"),sb=JsonSerializer.SerializeToUtf8Bytes(summary,new JsonSerializerOptions{WriteIndented=true});
            var files=new Dictionary<string,byte[]>{{"selected-memberships.jsonl",mb},{"selected-objects.jsonl",ob},{"summary.json",sb}};
            long outBytes=files.Values.Sum(x=>(long)x.Length);foreach(string f in Directory.GetFiles(b.output_root,"*",SearchOption.AllDirectories))outBytes+=new FileInfo(f).Length;
            if(outBytes>b.max_output_bytes)throw new InvalidOperationException("CAP_OUTPUT");Check(b,sw,total,"before_output",true);
            Check(b,sw,total,"before_receipt",true);var receipt=new{schema="niko.selected_catalog_projection.run_receipt.v1",status="COMPLETE_SELECTED_CATALOG_PROJECTION",prediction_sha256=b.prediction_sha256,prediction_bytes=b.prediction_bytes,export_sha256=exportSha,export_bytes=b.owner_reported_export_bytes,export_top_level_key_order=hs.RootOrder.ToArray(),export_root_array_order=hs.RootArrayOrder.ToArray(),metadata_order_plan=orderPlan,metadata_passes=2,total_input_bytes_read=total,max_total_bytes_read=b.max_total_bytes_read,private_bytes_peak_observed=PeakPrivate,private_usage_observer="GetProcessMemoryInfo.PrivateUsage",private_usage_poll_rows=PrivateSampleEveryRows,private_usage_sample_count=PrivateSampleCount,max_private_bytes=b.max_private_bytes,runner_elapsed_seconds=sw.Elapsed.TotalSeconds,outer_wall_ceiling_seconds=b.max_wall_seconds,output_bytes_before_receipt=outBytes,max_output_bytes=b.max_output_bytes,marker_absent_at_start=!MarkerPresentAt("preflight"),marker_absent_after_hash=!MarkerPresentAt("after_hash"),marker_absent_after_pass1=!MarkerPresentAt("after_pass1"),marker_absent_after_pass2=!MarkerPresentAt("after_pass2"),marker_declared_at_start=TenantDeclaredAt("preflight"),marker_declared_after_hash=TenantDeclaredAt("after_hash"),marker_declared_after_pass1=TenantDeclaredAt("after_pass1"),marker_declared_after_pass2=TenantDeclaredAt("after_pass2"),marker_present_checkpoints=MarkerObservations.Where(x=>x.marker_present).Select(x=>x.checkpoint).ToArray(),tenant_declared_checkpoints=MarkerObservations.Where(x=>x.declared_tenant).Select(x=>x.checkpoint).ToArray(),tenant_declaration_path=b.tenant_declaration_path,tenant_declaration_sha256_last_observed=LastTenantDeclarationSha,command_sha256=ActiveCommandSha,logical_export_row_counts=logicalCounts,per_kind_export_row_counts=new{records=recordKindCounts,edges=edgeKindCounts},selected_membership_row_occurrences=selected.Count,unique_selected_membership_ids=selectedMemberIds.Count,duplicate_selected_membership_occurrences=selected.Count-selectedMemberIds.Count,unique_selected_object_digests=selectedSha.Count,selected_source_record_rows=selectedRecordRows,excluded_source_record_rows=excludedRecordRows,nonselected_source_record_rows=excludedRecordRows,selected_source_edge_rows=selectedEdgeRows,excluded_source_edge_rows=excludedEdgeRows,nonselected_source_edge_rows=excludedEdgeRows,count_class_semantics="excluded and nonselected overlap exactly; do not add all three. Logical rows count once; pass observations are separate. Global evaluation_object edges remain analysis context.",priority=Process.GetCurrentProcess().PriorityClass.ToString(),compute_parallelism=1,source_sha256=b.source_sha256,binding_sha256=expectedBindingSha,runner_sha256=b.runner_sha256,global_admitted_total="UNKNOWN",current_208="UNKNOWN"};
            byte[] rb=JsonSerializer.SerializeToUtf8Bytes(receipt,new JsonSerializerOptions{WriteIndented=true});if(outBytes+rb.LongLength>b.max_output_bytes)throw new InvalidOperationException("CAP_OUTPUT_RECEIPT");
            Directory.CreateDirectory(runDir);foreach(var x in files){Check(b,sw,total,"output_write",true);File.WriteAllBytes(Path.Combine(runDir,x.Key),x.Value);}Check(b,sw,total,"before_receipt",true);File.WriteAllBytes(Path.Combine(runDir,"run-receipt.json"),rb);
            exportFile.Dispose();Console.WriteLine("COMPLETE_SELECTED_CATALOG_PROJECTION");Console.WriteLine(runDir);
        }

    }
}
