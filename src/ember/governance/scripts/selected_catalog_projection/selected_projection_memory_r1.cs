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
            public object[] runtime_phase_observations { get; set; }
            public object final_validation_index_counts { get; set; }
            public string unaccepted_staging_root { get; set; }
            public string error_type { get; set; }
            public string reason_code { get; set; }
            public string stack_trace { get; set; }
            public long a_input_bytes_read { get; set; }
            public long? private_bytes_peak_observed { get; set; }
            public long private_usage_sample_count { get; set; }
            public ExceptionLevel[] exception_chain { get; set; }
            public DiagnosticSnapshot[] diagnostic_snapshots { get; set; }
        }
        public sealed class DiagnosticSnapshot {
            public string checkpoint { get; set; }
            public string pass_name { get; set; }
            public long pass_rows { get; set; }
            public long private_usage_bytes { get; set; }
            public long membership_id_set_count { get; set; }
            public long retained_member_object_count { get; set; }
            public long selected_membership_id_count { get; set; }
            public long selected_dataset_membership_link_count { get; set; }
            public long heldout_hash_index_count { get; set; }
            public long quarantine_hash_index_count { get; set; }
            public long adjudicated_hash_index_count { get; set; }
            public long protected_evaluation_hash_index_count { get; set; }
            public long seen_version_edge_index_count { get; set; }
            public long candidate_type_index_count { get; set; }
            public long selected_sha_index_count { get; set; }
            public long sha_dataset_index_count { get; set; }
            public long object_index_count { get; set; }
            public long object_id_value_count { get; set; }
            public long receipt_link_index_count { get; set; }
            public long receipt_link_value_count { get; set; }
            public long receipt_sha_index_count { get; set; }
            public long receipt_row_index_count { get; set; }
        }
        public sealed class Binding {
            public string prediction_path, prediction_sha256, export_path, output_root, marker_path, tenant_declaration_path, tenant_declaration_key, tenant_command_sha_key, command_path, source_path, source_sha256, runner_path, runner_sha256;
            public long prediction_bytes, owner_reported_export_bytes, max_export_bytes, max_total_bytes_read, max_wall_seconds, max_private_bytes, max_output_bytes, min_C_free_bytes, max_tenant_declaration_bytes;
            public string terminal_receipt_path,terminal_receipt_reservation_sha256;
            public long terminal_receipt_reserved_bytes;
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
            public string Mode="",PendingRoot="",PassName="";
        }
        sealed class MarkerObservation { public string checkpoint,declaration_sha256; public bool marker_present,declared_tenant; }
        static readonly UTF8Encoding Utf8=new UTF8Encoding(false,true);
        static readonly long MiB=1024L*1024L;
        static readonly long MaxBuffer=512L*MiB;
        static readonly List<object> RuntimePhases=new List<object>();
        static object FinalValidationCounts;
        static string StagingRoot="";
        [StructLayout(LayoutKind.Sequential)] struct JobBasic {
            public long ProcessTime,JobTime; public uint Flags; public UIntPtr MinWorking,MaxWorking;
            public uint ActiveLimit; public UIntPtr Affinity; public uint Priority,Scheduling;
        }
        [StructLayout(LayoutKind.Sequential)] struct IoCounters { public ulong ReadOps,WriteOps,OtherOps,ReadBytes,WriteBytes,OtherBytes; }
        [StructLayout(LayoutKind.Sequential)] struct JobExtended {
            public JobBasic Basic; public IoCounters Io; public UIntPtr ProcessLimit,JobLimit,PeakProcess,PeakJob;
        }
        [DllImport("kernel32.dll",SetLastError=true)] static extern bool QueryInformationJobObject(IntPtr job,int kind,out JobExtended info,uint size,IntPtr returned);
        static void RuntimePhase(string phase,Binding b) {
            try {
                JobExtended job;
                if(!QueryInformationJobObject(IntPtr.Zero,9,out job,(uint)Marshal.SizeOf(typeof(JobExtended)),IntPtr.Zero))throw new Win32Exception(Marshal.GetLastWin32Error());
                if((job.Basic.Flags&0x300)!=0x300||job.ProcessLimit.ToUInt64()!=536870912UL||job.JobLimit.ToUInt64()!=536870912UL)throw new InvalidOperationException("JOB_CAPS_NOT_512_MIB");
                var gc=GC.GetGCMemoryInfo();
                var method=typeof(GC).GetMethod("GetConfigurationVariables",System.Reflection.BindingFlags.Public|System.Reflection.BindingFlags.Static);
                if(method==null)throw new InvalidOperationException("GC_CONFIGURATION_QUERY_UNAVAILABLE");
                var config=method.Invoke(null,null);
                if(config==null)throw new InvalidOperationException("GC_CONFIGURATION_QUERY_NULL");
                using(var process=Process.GetCurrentProcess()) {
                    RuntimePhases.Add(new{phase=phase,observed_utc=DateTime.UtcNow.ToString("o"),runtime_path=process.MainModule.FileName,runtime_file_version=process.MainModule.FileVersionInfo.FileVersion,dotnet_version=Environment.Version.ToString(),framework=RuntimeInformation.FrameworkDescription,architecture=RuntimeInformation.ProcessArchitecture.ToString(),gc_configuration=config,gc_index=gc.Index,gc_measurement_semantics="GCMemoryInfo describes the last GC; Index zero has no completed GC",gc_total_available_memory_bytes=gc.TotalAvailableMemoryBytes,gc_heap_size_bytes=gc.HeapSizeBytes,gc_total_committed_bytes=gc.TotalCommittedBytes,gc_fragmented_bytes=gc.FragmentedBytes,gc_memory_load_bytes=gc.MemoryLoadBytes,gc_high_memory_load_threshold_bytes=gc.HighMemoryLoadThresholdBytes,job_limit_flags=job.Basic.Flags,process_memory_limit_bytes=job.ProcessLimit.ToUInt64(),job_memory_limit_bytes=job.JobLimit.ToUInt64(),job_peak_process_memory_bytes=job.PeakProcess.ToUInt64(),job_peak_memory_bytes=job.PeakJob.ToUInt64()});
                }
                if(job.PeakProcess.ToUInt64()>536870912UL||job.PeakJob.ToUInt64()>536870912UL)throw new InvalidOperationException("JOB_PEAK_ABOVE_CAP");
            } catch(ObserverFailedException) { throw; } catch(Exception e) { throw new ObserverFailedException(e); }
        }
        const long TerminalReservationBytes=8192;
        static void VerifyTerminalReservation(Binding b) {
            if(b.terminal_receipt_reserved_bytes!=TerminalReservationBytes||!IsSha(b.terminal_receipt_reservation_sha256))throw new InvalidOperationException("TERMINAL_RESERVATION_BINDING");
            string expected=Path.Combine(b.output_root,"run-terminal-memory-r1.json");
            if(String.IsNullOrWhiteSpace(b.terminal_receipt_path)||Norm(b.terminal_receipt_path)!=Norm(expected))throw new InvalidOperationException("TERMINAL_RESERVATION_PATH");
            var info=new FileInfo(expected);
            if(!info.Exists||info.Length!=TerminalReservationBytes)throw new InvalidOperationException("TERMINAL_RESERVATION_LENGTH");
            if(Hash(File.ReadAllBytes(expected))!=b.terminal_receipt_reservation_sha256.ToLowerInvariant())throw new InvalidOperationException("TERMINAL_RESERVATION_HASH");
        }
        sealed class OutputBudget {
            public Binding B; public Stopwatch Watch; public long InputBytes,BaseBytes,WrittenBytes;
            public readonly Dictionary<string,object> Files=new Dictionary<string,object>(StringComparer.Ordinal);
            public void CheckWrite(int bytes) {
                long next=checked(WrittenBytes+bytes);
                if(checked(BaseBytes+next)>B.max_output_bytes)throw new InvalidOperationException("CAP_OUTPUT");
                Check(B,Watch,InputBytes,"metadata_row");
                if(new DriveInfo(Path.GetPathRoot(B.output_root)).AvailableFreeSpace<B.min_C_free_bytes)throw new InvalidOperationException("C_SPACE:output");
            }
        }
        sealed class BoundedOutput : Stream {
            readonly FileStream file; readonly IncrementalHash hash=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            readonly OutputBudget budget; readonly string name; long length;
            public BoundedOutput(OutputBudget budget,string name) { this.budget=budget;this.name=name;file=new FileStream(Path.Combine(StagingRoot,name),FileMode.CreateNew,FileAccess.Write,FileShare.None,65536,FileOptions.SequentialScan); }
            public override void Write(byte[] buffer,int offset,int count) {
                if(count>1048576)throw new InvalidOperationException("CAP_OUTPUT_BUFFER");
                budget.CheckWrite(count);file.Write(buffer,offset,count);hash.AppendData(buffer,offset,count);length=checked(length+count);budget.WrittenBytes=checked(budget.WrittenBytes+count);
            }
            public void Finish() { file.Flush(true);budget.Files.Add(name,new{bytes=length,sha256=BitConverter.ToString(hash.GetHashAndReset()).Replace("-","").ToLowerInvariant()}); }
            public override void Flush(){file.Flush();} public override bool CanRead{get{return false;}} public override bool CanSeek{get{return false;}} public override bool CanWrite{get{return true;}}
            public override long Length{get{return length;}} public override long Position{get{return length;}set{throw new NotSupportedException();}}
            public override int Read(byte[] b,int o,int c){throw new NotSupportedException();} public override long Seek(long o,SeekOrigin s){throw new NotSupportedException();} public override void SetLength(long n){throw new NotSupportedException();}
            protected override void Dispose(bool disposing){if(disposing){file.Dispose();hash.Dispose();}base.Dispose(disposing);}
        }
        static readonly JsonSerializerOptions RowOptions=new JsonSerializerOptions{DefaultBufferSize=65536};
        static readonly JsonSerializerOptions DocumentOptions=new JsonSerializerOptions{DefaultBufferSize=65536,WriteIndented=true};
        static void WriteDocument(OutputBudget budget,string name,object value) { using(var output=new BoundedOutput(budget,name)){JsonSerializer.Serialize(output,value,DocumentOptions);output.Finish();} }
        sealed class SelectionStats { public int Rows,UniqueIds; public long StateMismatch,TokenizerMismatch,WindowInvalid,RepeatSha; }
        // All Member/enumerator/sorted-list references are confined to this call and cease before pass 2.
        static SelectionStats WriteMemberships(OutputBudget budget,Prediction p,Dictionary<string,string> datasets,Dictionary<string,Member> members,Dictionary<string,List<string>> byDataset,HashSet<string> selectedSha,Dictionary<string,HashSet<string>> shaDatasets,Dictionary<string,long> perDataset) {
            var stats=new SelectionStats();var uniqueIds=new HashSet<string>(StringComparer.Ordinal);
            using(var output=new BoundedOutput(budget,"selected-memberships.jsonl")) {
                foreach(string dsid in p.Ids.OrderBy(x=>x,StringComparer.Ordinal)) {
                    string state;if(!datasets.TryGetValue(dsid,out state))throw new InvalidOperationException("DATASET_MISSING");if(state!="admitted")stats.StateMismatch++;
                    var ids=byDataset[dsid].OrderBy(x=>x,StringComparer.Ordinal).ToList();if(ids.Count==0)throw new InvalidOperationException("MEMBERSHIP_EMPTY");perDataset[dsid]=ids.Count;
                    foreach(string id in ids) {
                        Member m;if(!members.TryGetValue(id,out m))throw new InvalidOperationException("MEMBERSHIP_MISSING");uniqueIds.Add(id);
                        if(m.Split!="train"||m.Admission!="admitted")stats.StateMismatch++;if(!String.Equals(m.Tokenizer,p.Tokenizer,StringComparison.OrdinalIgnoreCase))stats.TokenizerMismatch++;
                        long a,z;if(!Int64.TryParse(m.Start,NumberStyles.Integer,CultureInfo.InvariantCulture,out a)||!Int64.TryParse(m.End,NumberStyles.Integer,CultureInfo.InvariantCulture,out z)||a<0||z<=a)stats.WindowInvalid++;
                        if(!selectedSha.Add(m.Sha))stats.RepeatSha++;HashSet<string> ds;if(!shaDatasets.TryGetValue(m.Sha,out ds)){ds=new HashSet<string>(StringComparer.Ordinal);shaDatasets[m.Sha]=ds;}ds.Add(dsid);
                        JsonSerializer.Serialize(output,new{dataset_id=dsid,membership_id=id,exact_sha256=m.Sha,split=m.Split,admission_state=m.Admission,tokenizer_sha256=m.Tokenizer,window_start=m.Start,window_end=m.End},RowOptions);output.WriteByte(10);stats.Rows=checked(stats.Rows+1);
                    }
                }
                output.Finish();
            }
            stats.UniqueIds=uniqueIds.Count;return stats;
        }
        static void WriteObjects(OutputBudget budget,HashSet<string> selectedSha,Dictionary<string,List<string>> objects,Dictionary<string,HashSet<string>> shaDatasets,Dictionary<string,List<string>> receiptLinks) {
            using(var output=new BoundedOutput(budget,"selected-objects.jsonl")) {
                foreach(string h in selectedSha.OrderBy(x=>x,StringComparer.Ordinal)) {
                    var rs=receiptLinks.ContainsKey(h)?receiptLinks[h].OrderBy(x=>x,StringComparer.Ordinal).ToArray():new string[0];
                    JsonSerializer.Serialize(output,new{sha256=h,catalog_object_ids=objects[h].OrderBy(x=>x,StringComparer.Ordinal).ToArray(),selected_dataset_ids=shaDatasets[h].OrderBy(x=>x,StringComparer.Ordinal).ToArray(),receipt_sha256s=rs},RowOptions);output.WriteByte(10);
                }
                output.Finish();
            }
        }
        static int GuardCapacity(long count,Binding b) {
            if(count<0||count>Int32.MaxValue||checked(count*64L)>b.max_private_bytes)throw new InvalidOperationException("CAP_INDEX_CAPACITY");return (int)count;
        }
        static void VerifyOutputs(OutputBudget budget) {
            foreach(var entry in budget.Files) {
                var expected=JsonSerializer.SerializeToElement(entry.Value);string path=Path.Combine(StagingRoot,entry.Key);
                using(var input=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.Read,65536,FileOptions.SequentialScan))
                using(var hash=IncrementalHash.CreateHash(HashAlgorithmName.SHA256)) {
                    byte[] bytes=new byte[65536];int count;long length=0;
                    while((count=input.Read(bytes,0,bytes.Length))>0){Check(budget.B,budget.Watch,budget.InputBytes,"metadata_row");hash.AppendData(bytes,0,count);length=checked(length+count);}
                    string digest=BitConverter.ToString(hash.GetHashAndReset()).Replace("-","").ToLowerInvariant();
                    if(length!=expected.GetProperty("bytes").GetInt64()||digest!=expected.GetProperty("sha256").GetString())throw new InvalidOperationException("OUTPUT_HASH_LENGTH");
                }
            }
        }
        public static long LastAInputBytesRead=0;
        static long PeakPrivate,PrivateSampleCount,LastPrivateCapObservation;
        static int PrivateRowsSinceSample;
        const int PrivateSampleEveryRows=64;
        static string ActiveBindingSha="",ActiveCommandSha="";
        static readonly List<MarkerObservation> MarkerObservations=new List<MarkerObservation>();
        static string LastTenantDeclarationSha=""; static readonly List<DiagnosticSnapshot> DiagnosticSnapshots=new List<DiagnosticSnapshot>();
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
            return new FailureDiagnostics{error_type=error.GetType().FullName,reason_code=reason,stack_trace=error.ToString(),a_input_bytes_read=bytesRead,private_bytes_peak_observed=PrivateSampleCount>0?(long?)PeakPrivate:null,private_usage_sample_count=PrivateSampleCount,exception_chain=chain.ToArray(),diagnostic_snapshots=DiagnosticSnapshots.ToArray(),runtime_phase_observations=RuntimePhases.ToArray(),final_validation_index_counts=FinalValidationCounts,unaccepted_staging_root=StagingRoot};
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
            if(where=="metadata_row"||where=="hash_row") {
                PrivateRowsSinceSample++;
                if(PrivateRowsSinceSample>=PrivateSampleEveryRows) { PrivateRowsSinceSample=0; samplePrivate=true; }
            } else if(IsPrivateSampleBoundary(where)||where=="buffer_growth") {
                PrivateRowsSinceSample=0;
                samplePrivate=true;
            }
            if(samplePrivate) {
                long p=ObservePrivateUsage();
                if(p>b.max_private_bytes) { LastPrivateCapObservation=p; throw new InvalidOperationException("CAP_PRIVATE:"+where); }
            }
            if(markerCheckpoint)ObserveMarker(b,where);
        }
        static long Metric(Dictionary<string,long> x,string key) { long n; return x!=null&&x.TryGetValue(key,out n)?n:0; }
        static void CaptureDiagnosticSnapshot(string checkpoint,ScanState state,long maxPrivate,Func<Dictionary<string,long>> indexCounts) {
            long value=checkpoint=="row_failure"&&LastPrivateCapObservation>0?LastPrivateCapObservation:ObservePrivateUsage();
            var counts=indexCounts==null?new Dictionary<string,long>(StringComparer.Ordinal):indexCounts();
            DiagnosticSnapshots.Add(new DiagnosticSnapshot{
                checkpoint=checkpoint,pass_name=state==null?"":state.PassName,pass_rows=state==null?0:state.Rows,private_usage_bytes=value,
                membership_id_set_count=Metric(counts,"membership_id_set_count"),
                retained_member_object_count=Metric(counts,"retained_member_object_count"),
                selected_membership_id_count=Metric(counts,"selected_membership_id_count"),
                selected_dataset_membership_link_count=Metric(counts,"selected_dataset_membership_link_count"),
                heldout_hash_index_count=Metric(counts,"heldout_hash_index_count"),
                quarantine_hash_index_count=Metric(counts,"quarantine_hash_index_count"),
                adjudicated_hash_index_count=Metric(counts,"adjudicated_hash_index_count"),
                protected_evaluation_hash_index_count=Metric(counts,"protected_evaluation_hash_index_count"),
                seen_version_edge_index_count=Metric(counts,"seen_version_edge_index_count"),
                candidate_type_index_count=Metric(counts,"candidate_type_index_count"),
                selected_sha_index_count=Metric(counts,"selected_sha_index_count"),
                sha_dataset_index_count=Metric(counts,"sha_dataset_index_count"),
                object_index_count=Metric(counts,"object_index_count"),
                object_id_value_count=Metric(counts,"object_id_value_count"),
                receipt_link_index_count=Metric(counts,"receipt_link_index_count"),
                receipt_link_value_count=Metric(counts,"receipt_link_value_count"),
                receipt_sha_index_count=Metric(counts,"receipt_sha_index_count"),
                receipt_row_index_count=Metric(counts,"receipt_row_index_count")
            });
            if(value>maxPrivate)throw new InvalidOperationException("CAP_PRIVATE:diagnostic_snapshot:"+checkpoint);
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
        // The existing hash traversal also preselects membership IDs from direct edge fields. Records stay unmaterialized in that traversal.
        static string Scan(FileStream fs,Binding b,Stopwatch sw,ref long total,bool hashPass,bool rootOrderGate,Action<Row> onRow,ScanState s,Func<Dictionary<string,long>> indexCounts) {
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
                        if(onRow!=null&&(!hashPass||s.Mode=="edges")&&(s.Mode=="records"||s.Mode=="edges")&&r.TokenType==System.Text.Json.JsonTokenType.StartObject&&r.CurrentDepth==2) {
                            if(row!=null)throw new InvalidOperationException("ROW_NESTING");row=new Row();pending=null;
                        }
                        else if(row!=null&&r.TokenType==System.Text.Json.JsonTokenType.PropertyName&&r.CurrentDepth==3) {
                            if(hashPass) {
                                pending=r.ValueTextEquals("kind")?"kind":r.ValueTextEquals("from_id")?"from_id":r.ValueTextEquals("to_id")?"to_id":null;
                                if(pending!=null&&!row.SeenKeys.Add(pending))throw new InvalidOperationException("DUPLICATE_ROW_PROPERTY");
                            } else if(r.ValueSpan.Length<=256) {
                                pending=r.GetString();if(!row.SeenKeys.Add(pending))throw new InvalidOperationException("DUPLICATE_ROW_PROPERTY");
                            } else pending=null;
                        }
                        else if(row!=null&&r.CurrentDepth==3&&r.TokenType!=System.Text.Json.JsonTokenType.PropertyName&&r.TokenType!=System.Text.Json.JsonTokenType.EndObject&&r.TokenType!=System.Text.Json.JsonTokenType.EndArray) {
                            string k=pending;pending=null;
                            if(!String.IsNullOrEmpty(k)) {
                                if(k=="kind")row.KindType=TypeName(r.TokenType);
                                if(!hashPass&&Candidate(k))Add(row.CandidateTypes,k+"|"+TypeName(r.TokenType));
                                else if(hashPass||Capture.Contains(k)) {
                                    string v=null;
                                    if(r.TokenType==System.Text.Json.JsonTokenType.String)v=ReadSmallString(ref r,k);
                                    else if(r.TokenType==System.Text.Json.JsonTokenType.Number){long n;if(r.TryGetInt64(out n))v=n.ToString(CultureInfo.InvariantCulture);}
                                    else if(r.TokenType==System.Text.Json.JsonTokenType.True)v="true";
                                    else if(r.TokenType==System.Text.Json.JsonTokenType.False)v="false";
                                    if(v!=null)row.V[k]=v;
                                }
                            }
                        }
                        else if(row!=null&&(r.TokenType==System.Text.Json.JsonTokenType.StartObject||r.TokenType==System.Text.Json.JsonTokenType.StartArray)&&r.CurrentDepth==3) {
                            if(pending=="kind")row.KindType=TypeName(r.TokenType);
                            if(!hashPass&&!String.IsNullOrEmpty(pending)&&Candidate(pending))Add(row.CandidateTypes,pending+"|"+TypeName(r.TokenType));pending=null;
                        }
                        else if(hashPass&&r.TokenType==System.Text.Json.JsonTokenType.EndObject&&r.CurrentDepth==2&&(s.Mode=="records"||s.Mode=="edges")) {
                            s.Rows++;if(s.Mode=="records")s.RecordRows++;else s.EdgeRows++;
                            try {
                                if(row!=null){onRow(row);row=null;}pending=null;Check(b,sw,total,"hash_row");
                                if(s.Rows%4096L==0)CaptureDiagnosticSnapshot("every_4096_rows",s,b.max_private_bytes,indexCounts);
                            } catch {
                                try { CaptureDiagnosticSnapshot("row_failure",s,b.max_private_bytes,indexCounts); } catch {}
                                throw;
                            }
                        }
                        else if(!hashPass&&row!=null&&r.TokenType==System.Text.Json.JsonTokenType.EndObject&&r.CurrentDepth==2) {
                            s.Rows++;if(s.Mode=="records"){s.RecordRows++;Add(s.RecordKindCounts,row.KindCountKey);}else{s.EdgeRows++;Add(s.EdgeKindCounts,row.KindCountKey);}
                            try {
                                onRow(row);row=null;pending=null;Check(b,sw,total,"metadata_row");
                                if(s.Rows%4096L==0)CaptureDiagnosticSnapshot("every_4096_rows",s,b.max_private_bytes,indexCounts);
                            } catch {
                                try { CaptureDiagnosticSnapshot("row_failure",s,b.max_private_bytes,indexCounts); } catch {}
                                throw;
                            }
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
            LastAInputBytesRead=0;PeakPrivate=0;PrivateSampleCount=0;PrivateRowsSinceSample=0;LastPrivateCapObservation=0;MarkerObservations.Clear();LastTenantDeclarationSha="";DiagnosticSnapshots.Clear();RuntimePhases.Clear();FinalValidationCounts=null;StagingRoot="";byte[] bindingRaw=File.ReadAllBytes(bindingPath);if(Hash(bindingRaw)!=expectedBindingSha.ToLowerInvariant())throw new InvalidOperationException("BINDING_HASH");
            Binding b;using(var d=JsonDocument.Parse(bindingRaw))b=JsonSerializer.Deserialize<Binding>(d.RootElement.GetRawText(),new JsonSerializerOptions{IncludeFields=true});
            if(b==null||b.max_metadata_passes!=2)throw new InvalidOperationException("BINDING_SCHEMA");
            if(!IsSha(expectedCommandSha)||Norm(b.command_path)!=Norm(commandPath)||Hash(File.ReadAllBytes(b.command_path))!=expectedCommandSha.ToLowerInvariant())throw new InvalidOperationException("COMMAND_HASH");
            if(Hash(File.ReadAllBytes(b.source_path))!=b.source_sha256.ToLowerInvariant()||Hash(File.ReadAllBytes(b.runner_path))!=b.runner_sha256.ToLowerInvariant())throw new InvalidOperationException("SOURCE_RUNNER_HASH");
            if(Norm(b.output_root)!=Norm(Path.GetDirectoryName(bindingPath)))throw new InvalidOperationException("OUTPUT_ROOT");
            VerifyTerminalReservation(b);
            ActiveBindingSha=expectedBindingSha.ToLowerInvariant();ActiveCommandSha=expectedCommandSha.ToLowerInvariant();
            var sw=Stopwatch.StartNew();var proc=Process.GetCurrentProcess();if(proc.PriorityClass!=ProcessPriorityClass.BelowNormal)throw new InvalidOperationException("LAUNCH_PRIORITY");
            if(ObservePrivateUsage()>b.max_private_bytes)throw new InvalidOperationException("CAP_PRIVATE:launch");long total=0;
            string runDir=Path.Combine(b.output_root,"run");if(Directory.Exists(runDir))throw new InvalidOperationException("OUTPUT_EXISTS");
            if(new DriveInfo(Path.GetPathRoot(b.output_root)).AvailableFreeSpace<b.min_C_free_bytes)throw new InvalidOperationException("C_SPACE");
            RuntimePhase("launch",b);Check(b,sw,total,"preflight",true);Prediction p=ReadPrediction(b,sw,ref total);
            if(Norm(p.ExportPath)!=Norm(b.export_path)||!IsSha(p.ExportSha)||!IsSha(p.Tokenizer))throw new InvalidOperationException("PREDICTION_BINDING");
            if(b.owner_reported_export_bytes>b.max_export_bytes)throw new InvalidOperationException("EXPORT_CAP");
            var exportFile=new FileStream(b.export_path,FileMode.Open,FileAccess.Read,FileShare.Read,1024*1024,FileOptions.SequentialScan);
            var selectedIdsForRetention=new HashSet<string>(StringComparer.Ordinal);
            var selectedDatasetIds=new HashSet<string>(p.Ids,StringComparer.Ordinal);
            Func<Dictionary<string,long>> hashIndexes=()=>new Dictionary<string,long>(StringComparer.Ordinal){{"selected_membership_id_count",(selectedIdsForRetention==null?0:selectedIdsForRetention.Count)}};
            var hs=new ScanState{PassName="hash"};CaptureDiagnosticSnapshot("before_hash",hs,b.max_private_bytes,hashIndexes);
            string exportSha=Scan(exportFile,b,sw,ref total,true,false,row=>{
                if(row.Kind=="version_membership"){
                    string from,to;if(row.V.TryGetValue("from_id",out from)&&row.V.TryGetValue("to_id",out to)&&selectedDatasetIds.Contains(from))selectedIdsForRetention.Add(to);
                }
            },hs,hashIndexes);
            CaptureDiagnosticSnapshot("after_hash",hs,b.max_private_bytes,hashIndexes);
            if(!String.Equals(exportSha,p.ExportSha,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("EXPORT_HASH");
            RuntimePhase("after_hash",b);Check(b,sw,total,"after_hash",true);string orderPlan=ValidateTwoPassOrder(hs);CaptureDiagnosticSnapshot("after_root_order_check",hs,b.max_private_bytes,hashIndexes);Check(b,sw,total,"after_root_order_check",true);

            var datasets=new Dictionary<string,string>(StringComparer.Ordinal);var members=new Dictionary<string,Member>(StringComparer.Ordinal);var membershipIds=new HashSet<string>(StringComparer.Ordinal);
            var byDataset=new Dictionary<string,List<string>>(StringComparer.Ordinal);foreach(string id in p.Ids)byDataset[id]=new List<string>();
            var heldout=new HashSet<string>(StringComparer.Ordinal);var quarantine=new HashSet<string>(StringComparer.Ordinal);var adjudicated=new HashSet<string>(StringComparer.Ordinal);var protectedEval=new HashSet<string>(StringComparer.Ordinal);
            var candidateTypes=new Dictionary<string,long>(StringComparer.Ordinal);var seenVersionEdges=new HashSet<string>(StringComparer.Ordinal);long duplicateVersionEdges=0,selectedVersionMembershipEdges=0;var p1=new ScanState{PassName="pass1"};
            Func<Dictionary<string,long>> pass1Indexes=()=>{
                var c=new Dictionary<string,long>(StringComparer.Ordinal);
                c["membership_id_set_count"]=(membershipIds==null?0:membershipIds.Count);c["retained_member_object_count"]=(members==null?0:members.Count);c["selected_membership_id_count"]=(selectedIdsForRetention==null?0:selectedIdsForRetention.Count);
                c["selected_dataset_membership_link_count"]=(byDataset==null?0:byDataset.Values.Sum(x=>(long)x.Count));c["heldout_hash_index_count"]=(heldout==null?0:heldout.Count);c["quarantine_hash_index_count"]=(quarantine==null?0:quarantine.Count);c["adjudicated_hash_index_count"]=(adjudicated==null?0:adjudicated.Count);
                c["protected_evaluation_hash_index_count"]=(protectedEval==null?0:protectedEval.Count);c["seen_version_edge_index_count"]=(seenVersionEdges==null?0:seenVersionEdges.Count);c["candidate_type_index_count"]=candidateTypes.Count;
                return c;
            };
            CaptureDiagnosticSnapshot("before_pass1",p1,b.max_private_bytes,pass1Indexes);
            string pass1Sha=Scan(exportFile,b,sw,ref total,false,false,row=>{
                foreach(var x in row.CandidateTypes)Add(candidateTypes,row.Kind+"|"+x.Key,x.Value);
                if(row.Kind=="dataset_version"){string id;if(row.V.TryGetValue("id",out id)&&byDataset.ContainsKey(id)){if(datasets.ContainsKey(id))throw new InvalidOperationException("DATASET_DUPLICATE");datasets[id]=row.V.ContainsKey("state")?row.V["state"]:"";}}
                else if(row.Kind=="membership"){
                    string id=Need(row.V,"id","MEMBERSHIP_ID"),sha=Need(row.V,"exact_sha256","MEMBERSHIP_SHA").ToLowerInvariant();if(!IsSha(sha))throw new InvalidOperationException("MEMBERSHIP_SHA");
                    string split=row.V.ContainsKey("split")?row.V["split"]:"",adm=row.V.ContainsKey("admission_state")?row.V["admission_state"]:"";
                    if(!membershipIds.Add(id))throw new InvalidOperationException("MEMBERSHIP_DUPLICATE");
                    if(selectedIdsForRetention.Contains(id))members[id]=new Member{Id=id,Sha=sha,Split=split,Admission=adm,Tokenizer=row.V.ContainsKey("tokenizer_sha256")?row.V["tokenizer_sha256"]:"",Start=row.V.ContainsKey("window_start")?row.V["window_start"]:"",End=row.V.ContainsKey("window_end")?row.V["window_end"]:""};
                    if(split!="train"&&adm=="admitted")heldout.Add(sha);if(split=="train"&&adm!="admitted")quarantine.Add(sha);if(split!="train"&&adm!="admitted")adjudicated.Add(sha);
                }
                else if(row.Kind=="version_membership"){string f,t;if(row.V.TryGetValue("from_id",out f)&&row.V.TryGetValue("to_id",out t)&&byDataset.ContainsKey(f)){selectedVersionMembershipEdges++;if(!seenVersionEdges.Add(f+"|"+t))duplicateVersionEdges++;byDataset[f].Add(t);}}
                else if(row.Kind=="evaluation_object"){string t;if(row.V.TryGetValue("to_id",out t)){string h=EdgeHash(t,"object");if(h!=null)protectedEval.Add(h);}}
            },p1,pass1Indexes);if(!String.Equals(pass1Sha,p.ExportSha,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("EXPORT_CHANGED_PASS1");
            CaptureDiagnosticSnapshot("after_pass1",p1,b.max_private_bytes,pass1Indexes);RuntimePhase("after_pass1",b);Check(b,sw,total,"after_pass1",true);
            foreach(string id in selectedIdsForRetention)if(!members.ContainsKey(id))throw new InvalidOperationException("MEMBERSHIP_MISSING");
            CaptureDiagnosticSnapshot("after_selected_membership_totality",p1,b.max_private_bytes,pass1Indexes);

            StagingRoot=Path.Combine(b.output_root,"staging-unaccepted");
            if(Directory.Exists(StagingRoot))throw new InvalidOperationException("STAGING_EXISTS");
            long baseBytes=0;foreach(string file in Directory.EnumerateFiles(b.output_root,"*",SearchOption.AllDirectories))baseBytes=checked(baseBytes+new FileInfo(file).Length);
            var outputBudget=new OutputBudget{B=b,Watch=sw,InputBytes=total,BaseBytes=baseBytes};
            Directory.CreateDirectory(StagingRoot);
            var selectedSha=new HashSet<string>(StringComparer.Ordinal);
            var shaDatasets=new Dictionary<string,HashSet<string>>(StringComparer.Ordinal);var perDataset=new Dictionary<string,long>(StringComparer.Ordinal);
            RuntimePhase("before_membership_serialization",b);
            var selection=WriteMemberships(outputBudget,p,datasets,members,byDataset,selectedSha,shaDatasets,perDataset);
            int selectedCount=selection.Rows,selectedMemberCount=selection.UniqueIds,selectedShaCount=selectedSha.Count;
            long stateMismatch=selection.StateMismatch,tokenizerMismatch=selection.TokenizerMismatch,windowInvalid=selection.WindowInvalid,repeatSha=selection.RepeatSha;
            long heldoutHit=selectedSha.Count(x=>heldout.Contains(x)),quarantineHit=selectedSha.Count(x=>quarantine.Contains(x)),protectedHit=selectedSha.Count(x=>protectedEval.Contains(x)),adjudicatedHit=selectedSha.Count(x=>adjudicated.Contains(x));

            FinalValidationCounts=pass1Indexes();
            // All-row checks, four intersections, and membership output are complete. Drop captured references and delegates.
            hashIndexes=null;pass1Indexes=null;selectedIdsForRetention=null;selectedDatasetIds=null;
            membershipIds=null;seenVersionEdges=null;heldout=null;quarantine=null;adjudicated=null;protectedEval=null;members=null;byDataset=null;
            RuntimePhase("after_pass1_release",b);
            int selectedCapacity=GuardCapacity(selectedShaCount,b),receiptCapacity=GuardCapacity(checked(GetCount(p1.RecordKindCounts,"string:receipt")+GetCount(p1.EdgeKindCounts,"string:receipt")),b);
            var objects=new Dictionary<string,List<string>>(selectedCapacity,StringComparer.Ordinal);var receiptLinks=new Dictionary<string,List<string>>(selectedCapacity,StringComparer.Ordinal);long selectedObjectReceiptEdges=0;var receiptShas=new HashSet<string>(StringComparer.Ordinal);var receiptRowsBySha=new Dictionary<string,long>(receiptCapacity,StringComparer.Ordinal);var p2=new ScanState{PassName="pass2"};
            Func<Dictionary<string,long>> pass2Indexes=()=>{
                var c=new Dictionary<string,long>(StringComparer.Ordinal);
                c["membership_id_set_count"]=(membershipIds==null?0:membershipIds.Count);c["retained_member_object_count"]=(members==null?0:members.Count);c["selected_membership_id_count"]=0;
                c["selected_dataset_membership_link_count"]=(byDataset==null?0:byDataset.Values.Sum(x=>(long)x.Count));c["heldout_hash_index_count"]=(heldout==null?0:heldout.Count);c["quarantine_hash_index_count"]=(quarantine==null?0:quarantine.Count);c["adjudicated_hash_index_count"]=(adjudicated==null?0:adjudicated.Count);
                c["protected_evaluation_hash_index_count"]=(protectedEval==null?0:protectedEval.Count);c["seen_version_edge_index_count"]=(seenVersionEdges==null?0:seenVersionEdges.Count);c["candidate_type_index_count"]=candidateTypes.Count;
                c["selected_sha_index_count"]=selectedSha.Count;c["sha_dataset_index_count"]=shaDatasets.Count;c["object_index_count"]=objects.Count;c["object_id_value_count"]=objects.Values.Sum(x=>(long)x.Count);
                c["receipt_link_index_count"]=receiptLinks.Count;c["receipt_link_value_count"]=receiptLinks.Values.Sum(x=>(long)x.Count);c["receipt_sha_index_count"]=receiptShas.Count;c["receipt_row_index_count"]=receiptRowsBySha.Count;
                return c;
            };
            CaptureDiagnosticSnapshot("after_pass1_release",new ScanState{PassName="release"},b.max_private_bytes,pass2Indexes);CaptureDiagnosticSnapshot("before_pass2",p2,b.max_private_bytes,pass2Indexes);RuntimePhase("before_pass2",b);
            string pass2Sha=Scan(exportFile,b,sw,ref total,false,false,row=>{
                if(row.Kind=="immutable_object"){string h;if(row.V.TryGetValue("sha256",out h)&&selectedSha.Contains(h.ToLowerInvariant())){List<string> ids;if(!objects.TryGetValue(h.ToLowerInvariant(),out ids)){ids=new List<string>();objects[h.ToLowerInvariant()]=ids;}ids.Add(row.V.ContainsKey("id")?row.V["id"]:"");}}
                else if(row.Kind=="object_receipt"){string f,t;if(row.V.TryGetValue("from_id",out f)&&row.V.TryGetValue("to_id",out t)){string h=EdgeHash(f,"object"),r=EdgeHash(t,"receipt");if(h!=null&&r!=null&&selectedSha.Contains(h)){List<string>s;if(!receiptLinks.TryGetValue(h,out s)){s=new List<string>();receiptLinks[h]=s;}s.Add(r);selectedObjectReceiptEdges++;}}}
                else if(row.Kind=="receipt"){string h;if(row.V.TryGetValue("sha256",out h)&&IsSha(h)){h=h.ToLowerInvariant();receiptShas.Add(h);Add(receiptRowsBySha,h);}}
            },p2,pass2Indexes);if(!String.Equals(pass2Sha,p.ExportSha,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("EXPORT_CHANGED_PASS2");CaptureDiagnosticSnapshot("after_pass2",p2,b.max_private_bytes,pass2Indexes);RuntimePhase("after_pass2",b);Check(b,sw,total,"after_pass2",true);VerifyPassCounts(p1,p2);
            long missingObject=selectedSha.LongCount(x=>!objects.ContainsKey(x)),duplicateObject=objects.Values.LongCount(x=>x.Count!=1);if(missingObject!=0||duplicateObject!=0)throw new InvalidOperationException("OBJECT_TOTALITY");
            long unresolvedReceipt=receiptLinks.Sum(x=>x.Value.LongCount(y=>!receiptShas.Contains(y)));
            var selectedRecordKinds=new Dictionary<string,long>(StringComparer.Ordinal);Add(selectedRecordKinds,"string:dataset_version",p.Ids.Count);Add(selectedRecordKinds,"string:membership",selectedMemberCount);Add(selectedRecordKinds,"string:immutable_object",objects.Values.Sum(x=>(long)x.Count));
            var referencedReceiptHashes=new HashSet<string>(receiptLinks.Values.SelectMany(x=>x),StringComparer.Ordinal);long selectedReceiptRows=receiptRowsBySha.Where(x=>referencedReceiptHashes.Contains(x.Key)).Sum(x=>x.Value);Add(selectedRecordKinds,"string:receipt",selectedReceiptRows);
            var selectedEdgeKinds=new Dictionary<string,long>(StringComparer.Ordinal);Add(selectedEdgeKinds,"string:version_membership",selectedVersionMembershipEdges);Add(selectedEdgeKinds,"string:object_receipt",selectedObjectReceiptEdges);
            long selectedRecordRows=selectedRecordKinds.Values.Sum(),selectedEdgeRows=selectedEdgeKinds.Values.Sum();long excludedRecordRows=p1.RecordRows-selectedRecordRows,excludedEdgeRows=p1.EdgeRows-selectedEdgeRows;
            if(excludedRecordRows<0||excludedEdgeRows<0)throw new InvalidOperationException("COUNT_SELECTED_EXCEEDS_TOTAL");
            object[] recordKindCounts=BuildKindCounts("record",p1.RecordKindCounts,p1.RecordKindCounts,p2.RecordKindCounts,selectedRecordKinds),edgeKindCounts=BuildKindCounts("edge",p1.EdgeKindCounts,p1.EdgeKindCounts,p2.EdgeKindCounts,selectedEdgeKinds);
            var logicalCounts=new{records=new{unit="record",logical_rows=p1.RecordRows,pass1_observations=p1.RecordRows,pass2_observations=p2.RecordRows,selected_rows=selectedRecordRows,excluded_rows=excludedRecordRows,nonselected_rows=excludedRecordRows},edges=new{unit="edge",logical_rows=p1.EdgeRows,pass1_observations=p1.EdgeRows,pass2_observations=p2.EdgeRows,selected_rows=selectedEdgeRows,excluded_rows=excludedEdgeRows,nonselected_rows=excludedEdgeRows}};
            long globalContextEdges=GetCount(p1.EdgeKindCounts,"string:evaluation_object");
            var summary=new{schema="niko.selected_catalog_projection.summary.v1",status="COMPLETE_SELECTED_CATALOG_PROJECTION",scope="eight frozen dataset IDs only; not a global admitted total or current_208 selector",dataset_ids=p.Ids.OrderBy(x=>x,StringComparer.Ordinal).ToArray(),selected_dataset_version_states=p.Ids.OrderBy(x=>x,StringComparer.Ordinal).Select(x=>new{dataset_id=x,state=datasets[x]}).ToArray(),selected_membership_edge_rows=selectedCount,selected_membership_row_occurrences=selectedCount,unique_selected_membership_ids=selectedMemberCount,duplicate_selected_membership_occurrences=selectedCount-selectedMemberCount,unique_selected_sha256s=selectedSha.Count,unique_selected_object_digests=selectedSha.Count,selected_source_record_rows=selectedRecordRows,excluded_source_record_rows=excludedRecordRows,nonselected_source_record_rows=excludedRecordRows,selected_source_edge_rows=selectedEdgeRows,excluded_source_edge_rows=excludedEdgeRows,nonselected_source_edge_rows=excludedEdgeRows,global_analysis_context_edge_rows=globalContextEdges,logical_export_row_counts=logicalCounts,per_kind_export_row_counts=new{records=recordKindCounts,edges=edgeKindCounts},count_class_semantics="selected rows match the frozen selector or selected digest joins; excluded and nonselected are the same unmatched subset and overlap exactly, so do not add all three. Logical source rows count once; pass1_observations and pass2_observations are visits. evaluation_object edges remain global leakage context even though they are nonselected from the selected projection.",repeated_digest_membership_edges=repeatSha,per_dataset_membership_edges=perDataset,dataset_or_membership_state_mismatch_rows=stateMismatch,tokenizer_mismatch_rows=tokenizerMismatch,invalid_or_missing_declared_window_rows=windowInvalid,missing_selected_objects=missingObject,duplicate_object_rows=duplicateObject,duplicate_selected_version_membership_edges=duplicateVersionEdges,selected_object_receipt_edge_rows=selectedObjectReceiptEdges,unresolved_receipt_edges=unresolvedReceipt,selected_sha_intersections=new{admitted_non_train=heldoutHit,quarantined_train=quarantineHit,protected_evaluation=protectedHit,adjudicated_non_train=adjudicatedHit},export_top_level_key_order=hs.RootOrder.ToArray(),export_root_array_order=hs.RootArrayOrder.ToArray(),metadata_order_plan=orderPlan,candidate_key_type_counts=candidateTypes,candidate_boundary="direct property names/types only; values unread",content_boundary="paths/captions/payloads/source text/token arrays/image bytes not materialized",current_208="UNKNOWN"};
            outputBudget.InputBytes=total;
            Check(b,sw,total,"before_output",true);RuntimePhase("before_object_serialization",b);
            WriteObjects(outputBudget,selectedSha,objects,shaDatasets,receiptLinks);
            WriteDocument(outputBudget,"summary.json",summary);
            RuntimePhase("after_output_serialization",b);
            long outBytes=checked(outputBudget.BaseBytes+outputBudget.WrittenBytes);
            Check(b,sw,total,"before_receipt",true);var receipt=new{schema="niko.selected_catalog_projection.run_receipt.v2",status="COMPLETE_SELECTED_CATALOG_PROJECTION",prediction_sha256=b.prediction_sha256,prediction_bytes=b.prediction_bytes,export_sha256=exportSha,export_bytes=b.owner_reported_export_bytes,export_top_level_key_order=hs.RootOrder.ToArray(),export_root_array_order=hs.RootArrayOrder.ToArray(),metadata_order_plan=orderPlan,membership_retention_strategy="hash_preselected_ids_only",metadata_passes=2,total_input_bytes_read=total,max_total_bytes_read=b.max_total_bytes_read,private_bytes_peak_observed=PeakPrivate,private_usage_observer="GetProcessMemoryInfo.PrivateUsage",private_usage_poll_rows=PrivateSampleEveryRows,diagnostic_snapshot_interval_rows=4096,diagnostic_snapshots=DiagnosticSnapshots.ToArray(),runtime_phase_observations=RuntimePhases.ToArray(),final_validation_index_counts=FinalValidationCounts,output_artifact_hashes=outputBudget.Files,output_buffer_limit_bytes=1048576,terminal_receipt_path=b.terminal_receipt_path,terminal_receipt_reserved_bytes=b.terminal_receipt_reserved_bytes,terminal_receipt_reservation_sha256=b.terminal_receipt_reservation_sha256,terminal_receipt_budget_semantics="same-root pending file counted in BaseBytes; parent finalizes in place without growth",staging_promotion="same-volume Directory.Move after all unchanged final checks",private_usage_sample_count=PrivateSampleCount,max_private_bytes=b.max_private_bytes,runner_elapsed_seconds=sw.Elapsed.TotalSeconds,outer_wall_ceiling_seconds=b.max_wall_seconds,output_bytes_before_receipt=outBytes,max_output_bytes=b.max_output_bytes,marker_absent_at_start=!MarkerPresentAt("preflight"),marker_absent_after_hash=!MarkerPresentAt("after_hash"),marker_absent_after_pass1=!MarkerPresentAt("after_pass1"),marker_absent_after_pass2=!MarkerPresentAt("after_pass2"),marker_declared_at_start=TenantDeclaredAt("preflight"),marker_declared_after_hash=TenantDeclaredAt("after_hash"),marker_declared_after_pass1=TenantDeclaredAt("after_pass1"),marker_declared_after_pass2=TenantDeclaredAt("after_pass2"),marker_present_checkpoints=MarkerObservations.Where(x=>x.marker_present).Select(x=>x.checkpoint).ToArray(),tenant_declared_checkpoints=MarkerObservations.Where(x=>x.declared_tenant).Select(x=>x.checkpoint).ToArray(),tenant_declaration_path=b.tenant_declaration_path,tenant_declaration_sha256_last_observed=LastTenantDeclarationSha,command_sha256=ActiveCommandSha,logical_export_row_counts=logicalCounts,per_kind_export_row_counts=new{records=recordKindCounts,edges=edgeKindCounts},selected_membership_row_occurrences=selectedCount,unique_selected_membership_ids=selectedMemberCount,duplicate_selected_membership_occurrences=selectedCount-selectedMemberCount,unique_selected_object_digests=selectedSha.Count,selected_source_record_rows=selectedRecordRows,excluded_source_record_rows=excludedRecordRows,nonselected_source_record_rows=excludedRecordRows,selected_source_edge_rows=selectedEdgeRows,excluded_source_edge_rows=excludedEdgeRows,nonselected_source_edge_rows=excludedEdgeRows,count_class_semantics="excluded and nonselected overlap exactly; do not add all three. Logical rows count once; pass observations are separate. Global evaluation_object edges remain analysis context.",priority=Process.GetCurrentProcess().PriorityClass.ToString(),compute_parallelism=1,source_sha256=b.source_sha256,binding_sha256=expectedBindingSha,runner_sha256=b.runner_sha256,global_admitted_total="UNKNOWN",current_208="UNKNOWN"};
            WriteDocument(outputBudget,"run-receipt.json",receipt);
            Check(b,sw,total,"before_receipt",true);RuntimePhase("before_atomic_promotion",b);
            WriteDocument(outputBudget,"phase-observations.json",RuntimePhases.ToArray());
            VerifyOutputs(outputBudget);
            long actualRootBytes=0;foreach(string file in Directory.EnumerateFiles(b.output_root,"*",SearchOption.AllDirectories))actualRootBytes=checked(actualRootBytes+new FileInfo(file).Length);
            if(actualRootBytes!=checked(outputBudget.BaseBytes+outputBudget.WrittenBytes)||actualRootBytes>b.max_output_bytes)throw new InvalidOperationException("CAP_OUTPUT_FINAL");
            if(new DriveInfo(Path.GetPathRoot(b.output_root)).AvailableFreeSpace<b.min_C_free_bytes)throw new InvalidOperationException("C_SPACE:promotion");
            Check(b,sw,total,"before_receipt",true);
            VerifyTerminalReservation(b);
            Directory.Move(StagingRoot,runDir);
            exportFile.Dispose();Console.WriteLine("COMPLETE_SELECTED_CATALOG_PROJECTION");Console.WriteLine(runDir);
        }

    }
}
